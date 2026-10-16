"""Offline full-suite run with explicit pre-feature failure comparison.

Does not skip/xfail baseline tests or turn a failing full suite green. The
pytest exit status is retained; every new, changed, or absent failure is printed.
Run from revela_backend with its existing venv; no app database is accessed.
"""
from contextlib import ExitStack
import json
import os
from pathlib import Path
import re
import sys
from unittest.mock import patch

import pytest


BACKEND = Path(__file__).resolve().parents[1]


class BaselineComparison:
    def __init__(self, baseline):
        self.expected = baseline["failures"]
        self.failed = {}

    def pytest_runtest_logreport(self, report):
        if report.failed:
            self.failed[report.nodeid.replace("\\", "/")] = (
                report.longreprtext + report.capstdout + report.capstderr + report.caplog
            )

    def summarize(self):
        new = sorted(self.failed.keys() - self.expected.keys())
        absent = sorted(self.expected.keys() - self.failed.keys())
        changed = sorted(node for node in self.failed.keys() & self.expected.keys()
                         if not re.search(self.expected[node], self.failed[node], re.DOTALL))
        # Preserve the distinction from the old, credentials-related CORS gap.
        cors = "tests/test_cors.py::LoginCorsIntegrationTests::test_login_reaches_the_route_rather_than_being_blocked"
        if cors in self.failed and "Offline tests: database access blocked" not in self.failed[cors]:
            changed.append(cors + " (database failure cause changed)")
        for node, text in self.failed.items():
            if "test_expiry_uses_current_warning_level_not_old_history" in node and "no such function: MAKEDATE" not in text:
                changed.append(node + " (SQLite failure cause changed)")
        print("\nPRE-FEATURE BASELINE COMPARISON (848303d)")
        print(f"Recorded failures: {len(self.expected)}; current failures: {len(self.failed)}")
        for label, nodes in (("NEW", new), ("CHANGED CAUSE", changed), ("ABSENT", absent)):
            print(f"{label}: {len(nodes)}")
            for node in nodes:
                print("  " + node)
        print("Baseline failures remain failures, not resolved or correct behaviour.")
        return not new and not changed


def main():
    sys.path.insert(0, str(BACKEND))
    baseline = json.loads((BACKEND / "tests/feature_baseline_848303d.json").read_text(encoding="utf-8"))
    comparison = BaselineComparison(baseline)
    with ExitStack() as guards:
        guards.enter_context(patch.dict(os.environ, {"JWT_SECRET_KEY": "offline-test-key-only"}))
        guards.enter_context(patch("dotenv.load_dotenv", return_value=False))
        for target in ("MySQLdb.connect", "MySQLdb._mysql.connect"):
            guards.enter_context(patch(target, side_effect=RuntimeError("Offline tests: database access blocked")))
        guards.enter_context(patch("requests.sessions.Session.request", side_effect=RuntimeError("Offline tests: HTTP blocked")))
        guards.enter_context(patch("apscheduler.schedulers.background.BackgroundScheduler.start"))
        result = pytest.main(["tests", "-q", "--tb=short", "-p", "no:cacheprovider"], plugins=[comparison])
    comparison.summarize()
    return int(result)


if __name__ == "__main__":
    raise SystemExit(main())
