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
  be marked true until the workflow and its private secrets are installed,
  the runtime has been verified, and the isolated restore/cost gates pass.

## Deployment, export, restore, and recurring-operation gates

These are separate gates; a restore server is not a prerequisite for starting
the application:

- **Deploy/start with backups disabled:** keep
  `DB_BACKUP_ENABLED=0`, `DB_BACKUP_SCHEDULE_ENABLED=0`,
  `DB_BACKUP_CLEANUP_ENABLED=0`, and
  `DB_BACKUP_EXTERNAL_TRIGGER_ENABLED=0`. An incomplete backup-only
  configuration reports as not ready but does not prevent the API from
  starting. No backup account, backup CA, alert/heartbeat URL, external
  trigger secret, or restore instance is needed for this disabled deployment.
- **Read-only TLS preflight:** requires the dedicated DB credentials and a CA
  that validates the server certificate for the exact `BACKUP_DB_HOST`. It
  does not need a volume, alert endpoint, restore server, or enabled backup
  switch.
- **One-time manual export:** additionally requires the production volume and
  approved free-space reserve, the matching MySQL client, the private backup
  credentials/CA, and an HTTPS `BACKUP_ALERT_WEBHOOK`. It does not require
  `BACKUP_HEARTBEAT_URL`, a scheduler/trigger token, or an already-running
  restore server. A completed export is not accepted as a recovery test until
  it has also been restored and checked in isolation.
- **Isolated restore acceptance:** requires a completed export and matching
  receipt, plus a fresh, empty MySQL 9.7 test server bound only to loopback on
  a non-3306 port, with events off and a distinct server UUID. It is an
  operator-run one-time test, not a PC backup service or schedule.
- **Recurring operation:** additionally requires the external trigger and
  matching private token, an HTTPS success-heartbeat endpoint, current
  restore evidence, and separate retention/cost approvals. Do not remove
  heartbeat or failure-alert safeguards to make this gate pass.

The first non-secret runtime setting is now concrete in
`recovery/backup.env.example`: `DB_BACKUP_VOLUME_DIR` uses the recorded
Railway mount `/app/instance/inspection_evidence`, and the account name is
`revela_backup`. The positive free-space floor remains deliberately unset
until the live mount's free space and dump/scratch-space needs are confirmed.
The historical 85.7 MB used of 5,000 MB is not a current capacity guarantee.

### Dedicated account and verified CA setup

The intended production **private** endpoint was checked on 2026-10-29 through
a Railway SSH tunnel, using the API runtime's effective `DB_HOST` for TLS SNI.
The live endpoint negotiated TLS 1.3 and presented certificate SHA-256
`6729841233f18fcf5ce2ba70a74614ead3ff97eaac49dc4440311cae51a7863c`,
subject `CN=MySQL_Server_9.4.0_Auto_Generated_Server_Certificate`, issuer
`CN=MySQL_Server_9.4.0_Auto_Generated_CA_Certificate`, and **no DNS SAN**.
The certificate therefore does not match the intended private hostname.
This probe sent no DB credentials and did not verify the trust chain; the
hostname mismatch alone is sufficient to block strict identity verification.
This is now direct evidence from the private endpoint, not an inference from
the public proxy. Do not copy this certificate into the app or weaken client
verification.

The concrete required change is to configure MySQL with a server leaf
certificate whose DNS SAN exactly covers the private hostname in `DB_HOST`,
issued by a trusted CA; provide that CA, leaf certificate, and matching private
key through protected service configuration/mounts, then point the API CA file
at that CA. This requires a MySQL service configuration change and restart.
Expect a brief database connection interruption/reconnect while it restarts;
clients pinning the current certificate/CA may also need their trust updated.
Do not turn on server-wide `require_secure_transport` as part of this backup
change. No certificate, key, database setting, or MySQL service was changed.
After the replacement certificate is live, create the separate
`revela_backup` account with `REQUIRE SSL`, then prove the chain and hostname
with the read-only TLS preflight before any export.

After the verified endpoint exists, create a separate `revela_backup` MySQL
account restricted to the API's verified source host/private network and
require TLS (`REQUIRE SSL`). Set its password privately in the database
provider's protected account-creation flow; do not put it in this repository,
a command-line argument, logs, or chat. Grant only the rights needed for this
database-only dump and its inventory:

```sql
GRANT SELECT, SHOW VIEW, TRIGGER, EVENT
ON `REPLACE_WITH_APPLICATION_SCHEMA`.*
TO 'revela_backup'@'REPLACE_WITH_VERIFIED_API_SOURCE_HOST';
GRANT SHOW_ROUTINE ON *.*
TO 'revela_backup'@'REPLACE_WITH_VERIFIED_API_SOURCE_HOST';
```

Replace the schema and host identifiers before applying the grants. Do not
grant write, schema-creation, or administrative privileges. `SHOW_ROUTINE` is
needed for the configured routine inventory/dump; the data/object grants are
schema-scoped. Keep `REQUIRE SSL` on the account as well as client-side
certificate and hostname verification.

Privately inject these runtime values after the account and CA are provisioned:

```text
BACKUP_DB_HOST=<verified private MySQL hostname>
BACKUP_DB_PORT=3306
BACKUP_DB_NAME=<application schema>
BACKUP_DB_USER=revela_backup
BACKUP_DB_PASSWORD=<set directly in the runtime secret UI>
BACKUP_DB_SSL_CA_FILE=/run/secrets/mysql-ca.pem
DB_BACKUP_VOLUME_DIR=/app/instance/inspection_evidence
DB_BACKUP_VOLUME_REQUIRE_MOUNT=1
DB_BACKUP_MIN_FREE_BYTES=<positive reserve approved from live capacity>
BACKUP_ALERT_WEBHOOK=<existing HTTPS failure-alert endpoint>
```

The CA PEM is not a password, but its source and integrity must be trusted;
mount the CA file at the configured path and ensure the API process can read
it. Do not enable execution to test connectivity: run
`python -m recovery.cli tls-preflight` in the deployed API runtime with all
execution switches still `0`. Require verified certificate and hostname,
server version `9.7.4`, and a negotiated TLS cipher.

`BACKUP_ALERT_WEBHOOK` is currently required by runtime validation for a
manual export as well as a scheduled export. The existing admin inbox and
durable job status are additional safeguards, not a replacement for that
required HTTPS destination. Reuse an existing no-cost endpoint if available;
otherwise manual execution remains blocked until an endpoint is selected.
`BACKUP_HEARTBEAT_URL` is only required for recurring scheduling and is not
needed for this one-time manual export/restore test. No new paid alert service
is part of this setup.

### Isolated Windows restore instance

The existing `MySQL80` Windows service must remain untouched. The compatible
test target is a separate Oracle MySQL Community Server **9.7.4** Windows ZIP
distribution, extracted into a dedicated directory and run manually (not
installed as or registered with a Windows service). The official ZIP URL is
`https://cdn.mysql.com/Downloads/MySQL-9.7/mysql-9.7.4-winx64.zip`; its
official response reported **344,052,123 bytes** (about 328 MiB) on
2026-10-29. Extracted program size and eventual restore size are additional.
Use a fresh dedicated data directory, `127.0.0.1`, a non-3306 port such as
`33307`, and `event_scheduler=OFF`; do not add this server globally to PATH.
Pass its `bin\mysql.exe` explicitly to `restore-test`.

The workstation check found approximately **733 GiB free on C:**, and the
existing `MySQL80` service was running. The production export has not been
run, so its compressed archive and uncompressed SQL sizes are unknown; exact
restore-space needs cannot yet be calculated. The ZIP alone fits comfortably,
but do not start a restore until the archive size is known and there is room
for the ZIP, extracted server, compressed archive, expanded SQL, and database
data directory. No download or local MySQL change has been made.

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

   The direct private-endpoint TLS probe is documented above. It confirmed the
   currently presented auto-generated certificate has no DNS SAN, so strict
   identity verification cannot pass. A trusted CA and server leaf certificate
   covering the actual `DB_HOST` are required. Installing them would require a
   separately approved MySQL service configuration/restart, unless Railway
   provides a different private endpoint whose certificate independently
   passes verification.

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
   Privately configure the least-privilege MySQL identity and CA file. The
   HTTPS `BACKUP_ALERT_WEBHOOK` is required for manual as well as scheduled
   exports because failures must be reported (the admin inbox is also used).
   `BACKUP_HEARTBEAT_URL` is only required when recurring scheduling is
   enabled; it is sent for successful scheduled runs and is not required for
   the one-time manual export. Re-run the read-only TLS preflight in that
   runtime.
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
   and install the HTTPS failure-alert destination. `BACKUP_HEARTBEAT_URL`
   remains unset for the one-time manual test; install its HTTPS destination
   before any recurring schedule is enabled. Do not paste private values into
   code, logs, or chat.
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
