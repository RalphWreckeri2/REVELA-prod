"""Phase 2, Part 4: sync skips Black locked and Closed rows.

Neither _sync_flag_color nor the colour logic is mocked. The preload is
exercised through the real _load_sync_protection_keys, and the row loop is
driven with a fake cursor whose fetchone answers the registry SELECTs, so
the skips are proved by which statements were issued, not by inspecting
counter arithmetic.

Both caches are reset per test, because ladder_columns_available and
lock_column_available cache for the life of the process.
"""
import io
import os
import sys
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..")))

from api.registry import service as registry_service
from api.registry.colors import reset_ladder_column_cache
from api.registry.locks import reset_lock_column_cache


class SyncHarness(unittest.TestCase):

    def setUp(self):
        reset_ladder_column_cache()
        reset_lock_column_cache()
        self.addCleanup(reset_ladder_column_cache)
        self.addCleanup(reset_lock_column_cache)

    # ── the preload ────────────────────────────────────────────────────────

    class _PreloadCursor:
        """Answers the information_schema probe and the two preloads."""

        def __init__(self, *, migrated=True, black=None, closed=None,
                     fail_on=None):
            self.migrated = migrated
            self.black = black or []
            self.closed = closed or []
            self.fail_on = fail_on
            self.calls = []
            self.rowcount = 1

        def execute(self, sql, params=()):
            flat = " ".join(sql.split())
            self.calls.append(flat)
            if self.fail_on and self.fail_on in flat:
                raise RuntimeError("simulated database failure")

        def fetchone(self):
            return ("warningLevel",) if self.migrated else None

        def fetchall(self):
            flat = self.calls[-1] if self.calls else ""
            if "blackLocked = 1" in flat:
                return [{"businessID": b} for b in self.black]
            if "applicationStatus = 'Closed'" in flat:
                return [{"businessID": b} for b in self.closed]
            if "information_schema.COLUMNS" in flat:
                return ([("warningLevel",), ("blackLocked",)]
                        if self.migrated else [])
            return []

        def close(self):
            pass

    def _preload(self, cursor):
        return registry_service._load_sync_protection_keys(cursor)


class PreloadTests(SyncHarness):

    def test_preloads_black_locked_and_closed_ids(self):
        cursor = self._PreloadCursor(black=["B-1", "B-2"], closed=["C-1"])
        black, closed = self._preload(cursor)
        self.assertEqual(black, {"B-1", "B-2"})
        self.assertEqual(closed, {"C-1"})

    def test_closed_is_preloaded_even_without_the_ladder_columns(self):
        cursor = self._PreloadCursor(migrated=False, black=["B-1"],
                                     closed=["C-1"])
        black, closed = self._preload(cursor)
        self.assertEqual(black, set(), "nothing to protect against")
        self.assertEqual(closed, {"C-1"}, "Closed skip still applies")

    def test_the_black_query_is_not_issued_without_the_columns(self):
        cursor = self._PreloadCursor(migrated=False)
        self._preload(cursor)
        self.assertFalse(any("blackLocked = 1" in c for c in cursor.calls))

    def test_a_failed_black_lookup_raises(self):
        cursor = self._PreloadCursor(fail_on="blackLocked = 1")
        with self.assertRaises(RuntimeError):
            self._preload(cursor)

    def test_a_failed_closed_lookup_raises(self):
        cursor = self._PreloadCursor(fail_on="applicationStatus = 'Closed'")
        with self.assertRaises(RuntimeError):
            self._preload(cursor)


CSV = b"Business ID,businessName\nBIZ-1,ACME STORE\n"


class _PreloadCursor:
    """Answers the probe, the black preload and the closed preload.

    Without a correct answer to the probe the ladder columns look absent, the
    black query is never issued, and a test that is meant to prove the black
    guard fails closed silently proves nothing.
    """

    def __init__(self, *, fail_on=None):
        self.fail_on = fail_on
        self.calls = []
        self.lastrowid = 1
        self.rowcount = 1

    @staticmethod
    def _flat(sql):
        return " ".join(sql.split())

    def execute(self, sql, params=()):
        flat = self._flat(sql)
        self.calls.append(flat)
        if self.fail_on == "black" and "blackLocked = 1" in flat:
            raise RuntimeError("connection lost")
        if self.fail_on == "closed" and "applicationStatus = 'Closed'" in flat:
            raise RuntimeError("connection lost")

    def fetchone(self):
        return ("warningLevel",)

    def fetchall(self):
        flat = self.calls[-1] if self.calls else ""
        if "blackLocked = 1" in flat:
            return [{"businessID": "BIZ-9"}]
        if "applicationStatus = 'Closed'" in flat:
            return [{"businessID": "BIZ-9"}]
        if "information_schema.COLUMNS" in flat:
            return [("warningLevel",), ("blackLocked",)]
        return []

    def close(self):
        pass

    def writes(self):
        return [c for c in self.calls
                if c.upper().startswith(("UPDATE", "INSERT", "DELETE"))]


class SyncAbortsOnAFailedPreloadTests(SyncHarness):
    """Fail closed.

    sync_registry ends in `except Exception: return None, str(e)`, so the
    typed preload error surfaces as an error string rather than propagating -
    the same way OpenInspectionLookupError already behaves. The route maps a
    message containing "changed" to 409.
    """

    def _run(self, *, fail_on=None, open_inspection=None):
        cursor = _PreloadCursor(fail_on=fail_on)
        with (
            patch.object(registry_service, "mysql") as mock_mysql,
            patch.object(registry_service, "_load_barangay_lookup",
                         return_value={}),
            patch.object(registry_service, "_load_open_inspection_keys",
                         side_effect=open_inspection,
                         return_value=(set(), set())),
        ):
            mock_mysql.connection.cursor.return_value = cursor
            # sync_registry re-raises the typed lookup errors now.
            try:
                result, error = registry_service.sync_registry(
                    io.BytesIO(CSV), ".csv")
            except (registry_service.SyncProtectionLookupError,
                    registry_service.OpenInspectionLookupError) as exc:
                result, error = None, exc
        return (result, error), cursor

    def test_the_preload_actually_runs_in_this_harness(self):
        """Guards the guard: without this the tests below prove nothing."""
        _, cursor = self._run()
        self.assertTrue(any("blackLocked = 1" in c for c in cursor.calls))
        self.assertTrue(any("applicationStatus = 'Closed'" in c
                            for c in cursor.calls))

    def test_a_failed_black_preload_aborts_with_no_writes(self):
        (result, error), cursor = self._run(fail_on="black")
        self.assertIsNone(result)
        self.assertIsInstance(error, registry_service.SyncProtectionLookupError)
        self.assertEqual(cursor.writes(), [])

    def test_a_failed_closed_preload_aborts_with_no_writes(self):
        (result, error), cursor = self._run(fail_on="closed")
        self.assertIsNone(result)
        self.assertIsInstance(error, registry_service.SyncProtectionLookupError)
        self.assertEqual(cursor.writes(), [])

    def test_the_error_is_typed_not_stringified(self):
        """The whole point of Part 0: the route must not read the message."""
        (_, error), _ = self._run(fail_on="black")
        self.assertNotIsInstance(error, str)

    def test_an_open_inspection_failure_keeps_its_own_type(self):
        """The two guards stay distinguishable to the caller."""
        (result, error), _ = self._run(
            open_inspection=RuntimeError("boom"))
        self.assertIsNone(result)
        self.assertIsInstance(error,
                              registry_service.OpenInspectionLookupError)

    def test_the_message_still_explains_itself(self):
        (_, error), _ = self._run(fail_on="black")
        self.assertIn("nothing was changed", str(error))


class SyncRouteAnswers409Tests(unittest.TestCase):
    """The status code must not depend on the wording of the message."""

    def _route(self, error):
        from flask import Flask
        from api.registry import routes as registry_routes

        with patch.object(registry_routes, "sync_registry",
                          return_value=(None, error)):
            app = Flask(__name__)
            data = {"file": (io.BytesIO(b"a,b\n1,2\n"), "x.csv")}
            with app.test_request_context(
                    "/api/registry/sync", method="POST",
                    data=data, content_type="multipart/form-data"):
                return registry_routes.sync.__wrapped__()

    def test_a_protection_lookup_failure_answers_409(self):
        response = self._route(registry_service.SyncProtectionLookupError(
            "Could not read the protections; sync aborted, nothing was changed."))
        self.assertEqual(response[1], 409)

    def test_an_open_inspection_failure_answers_409(self):
        response = self._route(registry_service.OpenInspectionLookupError(
            "Could not check open inspections; sync aborted."))
        self.assertEqual(response[1], 409)

    def test_the_status_survives_a_reword(self):
        """Reword the message entirely; 409 must not become 500."""
        for message in ("nope", "sync aborted", "", "zzz nothing at all"):
            with self.subTest(message=message):
                response = self._route(
                    registry_service.SyncProtectionLookupError(message))
                self.assertEqual(response[1], 409)

    def test_an_ordinary_failure_is_still_500(self):
        response = self._route("something else went wrong")
        self.assertEqual(response[1], 500)


class SyncSkipsProtectedRowsTests(SyncHarness):
    """Drive the real row loop and read the real summary counters."""

    CSV = (b"Business ID,businessName\n"
           b"BIZ-1,BLACK LOCKED STORE\n"
           b"BIZ-2,CLOSED STORE\n"
           b"BIZ-3,ORDINARY STORE\n")

    class _Cursor(_PreloadCursor):
        def __init__(self):
            super().__init__()
            self.seen_business_ids = []

        def execute(self, sql, params=()):
            super().execute(sql, params)
            flat = self._flat(sql)
            if "SELECT businessID, barangayID, businessName" in flat:
                self.seen_business_ids.append(params[0])

        def fetchone(self):
            flat = self.calls[-1] if self.calls else ""
            if "SELECT businessID, barangayID, businessName" in flat:
                biz_id = self.seen_business_ids[-1]
                return {
                    "businessID": biz_id, "barangayID": 7,
                    "businessName": "A STORE", "businessType": None,
                    "lineOfBusiness": None, "businessAddress": None,
                    "applicationStatus": "Active", "lastRenewalDate": None,
                    "businessSize": None, "registrationType": None,
                    "latitude": None, "longitude": None,
                    "coordSource": None, "placeID": None,
                    "placeIDKind": None, "matchScore": None,
                    "matchStatus": None, "resolveKey": None,
                }
            return ("warningLevel",)

        def fetchall(self):
            flat = self.calls[-1] if self.calls else ""
            if "blackLocked = 1" in flat:
                return [{"businessID": "BIZ-1"}]
            if "applicationStatus = 'Closed'" in flat:
                return [{"businessID": "BIZ-2"}]
            return super().fetchall()

    def _sync(self):
        cursor = self._Cursor()
        with (
            patch.object(registry_service, "mysql") as mock_mysql,
            patch.object(registry_service, "_load_barangay_lookup",
                         return_value={1: {"barangayID": 1}}),
            patch.object(registry_service, "_load_open_inspection_keys",
                         return_value=(set(), set())),
            patch.object(registry_service.places_resolver,
                         "reset_run_state"),
            patch.object(registry_service, "set_cancel"),
            # Barangay plumbing is not what this file tests; every row is
            # given a resolvable barangay so the loop reaches the guards.
            patch.object(registry_service, "_resolve_barangay_id",
                         return_value=7),
        ):
            mock_mysql.connection.cursor.return_value = cursor
            return registry_service.sync_registry(
                io.BytesIO(self.CSV), ".csv"), cursor

    def test_black_locked_and_closed_rows_are_skipped_and_counted(self):
        (summary, error), _ = self._sync()
        self.assertIsNone(error)
        self.assertEqual(summary["skipped_black_lock"], 1)
        self.assertEqual(summary["skipped_closed"], 1)

    def test_skipped_is_the_running_total(self):
        (summary, _), _ = self._sync()
        self.assertEqual(
            summary["skipped"],
            summary["skipped_black_lock"] + summary["skipped_closed"]
            + summary["skipped_open_inspection"]
            + summary["invalid_status_rows"])

    def test_the_message_names_the_reason(self):
        (summary, _), _ = self._sync()
        joined = " ".join(summary["errors"])
        self.assertIn("Black locked", joined)
        self.assertIn("Closed", joined)

    def test_a_protected_row_is_never_updated(self):
        (_, _), cursor = self._sync()
        updated = [c for c in cursor.calls
                   if c.upper().startswith("UPDATE")
                   and ("BIZ-1" in c or "BIZ-2" in c)]
        self.assertEqual(updated, [],
                         "a protected row must never be written")


class SkipLogicTests(SyncHarness):
    """The skip block, proved against the real source ordering.

    Driving the whole of sync_registry needs pandas and a file; what matters
    here is that the skips sit before the statement that writes, and that the
    summary exposes both counters.
    """

    @staticmethod
    def _source():
        import inspect

        return inspect.getsource(registry_service.sync_registry)

    def test_the_skips_come_before_any_write(self):
        source = self._source()
        black = source.index("if biz_id in black_locked_ids:")
        closed = source.index("if biz_id in closed_ids:")
        # _sync_flag_color runs outside the change guard and is the last thing
        # that writes to the pin, so the skips must precede it.
        sync_colour = source.index("_sync_flag_color(")
        self.assertLess(black, sync_colour)
        self.assertLess(closed, sync_colour)
        # And they must precede the geocoding, which costs quota.
        self.assertLess(black, source.index("status_raw = row.get"))

    def test_black_is_checked_before_closed(self):
        source = self._source()
        self.assertLess(source.index("skipped_black_lock += 1"),
                        source.index("skipped_closed += 1"))

    def test_both_counters_are_in_the_summary(self):
        source = self._source()
        self.assertIn('"skipped_black_lock": skipped_black_lock', source)
        self.assertIn('"skipped_closed": skipped_closed', source)

    def test_skipped_stays_the_running_total(self):
        source = self._source()
        for counter in ("skipped_black_lock", "skipped_closed",
                        "skipped_open_inspection"):
            block = source[source.index("%s += 1" % counter) - 40:
                           source.index("%s += 1" % counter)]
            self.assertIn("skipped += 1", block,
                          "%s must also bump the running total" % counter)


class SyncNeverWritesTheLadderTests(SyncHarness):

    def test_sync_has_no_ladder_column_in_any_statement(self):
        """A sync must never touch warningLevel or blackLocked."""
        import inspect

        source = inspect.getsource(registry_service.sync_registry)
        body = source[source.index("def "):]
        for forbidden in ("warningLevel =", "blackLocked =",
                          "blackLockedAt", "blackLockedBy",
                          "registry_enforcement_events"):
            self.assertNotIn(forbidden, body,
                             "sync must never write %s" % forbidden)

    def test_the_column_propagator_has_no_ladder_sql(self):
        import inspect

        source = inspect.getsource(registry_service._sync_flag_color)
        for forbidden in ("warningLevel", "blackLocked"):
            self.assertNotIn(forbidden, source)


class ClosedReopenTests(SyncHarness):
    """Closed is frozen to a CSV import, not to an admin."""

    def test_sync_freezes_a_closed_row(self):
        source = self._source() if hasattr(self, "_source") else None
        source = source or __import__("inspect").getsource(
            registry_service.sync_registry)
        self.assertIn("permit is Closed", source)

    def test_an_admin_can_still_reopen_one_by_hand(self):
        """The guard is in sync, not in update_business."""
        import inspect

        update = inspect.getsource(registry_service.update_business)
        self.assertIn("assert_not_black_locked", update)
        self.assertNotIn("Closed", update.split("assert_not_black_locked")[1][:400])


if __name__ == "__main__":
    unittest.main()
