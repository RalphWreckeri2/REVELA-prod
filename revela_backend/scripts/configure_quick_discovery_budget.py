"""Repair a too-small execution cap within EXISTING method budgets; no Google calls.

Run on the backend host: python scripts/configure_quick_discovery_budget.py --apply
Without --apply, only the current plan and proposed setting are printed.
Daily/monthly API budgets, completed monthly scans, Cloud quotas and billing are
never raised by this command. Use the admin settings form for those decisions.
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))


def quick_discovery_patch(preflight, *, full_slices=False):
    from api.flags.scan_budget import estimate_requests
    needed = estimate_requests("quick", preflight["nearby_api_mode"], preflight["total_points"])["maximum_requests"]
    if full_slices:
        # This permits one fully bounded dense Full Coverage cell. The entire
        # municipality remains a resumable, separately budgeted operation.
        needed = max(needed, estimate_requests("full", preflight["nearby_api_mode"], 1)["maximum_requests"])
    if min(preflight["daily_cap"], preflight["monthly_cap"]) < needed:
        raise ValueError(f"Existing method budgets cannot fund {needed} requests; review the budget before changing any cap.")
    if preflight["work_slice_requests"] >= needed:
        return {}
    return {"run_detection.max_requests": needed}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--full-slices", action="store_true", help="Also allow one bounded Full Coverage cell per execution, within existing method budgets.")
    args = parser.parse_args()
    from flask import Flask
    from app import mysql
    from config import Config
    from api.flags.service import get_detection_preflight
    from api.models import app_settings
    from api.utils import quota_settings, test_mode
    app = Flask(__name__)
    app.config.from_object(Config)
    mysql.init_app(app)
    with app.app_context():
        # Fail closed rather than trusting load_all()'s read-failure fallback.
        cursor = mysql.connection.cursor()
        try:
            app_settings.ensure_settings_table()
            cursor.execute("SELECT settingKey, settingValue FROM revela_app_settings")
            cursor.fetchall()
        finally:
            cursor.close()
        if test_mode.is_enabled():
            parser.error("Test Mode is enabled. Review its request/scope settings explicitly before configuring a production scan.")
        preflight = get_detection_preflight("quick")
        patch = quick_discovery_patch(preflight, full_slices=args.full_slices)
        clean, errors = quota_settings.validate_patch(patch)
        if errors:
            parser.error(" ".join(errors))
        print(json.dumps({"preflight": preflight, "application_setting_patch": clean}, indent=2))
        if args.apply and clean:
            count, error = app_settings.save_many(clean)
            if error:
                parser.error(error)
            quota_settings.invalidate()
            print(f"Applied {count} application setting(s). API budgets and monthly scan allowance are preserved.")


if __name__ == "__main__":
    main()
