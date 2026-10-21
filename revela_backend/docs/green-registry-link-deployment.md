# Green registry-link preflight incident — 2026-10-21

## Confirmed live response

Origin: `https://www.revelasys.site`

Review URL:
`https://api.revelasys.site/api/inspections/7/green-registry-link?businessID=A-0401018-00078`

Read-only probes at **13:03:33 UTC**, repeated at **13:12:36–37 UTC**:

| Request | Status | Response |
| --- | --- | --- |
| Review OPTIONS, requested method GET, requested headers `authorization` | **404** | Flask HTML `404 Not Found` |
| Review OPTIONS with `authorization,content-type` | **404** | Same HTML 404 |
| Review OPTIONS with trailing slash | **404** | Same HTML 404 |
| Review GET without an Authorization header | **404** | Same HTML 404 |
| Verification OPTIONS, requested method POST, requested headers `authorization,content-type` | **204** | Empty body |

The failing preflight already contains:

```text
access-control-allow-origin: https://www.revelasys.site
access-control-allow-headers: authorization
access-control-allow-methods: DELETE, GET, OPTIONS, PATCH, POST, PUT
access-control-allow-credentials: true
vary: Origin
```

The observed cause is **the review route being absent from the backend served by
the API hostname**. Routing returns 404 before the review view/authentication is
reached. The responses contain no redirect. The known verification route is
reachable through the same host and proxy. A valid CORS header cannot turn an
HTTP 404 preflight into a successful preflight.

Local source at commit `d3251c8` already includes the GET route. Determining why
Railway is serving a backend without that route requires checking its actual
service, deployed SHA and build/runtime logs. Those provider details have not
been verified: the Railway CLI is blocked by this machine's application-control
policy, and no Railway authentication token is available. No deployment was run.

Useful correlation IDs for Railway/backend logs:

| UTC | Request | Backend `X-Request-ID` | `X-Railway-Request-ID` |
| --- | --- | --- | --- |
| 13:03:33 | Review OPTIONS 404 | `4f01dc401094` | `ySJ_x_7aQIiUuclIss7a6g` |
| 13:12:36 | Review OPTIONS 404 | `418095ae6c34` | `JRKrRqUhTEKSlb99w9P4nw` |
| 13:12:37 | Verification OPTIONS 204 | `24e0a46518f7` | `kt3Dc19KRx2YYrWLnTga3g` |

Existing request telemetry should emit the first failure as a line containing
`id=4f01dc401094 method=OPTIONS route=/api/inspections/7/green-registry-link status=404`.
Do not include Bearer tokens or request bodies when sharing logs.

## Source changes

- Review explicitly registers `GET` and `OPTIONS`. The existing admin decorator
  returns 204 for OPTIONS before JWT/session checks. GET and verification POST
  still require a signed JWT, active account/session and admin role.
- The original explicit CORS configuration now lives in
  `api.utils.cors_config.init_app`, shared by application startup and isolated
  HTTP fixtures. Allowed origins, headers and methods retain their prior values.
  No wildcard or catch-all OPTIONS route was added.
- Review/verification fetch failures now have `api_network_error`. Readable JSON
  backend errors retain their HTTP status/code/message, even when the message
  contains "fetch". Readable HTML 404 and unexpected proxy responses get distinct
  endpoint-missing/invalid-response messages. A browser-blocked preflight has no
  readable HTTP response; the deployment probe exposes its underlying status.
- `scripts/check_green_registry_link_deployment.py` checks preflight and endpoint
  availability without a JWT or any POST request.
- `scripts/check_green_registry_link_schema.py` inspects session/schema metadata
  using a READ ONLY MySQL session, then rolls back and closes the connection.

## Migration check is separate

The configured **loopback `revela_db`** database was inspected read-only. Its
confirmed-pin column/index/foreign-key and enforcement columns are missing.
No migration was applied. This local result does **not** establish the state of
Railway's production database.

An isolated HTTP/MySQL test demonstrates the separation: when the migration is
unavailable, OPTIONS still returns **204**, while authenticated review returns
JSON **409** with the migration-required message. The deployed **404** is a
routing/deployment failure, not evidence of a missing database column.

## Required deployment steps

1. In Railway, identify the production service behind `api.revelasys.site` and
   inspect the correlated request logs and deployed SHA. Confirm its source
   branch contains the Green-link implementation and these fixes, its root
   directory is `revela_backend`, and its entry point loads `app:create_app()`.
2. Check schema metadata using the **actual backend service's DB configuration**:

   ```powershell
   python scripts/check_green_registry_link_schema.py
   ```

   Confirm existing enforcement migrations are present. If required, have the
   deployment operator apply `migrations/20261021_01_confirmed_registry_pin.sql`
   after the enforcement migrations. These diagnostics do not apply migrations.
3. Deploy/redeploy the backend containing the review route and explicit OPTIONS
   handling. Keep `CORS_ORIGINS` explicitly set to
   `https://www.revelasys.site,https://revelasys.site` (the existing configuration
   also mirrors either spelling). Retain Authorization/Content-Type and GET/POST
   in the existing API policy.
4. Run the deployment smoke check:

   ```powershell
   python scripts/check_green_registry_link_deployment.py --report-id 7 --business-id A-0401018-00078
   ```

   Expected: review OPTIONS **204**, verification OPTIONS **204**, unauthenticated
   review GET **401**, correct explicit allowed origin/headers, no redirects.
   The script does not authenticate, confirm inspection #7, or modify records.
5. Deploy the web build for the improved error messages. Review/confirmation QA
   uses isolated data; no production confirmation is required for this incident.

The live smoke check currently fails with the 404 above. Redeployment and
production log/schema verification remain pending authorized deployment access.

## Verification completed

- **55 backend HTTP/CORS/diagnostic tests + 4 subtests passed**, including exact
  frontend preflight headers, missing/invalid JWTs, Inspector restrictions,
  deactivated/ended sessions, rejected origins, readable 400/409/500 responses,
  and read-only diagnostic safeguards.
- **25 disposable-MySQL tests passed**, including authenticated review returning
  the expected pin/registry/token/missing-field details without changing data,
  subsequent atomic verification, rollback/idempotency/conflicts, one-marker
  preservation after import/sync, and the independent migration check.
- **20 offline browser checks passed**, including network, HTML 404, proxy error,
  backend validation and verification-conflict messages.
- Frontend lint and production build passed. `git diff --check` passed.

Commands from `revela_backend`:

```powershell
python scripts/run_isolated_unit_tests.py -q tests/test_green_registry_link_preflight.py tests/test_green_registry_link_diagnostics.py tests/test_cors.py::OriginParsingTests tests/test_verify_ladder_writes.py::VerificationConflictSurfacingTests
python scripts/run_registry_sync_audit.py --mysqld "C:\Program Files\MySQL\MySQL Server 8.0\bin\mysqld.exe" --temp-root "C:\Users\RUFFAA~1\AppData\Local\Temp\opencode" --test tests.test_green_registry_link_mysql --verbose
```

From `revela_web`: `npm run lint`, `npm run test:green-link:browser`,
`npm run build`. Test runners block external HTTP/application DB access or
external browser DNS. No production business records were modified or confirmed.
