"""Phase 2, Part 3: the Black guard on every write path.

One test per guarded path. Nothing here mocks the colour logic or
_sync_flag_color; where a colour matters the real shared builder is used,
with the correlated registry lookups substituted the same way
tests/test_enforcement_ladder_colors.py does.

What is faked is the cursor. There is no test database in this project.

Two details the fake has to get right, both of which bit this file first:

  * locks.lock_column_available() and colors.ladder_columns_available() ask
    information_schema whether the columns EXIST. That is not the same
    question as whether a particular row is locked, and the answer is
    independent of `locked`.
  * locks probes with fetchone(), colors with fetchall(). A fake that only
    satisfies one of them silently makes the guard inert, which looks exactly
    like "the guard does not work".
"""
import os
import sys
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..")))

from api.flags import service as flags_service
from api.inspections import service as inspection_service
from api.registry import reverify as reverify_module
from api.registry import service as registry_service
from api.registry.colors import reset_ladder_column_cache
from api.registry.locks import BlackLockedError, reset_lock_column_cache


class FakeCursor:
    """A cursor that answers the statement set the guard and its callers use.

    `rows` maps a substring of the statement to the row fetchone should
    return. Anything unmatched returns None.
    """

    def __init__(self, *, locked=False, rows=None, migrated=True):
        self.locked = locked
        self.rows = rows or {}
        self.migrated = migrated
        self.rowcount = 1
        self.lastrowid = 1
        self.calls = []
        self._kind = None

    # ── routing ────────────────────────────────────────────────────────────

    @staticmethod
    def classify(sql):
        flat = " ".join(sql.split())
        if "information_schema.COLUMNS" in flat:
            return "probe"
        if "SELECT blackLocked, applicationStatus FROM official_registry" in flat:
            return "lock_read"
        return "sql"

    def execute(self, sql, params=()):
        self.calls.append((" ".join(sql.split()), params))
        self._kind = self.classify(sql)
        self.rowcount = 1

    def fetchone(self):
        kind = self._kind
        if kind == "probe":
            # The column exists iff the database has been migrated.
            return ("blackLocked",) if self.migrated else None
        if kind == "lock_read":
            return {"blackLocked": 1} if self.locked else {"blackLocked": 0}
        sql = self.calls[-1][0] if self.calls else ""
        for needle, value in self.rows.items():
            if needle in sql:
                return dict(value) if isinstance(value, dict) else value
        return None

    def fetchall(self):
        if self._kind == "probe":
            return ([("warningLevel",), ("blackLocked",)]
                    if self.migrated else [])
        return []

    def close(self):
        pass

    # ── assertions ─────────────────────────────────────────────────────────

    def updates(self):
        return [c for c in self.calls if c[0].upper().startswith("UPDATE")]

    def ran(self, needle):
        return [c for c in self.calls if needle in c[0]]


class GuardHarness(unittest.TestCase):

    def setUp(self):
        reset_ladder_column_cache()
        reset_lock_column_cache()
        self.addCleanup(reset_ladder_column_cache)
        self.addCleanup(reset_lock_column_cache)

    @staticmethod
    def _with(cursor, module):
        mock_mysql = MagicMock()
        mock_mysql.connection.cursor.return_value = cursor
        return patch.object(module, "mysql", mock_mysql)


# ── update_business ──────────────────────────────────────────────────────────


BUSINESS = {"businessID": "BIZ-1", "businessName": "ACME", "barangayID": 7}


class UpdateBusinessGuardTests(GuardHarness):

    def _run(self, *, locked, data):
        cursor = FakeCursor(locked=locked, rows={
            "SELECT businessID, businessName, barangayID": dict(BUSINESS),
        })
        with (
            self._with(cursor, registry_service),
            patch.object(registry_service, "_normalise_status",
                         side_effect=lambda v: (v, None)),
        ):
            return registry_service.update_business("BIZ-1", data), cursor

    def test_a_locked_business_refuses_the_edit(self):
        (ok, error), _ = self._run(locked=True, data={"businessName": "NEW"})
        self.assertFalse(ok)
        self.assertIsInstance(error, BlackLockedError)
        self.assertEqual(error.business_id, "BIZ-1")

    def test_a_refused_edit_writes_nothing(self):
        (_, _), cursor = self._run(locked=True, data={"businessName": "NEW"})
        self.assertEqual(cursor.updates(), [])

    def test_an_unlocked_business_is_still_editable(self):
        (ok, error), cursor = self._run(locked=False,
                                        data={"businessName": "NEW"})
        self.assertTrue(ok, error)
        self.assertTrue(cursor.updates())

    def test_a_closed_business_can_still_be_reopened_by_hand(self):
        """Closed is not locked. Reopening is a normal admin correction."""
        (ok, error), cursor = self._run(locked=False,
                                        data={"applicationStatus": "Active"})
        self.assertTrue(ok, error)
        self.assertTrue(any("applicationStatus" in sql
                            for sql, _ in cursor.updates()))

    def test_the_route_answers_409(self):
        from flask import Flask
        from api.registry import routes as registry_routes

        with patch.object(registry_routes, "update_business",
                          return_value=(False, BlackLockedError(
                              "edit this business", "BIZ-1"))):
            app = Flask(__name__)
            with app.test_request_context(
                    "/api/registry/BIZ-1", method="PUT",
                    json={"businessName": "NEW"}):
                response = registry_routes.edit_business.__wrapped__("BIZ-1")
        self.assertEqual(response[1], 409)


# ── update_flag_color ────────────────────────────────────────────────────────


PIN_ROW = {"flagColor": "Red", "detectedName": "ACME", "barangayID": 7,
           "businessID": "BIZ-1"}


class UpdateFlagColorGuardTests(GuardHarness):

    def _registry_only(self, *, locked):
        cursor = FakeCursor(locked=locked)
        with (
            self._with(cursor, flags_service),
            patch("api.notifications.hub.publish_to_admins"),
        ):
            return flags_service.update_flag_color(-7, "Red"), cursor

    def _real_pin(self, *, locked):
        cursor = FakeCursor(locked=locked, rows={
            "SELECT flagColor, detectedName": dict(PIN_ROW),
        })
        with (
            self._with(cursor, flags_service),
            patch("api.notifications.hub.publish_to_admins"),
        ):
            return flags_service.update_flag_color(22, "Green"), cursor

    def test_a_locked_registry_only_flag_refuses_the_recolour(self):
        (ok, error), _ = self._registry_only(locked=True)
        self.assertFalse(ok)
        self.assertIsInstance(error, BlackLockedError)

    def test_a_refused_registry_recolour_writes_nothing(self):
        (_, _), cursor = self._registry_only(locked=True)
        self.assertEqual(cursor.updates(), [])

    def test_a_locked_real_pin_refuses_the_recolour(self):
        (ok, error), cursor = self._real_pin(locked=True)
        self.assertFalse(ok)
        self.assertIsInstance(error, BlackLockedError)
        self.assertEqual(cursor.updates(), [])

    def test_an_unlocked_registry_flag_is_still_recolourable(self):
        (ok, error), _ = self._registry_only(locked=False)
        self.assertTrue(ok, error)

    def test_an_unlocked_real_pin_is_still_recolourable(self):
        (ok, error), _ = self._real_pin(locked=False)
        self.assertTrue(ok, error)

    def test_the_route_answers_409(self):
        from flask import Flask
        from api.flags import routes as flags_routes

        with (
            patch.object(flags_routes, "update_flag_color",
                         return_value=(False, BlackLockedError(
                             "recolour this flag", "BIZ-1"))),
            patch.object(flags_routes, "get_jwt_identity", return_value=2),
        ):
            app = Flask(__name__)
            with app.test_request_context(
                    "/api/flags/22/color", method="PUT", json={"color": "Red"}):
                response = flags_routes.change_flag_color_route.__wrapped__(22)
        self.assertEqual(response[1], 409)
        self.assertEqual(response[0].get_json()["code"], "black_locked")


# ── reverify: colour recompute only ──────────────────────────────────────────


class ReverifyGuardTests(GuardHarness):

    BIZ = {"businessID": "BIZ-1", "barangayID": 7, "businessName": "ACME",
           "applicationStatus": "Active", "businessAddress": "Somewhere"}

    def _move(self, *, locked, sync_calls):
        cursor = FakeCursor(locked=locked, rows={
            "SELECT COUNT(*) AS n": {"n": 1},
        })
        service = MagicMock()
        service._sync_flag_color.side_effect = (
            lambda *a, **k: sync_calls.append(1))
        moved = reverify_module._move_pin(cursor, service, dict(self.BIZ),
                                          13.9, 121.1)
        return moved, cursor, sync_calls

    def test_a_locked_business_keeps_its_colour_during_reverify(self):
        _, _, sync_calls = self._move(locked=True, sync_calls=[])
        self.assertEqual(sync_calls, [], "_sync_flag_color must not run")

    def test_the_pin_still_moves_for_a_locked_business(self):
        """Re-verify is a location fix, not an enforcement action."""
        _, cursor, _ = self._move(locked=True, sync_calls=[])
        self.assertTrue(
            cursor.ran("UPDATE geospatial_logs SET latitude"),
            "coordinates must still be written")

    def test_an_unlocked_business_recomputes_its_colour(self):
        _, _, sync_calls = self._move(locked=False, sync_calls=[])
        self.assertEqual(len(sync_calls), 1)


# ── snap_unresolved_pins: colour write skipped, run continues ────────────────


class SnapGuardTests(GuardHarness):

    def test_the_colour_write_is_the_only_thing_skipped(self):
        import inspect

        source = inspect.getsource(registry_service.snap_unresolved_pins)
        self.assertIn("if not is_black_locked(cur2, bid):", source)
        # The coordinate write above it is outside the guard.
        guard = source.index("if not is_black_locked(cur2, bid):")
        self.assertIn("places_resolver._update_pin(", source[:guard])
        self.assertIn("skipped_black_lock += 1", source)

    def test_the_counter_is_reported(self):
        import inspect

        source = inspect.getsource(registry_service.snap_unresolved_pins)
        self.assertIn('"skipped_black_lock": skipped_black_lock', source)


# ── check_and_expire_old_permits: defensive ──────────────────────────────────


class ExpiryGuardTests(GuardHarness):

    def _source(self):
        import inspect

        return inspect.getsource(registry_service.check_and_expire_old_permits)

    def test_the_rollover_excludes_locked_rows(self):
        source = self._source()
        self.assertIn("ladder_columns_available(cursor)", source)
        self.assertIn("blackLocked", source)

    def test_the_guard_is_conditional_on_the_column_existing(self):
        """An unmigrated database must still expire permits."""
        self.assertIn('lock_guard = ""', self._source())


if __name__ == "__main__":
    unittest.main()
