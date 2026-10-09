# Places API and Pin Accuracy Implementation Plan

**Prepared:** 2026-10-09  
**Scope:** Registry import and pin placement, Re-verify Pins, Run Detection, Places API budgets, and deployment configuration.

## 1. Goals and non-negotiable behavior

This plan brings together the requirements discussed for the Maps/Flags and Registry workflows:

1. Preserve the Registry import and Run Detection data-cleaning and matching behavior; changing the search endpoint must not bypass reconciliation or the municipality boundary checks.
2. Improve discovery of visible businesses and placement of registry pins without treating Google results as infallible.
3. Never turn a quota stop or Google API error into a successful "no match", "below threshold", or a destructive pin/flag change.
4. Keep a persistent database usage ledger, reserve a slot before every external request, and stop work gracefully at app or Google Cloud limits.
5. Keep each method/SKU’s requests separately measurable. Text Search, Place Details, Geocoding, legacy Nearby Search, and Nearby Search (New) are not one interchangeable allowance.
6. Make uncertain business matches reviewable. A returned Google coordinate is the Google POI's coordinate; it is not proof of the correct business branch or storefront entrance.
7. Preserve run progress and resume unfinished records/cells rather than claiming unsearched data has no match.

## 2. Important pricing and quota facts to verify before implementation

### 2.1 Free usage cap is not the request quota

Google's monthly free usage cap is billing/SKU usage. GCP request quotas are separate limits, often per API method and project. A free monthly allowance does not prevent a daily or per-minute HTTP 429. App-side limits must be below the corresponding configured Cloud quota, with headroom for retries and other applications using the same project/key.

Current Google documentation reviewed for this plan describes:

- **Text Search (New) Pro:** 5,000 free events/month.
- **Nearby Search (New) Pro:** 5,000 free events/month.
- **Nearby Search (New) Enterprise:** 1,000 free events/month.
- **Place Details (New) Essentials:** 10,000 free events/month.
- **Place Details (New) Pro:** 5,000 free events/month.
- **Place Details (New) Enterprise:** 1,000 free events/month.
- Geocoding has its own SKU/cost and quota; it is not part of the Places Search counters.

These are per-SKU monthly free caps, not allowances reserved for REVELA. Other products/projects using the same billing account/project may affect total billing. Re-check the current project’s pricing SKU names, region, usage, and limits in Cloud Console at implementation time.

### 2.2 Fields proposed for Nearby Search (New)

The proposed field mask is:

```text
places.id,places.displayName,places.location,places.primaryType,places.businessStatus
```

For Nearby Search (New), these fields trigger **Nearby Search Pro**, not an Essentials tier. Adding `places.types` also remains Pro; it does not make the request Enterprise by itself. The previously cited 10,000 Essentials cap applies to Place Details Essentials, not Nearby Search. Nearby Search's `maxResultCount` is at most 20 results per request.

Text Search (New) already requests Pro fields (`places.displayName`, `places.location`, and type information), so adding `businessStatus` there would not raise its existing Pro tier. Place Details refresh currently asks only for `location`, which is Essentials.

Official references:

- [Nearby Search (New) guide and field mask](https://developers.google.com/maps/documentation/places/web-service/nearby-search)
- [Places usage and billing](https://developers.google.com/maps/documentation/places/web-service/usage-and-billing)
- [Places pricing and free usage caps](https://developers.google.com/maps/billing-and-pricing/pricing#places-pricing)
- [Manage quotas and costs](https://developers.google.com/maps/billing-and-pricing/manage-costs)

### 2.3 Current app configuration risk

The repository currently has these defaults:

| Workflow | Current app default | Previously reported GCP limit | Action |
|---|---:|---:|---|
| Registry Text Search (New) | `TS_DAILY_CAP=75`, `TS_MONTHLY_CAP=2500` | 80/day was reported | Keep the Railway app cap at 75/day unless the verified GCP quota is deliberately increased. Keep monthly app cap 2,500 unless deliberately revised. |
| Place Details refresh (New) | `PD_DAILY_CAP=90`, `PD_MONTHLY_CAP=3000` | 95/day was reported | Daily cap 90 is below the reported Cloud limit. Monthly cap 3,000 is a conservative app limit, below Essentials free cap if Details stays Essentials. |
| Run Detection legacy Nearby Search | `PLACES_DAILY_CAP=1000`, `PLACES_MONTHLY_CAP=2000` | Must be checked in Cloud Console | These are legacy-method app counters; do not assume they apply to Nearby Search (New). |
| Re-verify batch | `BATCH_LIMIT=50` | n/a | Retain the bounded batch and resumability. |

The values in the GCP column are user-reported, not independently observed from the project. Confirm the method-specific quotas in Cloud Console before setting Railway variables. A 500 Text Search requests/day app cap is not safe against an 80/day Cloud quota.

The repository default for `TS_DAILY_CAP` is now 75. This protects deployments that omit the variable as well as Railway deployments, but it does not verify or replace the Cloud Console quota.

## 3. Workflow design

### 3.1 Registry import and Snap Pins

**Purpose:** Plot official registry records on the map and preserve coordinate provenance.

**Current flow:** Registry import/sync can preserve usable coordinates from the uploaded data. For records needing coordinates, the resolver attempts Places Text Search (New), ranks returned places using name/category matching and municipality bounds, then may fall back to Geocoding. Snap Pins can resolve missing pins and refresh some geocode-derived pins. Resolver cache keys avoid repeating unchanged resolutions.

**Implementation approach:**

1. Keep this path distinct from Run Detection.
2. Preserve valid uploaded/manual coordinates; do not replace `coordSource='manual'` or trusted CSV coordinates without an explicit refresh policy.
3. Continue Text Search (New) before Geocoding fallback for records with no usable coordinates or eligible geocode pins.
4. Keep Place Details limited to `location` for periodic coordinate refresh unless a specific feature justifies more fields.
5. Track Text Search, Place Details, and Geocoding requests separately, persistently, including failed attempts and retries.
6. Respect the existing resolve cache and rejected-place records. A quota/API failure must not persist a result shaped like a permanent failed/no-match cache entry.
7. Treat low-confidence candidates as review, not automatic coordinate changes.

**Expected volume for 859 imported records:** 859 is an upper-bound estimate for one Text Search per record only if every record needs a fresh request. Existing coordinates, unchanged resolve keys, and cache hits should lower usage. Retries add requests. Import, Snap, and Re-verify share the Text Search method/SKU budget.

### 3.2 Re-verify Pins

**Purpose:** Improve the placement of existing official-registry pins by resolving their business names/addresses to a better Google POI.

**Implementation approach:**

1. Retain `BATCH_LIMIT=50` by default; enforce it server-side even if the client submits a larger value.
2. Select unverified candidates first. Continue prioritizing businesses already associated with a Google POI over micro/stacked pins, then process remaining eligible records.
3. Use Text Search (New) with concise business, address, barangay, municipality, and country context, plus the current location bias/bounds.
4. Match first by an exact existing `placeID` where applicable. Otherwise retain name similarity, line-of-business/category signals, barangay and distance logic.
5. Automatically move a pin only for a sufficiently strong match under existing policy. Route ambiguous/marginal candidates to review without overwriting coordinates.
6. Keep statuses separate: verified/moved/review/no match/quota/API error. Quota and API failures must not overwrite coordinates, pin colors, or match status as though a result was evaluated.
7. Make a new run continue with not-yet-verified rows, not repeat rows already successfully handled unless the user explicitly requests a refresh.
8. Report run results and Text Search/Details/Geocoding usage separately.

**Limit:** Google can return a correctly named place with coordinates at a map label/parcel rather than the exact business entrance. Re-verify can make the match tighter, but an admin review or manual coordinate correction remains necessary for ambiguous or visibly misplaced cases.

### 3.3 Run Detection migration to Nearby Search (New)

**Purpose:** Discover Google POIs across the municipality, match them to the official registry for data cleaning, and create/reconcile flags for unmatched businesses.

**Current behavior:** Run Detection currently calls the legacy Nearby Search endpoint, using a grid and an 850 m radius. The legacy results are capped at 60 per search point. Recent changes expanded grid-center coverage beyond the municipal polygon by approximately the search radius and added bounded adaptive searches for saturated cells. Matching, non-business filtering, and reconciliation remain in the Flags service.

**Target endpoint and request:**

```text
POST https://places.googleapis.com/v1/places:searchNearby
X-Goog-Api-Key: <server-side key>
X-Goog-FieldMask: places.id,places.displayName,places.location,places.primaryType,places.businessStatus
```

Start with a broad, all-business discovery query rather than a restaurant-only `includedTypes` filter. Apply a carefully reviewed list of `excludedTypes` on the server for clearly non-business types. Keep `_is_non_business_place` name-keyword heuristics as a second-stage safeguard. Do not make the exclusions so broad that ordinary small businesses or mixed-use locations disappear.

**Search fields and handling:**

- `places.id`: deduplication, pin/registry identity, repeat-scan prevention.
- `places.displayName`: label and name matching.
- `places.location`: candidate map coordinates.
- `places.primaryType`: category-aware match support; category boost will be weaker than using both `primaryType` and `types`.
- `places.businessStatus`: do not silently filter closed places. A closed Google POI should remain visible for admin assessment; the agreed map workflow is for admins to classify a confirmed closed place as Purple. Do not automatically recolor/close an official registry business based only on Google status.
- Do not request `places.types` in the first pass unless an offline/test comparison demonstrates sufficient matching or filtering benefit. If included, it is still Nearby Search Pro. If excluded, keep keyword heuristics and `primaryType` matching; document the weaker category signal.

**Coverage and result saturation:**

1. Establish grid points from the municipality geometry plus a search-radius buffer so edge circles cover the municipal boundary.
2. Choose and test a base radius/spacing. Do not assume 200 m is best: smaller circles may improve density but multiply request counts over the full municipality.
3. Set `maxResultCount` to 20 (the New API maximum).
4. When a cell returns 20, treat it as potentially saturated and subdivide into bounded smaller circles. Deduplicate all parent/child results by `places.id`.
5. Bound depth and total child calls per root cell. Never recursively refine without a strict request budget.
6. If the limit is reached or a child query fails, mark the root grid cell incomplete and do not checkpoint it as complete. Retry it in a later run.
7. Keep existing municipality geometry validation even after server-side `locationRestriction`; the restriction is not a substitute for app boundary validation.
8. Use bounded retries with backoff only for transient/per-minute failures identified from the response. For daily/monthly `RESOURCE_EXHAUSTED`, stop Places calls for that run. Count each transmitted retry.

**Data cleaning and flags:**

1. Deduplicate by Google `place_id`/`places.id`.
2. Ignore results without valid coordinates or outside the municipality.
3. Preserve the non-business keyword rules and existing registry matching/reconciliation.
4. Exact place-ID matches should outrank name-only matches.
5. Keep existing match thresholds initially; do not lower them merely to increase discovery counts.
6. A Google POI confidently matched to an official registry record should be reconciled to the registry’s permit/application state under existing rules.
7. Unmatched business candidates may appear as Red flags. Ambiguous matches should be reviewable. Closed status from Google is evidence for the admin, not permission to silently change official records or automatically label the POI Purple.
8. Persist inserted flag IDs/checkpoints such that cancellation and partial quota stops do not create incomplete state.

### 3.4 Independent budgets and dashboard

Use distinct persistent usage counters, keyed by API method/SKU class and date:

| Counter | Used by | Notes |
|---|---|---|
| Text Search (New) | import resolution, Snap Pins, Re-verify | Shared across those workflows; daily and monthly caps. |
| Place Details (New) Essentials/Pro as configured | coordinate refresh | Track separately from Text Search; today only `location` is requested. |
| Geocoding | resolver fallback/import fallback | Its own GCP quota and app cap. |
| Nearby Search legacy | Run Detection before migration / rollback mode | Keep separate while legacy is callable. |
| Nearby Search (New) | Run Detection after migration | Separate daily/monthly usage and dashboard status; every adaptive child query is another event. |

The request reservation should be atomic across Railway workers. Prefer one usage-table implementation or a clearly documented common helper so per-method counts cannot drift between Flags and Registry. Reserve one call immediately before sending it. A failed request consumes the reserved slot; if the app can prove a request was never transmitted, handle release explicitly and test it.

Expose current usage and lockout reasons from backend endpoints. In the dashboard:

- Show separate daily/monthly usage for Text Search, Details, Geocoding where applicable, and Run Detection Nearby Search.
- Disable only actions that require a depleted budget; do not block a DB-only flag editing action because a Places budget is depleted.
- Show cap, used count, reset timing, and clear distinction between application cap and Cloud quota.
- Return machine-readable `daily_quota_exceeded`, `monthly_quota_exceeded`, `skipped_quota`, and `api_error` outcomes for callers.
- Avoid hardcoded front-end quota text; render the cap/usage returned by the API.

## 4. Files and responsibilities

### Backend

- `revela_backend/api/registry/service.py`
  - Registry import/sync, coordinate preservation, Snap Pins orchestration, green flag synchronization, progress/cancel behavior.
- `revela_backend/api/registry/places_resolver.py`
  - Text Search, Geocoding fallback, Place Details refresh, FieldMasks, cache, status classification, pacing and request reservations.
- `revela_backend/api/registry/reverify.py`
  - Re-verify candidate priority, batch cap, result classification, resumability and summary.
- `revela_backend/api/registry/routes.py`
  - Import/Snap/Re-verify route validation and distinct quota/error responses.
- `revela_backend/api/flags/service.py`
  - Run Detection grid generation, Nearby Search request method, saturation subdivision, non-business filtering, registry matching/reconciliation, flag creation, legacy/new counters and run summaries.
- `revela_backend/api/flags/routes.py`
  - Detection start/cancel, quota/Places usage endpoints, flag editing endpoints.
- `revela_backend/api/models/detection_runs.py`
  - Monthly Run Detection scan accounting and run status; keep scan quota distinct from API request usage.
- `revela_backend/api/models/geospatial.py`
  - Shared geospatial flag persistence where existing operations are reused.
- `revela_backend/api/utils/name_match.py`
  - Shared category/name match behavior; test any reduction in category signal if `types` is omitted.
- `revela_backend/api/utils/cancellation.py`
  - Cancellation semantics for partial scans.
- `revela_backend/app.py`
  - Blueprint registration, app startup and scheduled coordinate maintenance; change only if startup/maintenance wiring is required.

### Frontend

- `revela_web/src/pages/MapPage.jsx`
  - Map/flag display, Run Detection, Snap/Re-verify controls, progress/cancel, budget badges and disabled states.
- `revela_web/src/pages/RegistryPage.jsx`
  - Registry list/import/review interactions and any registry-specific action UI.
- `revela_web/src/services/api.js`
  - HTTP request functions and response handling for registry, flags, detection and quota endpoints.
- `revela_web/src/utils/googleMaps.js`
  - Shared Google Maps JavaScript loading; not the server-side Places search implementation.
- `revela_web/src/utils/mapStyles.js`
  - Map styling only; not discovery or quota logic.

### Tests and deployment

- Extend `revela_backend/tests/test_places_resolver.py` for Text Search/Details/Geocoding reservations and error/status integrity.
- Extend/add Run Detection tests for New Nearby payload and FieldMask, excluded types, bounds, deduplication, 20-result saturation, bounded subdivision, quota stop and incomplete checkpoints.
- Retain `revela_backend/tests/test_reverify_priority.py`; add cases for exact place-ID match, uncertain review, quota/API error preserving coordinates and resume.
- Add frontend tests if the project has suitable existing component tests; otherwise validate dashboard request/lockout manually in staging.
- Inspect Railway service variables and build/start commands; do not put a server API key in frontend `VITE_*` variables.

## 5. Step-by-step implementation sequence

### Phase 0 — Baseline and project quota verification

1. Record current deployed commit and Railway service/environment for backend and frontend.
2. In Google Cloud Console, select the exact project associated with the server API key and confirm:
   - Places API (New) is enabled.
   - Geocoding API is enabled if fallback remains enabled.
   - Billing account and budget alerts are active.
   - Per-method quotas for Text Search (New), Place Details (New), Nearby Search (New), and Geocoding.
   - Current usage by SKU, including usage from any other app sharing this project.
   - Key restriction type/application restrictions and API restrictions.
3. Capture verified quota numbers and usage baselines. Do not raise Cloud quotas yet.
4. Confirm deployed Railway values; environment variables override repository defaults. Pay special attention to `TS_DAILY_CAP`, `TS_MONTHLY_CAP`, `PD_DAILY_CAP`, `PD_MONTHLY_CAP`, `PLACES_DAILY_CAP`, `PLACES_MONTHLY_CAP`, `BATCH_LIMIT`, and resolver enablement.
5. Set immediate safety values before enabling new behavior:
   - `TS_DAILY_CAP=75` if Text Search GCP daily quota remains 80.
   - `PD_DAILY_CAP=90` if Place Details GCP daily quota remains 95.
   - `TS_MONTHLY_CAP=2500`, `PD_MONTHLY_CAP=3000`, `BATCH_LIMIT=50` unless product owners deliberately change them.
   - Do not assume the existing legacy `PLACES_*` limits apply to the New Nearby Search method.
6. Make no live Cloud quota increase until the app reservation, stop, and UI behavior are tested.

**Gate:** verified Cloud quota list and Railway variable list exist; app-side Text Search cannot exceed the actual 80/day Cloud limit.

### Phase 1 — Make counters correct and observable

1. Use the shared atomic reservation helper for Registry and Flags, with separate persistent keys for each method. Legacy Nearby Search keeps its existing `month`/`day` rows so deployment does not silently reset prior usage.
2. Add/standardize keys for `imp_ts`, `imp_pd`, `geocode`, `legacy_nearby`, and `new_nearby`; persist day and month counts using DB date boundaries.
3. Ensure reservation is atomic across multiple app workers and checks daily and monthly caps in the same transaction.
4. Reserve before each transmitted request, including retries, page requests if any, and every adaptive child search.
5. Log method, attempt number, response status, bounded response body/error details, counter decision, run ID, and stop reason. Never log the API key.
6. Return usage status with actual configured caps so UI never presents stale hardcoded numbers.
7. Add concurrency/reservation tests, boundary-at-cap tests, and "failed request still counted" tests.

**Gate:** tests demonstrate no request is sent when a cap is reached and concurrent workers cannot overspend the app-side limit.

**Initial implementation note:** the shared reservation helper and New Nearby Search client have been added behind `RUN_DETECTION_NEARBY_API=legacy|new`. New Nearby Search remains disabled by default. `NEW_NEARBY_DAILY_CAP` and `NEW_NEARBY_MONTHLY_CAP` default to `0`, which fails closed; set positive values only after confirming the specific Cloud method quotas and monthly project usage.

### Phase 2 — Harden registry import, Snap Pins, and Re-verify

1. Review import coordinate precedence and ensure supplied/manual coordinates are preserved under the documented policy.
2. Verify all resolver requests use minimal FieldMasks:
   - Text Search: retain fields required for candidate identity, label, coordinates, and matching.
   - Details refresh: `location` only unless a specific tested use case requires more.
3. Keep Geocoding as explicit fallback, with independent counter and distinct metadata (`coordSource='geocode'`).
4. Ensure 429/RESOURCE_EXHAUSTED and other API failures do not fall through into no-match/failed caching or modify pins/colors.
5. Keep 50-item Re-verify limit and current business-first priority. Confirm high-confidence-only moves; ambiguous outcomes go to review.
6. Keep known Google POI associations and resolved coordinates cached; define refresh rules for stale Geocoding coordinates and rejected IDs.
7. Verify daily quota status can stop a batch gracefully, preserve successful earlier rows, and leave unprocessed rows eligible for the next run.
8. Add summary fields for resolved, moved, review, no match, skipped quota, API error, cache hits, and per-method daily/monthly counts.

**Gate:** import/Snap/Re-verify tests verify pin and flag data does not change on API/quota failure and that a resumed batch skips successfully handled records.

**Phase 2 implementation note:** Registry imports now accept only finite, geographically valid coordinate pairs; manual/approved coordinates remain locked, valid CSV coordinates retain `coordSource='csv'`, and successful Geocoding fallback is explicitly marked `coordSource='geocode'`. A changed registry name/address is resolved again rather than silently reusing an old non-manual pin. API/quota failures preserve the previous pin and flag, do not write a completed `resolveKey`, and remain eligible for a later Snap/Re-verify run. Geocoding reservations and summaries remain separate from Text Search and Place Details. Re-verify is capped at 50, tries an existing place ID first, and stores uncertain candidate coordinates in pin history without moving the official pin; admin approval applies the proposed move, while rejection preserves the existing pin. Import, Snap, and Re-verify summaries include outcome counts and per-method daily/monthly usage.

**Business-match hardening:** The shared matcher now folds Unicode accents, uses one-to-one weighted Dice token overlap rather than shorter-name containment, blocks single-token-only evidence unless business categories agree, and rejects incompatible specific categories (including supermarket vs. event venue). Address overlap can only support a name match; it cannot create one. Automatic association requires a score of at least 0.80 and coordinates within 300 m; missing coordinates require same-barangay and strong address agreement, and near-tied candidates are downgraded to review. Nearby Search persists Google POI types in `geospatial_logs.placeTypes` so Reconcile can use the same category evidence; the column is added on the first detection/reconciliation run. Text Search asks for `formattedAddress` to compare Places results to registry addresses. These rules are deterministic; no model training or inference is required.

**Review UI enhancement:** Existing business pins with `matchStatus='review'` display a yellow exclamation indicator on the map (including clustered markers). Clicking the pin retains the normal business-information modal; its "Review suggested location" button opens the Re-verify Pin Suggestions modal filtered to that business, where admins can inspect current/proposed coordinates and approve or reject. Review metadata is joined to an existing geospatial pin by business ID, then exact place ID, then the legacy exact name/barangay association, preventing a duplicate registry-only marker when an existing POI pin matches by place ID. The modal also supports server-side search by business name, business ID, address, and barangay; approve/reject refreshes map flags to clear the review indicator when the decision is complete.

**Map modal camera behavior:** Opening a pin remembers the previous map center and zoom. Closing its business-information modal restores that camera position. The map's React `GoogleMap` props remain at their initial center/zoom rather than being derived from `selectedFlag`; marker selection pans/zooms imperatively, so clearing selection on close cannot reset the controlled map props and override camera restoration.

**Street View map layer:** On the web map, Street View coverage is drawn directly over the map at zoom level 16 and closer. Use the Google Maps Pegman control to open a covered road in the map's Street View panorama. This uses the enabled Maps JavaScript API; Street View coverage is hidden when zooming back out or while selecting a pin location. The mobile app remains unchanged.

### Phase 3 — Implement Nearby Search (New) behind a feature switch

1. Keep `RUN_DETECTION_NEARBY_API=legacy` until staging approval. The backend switch and initial New Nearby client are implemented; verify the exact request contract and quota behavior in tests before enabling.
2. Validate the implemented `POST https://places.googleapis.com/v1/places:searchNearby` request: server-side key, JSON body, `locationRestriction.circle`, `maxResultCount=20`, and explicit FieldMask.
3. Do not hardcode the sample's restaurant-only filter. Search all relevant local businesses and send a reviewed `excludedTypes` list. Validate each excluded type against Table A and known Mataasnakahoy businesses.
4. Keep `_is_non_business_place`'s name-keyword heuristics. Add tests proving the type exclusions and local heuristics do not hide common local business categories.
5. Request `places.businessStatus` for the agreed closed-business admin workflow; no `openingHours`, reviews, ratings, photos, or other Enterprise/Atmosphere fields.
6. Start without `places.types`; use `places.primaryType` for category matching. Only add `places.types` after side-by-side tests show it materially improves matching/filtering; it remains Pro.
7. Preserve geometry/bounds validation and all existing cleaning/matching/reconciliation stages.
8. Deduplicate parent/child query results by place ID and preserve original best coordinates/metadata consistently.
9. Treat a response with 20 results as potentially saturated. Refine by a fixed, tested child layout with explicit max depth and max child-query budget. Do not exceed the per-run Nearby budget.
10. A child query error, quota stop, or still-saturated leaf means the root cell is incomplete and must not be checkpointed as complete.
11. Keep closed results visible for review. Never automatically mark a place Purple based solely on Google's businessStatus; the admin explicitly classifies confirmed closed places.
12. Add run summary: grid cells completed/incomplete, initial calls, adaptive calls, results, duplicate results, outside-boundary results, non-business exclusions, matched, review, Red flags created, API errors and quota stops.

**Gate:** contract tests assert the exact endpoint, header, field mask, payload shape, excluded type list, max result count, and count reservation per call. No production requests yet.

**Run Detection latency diagnosis and plan:** The scan executes synchronously inside one HTTP POST. Grid points are processed serially, each saturated root can issue up to 12 adaptive child requests in addition to its root request, and reconciliation runs before the grid scan. The former name matcher reparsed the same registry names for every POI, and the municipality tolerance buffer was rebuilt for each containment check. These costs make a long request and upstream/client disconnect plausible; production Railway/proxy logs are still needed to identify which timeout caused the reported SweetAlert failure.

The implementation caches immutable parsed names/categories while preserving fresh mutable results from `parse_name`, prepares the municipality tolerance polygon once, and performs the scan's containment check only once per POI. Barangay-name rows are loaded once; fallback registry coordinates are queried only on the exceptional no-polygon path so mid-run pin updates cannot make a preloaded fallback snapshot stale. The scan-work clock starts immediately before grid traversal, and each POI, Places request, and grid boundary checks the 90-second `RUN_DETECTION_MAX_SECONDS` work slice (default) and 120-request `RUN_DETECTION_MAX_REQUESTS` cap. Responses report both end-to-end `elapsed_seconds` and `scan_elapsed_seconds`; pre-scan reconciliation remains part of end-to-end time and must be monitored against the hosting request deadline.

If a time/request limit or API error interrupts the scan, it returns resumable `status='partial'`; the in-flight cell remains uncheckpointed and does not consume the monthly scan quota. If every root cell was attempted but one or more remained saturated at the bounded refinement depth, the run ends as `status='completed_with_gaps'`, consumes a monthly scan, and the UI warns that coverage is incomplete instead of promising an identical retry. This prevents repeated clicks from re-spending the request budget on permanently capped cells. Tune the limits only after staging measurements of total latency, scan latency, Places calls, registry size, and coverage. A request already in flight and the current POI evaluation can finish, so the scan slice may be exceeded slightly.

**Gate:** verify the name cache preserves matcher decisions; the prepared boundary preserves geographic acceptance cases; partial runs resume without losing returned POIs; completed-with-gaps runs count against monthly quota; and both elapsed metrics stay within the hosting request deadline in a bounded staging run.

### Phase 4 — Side-by-side quality and bounded staging

1. Build a set of representative grid cells and expected examples: visible obvious businesses, dense clusters, boundary locations, non-business POIs, closed businesses, official-registry matches, duplicate branches, and known false matches.
2. Prefer saved/test fixtures or controlled low-volume cells. Do not run a full old and new live scan in parallel unless the duplicate cost has been explicitly budgeted.
3. Compare:
   - Unique POIs found by each approach.
   - POIs missed/added in dense and boundary cells.
   - Candidate-to-registry match precision and review rate.
   - Coordinate distance from verified local reference points.
   - API events consumed per completed municipality cell.
4. Tune grid spacing/radius and child budget based on coverage and calls per unique valid POI. Do not tune only for raw results.
5. Enable New Nearby Search for a small, explicitly bounded set of cells in staging or a controlled production run. Keep the legacy switch available for immediate rollback.
6. Inspect live Cloud metrics and the DB ledger after the test. Confirm actual method/SKU usage aligns with app counts.

**Gate:** acceptance threshold for matching accuracy and maximum query count per cell is written down and met; quota display and rollback tested.

### Phase 5 — Full rollout and legacy retirement decision

1. Start with a per-run Nearby Search app cap safely below both the verified GCP daily quota and remaining monthly free allowance after other project usage. Treat 5,000/month as a ceiling, not the default app cap.
2. Roll out in increasing bounded batches, monitoring unique POIs per request, saturated cells, errors, match reviews, and actual billing SKU events.
3. If the free-cap target is exceeded or project usage is shared/uncertain, stop/hold rollout and lower the app cap or use a smaller scan scope.
4. Keep legacy Nearby Search and its separate counters until New Nearby is proven and a rollback window has passed.
5. Only remove legacy code/counters after confirming no other caller uses it and successful run/resume behavior in production.
6. Revisit whether the monthly Run Detection scan quota is still appropriate. It is a product-level scan allowance and is distinct from method-level request budgets.

## 6. Google Cloud Console operational checklist

### Before code rollout

1. Open **Google Cloud Console → project selector** and choose the same project as the backend API key.
2. Open **Google Maps Platform → APIs & Services / APIs**:
   - Verify Places API is enabled for Places API (New).
   - Verify Geocoding API is enabled if fallback is retained.
3. Open **Google Maps Platform → Quotas**:
   - Inspect method-specific request/day and request/minute quotas for Text Search (New), Place Details (New), Nearby Search (New), and Geocoding.
  - Verify the exact Legacy Nearby Search method quota and billable SKU separately; do not infer it from Nearby Search (New).
   - Export/screenshot current values for the change record.
   - Do not assume Legacy Nearby Search quotas are interchangeable with New API method quotas.
4. Open **Google Maps Platform → Metrics / Reports / SKU usage**:
   - Check recent and month-to-date calls for each SKU.
  - Record each applicable per-SKU monthly free-call allowance and remaining usage; check whether another key/service consumes the same project’s quota or free allowance.
  - Do not budget against the retired USD $200 monthly credit; free calls are SKU-specific and do not offset usage on another SKU.
5. Open **Billing → Budgets & alerts**:
   - Create or verify a low-threshold alert for forecast/actual Places spend.
   - Alerts are notifications, not hard spending caps.
6. Open **Credentials → server API key**:
   - Keep the Places key server-side in Railway only.
   - Restrict API access to only required APIs (Places API and Geocoding API if used).
   - Choose application restriction compatible with Railway/backend egress and deployment. Do not apply browser HTTP-referrer restrictions to a server-side key.
   - If frontend map rendering uses a separate browser key, keep a separate key with website/referrer restriction; never expose the server Places key as `VITE_*`.
7. Do not edit Cloud quotas until the app is safe at current quotas. If an increase is required, request only the specific per-method quota needed and document expected monthly SKU cost separately.

### If Cloud quotas need updating

1. Confirm desired peak requests/minute and requests/day from measured app behavior, including adaptive searches and retries.
2. Set Railway app caps below the approved Cloud caps (safety margin; initially keep Text Search at 75/day for reported GCP 80/day and Details at 90/day for reported 95/day).
3. In **Google Maps Platform → Quotas**, select the specific API/method quota, choose **Edit**, enter the justified value, and submit/request approval if Google requires it.
4. Change only that method's limit. Do not increase all Places API quotas together.
5. Watch status/approval and verify the new limit in Cloud Console before raising the matching Railway cap.
6. Compare billing SKU and request metrics after deployment; a higher GCP request limit does not increase the monthly free usage cap.

## 7. Railway deployment checklist

### Environment separation

Maintain separate Railway variables for backend server and frontend:

**Backend service only**

```text
GOOGLE_MAPS_API_KEY=<restricted server-side key>
PLACES_RESOLVER_ENABLED=1
TS_DAILY_CAP=75                 # if Cloud Text Search daily quota stays at 80
TS_MONTHLY_CAP=2500
PD_DAILY_CAP=90                 # if Cloud Place Details daily quota stays at 95
PD_MONTHLY_CAP=3000
BATCH_LIMIT=50
RUN_DETECTION_NEARBY_API=legacy # initially; switch only after rollout gates
RUN_DETECTION_MAX_SECONDS=90    # maximum work slice per synchronous run request
RUN_DETECTION_MAX_REQUESTS=120 # includes retries and adaptive requests
NEW_NEARBY_DAILY_CAP=<approved conservative value>
NEW_NEARBY_MONTHLY_CAP=<approved conservative value>
```

`NEW_NEARBY_*` caps default to `0`, so selecting `new` without configuring positive verified caps will stop before sending a request. Do not set them to 5,000 automatically: first subtract other project usage, then select a lower app safety cap.

**Legacy Run Detection while still available**

```text
PLACES_DAILY_CAP=<value below verified Legacy Nearby daily quota>
PLACES_MONTHLY_CAP=<value below remaining acceptable Legacy Nearby usage>
```

**Frontend service**

- `VITE_API_ORIGIN` points to the deployed backend as currently configured.
- `VITE_GOOGLE_MAPS_API_KEY` is only the restricted browser map-rendering key, not the server-side Places key.

### Deploy procedure

1. Deploy backend first with the new implementation disabled and compatible DB table migrations/auto-creation tested.
2. Confirm health endpoint, DB connectivity, quota usage endpoint, and logs after restart.
3. Deploy frontend only after backend response fields are stable.
4. Run one bounded staging/production test with a known max request budget.
5. Confirm DB ledger increments, Railway logs show endpoint/method and summary, and Cloud SKU metrics agree.
6. Enable New Nearby Search for bounded cells; raise scope gradually.
7. Keep an operational rollback variable that restores legacy mode without a code rollback.

### Railway monitoring

For each run, log the run identifier, mode, API method, request count, retries, grid cells completed/incomplete, result counts, stop reason, and day/month usage. Never include API keys or unbounded personal/business data in logs.

Alert on:

- App usage unexpectedly approaching its configured cap.
- Any 429 / `RESOURCE_EXHAUSTED`, split by per-minute and per-day/month details when the response provides them.
- Google Cloud SKU usage that diverges from the app ledger.
- Large incomplete-cell count or a sudden increase in requests per unique POI.
- Sudden increases in low-confidence/incorrect matches or manually moved pins.

## 8. Test plan and acceptance criteria

### Unit and integration tests

- Text Search, Details, Geocoding, Legacy Nearby, and New Nearby each increment only their own persistent counters.
- Failed transmitted calls and retries count. Reservation denial means the HTTP client is not called.
- Reservation remains safe under concurrent workers and DB errors fail closed.
- Quota/API errors return distinct outcomes and do not alter coordinates, match status, or flags as a no-match.
- Import preserves valid supplied/manual coordinates according to policy.
- Resolver caching avoids duplicate calls when source business data has not changed.
- Re-verify obeys the 50-item cap, prioritizes unverified business candidates, resumes remaining rows, and preserves uncertain pins for review.
- New Nearby Search uses the correct endpoint, exact JSON schema, API-key header, and explicit FieldMask.
- Excluded types and keyword heuristics remove known non-businesses without filtering representative local businesses.
- Exactly 20 results triggers saturation refinement; child calls are bounded; place IDs are deduplicated.
- Per-run time/request limits stop between external calls, keep incomplete cells uncheckpointed, and report an explicit partial outcome; cached barangay lookups do not issue one repeated database read per POI.
- Saturated/error/quota-limited cells are not marked complete; later runs retry them.
- Out-of-boundary results cannot create flags even if the API returns them.
- Closed status is surfaced for admin review but does not automatically mutate official registry status or assign Purple.
- Dashboard displays server-returned cap/usage and disables only actions requiring exhausted budgets.

### Operational acceptance

Do not declare rollout complete until all are true:

1. Cloud method-level quotas, exact Legacy Nearby SKU, per-SKU free-call allowances, shared project usage, and Railway app caps are verified and recorded; no cost estimate relies on the retired USD $200 monthly credit.
2. Text Search daily app cap is lower than its Cloud daily limit.
3. Place Details and Geocoding have independent usage controls.
4. Nearby New and Legacy counters remain separate during transition.
5. At least one bounded New Nearby run completes and one quota-stop/resume path is verified.
6. Cloud SKU usage is consistent with app ledger counts.
7. Boundary and dense-area checks show no obvious coverage gaps and calls per root cell remain within the documented ceiling.
8. Reviewed matches meet the agreed precision threshold; ambiguous cases remain reviewable.
9. Rollback to Legacy mode is tested.

## 9. Rollback and incident procedures

### Nearby Search migration rollback

1. Set Railway `RUN_DETECTION_NEARBY_API=legacy`.
2. Confirm a new run uses the legacy endpoint and increments only legacy counters.
3. Keep New Nearby partial checkpoints distinct from legacy checkpoints if request semantics differ; do not mark cells complete across modes without confirming equivalence.
4. Preserve valid flags already created. Do not bulk-delete based only on a method switch; use a reviewed run ID and explicit reconciliation if cleanup is needed.
5. Investigate fields, type exclusions, query radius, deduplication, and matching metrics before re-enabling New Nearby.

### Quota incident

1. Stop the affected method in Railway via its mode/enable flag or set its app cap to zero.
2. Inspect the response body and Cloud method/SKU metrics; identify per-minute versus daily/monthly exhaustion.
3. Do not reset the persistent counter to bypass a Cloud quota.
4. Let per-minute throttling recover; for daily/monthly exhaustion, wait for the reset or obtain a deliberate quota change.
5. Resume only incomplete work after verifying the API is responding and data integrity is intact.

### Key restriction or API error

1. Check backend logs for request-denied status without exposing the key.
2. Verify API enablement, billing, key API restrictions, and server-compatible application restrictions.
3. Never loosen restrictions to unrestricted as a permanent workaround; rotate a key if exposed.

## 10. Decisions to lock before coding

These questions have measurable impact and should be settled using the Cloud/project evidence and bounded tests:

1. **Nearby Search monthly app cap:** choose below 5,000 Pro events and subtract other project usage; do not use the free cap as the app cap.
2. **Nearby daily/per-minute cap:** take from the exact method quota in Cloud Console, then choose a lower app guard with headroom.
3. **Base grid radius/spacing:** compare wider base searches plus bounded subdivision against 200 m circles using observed calls per unique, valid POI.
4. **Whether to request `places.types`:** default omit from New Nearby first pass; add only if test fixtures show its category signal materially improves safe matching.
5. **Closed POI behavior:** retain visibility for admin classification; do not allow Google status alone to close/change official registry data.
6. **Confidence thresholds:** initially preserve current matching thresholds; change only after labeled local data demonstrates improved precision, not just more matches.
7. **What counts as “verified” for resume ordering:** define success statuses (e.g. exact/auto/review decision) separately from quota/API error and unresolved candidates.
8. **Geocoding policy for import:** confirm which uploaded coordinates count as authoritative and when fallback is permitted.
