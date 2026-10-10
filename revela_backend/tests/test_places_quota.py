import unittest
from concurrent.futures import ThreadPoolExecutor
import threading
from unittest.mock import MagicMock, patch

from api.flags import service as flags_service
from api.utils import places_quota


class PlacesQuotaLedgerTests(unittest.TestCase):

    def setUp(self):
        places_quota._table_ready = False

    def test_detection_budget_setup_does_not_drop_or_truncate_tables(self):
        from api.flags import service

        cursor = MagicMock()
        with patch.object(service, "mysql") as mysql, \
                patch.object(service, "_budget_tables_ready", False):
            mysql.connection.cursor.return_value = cursor

            service._ensure_budget_tables()

        queries = [call.args[0].upper()
                   for call in cursor.execute.call_args_list]
        self.assertTrue(
            any("CREATE TABLE IF NOT EXISTS PLACES_API_USAGE" in q for q in queries))
        self.assertTrue(
            any("CREATE TABLE IF NOT EXISTS SCAN_POINT_LOG" in q for q in queries))
        self.assertFalse(
            any("DROP TABLE" in q or "TRUNCATE TABLE" in q for q in queries))
        mysql.connection.commit.assert_called_once()

    @patch("api.utils.places_quota._ensure_table")
    def test_reservation_uses_conditional_updates_and_commits(self, _ensure):
        connection = MagicMock()
        cursor = connection.cursor.return_value
        cursor.rowcount = 1

        allowed, reason = places_quota.reserve_usage_slot(
            connection, "imp_ts_month", "imp_ts_day", 2500, 75
        )

        self.assertTrue(allowed)
        self.assertIsNone(reason)
        update_queries = [
            call.args[0]
            for call in cursor.execute.call_args_list
            if "UPDATE places_api_usage SET requestCount = requestCount + 1" in call.args[0]
        ]
        self.assertEqual(len(update_queries), 2)
        self.assertTrue(
            all("requestCount < %s" in query for query in update_queries))
        connection.commit.assert_called_once()
        connection.rollback.assert_not_called()

    @patch("api.utils.places_quota._ensure_table")
    def test_daily_denial_rolls_back_monthly_reservation(self, _ensure):
        connection = MagicMock()
        cursor = connection.cursor.return_value
        cursor.rowcount = 1

        def execute(sql, _params=None):
            if "WHERE usageDate = CURDATE()" in sql and "requestCount = requestCount + 1" in sql:
                cursor.rowcount = 0
            else:
                cursor.rowcount = 1

        cursor.execute.side_effect = execute
        allowed, reason = places_quota.reserve_usage_slot(
            connection, "imp_ts_month", "imp_ts_day", 2500, 75
        )

        self.assertFalse(allowed)
        self.assertEqual(reason, "daily_quota_exceeded")
        connection.rollback.assert_called_once()
        connection.commit.assert_not_called()

    @patch("api.utils.places_quota._ensure_table")
    def test_shared_and_workflow_budgets_reserve_atomically(self, _ensure):
        connection = MagicMock()
        cursor = connection.cursor.return_value
        cursor.rowcount = 1

        allowed, reason = places_quota.reserve_usage_slot(
            connection,
            "imp_ts_month",
            "imp_ts_day",
            2500,
            400,
            additional_daily_limits=(("ts_snap_day", 100),),
        )

        self.assertTrue(allowed)
        self.assertIsNone(reason)
        increments = [
            call for call in cursor.execute.call_args_list
            if "UPDATE places_api_usage SET requestCount = requestCount + 1" in call.args[0]
        ]
        self.assertEqual(len(increments), 3)
        self.assertEqual(increments[0].args[1][0], "imp_ts_month")
        self.assertEqual(increments[1].args[1][0], "imp_ts_day")
        self.assertEqual(increments[2].args[1][0], "ts_snap_day")
        connection.commit.assert_called_once()
        connection.rollback.assert_not_called()

    @patch("api.utils.places_quota._ensure_table")
    def test_workflow_daily_denial_rolls_back_all_buckets(self, _ensure):
        connection = MagicMock()
        cursor = connection.cursor.return_value

        def execute(sql, params=None):
            if "UPDATE places_api_usage SET requestCount = requestCount + 1" in sql:
                cursor.rowcount = 0 if params[0] == "ts_snap_day" else 1
            else:
                cursor.rowcount = 1

        cursor.execute.side_effect = execute
        allowed, reason = places_quota.reserve_usage_slot(
            connection,
            "imp_ts_month",
            "imp_ts_day",
            2500,
            400,
            additional_daily_limits=(("ts_snap_day", 100),),
        )

        self.assertFalse(allowed)
        self.assertEqual(reason, "daily_quota_exceeded")
        connection.rollback.assert_called_once()
        connection.commit.assert_not_called()

    @patch("api.utils.places_quota._ensure_table")
    def test_monthly_denial_never_attempts_daily_increment(self, _ensure):
        connection = MagicMock()
        cursor = connection.cursor.return_value

        def execute(sql, _params=None):
            cursor.rowcount = (
                0 if "requestCount = requestCount + 1" in sql else 1
            )

        cursor.execute.side_effect = execute
        allowed, reason = places_quota.reserve_usage_slot(
            connection, "imp_ts_month", "imp_ts_day", 2500, 75
        )

        self.assertFalse(allowed)
        self.assertEqual(reason, "monthly_quota_exceeded")
        self.assertFalse(any(
            "WHERE usageDate = CURDATE()" in call.args[0]
            and "requestCount = requestCount + 1" in call.args[0]
            for call in cursor.execute.call_args_list
        ))

    @patch("api.utils.places_quota._ensure_table")
    def test_database_error_rolls_back_and_propagates(self, _ensure):
        connection = MagicMock()
        cursor = connection.cursor.return_value
        cursor.execute.side_effect = RuntimeError("database unavailable")

        with self.assertRaisesRegex(RuntimeError, "database unavailable"):
            places_quota.reserve_usage_slot(
                connection, "imp_ts_month", "imp_ts_day", 2500, 75
            )

        connection.rollback.assert_called_once()
        connection.commit.assert_not_called()

    def test_concurrent_admin_requests_share_one_atomic_global_budget(self):
        """Independent request connections cannot reserve past a shared cap."""
        state = {"rows": {}, "lock": threading.RLock()}

        class SharedLedgerCursor:
            def __init__(self, connection):
                self.connection = connection
                self.rowcount = 0
                self.result = None

            def execute(self, sql, params=()):
                if sql.startswith("SELECT requestCount FROM places_api_usage"):
                    period = "month" if "DATE_SUB(" in sql else "day"
                    self.result = {
                        "requestCount": state["rows"].get(
                            (period, params[0]), 0)
                    }
                    return
                if sql.startswith("INSERT IGNORE"):
                    self.rowcount = 1
                    return
                if "UPDATE places_api_usage SET requestCount" not in sql:
                    raise AssertionError(f"Unexpected query: {sql}")
                kind, cap = params
                period = "month" if "DATE_SUB(" in sql else "day"
                key = (period, kind)
                used = state["rows"].get(key, 0)
                if used < cap:
                    state["rows"][key] = used + 1
                    self.rowcount = 1
                else:
                    self.rowcount = 0

            def fetchone(self):
                return self.result

            def close(self):
                pass

        class SharedLedgerConnection:
            def __init__(self):
                self.snapshot = None

            def begin(self):
                state["lock"].acquire()
                self.snapshot = dict(state["rows"])

            def cursor(self):
                return SharedLedgerCursor(self)

            def commit(self):
                self.snapshot = None
                state["lock"].release()

            def rollback(self):
                state["rows"] = self.snapshot
                self.snapshot = None
                state["lock"].release()

        def reserve_as_admin(_admin_role):
            # Each account/request receives its own DB connection, but both
            # reserve against the same application-wide database ledger.
            connection = SharedLedgerConnection()
            return places_quota.reserve_usage_slot(
                connection, "imp_ts_month", "imp_ts_day", 10, 10
            )[0]

        with patch.object(places_quota, "_ensure_table"):
            with ThreadPoolExecutor(max_workers=24) as executor:
                outcomes = list(executor.map(
                    reserve_as_admin,
                    ["Admin", "SUPER_ADMIN"] * 50,
                ))

        self.assertEqual(sum(outcomes), 10)
        self.assertEqual(state["rows"][("month", "imp_ts_month")], 10)
        self.assertEqual(state["rows"][("day", "imp_ts_day")], 10)
        with patch.object(places_quota, "_ensure_table"):
            admin_views = [
                places_quota.read_usage(
                    SharedLedgerConnection(), "imp_ts_month", "imp_ts_day")
                for _role in ("Admin", "SUPER_ADMIN")
            ]
        self.assertEqual(admin_views[0], admin_views[1])
        self.assertEqual(admin_views[0], {"month": 10, "day": 10})

    def test_places_usage_reports_effective_admin_overrides(self):
        caps = {
            "quota.geocoding.daily": 21,
            "quota.geocoding.monthly": 210,
            "quota.text_search.daily": 22,
            "quota.text_search.monthly": 220,
            "quota.place_details.daily": 23,
            "quota.place_details.monthly": 230,
            "quota.text_search.workflow.registry_import": 5,
            "quota.text_search.workflow.snap_pins": 6,
            "quota.text_search.workflow.reverify": 7,
            "quota.legacy_nearby.daily": 24,
            "quota.legacy_nearby.monthly": 240,
            "quota.nearby_new.daily": 25,
            "quota.nearby_new.monthly": 250,
            "run_detection.monthly_scan_limit": 8,
        }

        def usage_for(_connection, monthly_kind, daily_kind):
            return {"month": 40, "day": 4}

        with patch.object(flags_service, "_ensure_budget_tables"), \
                patch.object(flags_service, "mysql", MagicMock()), \
                patch.object(flags_service, "_places_usage_count",
                             side_effect=lambda _cursor, _kind,
                             today=False: 4 if today else 40), \
                patch.object(flags_service, "read_usage",
                             side_effect=usage_for), \
                patch.object(flags_service, "read_daily_usage", return_value=2), \
                patch.object(flags_service.quota_settings, "cap",
                             side_effect=caps.__getitem__), \
                patch.object(flags_service, "_nearby_api_mode",
                             return_value="legacy"):
            report = flags_service.get_places_usage_today()

        self.assertEqual(report["text_search_day"]["cap"], 22)
        self.assertEqual(report["text_search_month"]["cap"], 220)
        self.assertEqual(report["text_search_workflows"]["snap_pins"]["daily_cap"], 6)
        self.assertEqual(report["geocode"]["cap"], 21)
        self.assertEqual(report["place_details_day"]["cap"], 23)
        self.assertEqual(report["nearby_search_active"]["daily_cap"], 24)
        self.assertEqual(
            report["quota_settings"]["run_detection_monthly_scan_limit"], 8)


if __name__ == "__main__":
    unittest.main()
