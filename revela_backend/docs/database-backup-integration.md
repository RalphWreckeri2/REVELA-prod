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
  requires both certificate and hostname TLS verification in both Connector/Python
  and the `mysqldump` client; remote dump options fail closed if either
  verification flag or the CA file is missing. Dumps use `--single-transaction`
  and reject non-InnoDB tables. The exporter compares schema/object inventories
  immediately before and after the dump and rejects detected changes. MySQL
  still requires operators to avoid DDL/schema migrations during the export:
  no before/after inventory can detect every possible in-place DDL change.
  The existing restore tooling refuses a target unless it is explicitly isolated.
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
  credentials/CA. An HTTPS `BACKUP_ALERT_WEBHOOK` is optional: without one,
  failure is recorded in durable status/history and sent through the existing
  in-app admin inbox, which is not an independent channel. It does not require
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

The non-secret runtime settings in `recovery/backup.env.example` use the
existing Railway mount `/app/instance/inspection_evidence` and a proposed
`DB_BACKUP_MIN_FREE_BYTES=1073741824` (1 GiB) floor. The current read-only
container check verified the mount and measured 4,820,172,800 free bytes
(about 4.49 GiB). This leaves about 3.49 GiB above the preflight floor for the
first archive and work directory. Actual dump and workspace use must be
measured during the authorized run; abort if the API reports insufficient
capacity. The API variable was set for the next deployment with deploys
skipped. Backup execution remains disabled.

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

The concrete certificate is a CA-issued TLS server leaf certificate with
`subjectAltName = DNS:<the exact private DB_HOST value>`, `serverAuth` extended
key usage, and a chain to the CA bundle trusted by the API. The DBA must
compare the SAN to the private `DB_HOST` in the protected provider UI; do not
copy the hostname into chat or public logs. Do not mount or distribute the CA
signing key.

The proposed `/run/secrets/...` paths are **not** mounted by this Railway
deployment. Read-only provider verification found Railway Variables are
runtime environment variables (sealed values are still supplied to the
service as environment variables), not mounted files ([Railway Variables
docs](https://docs.railway.com/variables)). Railway does support persistent
volume files and file upload through its CLI ([Volumes](https://docs.railway.com/volumes/reference),
[volume CLI](https://docs.railway.com/cli/volume)). The current MySQL
service's existing `mysql-volume` is mounted at `/var/lib/mysql`; the API's
existing `revela-prod-volume` is mounted at
`/app/instance/inspection_evidence`. Each service already has its one volume,
so do not add or replace volumes.

Railway SSH inspection confirmed the MySQL daemon runs as UID/GID `999:999`.
The existing `/var/lib/mysql/tls` directory is owned by that UID with mode
`700`. An EC P-256 server private key is held at
`/var/lib/mysql/tls/server-key.pem`, owned by `999:999`, mode `600`; its
verified CSR is `/var/lib/mysql/tls/server.csr`. The private key never left
the MySQL volume. The DBA-issued private root and leaf are now present as
public files at `/app/instance/inspection_evidence/tls/mysql-ca.pem` and
`/var/lib/mysql/tls/server-chain.pem`; their uploads were hash-verified. The
encrypted CA signing key remains in the protected local signing folder and
was not uploaded.

#### Issued certificate artifacts

The approved private-CA process signed the existing CSR; no new CA or server
key was generated in this implementation pass. The local PowerShell signing
helper is at
`%LOCALAPPDATA%\REVELA\DatabaseBackupCA\Sign-MySqlServerCertificate.ps1`,
outside the repository in a folder restricted to the current account, SYSTEM,
and local Administrators. If the existing issuance needs revalidation, run it
privately from PowerShell 7; it prompts for the passphrase and hostname
without echoing them:

```powershell
pwsh.exe -NoProfile -File "$env:LOCALAPPDATA\REVELA\DatabaseBackupCA\Sign-MySqlServerCertificate.ps1"
```

The existing outputs are `mysql-ca-key.pem`, `mysql-ca.pem`,
`server-leaf.pem`, `server-chain.pem`, and `mysql-ca.srl`; the CSR and signing
script are expected inputs, not output collisions. The updated guard validates
and reuses a complete issuance without writing, and stops on a partial set
without overwriting. This update has passed PowerShell syntax validation; its
private-passphrase reuse validation has not been run in this session. The
encrypted CA key remains local; never upload or share it.

Never paste PEM contents into a Railway variable, raw editor, shell command,
chat, or log. The server private key remains on the MySQL volume; only the
public CA and certificate files were uploaded. Railway volume and project
access controls plus OS permissions protect the key; a volume is not a
separate sealed secret manager.

The API's `tls` directory must remain a child of the evidence volume, not a
top-level file/directory replacement. Evidence usage scans only top-level
files; archive creation includes only photo filenames referenced by verified
inspection records and resolves those basenames in the top-level evidence
directory; Clear Server Storage likewise resolves and deletes only those
recorded photo basenames. It does not recursively include or delete files under
`tls`. A regression test creates a synthetic key marker under `tls/` and
checks it is absent from usage totals and generated ZIP contents and remains
untouched after cleanup (`tests/test_evidence_cleanup.py`). Do not place
certificate material at the volume root or reference it from photo metadata.

Current MySQL settings remain at their stock baseline after the failed reload
was rolled back: `ssl_ca=ca.pem`, `ssl_cert=server-cert.pem`,
`ssl_key=server-key.pem`, and `ssl_capath=NULL`, resolving the active files
under `/var/lib/mysql`. There are no persisted TLS entries. The old stock CA,
server certificate, and key are preserved. The proposed private-CA leaf did
not validate against that stock CA, which is why the first reload failed.

The local candidate bundle
`mysql-ca-bundle-candidate-reordered.pem` and the staged MySQL-volume copy
`/var/lib/mysql/tls/ca-bundle-candidate-reordered.pem` contain both the new
private root and the stock root, with the private root first. OpenSSL verified
that this candidate validates both the proposed leaf and the stock server
certificate; a download-back SHA-256 comparison confirmed the staged file.
No active TLS setting was changed. Do not use the earlier stock-first
candidate; it did not validate the proposed leaf.

The proposed in-place values, only after DBA review/approval, are:

```sql
SET PERSIST ssl_ca = '/var/lib/mysql/tls/ca-bundle-candidate-reordered.pem';
SET PERSIST ssl_cert = '/var/lib/mysql/tls/server-chain.pem';
SET PERSIST ssl_key = '/var/lib/mysql/tls/server-key.pem';
ALTER INSTANCE RELOAD TLS;
```

Changing `ssl_ca` preserves trust in the existing stock root while adding the
private root. It also expands the roots MySQL may accept when validating
client certificates for accounts that require X.509; have the DBA review
whether any such accounts exist before applying it. The API's client-side
trust remains separate at
`BACKUP_DB_SSL_CA_FILE=/app/instance/inspection_evidence/tls/mysql-ca.pem`,
with certificate and hostname verification enabled. Preserve current TLS
versions and `require_secure_transport=OFF`; do not broaden this change into
server-wide transport enforcement.

Before approval, the DBA can report client-certificate requirements without
exposing account names:

```sql
SELECT ssl_type, COUNT(*) AS account_count
FROM mysql.user
GROUP BY ssl_type
ORDER BY ssl_type;
```

An empty `ssl_type` means the account does not require TLS; `ANY` requires an
encrypted TLS connection but not a client certificate; `X509` requires a
valid client certificate; and `SPECIFIED` means one or more TLS constraints
(cipher, issuer, or subject) are configured. For `SPECIFIED`, the CA change
affects trust only when issuer/subject constraints require a client
certificate; a cipher-only constraint does not. Adding the private root does
not make certificates mandatory for all accounts, but can make a certificate
issued by that root eligible for `X509` accounts and matching
issuer/subject-constrained accounts. The stock root remains trusted.

**A MySQL process restart is not inherently required.** Oracle's MySQL 9.7
source test for dynamic TLS configuration verifies that `ssl_cert` and
`ssl_key` can be changed at runtime and that
`ALTER INSTANCE RELOAD TLS` activates the new TLS context. The same test
verifies that existing sessions continue with their original TLS session,
new sessions use the reloaded context, invalid reloads leave the previous
working context in place, and `CONNECTION_ADMIN` is required. See the
[MySQL 9.7 dynamic TLS test](https://github.com/mysql/mysql-server/blob/9.7/mysql-test/t/ssl_dynamic.test).
Railway's current MySQL volume is the server data directory, so MySQL's
persisted-system-variable file (`mysqld-auto.cnf`) is on that persistent
volume. The file exists, but the recorded post-rollback check found no
persisted TLS entries. MySQL 9.7 allows the dynamic TLS paths to be persisted
and reloaded in place; no MySQL restart is part of the approved procedure.

The DBA must use an authorized account with the MySQL 9.7 privileges needed to
persist these settings and run the reload;
`ALTER INSTANCE RELOAD TLS` requires `CONNECTION_ADMIN` (or an account with
equivalent documented administrative privilege). Use the provider's protected
DBA session, never the exposed `root` credential. Do not use `SET GLOBAL`
alone: it would not persist the paths through redeploy.

With an in-place reload, existing database sessions are not disconnected; no
planned outage is expected. New TLS handshakes use the new certificate. Clients
that pin the old certificate may reject new connections; stage appropriate CA
trust for verifying clients before reload. If a provider-required restart is
the only way to expose/persist the files, expect a brief DB connection
interruption while MySQL restarts and clients reconnect. The DBA should
preserve the current certificate/key paths and service configuration for
rollback.

The first attempt to reload the new leaf failed with MySQL Error 3888,
`Invalid certificates`; rollback restored the recorded stock certificate/key
baseline and removed the new persisted TLS entries. No MySQL restart occurred.
Before creating the backup account, have the DBA review the X.509 trust impact,
confirm the SAN against the private endpoint, and approve the proposed `ssl_ca`
change. After a successful reload, run the read-only strict TLS preflight.

### DBA change and rollback checklist

The certificate issuance, public-file uploads, candidate-bundle validation,
and isolated restore-server setup are complete. No active MySQL TLS settings
have been changed since the successful rollback. The only remaining DBA-side
configuration change is the exact additive `ssl_ca` plus `ssl_cert`/`ssl_key`
sequence shown above; it requires review of existing X.509 account use and
explicit approval before execution. If approved, use the protected DBA
session, preserve the current baseline values, apply only those three paths,
and run `ALTER INSTANCE RELOAD TLS`. Do not change TLS versions,
`require_secure_transport`, or unrelated settings.

After a successful reload, create the dedicated `revela_backup` account below,
inject its password privately, and run `python -m recovery.cli tls-preflight`
with all backup execution switches still `0`. Require verified certificate
and hostname, MySQL `9.7.4`, and a negotiated cipher before enabling a manual
export. If reload fails, do not restart MySQL; restore the recorded baseline
and remove only the newly persisted entries, as in the already successful
rollback.

After an approved reload, verify the live and persisted values from the same
private DBA session:

```sql
SELECT @@GLOBAL.ssl_ca, @@GLOBAL.ssl_cert, @@GLOBAL.ssl_key, @@GLOBAL.ssl_capath;

SELECT VARIABLE_NAME, VARIABLE_VALUE
FROM performance_schema.persisted_variables
WHERE VARIABLE_NAME IN ('ssl_ca', 'ssl_cert', 'ssl_key')
ORDER BY VARIABLE_NAME;
```

Expected active values are the three `/var/lib/mysql/tls/...` paths above;
`ssl_capath` remains `NULL`. Expect three persisted entries.

If any `SET PERSIST` or the reload fails, restore the recorded active baseline
without restarting MySQL:

```sql
SET PERSIST ssl_ca = 'ca.pem';
SET PERSIST ssl_cert = 'server-cert.pem';
SET PERSIST ssl_key = 'server-key.pem';
ALTER INSTANCE RELOAD TLS;

RESET PERSIST IF EXISTS ssl_ca;
RESET PERSIST IF EXISTS ssl_cert;
RESET PERSIST IF EXISTS ssl_key;
```

Verify active paths are back to `ca.pem`, `server-cert.pem`, and
`server-key.pem`, with `ssl_capath=NULL`, and the persisted-variable query
returns no TLS rows. Do not remove the uploaded files.

The API's Railway private IPv6 source was observed from a one-off runtime
connection, but Railway has not established that this address survives
redeploys. The public MySQL TCP proxy is enabled, so a `%` host is **not**
private-network-only. Static outbound IP is disabled and is not suitable for
the current private IPv6 path. The selected redeploy-compatible policy is a
dedicated client certificate: create `revela_backup` at host `%` with a
subject/issuer constraint matching a separate client-auth certificate, and
require TLS. This allows source address changes while making the account
require both its password and the dedicated certificate. The public proxy
remains reachable; protect the password and client private key, and do not
reuse the server key or CA signing key.

The existing server-signing helper issues a `serverAuth` leaf and cannot be
used for client authentication. A distinct private client key and
`clientAuth` certificate must be prepared and staged in the existing API
volume before creating the account. The backup connector and `mysqldump`
configuration require the CA, client certificate, and private-key file; the
private key must be owner-only. Workbench's existing account and public-proxy
access are unchanged.

Prepare the separate client identity from the protected workstation with the
dedicated helper; it refuses existing outputs, prompts for the CA passphrase
without echoing it, and writes all artifacts outside the repository:

```powershell
pwsh.exe -NoProfile -File .\scripts\Sign-MySqlBackupClientCertificate.ps1
```

It issues a 90-day client-auth leaf with a dedicated subject and reports only
the public subject/issuer metadata needed for the DBA's account constraint.
Keep `backup-client-key.pem` in the protected local folder until it is
uploaded through the protected Railway volume workflow to the documented API
volume path. Set its mode to `0600`; upload the public client certificate
separately. Never upload the CA signing key or MySQL server private key.

The confirmed account lookup returned no `revela_backup` rows. In MySQL
Workbench's SQL editor, create the account with a server-generated random
password. The SQL history contains only `RANDOM PASSWORD`, not the generated
secret; the result grid displays it only in the private DBA session. Copy it
directly into the Railway `BACKUP_DB_PASSWORD` secret field and nowhere else.
The host `%` is necessary because no stable API source address has been
verified; it is not a network restriction. Authentication additionally
requires the dedicated certificate subject and issuer below, plus its
password. This does not change Workbench's existing account:

```sql
CREATE USER 'revela_backup'@'%'
IDENTIFIED BY RANDOM PASSWORD
REQUIRE SUBJECT '/CN=REVELA-Database-Backup-Client'
AND ISSUER '/CN=REVELA Database Backup Private Root CA';
```

If the create statement reports that the account already exists, stop; do
not reset its password or change its grants. Have the DBA inspect that
account's current authentication/TLS requirements first. Otherwise, grant
only the rights needed for this database-only dump and its inventory:

```sql
GRANT SELECT, SHOW VIEW, TRIGGER, EVENT
ON `REPLACE_WITH_APPLICATION_SCHEMA`.*
TO 'revela_backup'@'%';
GRANT SHOW_ROUTINE ON *.*
TO 'revela_backup'@'%';
```

Replace the schema with the DBA-verified application schema. Use `%` only
with the dedicated client certificate requirement described above; it is not
a source-network restriction. Do not grant write, schema-creation, or
administrative privileges. `SHOW_ROUTINE` is needed for the configured routine
inventory/dump and is a global dynamic privilege on supported MySQL versions;
it can expose routine definitions outside the target schema. The data/object
grants are schema-scoped. The DBA must review this global visibility tradeoff;
if it is not acceptable, omit routine export/inventory as a separately
approved scope change rather than granting broader privileges silently. Set
the account's TLS requirement to the exact dedicated client-certificate
subject and issuer (`REQUIRE SUBJECT ... AND ISSUER ...`), in addition to
client-side server certificate and hostname verification.

Privately inject these runtime values after the account and CA are provisioned:

```text
BACKUP_DB_HOST=<verified private MySQL hostname>
BACKUP_DB_PORT=3306
BACKUP_DB_NAME=<application schema>
BACKUP_DB_USER=revela_backup
BACKUP_DB_PASSWORD=<set directly in the runtime secret UI>
BACKUP_DB_SSL_CA_FILE=/app/instance/inspection_evidence/tls/mysql-ca.pem
BACKUP_DB_SSL_CERT_FILE=/app/instance/inspection_evidence/tls/backup-client-cert.pem
BACKUP_DB_SSL_KEY_FILE=/app/instance/inspection_evidence/tls/backup-client-key.pem
DB_BACKUP_VOLUME_DIR=/app/instance/inspection_evidence
DB_BACKUP_VOLUME_REQUIRE_MOUNT=1
DB_BACKUP_MIN_FREE_BYTES=1073741824
# Optional for a one-time supervised manual export; existing HTTPS endpoint only
# BACKUP_ALERT_WEBHOOK=<existing HTTPS failure-alert endpoint>
```

The 1 GiB floor is a conservative preflight reserve based on 4,820,172,800
bytes free on the existing API volume. It is not a prediction of dump size;
the first run must still pass the actual capacity check and its measured
workspace use must be reviewed.

The CA PEM is not a password, but its source and integrity must be trusted;
mount the CA file at the configured path and ensure the API process can read
it. Do not enable execution to test connectivity: run
`python -m recovery.cli tls-preflight` in the deployed API runtime with all
execution switches still `0`. Require verified certificate and hostname,
server version `9.7.4`, and a negotiated TLS cipher.

`BACKUP_ALERT_WEBHOOK` is optional for the supervised one-time manual export.
If it is absent, failure details are recorded in durable status/history and a
notification is sent through the existing in-app admin inbox. This fallback
is explicit in the failure record as `external_alert=not_configured`; it is
not email and is not independent of the application database. If the inbox
write also fails, the service logs an explicit alert-delivery failure. Reuse
an existing approved HTTPS endpoint when available; do not add a paid service.
`BACKUP_HEARTBEAT_URL` is only required for recurring scheduling and is not
needed for this one-time manual export/restore test. No new paid alert service
is part of this setup.

### Isolated Windows restore instance

The existing isolated Oracle MySQL Community Server **9.7.4** Windows ZIP
instance is already prepared in a dedicated directory and run manually (not
installed as or registered with a Windows service). The existing `MySQL80`
service remains untouched. The official ZIP URL is
`https://cdn.mysql.com/Downloads/MySQL-9.7/mysql-9.7.4-winx64.zip`; its
official response reported **344,052,123 bytes** (about 328 MiB) on
2026-10-29, and the published checksum was verified. The test server is
loopback-only at `127.0.0.1:33307`, with events off and no Windows service;
no production data has been imported. Pass its `bin\mysql.exe` explicitly to
`restore-test`.

The production export has not been run, so archive and expanded SQL sizes are
still unknown; check free space again after the first actual backup and before
the restore. No production data has been imported.

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

   The direct private endpoint still presents the stock auto-generated
   certificate until the approved in-place reload, so strict identity
   verification has not passed. The private-CA leaf and client trust root are
   issued and uploaded. The staged additive CA bundle validates both the
   stock and proposed server certificates. The earlier reload failed because
   the active stock CA did not trust the new leaf; rollback restored the
   baseline and no restart occurred. Before applying the proposed `ssl_ca`,
   `ssl_cert`, and `ssl_key` paths, the DBA must review the X.509 client
   account impact and approve that exact change. The TLS preflight remains
   blocked until the in-place reload succeeds.

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
   `/app/instance/inspection_evidence`, mounted with 4,820,172,800 free bytes.
   `DB_BACKUP_MIN_FREE_BYTES=1073741824` is already set for the next deployment
   with deploys skipped. Privately configure the least-privilege MySQL
   identity and CA file. An existing HTTPS `BACKUP_ALERT_WEBHOOK` is optional
   for this supervised manual export; without one, only the existing in-app
   admin inbox and durable status/history report failures, and are not an
   independent channel. `BACKUP_HEARTBEAT_URL` is only required when recurring
   scheduling is enabled; it is not required for this one-time export. Re-run
   the read-only TLS preflight in that runtime.
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
   positive free-space floor, and privately inject the dedicated backup DB
   account and CA. An existing HTTPS failure-alert destination is optional for
   the one-time manual test; without it, the existing admin inbox is used and
   is not an independent channel. `BACKUP_HEARTBEAT_URL` remains unset for the
   one-time manual test; configure its HTTPS destination before any recurring
   schedule is enabled. Do not paste private values into code, logs, or chat.
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
