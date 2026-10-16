# Map compliance feature — pre-feature baseline

Recorded before feature changes on clean `main`, commit `848303d`.
The user authorized proceeding with these **23 existing failures**, not treating
them as correct or resolved. Machine-readable identities and failure signatures:
`tests/feature_baseline_848303d.json`.

Full backend: **948 passed, 23 failed, 28 skipped, 557 passing subtests**.
Frontend `npm run verify`: passed (154 tests, lint, context checks, build;
existing Vite large-chunk warning).

## Isolation and comparison

Python: `revela_backend/venv/Scripts/python.exe`; pytest `tests -q --tb=short`.
Dotenv loading was disabled; a process-local test JWT secret supplied. Both
MySQL connection entry points and real Requests HTTP were blocked. Scheduler
`start` was mocked. Factory-based CORS tests registered shutdown callbacks for
unstarted schedulers, producing ignored exit-time noise, not test failures.
The 28 disposable-MySQL tests skip under ordinary discovery.

The current CORS 500 is caused by **`RuntimeError: Offline tests: database access
blocked`**, NOT the earlier accepted MySQL 1045 root@localhost failure. Actual
credentials were not tested. The grid-count (38 vs 70) and SSE missing-JWT-context
failures match the earlier fix-batch causes. The old saturated-edge failure is
absent: `848303d` changed its expected intersection count from 2 to >0; there is
currently 1 intersecting child and 3 excluded children.

## Read-only triage (no repairs authorized)

Earlier fix-batch documentation survives at
`6648ff4:revela_backend/docs/registry_inspection_fix_batch.md`. `4734e7f` deleted
it and historical migrations while separating enforcement state and changing
Black dispatch/deletion policy.

- Grid count: old geographic expectation, 38 returned / 70 expected (1).
- Release contract: deleted `20261014_01_yellow_flag_idempotency.sql`; the next
  referenced submission-timestamps migration is also absent (1).
- Virtual Black escalation: fixture renames B-1 to 5 without renaming its
  polymorphic enforcement subject, leaving an extra unlocked fixture row (1).
- Black edit/recolor/reverify: old fake SQL router does not recognize the
  `official_registry LEFT JOIN enforcement_state` read (6). Correct-query
  diagnostics refuse writes; real-pin recolor additionally returns a plain
  string instead of the old typed 409 conflict. That contract issue is unfixed.
- CORS: offline database guard produces 500 (1), as distinguished above.
- Pin deletion: new lock read exhausts old sequential mock responses (2).
- Unsafe warning clear: helper keyword mismatch, `warningBaseColor`/`blackLocked`
  versus `base_color`/`locked` (2).
- Black dispatch grant: obsolete success expectation; new grants are prohibited
  by current policy (1).
- Black verification: correct lock is written to enforcement_state; assertions
  still read the retired registry column (3).
- Virtual location edit: unconstrained MagicMock is interpreted as locked (1).
- SSE: fake bearer verification does not establish JWT claims (1).
- Expiry: SQLite lacks MAKEDATE and the current joined-UPDATE translation (2).
- Orange verification: sequential fixture omits enforcement-table/state reads (1).

The feature does not repair these tests, restore migration files, or change
these policies. Final verification must compare identities **and causes**,
report missing baseline failures, and stop for new/changed failures.

## Existing Green / warning boundary

An unlinked pin's Green verification does not clear an active warning: its
effective color stays Orange. `clear_pin_warning` restores the recorded
pre-warning color, not necessarily Green. Red → warning → Green verification
→ Clear Warning returns to Red; Yellow returns to Yellow; only a Green base
returns to Green. Unknown bases and Black locks refuse clearance. The feature
uses the resulting current effective color without changing this workflow.
