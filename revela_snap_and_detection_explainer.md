# REVELA – Pin Snapping & Detection System Explainer
> For panel presentations and technical questions

---

## The Problem We Solved

When businesses are imported from the BPLO CSV, many have no GPS coordinates — only a barangay name.
The map used to pile them all on the **barangay centroid** (a single dot), making it look like clusters of random pins. This made the map misleading and the system look inaccurate.

There were **two distinct problems**:
1. Registry businesses with no real coordinates (centroid stacking)  
2. The grid scan not detecting **actual businesses** that are not in the registry (Red Flags)

---

## Solution 1 — Cost-Optimized Pin Snapping

### How it works (Places-first for better business-level matches)

| Tier | API Used | Free Quota | List Price |
|---|---|---|---|
| 1st | **Places Text Search (Pro)** (business name + location) | 5,000/month free | $32 per 1,000 after |
| 2nd | **Geocoding API** (address → coords fallback) | 10,000/month free | $5 per 1,000 after |
| 3rd | Name-only Geocode fallback | Same as Tier 2 | Same as Tier 2 |

> Places Text Search prioritizes business-name matching for more precise pins. Geocoding remains the fallback. The system processes up to 200 businesses per run by default, and the Text Search budget is capped at 2,500 requests/month.

### Smart Cache (`resolveKey`)
Each business has a SHA-1 hash of `businessName | businessAddress | barangayID` stored in the database. If the data hasn't changed since the last attempt, **zero API calls** are made. This means:
- Running "Snap Pins" skips unchanged entries already checked with Places. Existing `geocode` pins receive one Places recheck; a separate cache key prevents repeating that request.
- Only genuinely new or updated businesses consume quota.

### Budget Guards
Both Geocoding and Places APIs have **daily and monthly caps** enforced at the database level to help manage costs:
```
GEOCODE_DAILY_CAP  = 1,500 (env var, tunable)
GEOCODE_MONTHLY_CAP = 8,000 (default)
PLACES_DAILY_CAP   = 1,000 (default)
PLACES_MONTHLY_CAP = 2,500 (Text Search), 2,000 (Nearby Search)
```
If the daily or monthly cap is hit mid-run, the process safely breaks before consuming more quota, and progress is saved so the next run resumes where it left off.
*(Note: These guards track REVELA usage; they do not account for external usage on the same Google billing account).*

### How to trigger
Map Page → `⋯` (Advanced Tools) → **📍 Snap Pins**

A green progress overlay shows **Snapped / Cached / Total** in real time via Server-Sent Events (SSE).

---

## Solution 2 — Unregistered Business Detection (Red Flags)

### Grid Scan Architecture
The system divides Mataasnakahoy into a grid with each circle covering an 850m radius.
Every point fetches nearby places from Google's Nearby Search API, including pagination if a location has multiple pages of results.

### Municipality Boundary Filter
All results are screened against a precise **GeoJSON polygon** of Mataasnakahoy boundaries (with a ~55m buffer). Any POI outside the boundary is discarded before cross-referencing — this prevents Lipa / Balete businesses from appearing as false Red Flags.

### Cross-Referencing Algorithm
For each Google Places POI:

1. **Exact placeID match** against registry → Displays color based on permit status (Green for active, Purple for closed, etc.)
2. Name similarity ≥ 0.80 + same barangay or ≤ 300m → Auto-match
3. Name similarity 0.55–0.79 → Review queue (Yellow flag awaiting admin decision)
4. Score < 0.55 and no match → Unregistered (Red Flag)
5. Non-business types (church, school, govt) → Skipped (no flag)

The similarity scorer uses **Python's `difflib.SequenceMatcher`** for fuzzy token overlap, plus category adjustments (e.g. Pharmacy ≠ Apartment) to prevent cross-industry misidentification.

### Checkpointed Scans
Grid points are checkpointed in `scan_point_log`. If the daily budget runs out mid-scan, the next run continues from the last incomplete point.

### Monthly Limit
Detection scans are hard-coded to a limit of **2 per month** to prevent accidental quota burn.

---

## Architecture Decisions (Panel Questions)

**Q: Why Places Text Search before Geocoding?**

A: BPLO addresses can be only a barangay name. Text Search puts the business name first and can match a listed establishment; Geocoding remains a fallback for businesses that Places cannot locate. The Text Search budget is capped separately.

**Q: Why store coordinates in the database instead of calling Google every time?**  
A: Storing coordinates reduces API costs and means the map loads instantly on every page view. Our app schedule runs coordinate refreshes to comply with Google’s terms. Note: Place IDs are exempt from caching restrictions, but coordinate caching remains subject to the applicable Google Maps terms of service. Our stale coordinate purge aims to manage this.

**Q: What happens if two admins run detection simultaneously?**  
A: The budget guard uses atomic conditional SQL updates (`UPDATE ... WHERE requestCount < cap`). This atomic conditional ensures that concurrent workers cannot increment the counter beyond the enforced cap.

**Q: How do you know a detected business isn't in the registry?**  
A: Name similarity < 0.55 means no name match. The system also checks `placeID` (Google's unique identifier). If a business in the registry was previously matched to a specific `placeID`, that exact `placeID` is linked to the official registry record rather than becoming a Red Flag.

**Q: How do you prevent businesses from neighboring municipalities from being flagged?**  
A: The OSM-derived `_MUNICIPALITY_BOUNDARY` polygon with a 0.0005° buffer. Any POI outside this polygon is discarded before any matching occurs.

---

## Implementation Details

Core components implemented for this workflow include:
- `api/registry/service.py`: Database quota reservations, `snap_unresolved_pins()`, and atomic quota checking.
- `api/registry/routes.py`: Asynchronous `/api/registry/snap-unresolved` endpoint.
- `revela_web/src/pages/MapPage.jsx`: Advanced tools UI, SweetAlert2 confirmations, SSE listener for `revela:snap-progress`, and the progress overlay.
- `revela_web/src/components/DashboardLayout.jsx`: SSE event dispatch bridge.
- `api/flags/service.py`: Checkpointed grid scanning and bounded polygon detection.
- `api/registry/places_resolver.py`: `resolveKey` hashing and caching logic.
- `api/utils/name_match.py`: Fuzzy matching algorithms based on `difflib.SequenceMatcher`.
