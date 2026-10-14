"""Run only backend hotfix regressions, with real side effects forbidden.

Use the existing Python environment; no pytest or new packages are required.
This does not start the production Flask factory or execute database SQL.
"""

from contextlib import ExitStack
from pathlib import Path
import sys
import unittest
from unittest.mock import patch


BACKEND = Path(__file__).resolve().parents[1]
TEST_MODULES = (
    "tests.test_yellow_flag_validation",
    "tests.test_yellow_flag_idempotency",
    "tests.test_yellow_flag_address_search",
    "tests.test_inspection_submission_idempotency",
    "tests.test_barangay_scope",
    "tests.test_backend_release_contract",
    "tests.test_auth_inactivity",
    "tests.test_auth_sessions",
)


def main():
    sys.path.insert(0, str(BACKEND))
    blocked_attempts = []

    def forbid(kind):
        def blocked(*args, **kwargs):
            blocked_attempts.append(kind)
            raise AssertionError(f"Offline release tests forbid {kind}.")
        return blocked

    with ExitStack() as guards:
        guards.enter_context(patch("socket.socket.connect", forbid("socket connection")))
        guards.enter_context(patch("socket.socket.connect_ex", forbid("socket connection")))
        guards.enter_context(patch("socket.create_connection", forbid("socket connection")))
        guards.enter_context(patch("requests.sessions.Session.request", forbid("HTTP request")))
        guards.enter_context(patch("MySQLdb.connect", forbid("MySQL connection")))
        guards.enter_context(patch("MySQLdb._mysql.connect", forbid("MySQL connection")))
        # Never read a local dotenv file, even if one is added to this worktree.
        guards.enter_context(patch("dotenv.load_dotenv", return_value=False))

        import app
        guards.enter_context(patch.object(app, "create_app", forbid("production app startup")))
        guards.enter_context(patch.object(
            app, "_start_permit_expiry_scheduler", forbid("scheduler startup"),
        ))
        suite = unittest.defaultTestLoader.loadTestsFromNames(TEST_MODULES)
        result = unittest.TextTestRunner(verbosity=2).run(suite)

    print(f"Offline guard violations: {len(blocked_attempts)}")
    if blocked_attempts:
        print("Forbidden operation categories: " + ", ".join(sorted(set(blocked_attempts))))
    return 0 if result.wasSuccessful() and not blocked_attempts else 1


if __name__ == "__main__":
    raise SystemExit(main())
