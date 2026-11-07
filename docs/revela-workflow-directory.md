# REVELA Workflow Directory

Clickable guide to the files involved in importing registry data, PSIC sector
mapping, map pinning, detection, and analytics.

## 1. Registry Import and Sync

| File | Role |
|---|---|
| [`revela_backend/api/registry/routes.py`](../revela_backend/api/registry/routes.py) | API endpoints for registry upload, sync, Snap Pins, and Re-verify. |
| [`revela_backend/api/registry/service.py`](../revela_backend/api/registry/service.py) | Main import, sync, validation, coordinate handling, and registry updates. |
| [`revela_backend/api/registry/places_resolver.py`](../revela_backend/api/registry/places_resolver.py) | Resolves missing locations using Places Text Search, then Geocoding fallback. |
| [`revela_backend/api/registry/colors.py`](../revela_backend/api/registry/colors.py) | Shared flag-color/status rules used when registry records become map pins. |
| [`revela_web/src/pages/RegistryPage.jsx`](../revela_web/src/pages/RegistryPage.jsx) | Registry upload, sync, and registry-management UI. |
| [`revela_web/src/services/api.js`](../revela_web/src/services/api.js) | Frontend requests for registry import, sync, and pin workflows. |

### Data cleaning and normalization

| File | Role |
|---|---|
| [`revela_backend/api/registry/service.py`](../revela_backend/api/registry/service.py) | Cleans imported strings, normalizes controlled registry values, validates dates/statuses, and prepares rows before database writes. |
| [`_clean_str`](../revela_backend/api/registry/service.py#L184) | Trims whitespace and converts blank/NaN-like values to `None`. |
| [`_clean_upper`](../revela_backend/api/registry/service.py#L197) | Cleans a value and uppercases controlled registry text. |
| [`normalize_business_address`](../revela_backend/api/registry/service.py#L327) | Normalizes imported addresses and combines address/barangay information when needed. |
| [`_normalise_columns`](../revela_backend/api/registry/service.py#L373) | Maps incoming CSV/Excel headers to the internal registry column names. |
| [`_parse_renewal_date`](../revela_backend/api/registry/service.py#L906) | Parses and standardizes imported renewal dates. |
| [`revela_backend/api/utils/name_match.py`](../revela_backend/api/utils/name_match.py) | Normalizes business names and removes legal/generic terms before name matching; also extracts category hints. |
| [`parse_name`](../revela_backend/api/utils/name_match.py#L120) | Case-folds names, removes punctuation/legal filler, tokenizes the name, and extracts category groups. |
| [`address_similarity`](../revela_backend/api/utils/name_match.py#L182) | Compares normalized registry and Google addresses. |
| [`name_match`](../revela_backend/api/utils/name_match.py#L202) | Scores business-name compatibility and detects category conflicts. |
| [`revela_backend/api/registry/places_resolver.py`](../revela_backend/api/registry/places_resolver.py) | Normalizes lookup inputs and validates provider coordinates against municipal bounds. |
| [`normalize`](../revela_backend/api/registry/places_resolver.py#L223) | Normalizes resolver text for Places matching. |
| [`_is_within_municipal_bounds`](../revela_backend/api/registry/places_resolver.py#L174) | Rejects provider results outside the configured municipal bounds. |
| [`revela_backend/api/analytics/sector_mapping.py`](../revela_backend/api/analytics/sector_mapping.py) | Normalizes `lineOfBusiness` text before PSIC matching. |
| [`normalize_sector_text`](../revela_backend/api/analytics/sector_mapping.py#L22) | Lowercases sector text and removes non-alphanumeric characters. |

```text
Raw CSV/Excel -> clean and validate -> normalize names/fields
             -> resolve/validate coordinates -> save to MySQL
```

### Import flow

```text
CSV/Excel
  -> POST /api/registry/upload
  -> upload_registry()
  -> optional places_resolver.py for missing coordinates
  -> official_registry
  -> geospatial_logs map pin
  -> sector_mapping.py for line-of-business classification
```

### Core import functions

| Function | What it does |
|---|---|
| [`upload`](../revela_backend/api/registry/routes.py#L380) | Receives the uploaded CSV/Excel file, validates the extension, and starts the initial registry import. |
| [`upload_registry`](../revela_backend/api/registry/service.py#L1192) | Reads, cleans, validates, geocodes, and inserts the uploaded registry rows. |
| [`sync`](../revela_backend/api/registry/routes.py#L415) | Receives a registry file for merge/update mode instead of replacing the initial registry import. |
| [`sync_registry`](../revela_backend/api/registry/service.py#L2746) | Merges incoming rows by business identity, updates changed records, and inserts new records. |
| [`uploadRegistryFile`](../revela_web/src/services/api.js#L364) | Frontend request that sends the selected file to `/registry/upload`. |
| [`syncRegistryFile`](../revela_web/src/services/api.js#L386) | Frontend request that sends the selected file to `/registry/sync`. |
| [`handleSubmit`](../revela_web/src/components/UploadModal.jsx#L206) | Upload-modal flow that chooses initial upload versus sync and displays the result summary. |

```text
UploadModal
  -> uploadRegistryFile()
  -> POST /api/registry/upload
  -> upload()
  -> upload_registry()
  -> clean/validate/geocode
  -> official_registry + geospatial_logs
  -> sync_imported_registry_sector_values()
```

## 2. PSIC Auto-Sector Mapping

| File | Role |
|---|---|
| [`revela_backend/data/No. Of Business Per Line of Business (1).xlsx`](../revela_backend/data/No.%20Of%20Business%20Per%20Line%20of%20Business%20%281%29.xlsx) | PSIC workbook used as the master list of lines of business. |
| [`scripts/load_psic_sector_master.py`](../scripts/load_psic_sector_master.py) | Loads/version-controls the workbook and materializes PSIC database tables. |
| [`revela_backend/api/analytics/sector_mapping.py`](../revela_backend/api/analytics/sector_mapping.py) | Normalizes line-of-business text, matches PSIC lines, and writes sector mappings. |
| [`revela_backend/api/analytics/display_sector_defaults.json`](../revela_backend/api/analytics/display_sector_defaults.json) | Maps PSIC Major Types to dashboard display sectors. |
| [`revela_backend/api/analytics/sector_risk.py`](../revela_backend/api/analytics/sector_risk.py) | Stores and validates sector policy scores used by OPS. |
| [`revela_backend/migrations/20261029_01_psic_sector_mapping.sql`](../revela_backend/migrations/20261029_01_psic_sector_mapping.sql) | Creates the PSIC and sector-mapping tables. |
| [`revela_backend/docs/prescriptive_wlc_model.md`](../revela_backend/docs/prescriptive_wlc_model.md) | Documentation for sector policy and WLC behavior. |

### Automatic mapping during import

After a successful import or sync, the registry service calls
`sync_imported_registry_sector_values(...)`. The result is stored in
`registry_sector_map`; unmatched or ambiguous values go to the review queue.

```text
lineOfBusiness
  -> normalize_sector_text()
  -> decompose_registry_activity()
  -> PSIC Major Type
  -> display sector
  -> registry_sector_map
```

### Function-level map

| Function | What it does |
|---|---|
| [`read_psic_workbook`](../revela_backend/api/analytics/sector_mapping.py#L34) | Reads the PSIC workbook rows. |
| [`clean_major_type`](../revela_backend/api/analytics/sector_mapping.py#L27) | Cleans PSIC Major Type labels. |
| [`decompose_registry_activity`](../revela_backend/api/analytics/sector_mapping.py#L79) | Finds exact/longest-prefix PSIC matches and detects ambiguity. |
| [`display_sector_for_major`](../revela_backend/api/analytics/sector_mapping.py#L74) | Converts a PSIC Major Type to a dashboard sector. |
| [`sync_registry_sector_values`](../revela_backend/api/analytics/sector_mapping.py#L184) | Stores matched, combo, ambiguous, and unmatched mapping results. |
| [`sync_imported_registry_sector_values`](../revela_backend/api/analytics/sector_mapping.py#L253) | Runs sector-map synchronization after import/sync without rolling back the completed import. |

## 3. Map Pinning

| File | Role |
|---|---|
| [`revela_backend/api/registry/service.py`](../revela_backend/api/registry/service.py) | Creates and updates registry-backed geospatial pins. |
| [`revela_backend/api/registry/places_resolver.py`](../revela_backend/api/registry/places_resolver.py) | Places Text Search and Geocoding resolution logic. |
| [`revela_backend/api/registry/inspection_link.py`](../revela_backend/api/registry/inspection_link.py) | Links registry records, pins, and confirmed inspection locations. |
| [`revela_backend/api/registry/reverify.py`](../revela_backend/api/registry/reverify.py) | Re-checks existing pins and decides verified, moved, review, or unresolved. |
| [`revela_backend/api/registry/routes.py`](../revela_backend/api/registry/routes.py) | Snap Pins and Re-verify API routes. |
| [`revela_web/src/pages/RegistryPage.jsx`](../revela_web/src/pages/RegistryPage.jsx) | Pin workflow controls and progress display. |
| [`revela_web/src/pages/MapPage.jsx`](../revela_web/src/pages/MapPage.jsx) | Map display and detection-related pin UI. |

### Pin workflow summary

```text
Snap Pins:  no/reliable coordinates -> Text Search -> Geocoding fallback -> save pin
Reconcile:  existing Red flags -> local registry matching -> update status
Reverify:   existing coordinates -> Text Search/check -> keep, move, review, or unresolved
```

### Pinning functions

| Function | What it does |
|---|---|
| [`resolve_location`](../revela_backend/api/registry/places_resolver.py#L478) | Runs the location-resolution flow for a registry business. |
| [`_text_search`](../revela_backend/api/registry/places_resolver.py#L402) | Calls Places Text Search (New) and ranks candidates. |
| [`_geocode_fallback`](../revela_backend/api/registry/places_resolver.py#L428) | Uses Geocoding when Text Search cannot produce a usable result. |
| [`snap_unresolved_pins`](../revela_backend/api/registry/service.py#L3516) | Batch-processes registry businesses with missing or unresolved pins. |
| [`reverify.run`](../revela_backend/api/registry/reverify.py#L517) | Rechecks existing coordinates and records verified/moved/review outcomes. |

## 4. Run Detection

| File | Role |
|---|---|
| [`revela_backend/api/flags/service.py`](../revela_backend/api/flags/service.py) | Quick Discovery, Full Coverage, Nearby Search, matching, checkpoints, and reconciliation. |
| [`revela_backend/api/flags/routes.py`](../revela_backend/api/flags/routes.py) | Run Detection, cancel, quota, and progress endpoints. |
| [`revela_backend/api/models/detection_runs.py`](../revela_backend/api/models/detection_runs.py) | Detection-run persistence and usage tracking. |
| [`revela_backend/api/utils/barangay_points.json`](../revela_backend/api/utils/barangay_points.json) | Precomputed barangay representative points used by Quick Discovery. |
| [`revela_backend/api/utils/barangay_points.py`](../revela_backend/api/utils/barangay_points.py) | Loads and validates representative-point data. |
| [`scripts/generate_barangay_centroids.py`](../scripts/generate_barangay_centroids.py) | Generates deterministic interior representative points from barangay polygons. |
| [`revela_web/src/pages/MapPage.jsx`](../revela_web/src/pages/MapPage.jsx) | Detection mode selector, confirmation modal, progress, and cancellation UI. |
| [`revela_web/src/components/DashboardLayout.jsx`](../revela_web/src/components/DashboardLayout.jsx) | Receives detection SSE progress events. |

### Detection API services

```text
Quick Discovery / Full Coverage -> Nearby Search
Reconcile                       -> no Google API; database matching
```

### Core scanning flow

| Function | What it does |
|---|---|
| [`run_detection_route`](../revela_backend/api/flags/routes.py#L115) | API entry point for the Run Detection button; validates the mode and persists the workflow result. |
| [`runDetectionRequest`](../revela_web/src/services/api.js#L738) | Frontend request that starts a Quick Discovery or Full Coverage scan. |
| [`handleRunDetection`](../revela_web/src/pages/MapPage.jsx#L3786) | Map-page action that confirms and starts the selected detection mode. |
| [`handleCancelDetection`](../revela_web/src/pages/MapPage.jsx#L4549) | Map-page action that requests cancellation of an active scan. |
| [`run_detection`](../revela_backend/api/flags/service.py#L2741) | Prevents overlapping scans and starts one detection cycle. |
| [`_run_detection_cycle`](../revela_backend/api/flags/service.py#L2750) | Loads the registry, reconciles existing flags, scans points, matches Places results, and commits detection outcomes. |
| [`_detection_points_for_mode`](../revela_backend/api/flags/service.py#L1575) | Chooses Quick Discovery points or the Full Coverage grid. |
| [`_quick_discovery_points`](../revela_backend/api/flags/service.py#L1425) | Builds and ranks representative-point/offset candidates, capped at 24 points. |
| [`_grid_points`](../revela_backend/api/flags/service.py#L1506) | Builds the regular Full Coverage grid. |
| [`_fetch_point_results_for_mode`](../revela_backend/api/flags/service.py#L2084) | Chooses one lightweight Nearby Search request for Quick Discovery or adaptive refinement for Full Coverage. |
| [`_fetch_point_results_adaptive`](../revela_backend/api/flags/service.py#L2088) | Splits saturated Full Coverage search areas into smaller overlapping circles. |
| [`_scan_grid`](../revela_backend/api/flags/service.py#L2190) | Iterates through scan points, filters results to the municipality, processes them, and checkpoints completed points. |
| [`_match_poi_to_registry`](../revela_backend/api/flags/service.py#L702) | Matches a discovered Google place against the imported official registry. |
| [`reconcile_existing_flags`](../revela_backend/api/flags/service.py#L1162) | Rechecks existing Red flags against the registry without another Google request. |
| [`cancel_detection_route`](../revela_backend/api/flags/routes.py#L105) | Receives cancellation requests for an active scan. |

```text
Run Detection button
  -> runDetectionRequest()
  -> POST /api/flags/run-detection
  -> run_detection()
  -> _run_detection_cycle()
  -> choose points
  -> Nearby Search
  -> filter and deduplicate places
  -> match against official_registry
  -> create/update/reconcile flags
  -> checkpoint and return summary
```

## 5. JSON and GeoJSON Storage

These are reference/configuration files. The primary registry, map-log,
inspection, and analytics data is stored in MySQL.

| File | Role |
|---|---|
| [`revela_backend/api/utils/barangay_points.json`](../revela_backend/api/utils/barangay_points.json) | Precomputed barangay centroids and deterministic interior representative points for Quick Discovery. |
| [`revela_backend/api/utils/mataasnakahoy_mpdo_compatible.json`](../revela_backend/api/utils/mataasnakahoy_mpdo_compatible.json) | Canonical barangay boundary source used by the point generator. |
| [`revela_backend/api/utils/mataasnakahoy.json`](../revela_backend/api/utils/mataasnakahoy.json) | GeoJSON boundary data used by hotspot polygon attribution and spatial checks. |
| [`revela_backend/api/utils/adm4_en_barangay_ids.json`](../revela_backend/api/utils/adm4_en_barangay_ids.json) | Maps GeoJSON `ADM4_EN` names to database barangay IDs. |
| [`revela_backend/api/utils/barangay_points.py`](../revela_backend/api/utils/barangay_points.py) | Loads and validates `barangay_points.json`. |
| [`revela_backend/api/analytics/display_sector_defaults.json`](../revela_backend/api/analytics/display_sector_defaults.json) | Maps PSIC Major Types to dashboard display sectors. |
| [`revela_backend/api/analytics/sector_risk_policy.json`](../revela_backend/api/analytics/sector_risk_policy.json) | Sector policy-score configuration used by OPS. |
| [`revela_backend/api/analytics/wlc_config.json`](../revela_backend/api/analytics/wlc_config.json) | WLC defaults/configuration support, including weights and BPLO coordinates. |
| [`revela_backend/data/No. Of Business Per Line of Business (1).xlsx`](../revela_backend/data/No.%20Of%20Business%20Per%20Line%20of%20Business%20%281%29.xlsx) | PSIC workbook input; it is loaded into MySQL master tables. |

### Point and boundary flow

```text
Canonical GeoJSON + barangay ID mapping
  -> generate_barangay_centroids.py
  -> barangay_points.json
  -> barangay_points.py
  -> Quick Discovery representative points
```

## 6. Analytics Pipeline

| File | Role |
|---|---|
| [`revela_backend/api/analytics/routes.py`](../revela_backend/api/analytics/routes.py) | Analytics API endpoints and the descriptive, diagnostic, prescriptive, and operations pipeline. |
| [`revela_backend/api/analytics/filters.py`](../revela_backend/api/analytics/filters.py) | Parses analytics filters and builds SQL fragments. |
| [`revela_backend/api/analytics/hotspots.py`](../revela_backend/api/analytics/hotspots.py) | DBSCAN hotspot population, Haversine distance, clustering, and summaries. |
| [`revela_backend/api/analytics/scoring.py`](../revela_backend/api/analytics/scoring.py) | OPS/WLC scoring: risk, PSIC sector, proximity, and municipal ranks. |
| [`revela_backend/api/analytics/dispatch.py`](../revela_backend/api/analytics/dispatch.py) | Converts rankings into inspector deployment recommendations. |
| [`revela_backend/api/analytics/non_registry.py`](../revela_backend/api/analytics/non_registry.py) | Builds monitoring data for linked and non-registry pins. |
| [`revela_backend/api/analytics/service.py`](../revela_backend/api/analytics/service.py) | WLC configuration persistence and validation. |
| [`revela_web/src/pages/AnalyticsPage.jsx`](../revela_web/src/pages/AnalyticsPage.jsx) | Analytics dashboard UI. |
| [`revela_web/src/services/analyticsLoader.js`](../revela_web/src/services/analyticsLoader.js) | Loads and caches analytics sections. |
| [`revela_web/src/services/api.js`](../revela_web/src/services/api.js) | Frontend analytics API requests. |

### Analytics functions

| Function | What it does |
|---|---|
| [`cluster_hotspot_rows`](../revela_backend/api/analytics/hotspots.py#L318) | Runs Haversine-based DBSCAN and summarizes hotspot clusters. |
| [`_distance_m`](../revela_backend/api/analytics/hotspots.py#L306) | Calculates geographic distance in meters for hotspot checks. |
| [`weighted_burden`](../revela_backend/api/analytics/scoring.py#L23) | Converts Red/Yellow/Black counts into weighted flag burden. |
| [`haversine_km`](../revela_backend/api/analytics/scoring.py#L37) | Calculates straight-line distance from BPLO to the barangay target location. |
| [`calculate_rankings`](../revela_backend/api/analytics/scoring.py#L63) | Computes Risk, Sector, Proximity, OPS, and global barangay ranks. |
| [`weighted_sector_score`](../revela_backend/api/analytics/sector_risk.py#L217) | Averages PSIC sector policy scores, including neutral fallback entities. |
| [`generate_recommendations`](../revela_backend/api/analytics/dispatch.py#L143) | Converts OPS rankings into inspector deployment recommendations. |

### Analytics sections

```text
Descriptive  -> totals, status counts, barangay and sector distributions
Diagnostic   -> DBSCAN hotspots and spatial diagnostics
Prescriptive -> OPS/WLC ranking and inspector deployment recommendations
Operations   -> inspector workload, inspection status, and timelines
```

## 7. Quick “Where do I start?” Index

- **Import is failing:** start at [`registry/service.py`](../revela_backend/api/registry/service.py).
- **Missing coordinates:** inspect [`places_resolver.py`](../revela_backend/api/registry/places_resolver.py).
- **Sector is “Needs classification”:** inspect [`sector_mapping.py`](../revela_backend/api/analytics/sector_mapping.py) and the [PSIC loader](../scripts/load_psic_sector_master.py).
- **Quick Discovery points:** inspect [`flags/service.py`](../revela_backend/api/flags/service.py) and [`barangay_points.json`](../revela_backend/api/utils/barangay_points.json).
- **Hotspot calculation:** inspect [`hotspots.py`](../revela_backend/api/analytics/hotspots.py).
- **OPS score:** inspect [`scoring.py`](../revela_backend/api/analytics/scoring.py).
- **Inspector allocation:** inspect [`dispatch.py`](../revela_backend/api/analytics/dispatch.py).
- **What the user sees:** inspect [`AnalyticsPage.jsx`](../revela_web/src/pages/AnalyticsPage.jsx).
