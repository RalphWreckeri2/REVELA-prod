# Map filters and current-compliance report

## Implementation

- Flagged Locations offers Status, Source, Registry Link in that order, combined
  with AND logic and the existing search/barangay search. Map markers and the
  paginated location list receive the same complete filtered dataset. Counters
  reflect that view; detection scope/allowance and municipal priority rankings
  remain independent. The Map reads every API page before replacing its dataset.
- A shared custom combobox matches the Detection mode design, with keyboard
  navigation, focus restoration, Escape, outside-pointer and blur closing.
- Business details show the stored origin once below the address. Eligible
  unlinked businesses also show exactly:
  `Inspection-verified compliant · Not yet in imported registry`.
  The open detail uses refreshed data so linking removes this text immediately
  after refresh while preserving the source.
- Section 2 adds Inspection-Verified Compliant Businesses between Unregistered
  Businesses and the retained Dispatch Plan. It is independent of Section 1's
  registry-empty/loading/error state. View List has name/reference, barangay and
  registry-link filters, counts, pagination, clear/reset, retry and empty states.
- View List, CSV and the existing print/Save-as-PDF pipeline share one filtered
  report model. Exports refresh the same snapshot shown in the open list, and
  include every matching row, not just the visible page. CSV uses PapaParse with
  formula/quote/newline escaping and UTF-8 BOM. PDF includes title, scope,
  generation timestamp, applied filters, record count and all six columns.

## Exact definitions

**Source** is persisted `geospatial_logs.source`, projected as `originSource`.
`detection` = Business Detection; `manual` = Inspector Report; `registry` and
`registry_detected` = Official BPLO Registry (the latter is a registry business
also found by Places). Missing/unrecognized source is Unknown origin; it is
never silently classified as detection. Legacy `flagSource` compatibility is
retained for other readers, but the new Map/report do not use its guessed
fallback as provenance.

**Registry Link** on a real pin means its non-null `businessID` matches an
existing `official_registry.businessID`. Source, place/name matching used by
legacy color lookups, dangling IDs and similarity alone do not establish this
read-side relationship. A registry-only virtual location represents an actual
registry row and is linked by definition. Pin Reference is `logID`, never an
official Business ID.

**Current verified compliance** requires the existing shared effective-color
builder in `api/registry/colors.py` to return Green, plus reliable, applicable
Green verification evidence from `inspection_lifecycle_events` joined to its
current Verified/Green geospatial report. The event must have an actor and actual
verification timestamp, be the pin's latest lifecycle event, and still support
the stored Green pin. Later warning/Black enforcement invalidates older
evidence. The actor is attributed by the existing admin-only verification route;
historical actions are not reinterpreted using the actor's present-day role.

The details indicator adds the requirement of **no valid registry link**. The
report includes **source = detection** with either linkage state, and
**source = manual** only when there is no valid registry link. Registry,
registry-detected, unknown-origin and linked manual pins are excluded.
Orange warnings and Black locks exclude rows through the existing color rule.
Clear Warning does not itself supply Green inspection evidence and its workflow
is unchanged.

`Verified On` is the event's `eventTimestamp` (written by the existing
`UTC_TIMESTAMP(6)` writer), serialized with UTC `Z` and displayed consistently in
Asia/Manila. Dispatch, submission, import, update and detection times are not
used as substitutes.

## Direct import dependency

The earlier upload/new-sync branches unconditionally seeded new pins for many
new registry rows, including when a verified detected pin already existed. They
now reuse `_sync_flag_color` before seeding. Its established ID/name+barangay
association logic sets the actual imported foreign key and retains source,
logID, reports, and lifecycle history. New seed callers exclude unlinked pins
with any non-Verified inspection, preserving in-flight pin/report data. Other
callers retain their previous guards. No enforcement policy or source backfill
was added, and older ambiguous/duplicate records are not retroactively repaired.

## Verification and limitations

Final results on the feature working tree:

| Check | Result |
| --- | --- |
| Full backend suite | **986 passed, 23 failed, 28 skipped; 557 passing subtests** |
| Failure identity/cause comparison against 848303d | **0 new, 0 changed causes, 0 absent** |
| New backend feature cases (included in the full run) | **38 passed** |
| Frontend `npm run verify` | **Passed: lint, context checks, 167 tests, build** |
| Local Edge browser smoke | **22 checks passed** |

All 23 pre-feature failures still fail; none was repaired, skipped, weakened, or
declared correct. The CORS failure remains the documented offline-guard 500,
not a reverified MySQL 1045 credentials failure. The earlier saturated-edge
failure remains absent from both the recorded and final 23-failure sets.
Scheduler shutdown noise and the Vite large-chunk warning remain as documented.

The pre-feature baseline and its exact 23 failures are recorded separately in
`map_compliance_baseline_848303d.md` and `tests/feature_baseline_848303d.json`.
`scripts/verify_map_compliance.py` runs the entire backend suite offline,
compares failure identities/signatures and specific CORS/SQLite causes, and
retains pytest's failing exit status. It does not skip or xfail baseline tests.

New tests are confined to `tests/test_map_compliance.py`, frontend
`businessCompliance.test.js`, and the synthetic browser smoke harness. No
existing test was modified and there are no existing-test line-ledger entries.

Commands (from the respective backend/web directories):

```powershell
& "venv\Scripts\python.exe" -B "scripts\verify_map_compliance.py"
npm run verify
npm run test:business-compliance:browser
```

Browser smoke uses local Edge and a disposable profile under the approved temp
directory. Backend HTTP is replaced with synthetic responses and external DNS
is blocked. It exercises real dropdowns, the Map/details, the full Export Reports
page with an empty registry, report pagination/filtering/error/retry, and all-row
CSV/PDF-print DOM results at an 820px viewport. Downloads/printing are captured
in memory; it does not certify native PDF-driver output or live Google markers.
Backend workflow checks execute real color/evidence/import SQL using the
existing SQLite adapter; the 28 opt-in disposable-MySQL tests remain skipped in
ordinary discovery. Live MySQL concurrency, production data and real external
providers were not exercised.

Legacy rows with unknown provenance, missing actor/verification timestamp,
missing lifecycle events, or superseded evidence are conservatively excluded
from the report. No history or missing permit details are invented.
No schema changes, official-registry creation workflow, official Business IDs,
mobile changes, migrations/backfills, deployment or push are part of this work.

## File manifest

Modified existing application/configuration files:

- `revela_backend/api/flags/routes.py`
- `revela_backend/api/flags/service.py`
- `revela_backend/api/registry/service.py`
- `revela_web/package.json`
- `revela_web/src/pages/MapPage.jsx`
- `revela_web/src/pages/ExportReportsPage.jsx`
- `revela_web/src/services/api.js`
- `revela_web/src/styles/MapPage.css`
- `revela_web/src/styles/ExportReportsPage.css`

Added application files:

- `revela_backend/api/flags/compliance.py`
- `revela_backend/api/flags/compliance_report.py`
- `revela_web/src/components/businessCompliance.js`
- `revela_web/src/components/FilterDropdown.jsx`
- `revela_web/src/components/ComplianceReportCard.jsx`
- `revela_web/src/styles/FilterDropdown.css`

Added tests, verification assets and documentation:

- `revela_backend/tests/test_map_compliance.py`
- `revela_backend/tests/feature_baseline_848303d.json`
- `revela_backend/scripts/verify_map_compliance.py`
- `revela_backend/docs/map_compliance_baseline_848303d.md`
- `revela_backend/docs/map_compliance_feature.md`
- `revela_web/src/components/businessCompliance.test.js`
- `revela_web/scripts/compliance-smoke.html`
- `revela_web/scripts/compliance-smoke.jsx`
- `revela_web/scripts/verify-compliance-browser.mjs`

Existing tests modified: **none**. Commits created: **none**.
