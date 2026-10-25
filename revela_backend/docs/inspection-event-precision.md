# Inspection event precision (manual rollout)

The exported `inspection_lifecycle_events.eventTimestamp` is `DATETIME(0)`;
the application supplies `UTC_TIMESTAMP(6)`, whose fraction is currently lost.
`enforcement_events.createdAt` is `DATETIME(6)` but previously used its
session-local `CURRENT_TIMESTAMP(6)` default. The matching application update
explicitly writes `UTC_TIMESTAMP(6)` for all new enforcement events, including
Orange pin warnings. Future cross-table comparisons then use the same clock.

After reviewing a backup and the selected database, run the guarded script
`scripts/migrate_inspection_lifecycle_precision.py --expect-database NAME`
without `--apply` for a preflight. An authorized operator may separately use
`--apply --acknowledge-backup`. **No app startup or import applies this change.**
The migration is an `ALTER TABLE`, which MySQL auto-commits; it must not be
treated as part of an application transaction. Deploy the matching UTC event
writer with the schema change so new warning and verification timestamps use
the same UTC basis and retain microseconds.

Existing second-precision inspection events become `.000000`; the real order
of events inside those seconds cannot be reconstructed. Older enforcement
events may also have been recorded in a non-UTC session time zone. Do not
invent fractions, rewrite old timestamps, or ignore later warnings. The
current compliance evidence query remains conservative for ambiguous history;
an explicitly reviewed historical resolution would require independent audit
evidence, not an automatic backfill.
