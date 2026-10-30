"""Run the registry/inspection regressions against a disposable MySQL server.

No application factory, dotenv file, existing database, or external API is used.
The server has its own temporary datadir, random loopback port, and test schema.
"""

import argparse
from contextlib import ExitStack
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mysqld", default=shutil.which("mysqld"), required=False)
    parser.add_argument("--temp-root", required=True)
    parser.add_argument("--unit-tests", action="store_true")
    parser.add_argument("--baseline", action="store_true", help="Test the tracked HEAD implementation in memory")
    parser.add_argument("--test", action="append", help="Run a specific unittest name (repeatable)")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()
    if not args.mysqld or not Path(args.mysqld).is_file():
        parser.error("--mysqld must name a local MySQL 8 server executable")
    if not Path(args.temp_root).is_dir():
        parser.error("--temp-root must be an existing temporary directory")

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    import MySQLdb
    from MySQLdb.cursors import DictCursor

    with tempfile.TemporaryDirectory(prefix="revela-registry-audit-", dir=args.temp_root) as root:
        datadir = Path(root) / "data"
        with socket.socket() as reservation:
            reservation.bind(("127.0.0.1", 0))
            port = reservation.getsockname()[1]
        common = [str(args.mysqld), "--no-defaults", f"--datadir={datadir}"]
        initialized = subprocess.run(
            common + ["--initialize-insecure", "--console"],
            capture_output=True, text=True, timeout=120,
        )
        if initialized.returncode:
            raise RuntimeError(initialized.stdout + initialized.stderr)

        with tempfile.TemporaryFile() as log:
            server = subprocess.Popen(common + [
                "--console", "--bind-address=127.0.0.1", f"--port={port}",
                "--mysqlx=0", "--skip-log-bin",
                "--performance-schema=OFF", "--innodb-buffer-pool-size=32M",
            ] + (["--no-monitor"] if sys.platform == "win32" else []), stdout=log, stderr=subprocess.STDOUT)
            try:
                real_connect = MySQLdb.connect
                options = dict(host="127.0.0.1", port=port, user="root", passwd="",
                               charset="utf8mb4", cursorclass=DictCursor)
                deadline = time.monotonic() + 45
                while True:
                    try:
                        bootstrap = real_connect(**options)
                        break
                    except MySQLdb.Error:
                        if server.poll() is not None or time.monotonic() >= deadline:
                            log.seek(0)
                            raise RuntimeError(log.read().decode(errors="replace"))
                        time.sleep(0.2)
                with bootstrap.cursor() as cursor:
                    cursor.execute("CREATE DATABASE revela_registry_sync_audit CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci")
                    cursor.execute("SELECT VERSION() AS version")
                    print("Disposable MySQL:", cursor.fetchone()["version"], flush=True)
                bootstrap.close()

                def isolated_connect():
                    return real_connect(**options, db="revela_registry_sync_audit")

                def forbidden(*_args, **_kwargs):
                    raise AssertionError("Audit forbids production connections, external HTTP, and app startup")

                with ExitStack() as guards:
                    guards.enter_context(patch("dotenv.load_dotenv", return_value=False))
                    guards.enter_context(patch("MySQLdb.connect", forbidden))
                    guards.enter_context(patch("MySQLdb._mysql.connect", forbidden))
                    guards.enter_context(patch("requests.sessions.Session.request", forbidden))
                    import app
                    guards.enter_context(patch.object(app, "create_app", forbidden))
                    guards.enter_context(patch("apscheduler.schedulers.background.BackgroundScheduler.start", forbidden))
                    from tests import test_registry_inspection_sync as integration
                    # Additional read-only dashboard regressions use the same guarded,
                    # disposable connection factory; never app environment credentials.
                    if args.test and any(name.startswith("tests.test_dashboard_mysql") for name in args.test):
                        from tests import test_dashboard_mysql as dashboard
                        dashboard.connect_to_disposable_mysql = isolated_connect
                    if args.test and any(name.startswith("tests.test_sector_risk_policy_mysql") for name in args.test):
                        from tests import test_sector_risk_policy_mysql as sector_policy
                        sector_policy.connect_to_disposable_mysql = isolated_connect
                    if args.baseline:
                        from api.analytics import routes as analytics
                        for module, path in (
                            (integration.registry, "api/registry/service.py"),
                            (integration.places_resolver, "api/registry/places_resolver.py"),
                            (integration.flags, "api/flags/service.py"),
                            (integration.app_settings, "api/models/app_settings.py"),
                            (analytics, "api/analytics/routes.py"),
                        ):
                            source = subprocess.run(
                                ["git", "show", f"HEAD:revela_backend/{path}"],
                                cwd=Path(__file__).resolve().parents[1],
                                capture_output=True, text=True, encoding="utf-8", check=True,
                            ).stdout
                            exec(compile(source, f"HEAD:{path}", "exec"), module.__dict__)
                        print("Baseline: tracked HEAD source loaded in memory", flush=True)
                    integration.connect_to_disposable_mysql = isolated_connect
                    names = args.test or ["tests.test_registry_inspection_sync"]
                    if args.unit_tests:
                        names += [
                            "tests.test_registry_import_hardening",
                            "tests.test_lock_shield",
                            "tests.test_relational_joins",
                            "tests.test_review_queue_and_status",
                            "tests.test_inspection_submission_idempotency",
                            "tests.test_analytics_registry_compat",
                            "tests.test_places_quota",
                            "tests.test_places_resolver",
                            "tests.test_admin_settings.SettingsPersistenceTests",
                            "tests.test_admin_settings.QuotaEnforcementTests",
                            "tests.test_admin_settings.QuotaValidationTests",
                        ]
                    suite = unittest.defaultTestLoader.loadTestsFromNames(names)
                    result = unittest.TextTestRunner(verbosity=2 if args.verbose else 1).run(suite)
                    return 0 if result.wasSuccessful() else 1
            finally:
                try:
                    shutdown = real_connect(**options)
                    shutdown.shutdown()
                    shutdown.close()
                except MySQLdb.Error:
                    server.terminate()
                try:
                    server.wait(timeout=30)
                except subprocess.TimeoutExpired:
                    server.kill()
                    server.wait(timeout=10)
                time.sleep(1)  # Windows releases InnoDB file handles asynchronously.


if __name__ == "__main__":
    raise SystemExit(main())
