# Database structure reference — do not execute

`current_database_structure.sql` is a structure-only reference export, **not a
migration**. It contains `DROP TABLE` and session/global settings and must never
be run against an application database. It is kept outside `migrations/` so it
cannot be mistaken for an executable change. Its SQL contents are unchanged.

Use an explicitly approved, guarded migration for any schema change; this
reference alone does not establish the state of a live database.
