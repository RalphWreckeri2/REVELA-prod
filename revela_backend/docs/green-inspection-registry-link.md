# Green inspection → official registry link

## Deployment

For the deployed review-route 404/preflight investigation and rollout checks, see
[`green-registry-link-deployment.md`](green-registry-link-deployment.md).

Apply `migrations/20261021_01_confirmed_registry_pin.sql` after the existing
enforcement-state migrations and then
`migrations/20261021_02_compliance_confirmation_event.sql`, before deploying
the updated backend and web UI.
The migration adds only:

- nullable `official_registry.confirmedLogID`;
- a unique index on that reference (one registry identity per confirmed pin);
- a foreign key to `geospatial_logs.logID`, with deletion/update restricted.

The existing registry Business ID primary key and
`geospatial_logs.businessID` foreign key continue to enforce registry identity.
No data backfill, automatic name match, or bulk Green conversion is performed.
Green confirmations fail closed if the required schema is unavailable. Read
paths retain compatibility with a database that has not received the new column.
The migration has been executed only on a disposable test database.

## Admin workflow

1. The inspector submits the result and evidence through the existing workflow.
2. For a Submitted **Green** result, the admin enters the official Business ID.
   An actual existing pin link is displayed read-only and must also be reviewed.
3. **Review Business ID** performs a read-only exact-ID lookup and shows the
   registry identity beside the original inspected pin. It changes no status.
4. An existing registry record must agree on barangay and either its normalized
   name or an agreeing Place ID. Conflicting nonempty Place IDs, another
   confirmed pin, a different existing Business ID, or another linked field
   pin/inspection history refuse the link. Resolve an identity mismatch before
   retrying; name similarity never selects a registry record.
5. If no registry record exists, its required name and barangay are reused from
   the pin. The UI requests only a missing required value. Optional details,
   including addresses, business types and renewal dates, remain null when
   unknown. A landmark is not treated as an official street address.
6. The admin attests that the official ID/details match the inspection evidence,
   then confirms. The server rechecks the reviewed identity under row locks.
   Changed identity details require another review.

The confirmation saves the registry record/link, report verification, applicable
enforcement state and existing lifecycle audit event in one transaction. Failures
roll everything back; concurrent or repeated confirmations cannot create another
registry identity or verification event. IDs use the same normalization as
imports (trim, optional leading `#`, uppercase) and reject empty/placeholder IDs,
unsupported characters and values longer than the existing 50-character column.

The original log ID, coordinates, source, evidence and inspection history are
retained. Green confirmation does not offer an inspector-GPS relocation option.
Old uninspected registry-generated markers can remain as historical rows; map
counts/results and registry readers select only the confirmed pin. Other field
pins with a competing link require explicit conflict resolution.

Black locks, revoked permits, warning handling and inspector/admin role gates
remain enforced. A warning on a newly linked unregistered pin is retained and
mirrored into business enforcement state. A legacy single-use Black dispatch
grant can record a finding for its already linked pin but cannot move/recolour
the pin, change permit standing, or adopt an unlinked pin.

Real map pins cannot be changed directly to Green through the manual color
endpoint. Office reactivation of a closed field pin uses Business ID review and
the audited compliance-confirmation flow; registry-only records retain their
direct status-correction action.

## Clearing an Orange warning as compliance

An admin Clear Warning action means the office has confirmed compliance from
its own records; it does not require another inspector visit or a business
account. For a linked Registry business, the existing Business ID is used. The
action atomically clears the warning, sets `applicationStatus = 'Active'`, and
updates linked pins to Green while preserving Black-lock and open-inspection
protections and recording the actor, reason/reference, and warning history.

For an unregistered field pin, the admin must enter the official Business ID
and review the exact Registry identity against the original pin before
confirming. If there is no Registry record yet, the record is created from the
pin's name and barangay, linked to the original pin, activated, and made Green
in the same transaction. Identity conflicts, stale reviews, Black locks,
revoked permits, and pending inspections are refused without partial writes.
The office retains the compliance evidence; an optional reason/reference is
stored in the enforcement audit event.

## Office-confirmed compliance

An admin can confirm compliance on a Red, Yellow, or Purple pin when the office
already holds the supporting records, without dispatching an inspector. A
Purple field pin linked to a Closed Registry permit can be reactivated through
this reviewed flow. If the pin is not linked, the admin enters the official
Business ID and reviews its exact Registry identity against the pin; linked
pins use their existing ID. Confirmation activates the Registry record,
refreshes `lastRenewalDate` to the confirmation date, links the original pin,
sets it Green, and records a `compliance_confirmed` enforcement event
atomically. Clearing registered or pin-level warnings also refreshes the
renewal date. Active warnings, Black locks, revoked records, stale identity
reviews, and open inspections on the original pin or any linked, legacy
name/barangay-matched, or Place-ID-matched pin are refused.
This records office-confirmed compliance but does not fabricate a Green
inspector report or change inspection history.

## Import and Sync Registry

Both workflows match confirmed records by Business ID and share the same locked
update path. They update that existing registry row's business fields while
retaining `confirmedLogID` and copying coordinates only from the original pin.
CSV replacement coordinates, geocoding and barangay-centroid fallback never
replace that confirmed location. The helper updates the existing marker instead
of seeding another one. Source and inspection rows are not rewritten.

Open inspections, Black locks/revoked permits and Closed protections still skip
updates. Active-import warning clearing retains the existing policy. Import
continues to skip existing **unconfirmed** registry IDs; newly confirmed links
can be updated through Import as well as Sync. Neither workflow adopts an
unlinked field pin by name and barangay.

Detection, automatic pin updates, Snap Pins, Google-coordinate refresh and
coordinate expiry also preserve confirmed references. Copied registry
coordinates are marked approved, with unknown coordinate provenance left null;
the original source remains stored on the pin.

## API contract

- Admin-only `GET /api/inspections/{reportID}/warning-registry-link?businessID=…`
  previews the identity before clearing an Orange warning on an unregistered
  pin. Admin-only `POST /api/flags/{logID}/clear-warning` accepts the reviewed
  `reportID`, `businessID`, `registryReviewToken` and
  `confirmEstablishment: true`, plus an optional `reason`. A stale identity
  review or any enforcement conflict is refused without writes.
- Admin-only `GET /api/flags/{logID}/compliance-review?businessID=…` and
  `POST /api/flags/{logID}/confirm-compliance` review and confirm office-held
  Red/Yellow/Purple compliance without creating an inspection report.
- Admin-only `POST /api/registry/{businessID}/clear-warning` uses the existing
  registry ID and now marks the permit Active / Green as part of clearing the
  warning.
- Admin-only `GET /api/inspections/{reportID}/green-registry-link?businessID=…`
  returns registry/pin details, missing required fields and a review token.
- Existing admin-only `POST /api/inspections/{reportID}/verify` accepts:

  ```json
  {
    "businessID": "BPLO-001",
    "confirmEstablishment": true,
    "registryReviewToken": "token-from-review",
    "registryFields": {},
    "updateLocation": false
  }
  ```

  `registryFields` accepts only a missing `businessName` or `barangayID`.
  Validation errors return 400; identity/link/schema/concurrency conflicts return
  409. An already committed matching Green confirmation returns
  `alreadyVerified: true` without another write.
- Other inspection results keep their existing verification contract. Sending
  a Business ID alongside a non-Green result does not create a link or turn it
  Green.

## Isolated verification

From `revela_backend` (supply the installed local MySQL server executable):

```powershell
python scripts/run_registry_sync_audit.py --mysqld "C:\Program Files\MySQL\MySQL Server 8.0\bin\mysqld.exe" --temp-root "C:\Users\RUFFAA~1\AppData\Local\Temp\opencode" --test tests.test_green_registry_link_mysql --verbose
python scripts/run_isolated_unit_tests.py -q tests/test_inspection_clear_warning.py tests/test_verify_ladder_writes.py tests/test_black_dispatch_unlock.py tests/test_registry_import_hardening.py tests/test_registry_sync_open_inspection.py tests/test_relational_joins.py tests/test_lock_shield.py
python scripts/run_isolated_unit_tests.py -q tests/test_registry_pin_lateral.py tests/test_registry_manual_status_pin_sync.py tests/test_registry_only_source_label.py tests/test_verify_purple_registry_close.py tests/test_inspection_submission_idempotency.py tests/test_registry_snap.py tests/test_registry_derived_flag_color.py tests/test_geospatial_source.py
```

The MySQL runner initializes and destroys a separate data directory/schema on a
random loopback port. Application DB connections, dotenv loading, schedulers and
external HTTP are blocked. Fixtures contain only synthetic businesses. The
unit-test runner likewise blocks application DB connections and external HTTP.

Results:

- **25 MySQL tests passed**, including existing/new registry records, missing
  required details, missing/invalid/conflicting IDs, stale reviews, retries,
  same-report concurrency, two pins competing for one ID, database constraints,
  atomic rollback, role gates, enforcement safeguards, and subsequent
  import/sync retaining one original marker with zero location-resolution calls.
- **230 targeted backend tests and 96 subtests passed** across the two isolated
  unit-test commands above.
- `npm run test:green-link:browser`: **20 checks passed** with synthetic fetch
  responses and external DNS blocked by the local browser runner.
- Frontend lint, context checks, available unit-test scripts and production build
  passed. The aggregate `npm run verify` stops at the pre-existing missing file
  `src/components/mapMarkerPosition.test.js`; the later existing test scripts
  and build were run separately.

Broader legacy checks also exposed failures reproducible against the unmodified
HEAD implementation: `ManualEditRejectsBadStatusTests` in
`test_registry_status_validation.py` uses stale open-inspection mocks, and the
expiry cases in `test_registry_color_workflows.py` lack SQLite's `MAKEDATE`
function. These do not involve the new MySQL linking tests.
