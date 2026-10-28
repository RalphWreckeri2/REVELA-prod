# Database Backup UI integration

## Reconciled worktrees

The current `main` checkout (`0275fee`) is a descendant of Sol's
`backup-volume-preparation` checkout (`498c573`), so no commit merge was needed.
Sol's backup implementation and tests were uncommitted in that other worktree.
Their source files were added here without modifying that checkout. The current
worktree's newer uncommitted Settings UI/status changes were retained and
connected to the existing implementation rather than replaced by Sol's older
panel. Both worktrees remain uncommitted.

## Integrated behavior

- The Settings page reads `GET /api/admin-settings/database-backup/status`.
  It reads the durable artifact catalog, reports status/history, and returns
  private `no-store` responses. Browser status/manual/download routes use the
  existing `admin_required()` authorization.
- **Back Up Now** calls `POST /api/admin-settings/backups/run`. A manual job
  runs asynchronously through the existing exporter and shares the OS lock and
  source-server advisory lock with other jobs. `DB_BACKUP_ENABLED=0` remains
  the global execution kill switch.
- Completed history rows download through
  `GET /api/admin-settings/backups/<id>/download`; no public/static artifact
  URL is returned. The endpoint streams the private file and checks its SHA-256
  and length, requires authentication, and sets `private, no-store`.
- Volume storage is limited to the dedicated
  `revela-database-backups/` subdirectory of the configured mount. Atomic
  receipts, integrity checks, free-space preflight, and path/symlink guards
  protect unrelated volume contents. The adapter does not clean or relocate
  inspection evidence.
- The exporter remains database-only and uses a read transaction. Remote MySQL
  requires both certificate and hostname TLS verification. The existing
  restore tooling refuses a target unless it is explicitly isolated.
- Weekly scheduling is Friday at **7:00 PM Asia/Manila**. The last successful
  weekly export of each month is marked and preserved as the monthly archive.
  The proposed count-based retention is the four newest successful weekly
  copies plus the three newest monthly archives. Manual backups are a separate
  category with a **proposed 30-day retention**, not yet approved. Cleanup is
  off by default and requires `DB_BACKUP_CLEANUP_ENABLED=1` in addition to
  `DB_BACKUP_ENABLED=1`. No existing artifact was deleted.
- Automatic execution has a separate `DB_BACKUP_SCHEDULE_ENABLED=0` switch.
  Enabling `DB_BACKUP_ENABLED` for an explicitly approved manual export does
  not start the weekly scheduler. Both flags default to off; no scheduler or
  export runs in the default configuration.
- The external workflow in
  `.github/workflows/database-backup-trigger.yml` runs Fridays at 11:00 UTC
  (7:00 PM Asia/Manila), POSTs to the protected API trigger, then polls the
  durable job receipt for at most 60 minutes. The API remains the executor and
  writes to its existing configured storage; no separate worker/volume is
  involved. The trigger uses a bearer secret, an idempotency key, the existing
  job locks, and a bounded catch-up window: a weekly slot remains eligible
  from its Friday 7:00 PM Asia/Manila time until immediately before the next
  Friday slot (less than seven days). The API chooses the latest due slot, so
  a GitHub schedule delivered more than 15 minutes late still starts that
  week's backup. Same-key retries return the same job; different runs cannot
  create a second backup for a completed weekly slot, and overlapping jobs are
  rejected. API sleeping remains untouched; the trigger and polling requests
  wake/keep the API responsive as needed.
- Automatic execution is still disabled and not ready. The workflow is local
  only and undeployed; `DB_BACKUP_EXTERNAL_TRIGGER_ENABLED=0`,
  `DB_BACKUP_ENABLED=0`, and `DB_BACKUP_SCHEDULE_ENABLED=0`. Readiness must not
  be marked true until the workflow and both private secrets are installed,
  the runtime has been verified, and the isolated restore/cost gates pass.

## Status and history contract

The panel status is one of `not_configured`, `ready`, `running`, or `failed`.
`configured` reflects validated runtime configuration; `canManualBackup`
additionally requires the global execution switch. `schedule.enabled` and
`nextRunAt` are only reported when all automatic-readiness gates pass. The history is `null` when configuration
prevents querying storage and an array (possibly empty) when the catalog was
read successfully. Successful records contain actual IDs, timestamps, trigger,
size, and monthly-archive designation; failed/running records come from the
durable status ledger.

Status, manual execution, and downloads never treat frontend visibility as an
authorization boundary. Each backend route checks current admin authorization.
The downloaded archive is resolved by validated backup ID from private storage,
not from a client-supplied path.

The external scheduler is not an admin browser. Its `POST
/api/admin-settings/database-backup/trigger` and `GET
/api/admin-settings/database-backup/trigger/<job-id>` endpoints require
`Authorization: Bearer <DB_BACKUP_TRIGGER_TOKEN>`; the token must be at least
32 characters and is compared in constant time. The POST additionally requires
the global, schedule, and external-trigger switches, a valid runtime
configuration, a valid `Idempotency-Key`, and the current weekly slot's
bounded catch-up window. Both endpoints return `private, no-store`; the status
endpoint exposes only the matching job's safe state/result. The trigger status
is persisted in the existing backup state/catalog storage.

## Unresolved activation requirements

The implementation is prepared locally, but do not activate any execution or
cleanup switch until the following are resolved:

1. **MySQL/client match.** Railway's production MySQL metadata was read on
   2026-10-29 through the Railway SSH tunnel using read-only system-variable
   queries. It reported MySQL Community Server **9.7.4**, allowed TLS
   versions `TLSv1.2,TLSv1.3`, and
   `require_secure_transport=OFF`. A TLS cipher was negotiated inside the SSH
   tunnel; this did **not** verify the remote MySQL certificate or hostname
   for the application's direct connection. The old local `tls-preflight`
   `ValueError` is not evidence of a live TLS failure. The Docker image now
   pins Oracle APT component `mysql-9.7-lts` and package
   `9.7.4-1debian12`; the official Oracle package index was checked for that
   package. Runtime `mysqldump` version checking remains enabled. CI image
   build passed on commit `50cadc1` using the standard Linux runner and
   `docker.io/library/python:3.13-slim-bookworm`; the Dockerfile now uses that
   same base-image reference by default. The first attempt against Amazon ECR
   Public returned HTTP 429 (`toomanyrequests: Data limit exceeded`); no image
   was deployed, published, or uploaded as an artifact.

   Build after review with the verified versions:

   ```powershell
   docker build --build-arg PYTHON_BASE_IMAGE=docker.io/library/python:3.13-slim-bookworm --build-arg MYSQL_APT_COMPONENT=mysql-9.7-lts --build-arg MYSQL_CLIENT_VERSION=9.7.4-1debian12 -t revela-backend:<release-id> .
   ```

   After deploying the reviewed code in the future (with all execution flags
   off), configure the private least-privilege backup identity and CA in that
   runtime and run the already-deployed read-only command:

   ```powershell
   python -m recovery.cli tls-preflight
   ```

   Require a successful response with `mysql_version=9.7.4`, a non-empty
   `tls_cipher`, and both verification flags true before a production export.
2. **Runtime storage and secrets.** Confirm the production API volume mount,
   mounted status, free space, and approved minimum reserve without listing or
   changing inspection evidence. Set `DB_BACKUP_VOLUME_DIR`,
   `DB_BACKUP_MIN_FREE_BYTES`, and `DB_BACKUP_VOLUME_REQUIRE_MOUNT=1`.
   Railway currently reports the API volume mount as
   `/app/instance/inspection_evidence`; its measured usage was 85.7 MB of
   5,000 MB. Confirm that mount is still present in the new deployment and
   select a positive reserve that accommodates dump/scratch space plus the
   existing evidence; do not assume the measured free space is all available
   for backups.
   Privately configure the least-privilege MySQL identity, CA file, and
   HTTPS-only alert/heartbeat destinations. Re-run the read-only TLS
   preflight in that runtime.
3. **External trigger setup.** The GitHub Actions workflow and protected API
   endpoints are implemented locally, not deployed. For the future approved
   deployment, install GitHub Actions repository secrets
   `DB_BACKUP_TRIGGER_URL=https://api.revelasys.site/api/admin-settings/database-backup/trigger`
   and `DB_BACKUP_TRIGGER_TOKEN=<same random token as Railway>`. Set that
   token only through Railway's secret input and GitHub's Actions secret UI;
   never add it to source, an issue, or chat. Set
   `DB_BACKUP_EXTERNAL_TRIGGER_ENABLED=1` only after confirming the workflow
   exists on the default branch and both secret names are configured. Also set
   the GitHub Actions repository variable
   `DB_BACKUP_EXTERNAL_TRIGGER_ENABLED=true`; without it, the workflow skips
   before allocating a runner. Test
   authenticated rejection, same-key retry, duplicate-run `409`, durable
   polling, API wake-up, and status/catalog consistency with synthetic or
   non-production data. Do not disable sleeping.
4. **Retention approval.** Approve or change the proposed separate manual
   retention of 30 days, and approve the four-weekly/three-monthly count policy
   against measured volume capacity. Keep `DB_BACKUP_CLEANUP_ENABLED=0` until
   that approval and a synthetic retention run are confirmed. Existing
   artifacts were not pruned.
5. **Cost approval.** Read-only Railway measurements for the API over
   2026-09-28 through 2026-10-28 showed CPU average/max
   `0.00176/0.02465 vCPU`, memory average/max `721/4,483 MB`, and volume use
   `85.7 MB / 5,000 MB`; the current billing view showed `$0.108` usage and a
   `$3.75` period estimate. These are existing service totals, not backup
   measurements. Backup export duration and compressed size remain **unknown**
   because no approved export was run. At the published Railway rates
   ($0.00000772/vCPU-second and $0.00000386/GB-second), keeping the API awake
   for one hour at its historical average CPU/memory is approximately
   `$0.010` per run, or `$0.044/month` at 4.35 runs; using historical peak
   usage instead gives roughly `$0.063` per run, or `$0.274/month`. Neither is
   a bound on backup use: SQL export may increase CPU/memory, and the 60-minute
   polling deadline is a maximum wait, not measured job duration. The owner
   confirmed the GitHub Actions dashboard shows `$0 / $18` included compute,
   `0 GB / 2 GB` storage, and `$0` billable usage. The Actions budget remains
   `$0` with paid usage blocked. This repository is public and the CI image
   validation used a standard GitHub-hosted Linux runner, which is free for
   public repositories; no paid runner or billing setting was used. YAML
   parsing, actionlint, and the actual Docker image build passed. Volume use
   leaves about `4.9 GB` capacity, but backup growth is unknown. The GitHub
   runner-minute allowance and any extra charge depend on the repository's
   plan and current Actions usage. No plan, billing limit, or billing setting
   was changed.
6. **Production/manual and isolated-restore acceptance.** These have not been
   run and require separate approval. After deploying only the reviewed image
   with `DB_BACKUP_ENABLED=0`, `DB_BACKUP_SCHEDULE_ENABLED=0`, and
   `DB_BACKUP_CLEANUP_ENABLED=0`, `DB_BACKUP_EXTERNAL_TRIGGER_ENABLED=0`, and
   `DB_BACKUP_SCHEDULER_MODE=external_api`, verify status/configuration and storage
   without starting a job. For an approved manual backup only, set the global
   switch to `1` while leaving schedule and cleanup at `0`, start it from the
   admin Settings panel, and verify the durable receipt, downloaded archive
   SHA-256/length, gzip integrity, database inventory, MySQL version and
   source-server UUID. The authenticated status response includes archive
   hash, version, source UUID, and table count; compare a downloaded file with
   `Get-FileHash -Algorithm SHA256 <downloaded-file>`. Obtain any private
   receipt needed by the restore drill only through the approved operator
   access path.

   Run `python -m recovery.cli restore-test` only against a freshly initialized
   isolated MySQL instance bound to loopback on a non-production port other
   than 3306, with `event_scheduler=OFF`, a different server UUID, the same
   MySQL major version, and no application schemas. Set
   `RECOVERY_ISOLATED=1`; provide the downloaded archive, matching receipt,
   a new output directory, and a private `--target-config` JSON containing
   only that isolated loopback target's connection settings (no `database`
   key). The command verifies checksums, imports the snapshot, compares object
   inventory, runs table checks, and writes `restore-report.json`. Retain that
   report as acceptance evidence; do not point this tool at production.

## Concrete activation sequence (requires separate approval)

1. Review and merge/deploy this local change only through the approved
   release path. Build the API with the pinned MySQL 9.7.4 client. Keep all
   four execution/cleanup/external-trigger flags at `0`; API sleeping remains
   as-is.
2. Set the API volume path to the observed mount, establish a conservative
   positive free-space floor, inject the dedicated backup DB account and CA,
   and install private alert/heartbeat destinations. Do not paste these values
   into code, logs, or chat.
3. Use Railway's deployed service console/CLI to run the read-only TLS
   preflight. Require verified certificate and hostname plus the 9.7.4 server
   version and negotiated cipher. Check status and volume preflight while the
   backup execution switches remain off.
4. Configure the GitHub Actions repository secrets:
   - `DB_BACKUP_TRIGGER_URL`:
     `https://api.revelasys.site/api/admin-settings/database-backup/trigger`
   - `DB_BACKUP_TRIGGER_TOKEN`: same randomly generated value (at least 32
     characters) as the Railway secret `DB_BACKUP_TRIGGER_TOKEN`.

   Keep the GitHub Actions repository variable
   `DB_BACKUP_EXTERNAL_TRIGGER_ENABLED` absent/`false` and the Railway
   `DB_BACKUP_EXTERNAL_TRIGGER_ENABLED=0` until the production backup and
   restore checks have been approved.
5. In a non-production environment, prove disabled requests cannot start work,
   invalid bearer tokens receive 401, a valid same-key retry returns the
   original job ID, concurrent different IDs receive 409, and polling reports
   queued/running/completed/failed from durable status. Confirm a trigger
   wakes the sleeping API and the job writes to the API's existing volume.
6. Only after explicit production-execution approval, run the single manual
   backup/isolated restore acceptance in gate 6. Obtain separate approval for
   automatic weekly execution and the cost estimate. Then, and only then, set
   `DB_BACKUP_ENABLED=1`, `DB_BACKUP_SCHEDULE_ENABLED=1`,
   `DB_BACKUP_EXTERNAL_TRIGGER_ENABLED=1`, and the matching GitHub Actions
   variable to `true`. Keep cleanup at `0` unless retention is separately
   approved; the 30-day manual retention remains proposal only.

Until these items are resolved and approved, preserve:

```text
DB_BACKUP_ENABLED=0
DB_BACKUP_SCHEDULE_ENABLED=0
DB_BACKUP_CLEANUP_ENABLED=0
DB_BACKUP_EXTERNAL_TRIGGER_ENABLED=0
```

No deployment, production export, restore, credential change, or billing change
was performed. Local synthetic tests are necessary but do not establish that
the production volume, TLS, database client, external trigger, isolated restore,
or cost is ready.

## Local validation

From `revela_backend`:

```powershell
python -m pytest -q tests/test_database_backups.py tests/test_volume_database_storage.py tests/test_admin_settings.py
```

From `revela_web`:

```powershell
npm test
```
