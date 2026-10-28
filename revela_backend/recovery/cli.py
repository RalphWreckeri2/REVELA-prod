"""Database export operator commands; no automatic bundle/escrow entry points."""
import argparse
import json
import os
from pathlib import Path
from datetime import timedelta


def main():
    import config  # noqa: F401 - load backend environment without starting Flask
    parser = argparse.ArgumentParser(description="REVELA database SQL.gz exports and isolated restoration")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("status")
    commands.add_parser("tls-preflight", help="Read-only strict certificate and hostname verification")
    commands.add_parser("run", help="Manual database-only export; never satisfies the scheduled-run monitor")
    commands.add_parser("scheduled-run", help="One-shot Railway Cron run using scheduled backup semantics")
    restore = commands.add_parser("restore-test")
    restore.add_argument("--file", required=True, type=Path)
    restore.add_argument("--receipt", required=True, type=Path)
    restore.add_argument("--output", required=True, type=Path)
    restore.add_argument("--target-config", required=True, type=Path)
    restore.add_argument("--mysql-bin", default="mysql")
    record = commands.add_parser("record-drill")
    record.add_argument("--report", required=True, type=Path)
    record.add_argument("--receipt", required=True, type=Path)
    record.add_argument("--state-dir", required=True, type=Path)
    args = parser.parse_args()
    if args.command == "status":
        from recovery.status import report
        result = report()
    elif args.command == "tls-preflight":
        from recovery.mysqltools import strict_tls_preflight
        try:
            result = {"success": True, **strict_tls_preflight()}
        except Exception as exc:
            error = {"success": False, "error_type": type(exc).__name__}
            if isinstance(getattr(exc, "errno", None), int):
                error["error_code"] = exc.errno
            if isinstance(getattr(exc, "sqlstate", None), str):
                error["sqlstate"] = exc.sqlstate
            print(json.dumps(error, sort_keys=True))
            return 1
    elif args.command == "run":
        from recovery.settings import database_enabled
        if not database_enabled():
            print(json.dumps({"success": False, "status": "disabled",
                              "reason": "database_backups_disabled"}))
            return 1
        from recovery.runner import run
        result = run()
    elif args.command == "scheduled-run":
        from recovery.settings import database_enabled, schedule_enabled, pc_managed, scheduler_mode
        from recovery.status import latest_due, now
        if not database_enabled():
            print(json.dumps({"success": False, "status": "disabled",
                              "reason": "database_backups_disabled"}))
            return 1
        if not schedule_enabled():
            print(json.dumps({"success": False, "status": "disabled",
                              "reason": "automatic_database_backups_disabled"}))
            return 1
        if (os.getenv("DB_BACKUP_ROLE") != "worker"
                or pc_managed() or scheduler_mode() != "railway_cron"):
            parser.error("scheduled-run requires an enabled Railway worker role and railway_cron scheduler mode")
        scheduled_for = latest_due()
        if now() - scheduled_for > timedelta(minutes=15):
            parser.error("scheduled-run is outside the 15-minute grace period for a weekly Manila slot")
        from recovery.runner import run
        try:
            result = run(scheduled=True, scheduled_for=scheduled_for.isoformat())
        except Exception as exc:
            from recovery.runner import _error_details
            print(json.dumps({"success": False, **_error_details(exc)}, sort_keys=True))
            return 1
    elif args.command == "restore-test":
        from recovery.db_export import restore_export
        if os.getenv("RECOVERY_ISOLATED") != "1":
            parser.error("RECOVERY_ISOLATED=1 and a fresh isolated instance are required")
        result = restore_export(args.file, json.loads(args.receipt.read_text(encoding="utf-8")),
                                args.output, json.loads(args.target_config.read_text(encoding="utf-8")), args.mysql_bin)
    else:
        from recovery.restore import record_drill
        from recovery.db_storage import FEATURE
        report = json.loads(args.report.read_text(encoding="utf-8"))
        receipt = json.loads(args.receipt.read_text(encoding="utf-8"))
        if (report.get("feature") != FEATURE or receipt.get("feature") != FEATURE
                or report.get("storage_identity") != receipt.get("storage_identity")):
            parser.error("Only matching database export drill evidence may be recorded")
        record_drill(report, receipt, args.state_dir)
        result = {"recorded": True, "note": "Isolated drill evidence merged; no database restored here"}
    print(json.dumps(result, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
