# Registry import / inspection auto-sync audit — 2026-10-15

## Result

Audited tracked baseline **`b7af780`** and reproduced behavior with real
**MySQL 8.0.46 / InnoDB**, synthetic registry rows, reports, and lifecycle events.
No production database, dotenv file, or external provider was used by the audit
runner. The existing local MySQL service was not used: each run starts a new
server with `--no-defaults`, a temporary datadir, and a random loopback port.

Earlier work was present:

- `98f6950`: preserve a verified Orange warning when the permit is expired.
- `7d559d8`: Business ID matching, normalized change detection, unchanged counts,
  and immediate annual permit-expiration derivation during import.
- Existing manual/approved coordinate locks and location reapproval safeguards.
- Existing offline report identity, assignment-cycle, timestamp, and retry guards.

Those safeguards were incomplete. Confirmed problems and focused corrections:

1. **Verified Black/Purple outcomes could be overwritten even by an unchanged
   file.** Map reads and analytics could independently display the permit color
   over the field finding. A shared effective-color rule now protects a
   still-applied verified Black/Purple outcome. Permit fields still update.
2. **Redispatch could remove Orange protection.** Redispatch deliberately reuses
   and clears the report row. Color resolution now consults the latest persisted
   `verified` lifecycle event, with Verified reports as the legacy fallback.
3. **A stale import snapshot could overwrite a newly verified Orange warning.**
   The decision now executes inside the `UPDATE geospatial_logs` statement, so
   InnoDB evaluates it against current committed/locking-read data.
4. **A renamed legacy business could acquire a second map pin.** If its old pin
   had no `businessID`, the incoming new name no longer found it. Sync now binds
   old-name/barangay pins before changing location-identifying registry fields,
   only when that old registry name/barangay identifies one registry business.
   It retains the original `logID`, report targets, and events.
5. **Failed imports could leave pending or partially committed registry writes.**
   Import exceptions now roll back and close their cursor. Places/Geocoding
   quota reservations and cold settings-table initialization use independent
   connections: their `BEGIN`, commits, and implicit DDL commits cannot commit
   business-import writes. Quota reservations themselves remain durable.

The same effective-color rule is used by registry flag updates, map output and
filters, analytics color expressions, same-pin detection rematching, and annual
expiry. Fixing just the stored import color would have left contradictory map
and analytics results.

## Identity and ownership

### IDs

- The file's external BPLO **Business ID** becomes
  **`official_registry.businessID`**. Headers such as `businessID`,
  `business_id`, `Business Identification No`, and even generic `id` / permit
  number aliases are normalized to this external field by `COLUMN_MAP`.
- IDs are read as strings, trimmed, stripped of a leading `#`, and uppercased.
  String leading zeros are retained. Sync performs
  `SELECT ... WHERE businessID = %s` followed by `UPDATE ... WHERE businessID = %s`.
- This is distinct from the internal **`geospatial_logs.logID`** and
  **`inspection_reports.reportID`**. Current reports have
  `targetType='geospatial_log'` and `targetID=logID`. Assignment-cycle IDs identify
  dispatch/reassignment generations, not businesses.
- No separate registry surrogate-primary-key definition is checked in. The
  source treats external `businessID` as its registry relational key; the
  deployed table's exact primary-key/unique-index DDL was not queried. The test
  registry intentionally has an independent `fixtureRowID` primary key and a
  unique string `businessID` to verify that updates retain row identity and do
  not match by a surrogate or name.

### Registry writes

Sync updates normalized `businessName`, `businessType`, `lineOfBusiness`,
`businessAddress`, `barangayID`, `applicationStatus`, `lastRenewalDate`,
`businessSize`, and `registrationType`. The external Business ID is not replaced.

Coordinates and coordinate provenance/cache metadata can also update:
`latitude`, `longitude`, `coordSource`, `placeID`, `placeIDKind`,
`coordFetchedAt`, `matchScore`, `matchStatus`, and `resolveKey`.

- Manual/approved pins are retained. A changed approved address/barangay creates
  a registry location-review history entry and sets `matchStatus='review'`.
- Existing CSV pins without replacement file coordinates are retained.
- Map coordinates move only through the existing pin/provenance rules; report
  GPS evidence is a separate set of columns and is preserved.
- `registrationType` uses `COALESCE` to retain a missing imported value.
- Other optional registry columns are full-row import values and can become
  null when omitted/blank. Missing/unrecognized permit status becomes `Pending`.
  A prior-year renewal with imported `Active` becomes `Expired`; this is not an
  inspection transition. Owner names are parsed but not stored.

Related writes are map color / missing map coordinates, legacy Business ID
linking, quota usage, and location-review history when applicable. Import does
not write `inspection_reports` or `inspection_lifecycle_events`, dispatch an
inspector, verify a submission, or delete evidence files.

## Actual color meanings

Colors are **not** `verificationStatus` values. Current active assignments are
`Assigned` / `Reassigned`; submissions become `Submitted`, then an explicit admin
verification makes them `Verified`. `In Progress` also appears in the duplicate
dispatch guard as a legacy state, but current task listing/submission uses
Assigned/Reassigned. Preservation of a legacy In Progress row was tested too.

| Color | Meaning in the inspection workflow | Stored representation / permit-derived equivalent |
|---|---|---|
| Green | Registered / compliant | `flagColor='Green'`, optional report `inspectionResult='Green'`; registry `Active` derives Green |
| Yellow | Suspected / needs verification | `flagColor='Yellow'`, optional report result Yellow; registry `Pending` derives Yellow |
| Red | Unregistered / non-compliant; also expired permit | `flagColor='Red'`, optional report result Red; registry `Expired` derives Red |
| **Black** | **Blacklisted / Non-Responsive**, including final escalation | `flagColor='Black'`, report result Black when inspected; registry `Revoked` / legacy `Blacklisted` derives Black |
| **Purple** | **Closed / Abandoned** | `flagColor='Purple'`, report result Purple; registry `Closed` derives Purple |
| **Orange** | **Warned / Non-Compliant**, monitoring / notice escalation | `flagColor='Orange'`, report result Orange and `noticeLevel`; there is no registry `Orange` application status |

Sources: `_status_to_flag_color`, `_normalise_status`, mobile inspection result
chips, and `verify_inspection`. Import normalizes `Blacklisted` to `Revoked`.
Manual escalation to Black also writes registry Revoked. Verifying an inspection
Black result does **not** itself write registry Revoked; verifying Purple
explicitly writes registry Closed. These are distinct existing code paths.

Submission alone does not apply the chosen inspection color. Admin verification
applies it. A verified Orange warning overlays expired/unregistered compliance;
a current Active renewal can legitimately show Green while its historical report
still says Orange/Verified and retains the notice level and evidence.

A protected terminal finding must still be the applied map color and match the
latest verified result. An explicit admin color change or later verified result
can replace it. Permit-derived Black/Purple without that field-verification
provenance can change when authoritative permit information changes.

## Workflow trace

1. `revela_web/src/pages/RegistryPage.jsx` opens `UploadModal` with `variant='sync'`
   for **Import & sync**. `UploadModal.handleSubmit` calls `syncRegistryFile`.
2. `POST /api/registry/sync` calls `sync_registry` synchronously. It merges by
   external Business ID. `/api/registry/upload` calls `upload_registry`, which
   seeds new IDs and **skips existing IDs** instead of updating them.
3. Pandas parses CSV / Excel, columns and IDs normalize, required ID/name/barangay
   validation runs, location resolution/cache/locks apply, registry rows update
   or insert, and map flags synchronize inline. There is no record replacement.
4. Successful import commits and publishes `registry_updated`. `DashboardLayout`
   translates it to `revela:registry-update`; `MapPage` refetches flags. The map
   also polls every 20 seconds. This refresh does not submit or reset inspections.
5. Snap Pins / Re-verify and Reconcile / Run Detection are separate operations.
   Import does not automatically launch them. Separate duplicate reconciliation
   can intentionally repoint report targets and lifecycle targets before deleting
   redundant map logs; that is not an import operation.
6. Startup + midnight permit expiry and 03:00 coordinate refresh are separately
   scheduled in `app.py`. Import derives the annual permit rule directly; it does
   not invoke the scheduled expiry function for the whole registry.
7. Mobile inspection auto-sync independently persists an account-owned draft,
   uploads evidence, and posts report ID, log ID, assignment cycle, result,
   original submission instant, notes, and GPS. Reconnect checks run every ten
   seconds, with bounded retry timing. Backend `submit_inspection` locks the
   report, validates owner/target/cycle, and accepts equivalent retries without
   a second submission event. Changed retries/stale cycles produce a conflict.

## Before-and-after effects

These are isolated records; inspector `9` and evidence paths are synthetic.
“History preserved” means exact equality of every report column and existing
lifecycle-event row, including photo references, remarks, report GPS, deadline,
dispatch/submission/receipt timestamps, notice level, and resolution time.

| Scenario / before | Registry after import | Inspection status after | Color before → after fix | Assignment / history |
|---|---|---|---|---|
| Assigned / Reassigned business, size changes | New size stored on same Business ID / row | Same active state | Green → Green | Same inspector, report ID, target log ID; history preserved |
| Ongoing assignment, current permit replaced by expired / prior-year permit | `Expired` | Same active state | Green → Red | Preserved; import does not complete/cancel it |
| Verified Black, registry still Active; unchanged file | Still Active | Still Verified / result Black | Black → Black; baseline incorrectly changed it to Green | Preserved |
| Verified Purple, incoming Active permit | Permit becomes Active independently of field finding | Still Verified / result Purple | Purple → Purple; baseline could show Green | Preserved; no field reopening |
| Permit-derived Black/Purple, no matching verified terminal finding; incoming Active permit | Active | Any existing assignment/report state retained | Black/Purple → Green | Preserved; valid permit transition allowed |
| Verified Orange, expired permit remains expired | Expired | Still Verified / result Orange | Orange → Orange | Preserved |
| Verified Orange, current valid renewal | Active / current renewal date | Still Verified / result Orange | Orange → Green | Preserved, including original warning and notice level |
| Prior verified warning/terminal finding is being reinspected | Imported permit fields update | Still Reassigned | Eligible Orange / Black / Purple retained using durable verified event | Current assignment and old events preserved |
| Same file imported twice | First update; second `updated=0`, `unchanged=1` for equivalent row | Unchanged | Same applicable effective color | No duplicate registry row / pin / report / event |
| Business absent from file | Untouched by import | Unchanged | Unchanged by import | Preserved |
| Missing Business ID / repeated normalized Business ID | Invalid row skipped / first valid row wins | Unchanged | No effect from skipped row | Preserved; row errors returned |
| Legacy pin lacks Business ID and business is renamed | Same registry row; unambiguous old pin gains the stable Business ID | Unchanged | Verified terminal color retained | Original log ID retained; baseline created a second pin |
| Offline submission commits while/after registry update | Imported registry data retained | Assigned → Submitted because of the inspector submission | Permit baseline until explicit verification | Same assignment identity; evidence retained; one submitted event appended |
| Verification commits after import snapshot | Imported permit rule and current field outcome reconciled atomically | Verified remains Verified | Verified Orange on expired business stays Orange | Verification event/report not overwritten |

Changing the external Business ID is a different identity to this importer and
can create another registry business. Existing duplicate/ambiguous historical
records are not silently deduplicated by import. The new legacy binding does not
adopt pins belonging to a different explicit Business ID or an ambiguous old
registry name/barangay.

## Verification evidence

`scripts/run_registry_sync_audit.py` creates the disposable server and guards
against production app startup, normal MySQL connection creation, dotenv loading,
and real Requests HTTP. Only its fixed disposable connection factory reaches SQL.
There are no real photo uploads or notifications.

- **178 targeted backend tests passed**, including **28 real-MySQL integration
  tests** in `tests/test_registry_inspection_sync.py` and relevant existing
  registry, locking, map filtering, resolver/quota, settings, analytics, and
  submission-idempotency regressions.
- **38 Flutter tests passed** across offline sync reliability, isolated SQLite
  draft storage, and timestamp formatting. Dio uses the test adapter.
- The original source was re-executed **in memory** with `--baseline`; real SQL
  reproduced terminal-color loss, warning loss after redispatch, the verification
  race, quota/DDL partial commits, missing exception rollback, and a second pin
  on a legacy rename. Files were not reverted to perform the comparison.
- Stored colors, map unfiltered output, each of the six color filters, and the
  analytics effective-color SQL were checked for agreement.
- CSV and `.xlsx`, string external IDs with leading zeros, stable surrogate/log/
  report IDs, first/second imports, missing rows, missing/duplicate IDs, explicit
  admin changes, annual expiry, same-pin rematching, location reapproval, offline
  retry idempotency, and stale reassignment conflicts were exercised.
- A broader admin-settings run exposed the pre-existing
  `TestModeScopeTests.test_full_grid_when_test_mode_is_off` failure: **38 points
  returned vs 70 expected**. It also fails on baseline `b7af780`; this GIS
  expectation is outside the import fix and was not changed.

From `revela_backend` on this workstation:

```powershell
& "venv\Scripts\python.exe" "scripts\run_registry_sync_audit.py" --mysqld "C:\Program Files\MySQL\MySQL Server 8.0\bin\mysqld.exe" --temp-root "C:\Users\RUFFAA~1\AppData\Local\Temp\opencode" --unit-tests
```

Add `--baseline` to exercise tracked HEAD source rather than the working tree;
fixed-behavior regressions are expected to fail against the pre-fix baseline.
`--test` can select individual unittest names and `--verbose` prints test names.

From `revela_mobile`:

```powershell
flutter test --no-pub test/offline_sync_reliability_test.dart test/offline_inspection_storage_test.dart test/inspection_timestamp_test.dart
```

## Changed functions/files

- `api/models/flag_status.py`: latest verified outcome, permit baseline, effective
  color, and exact-ID-first registry lookup SQL.
- `api/registry/service.py`: `_sync_flag_color`, `sync_registry` legacy binding,
  import exception rollback, `_reserve_geocode_call`, annual expiry color update.
- `api/registry/places_resolver.py`: `reserve_call` transaction isolation.
- `api/models/app_settings.py`: `ensure_settings_table` DDL isolation.
- `api/flags/service.py`: `get_flags` output/filter agreement and same-pin
  `_match_registry_to_google` preservation.
- `api/analytics/routes.py`: effective color and warning expressions / enforcement
  progress use the corresponding field-finding rule.
- New disposable runner/integration suite; existing SQL-mock assertions updated
  for atomic color evaluation. One stale submission-test fixture was updated to
  supply its already-required Assigned state and receipt timestamp lookup.

## Limits and source-observed follow-ups

- Production DDL, existing production duplicates/constraints/indexes, already
  overwritten production colors, production performance, live Google/SSE,
  physical APK reconnect behavior, legacy `.xls`, and exhaustive multi-worker
  contention were not exercised. Concurrent SQL verification/submission checks
  use controlled interleavings on independent InnoDB connections, not a load test.
- The protection prevents future overwrites of still-applied verified terminal
  findings. It does not bulk-restore a historical Black/Purple pin that is already
  Green: that could undo an intentional admin change. Such recovery requires
  reviewing its history. No production records were repaired or migrated.
- The existing lifecycle-event table is required by the current inspection
  workflow and by the preservation query; no new application schema is added.
- Registry business-detail `inspectionHistory` still queries legacy
  `targetType='business'`, whereas current dispatched reports target
  `geospatial_log`. That view can therefore look empty without any import data
  deletion. Current inspector history and calendar use the current linkage.
- The archive HTML badge helper labels Purple as “RE-INSPECTION REQUIRED”, which
  conflicts with the actual Closed/Abandoned inspection and registry code. This
  pre-existing presentation discrepancy was identified from source and not
  changed as part of the import fix.

## Direct answer

**“Madadamay ba ang currently being inspected, BLACK, PURPLE, at ORANGE businesses
kapag nag-import at nag-auto-sync?”**

**Oo, maa-update pa rin ang kanilang registry/permit data. Pagkatapos ng fix,
hindi nire-reset o kinakansela ng import ang ongoing inspection, assignment,
reports, photos/evidence references, o history. Protected ang verified BLACK at
PURPLE field outcomes. Ang ORANGE ay mananatili kung expired pa rin ang permit,
pero puwedeng maging GREEN kapag valid na ang renewal; preserved pa rin ang
warning report at history. May totoong color-overwrite, legacy-linking, at
transaction bugs sa dating source; na-reproduce at naayos ang mga iyon.**
