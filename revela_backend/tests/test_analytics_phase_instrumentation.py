"""Measurement-only instrumentation for the analytics pipeline.

The phase summary must never fabricate work: ``phases_sum_ms`` is the sum of
exclusive, non-overlapping leaf spans only. Inclusive parent spans (those that
enclose other timed work) are logged for context and deliberately excluded, so
``coverage = phases_sum_ms / wall_ms`` stays <= 1.0 unless spans are
double-counted or mis-correlated.
"""
import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..")))

from flask import Flask, g

from api.analytics import routes


class _FakeCursor:
    def __init__(self):
        self.executed = []
        self.closed = False

    def execute(self, sql, params=None):
        self.executed.append(sql)
        return len(self.executed)

    def fetchall(self):
        return [{"ok": 1}]

    def close(self):
        self.closed = True


class PhaseCollectorTests(unittest.TestCase):

    def test_sum_counts_only_exclusive_spans(self):
        collector = routes._PhaseCollector()
        collector.add_exclusive("sql#1", 10.0)
        collector.add_exclusive("sql#2", 20.0)
        # An inclusive parent that encloses the two SQL calls must NOT count.
        collector.add_inclusive("py:dbscan", 100.0)

        self.assertEqual(collector.exclusive_sum_ms(), 30.0)

    def test_inclusive_span_never_reaches_the_sum(self):
        collector = routes._PhaseCollector()
        collector.add_inclusive("py:get_recent_detection_runs", 42.0)

        self.assertEqual(collector.exclusive_sum_ms(), 0.0)

    def test_timed_cursor_times_each_execute_and_forwards_everything_else(self):
        collector = routes._PhaseCollector()
        raw = _FakeCursor()
        cur = routes._TimedCursor(raw, collector)

        cur.execute("SELECT 1")
        cur.execute("SELECT 2")

        self.assertEqual([name for name, _ in collector.exclusive],
                         ["sql#1", "sql#2"])
        self.assertTrue(all(dur >= 0 for _, dur in collector.exclusive))
        # Non-timed attributes are forwarded to the wrapped cursor unchanged.
        self.assertEqual(cur.fetchall(), [{"ok": 1}])
        cur.close()
        self.assertTrue(raw.closed)


class PhaseLoggingTests(unittest.TestCase):

    def test_log_line_carries_req_id_and_coverage(self):
        collector = routes._PhaseCollector()
        collector.add_exclusive("sql#1", 30.0)
        collector.add_inclusive("py:dbscan", 5.0)

        app = Flask(__name__)
        with app.test_request_context("/api/analytics/all"):
            g._revela_id = "abc123"
            with self.assertLogs("revela.analytics", level="INFO") as captured:
                routes._log_analytics_phases(collector, 100.0, "deadbeefcafe")

        joined = "\n".join(captured.output)
        self.assertIn("[analytics-phases]", joined)
        self.assertIn("req_id=abc123", joined)
        self.assertIn("phases_sum_ms=30.0", joined)
        self.assertIn("wall_ms=100.0", joined)
        self.assertIn("coverage=0.300", joined)
        # The inclusive parent is reported separately, never inside the sum.
        self.assertIn("py:dbscan=5.0", joined)

    def test_coverage_above_one_is_visible_as_a_bug_signal(self):
        collector = routes._PhaseCollector()
        collector.add_exclusive("sql#1", 20.0)

        app = Flask(__name__)
        with app.test_request_context("/api/analytics/all"):
            with self.assertLogs("revela.analytics", level="INFO") as captured:
                routes._log_analytics_phases(collector, 10.0, "deadbeefcafe")

        self.assertIn("coverage=2.000", "\n".join(captured.output))

    def test_cache_line_shares_the_same_req_id(self):
        app = Flask(__name__)
        with app.test_request_context("/api/analytics/all"):
            g._revela_id = "abc123"
            with self.assertLogs("revela.analytics", level="INFO") as captured:
                routes._log_analytics_cache("hit", 0, 0.0, "deadbeefcafe")

        joined = "\n".join(captured.output)
        self.assertIn("[analytics-cache]", joined)
        self.assertIn("req_id=abc123", joined)


class PhasesGateTests(unittest.TestCase):

    def test_gate_is_off_by_default(self):
        previous = os.environ.pop("REVELA_ANALYTICS_PHASES", None)
        try:
            self.assertFalse(routes._phases_enabled())
        finally:
            if previous is not None:
                os.environ["REVELA_ANALYTICS_PHASES"] = previous

    def test_gate_reads_truthy_values(self):
        previous = os.environ.get("REVELA_ANALYTICS_PHASES")
        try:
            for value in ("1", "true", "yes", "on"):
                os.environ["REVELA_ANALYTICS_PHASES"] = value
                self.assertTrue(routes._phases_enabled())
            os.environ["REVELA_ANALYTICS_PHASES"] = "0"
            self.assertFalse(routes._phases_enabled())
        finally:
            if previous is None:
                os.environ.pop("REVELA_ANALYTICS_PHASES", None)
            else:
                os.environ["REVELA_ANALYTICS_PHASES"] = previous


class PhaseOverheadTests(unittest.TestCase):
    """An off gate must read the clock zero times (exact zero-overhead)."""

    def test_phase_start_returns_none_without_reading_the_clock(self):
        with patch("time.perf_counter") as clock:
            self.assertIsNone(routes._phase_start(None))
        clock.assert_not_called()

    def test_phase_start_reads_the_clock_when_active(self):
        collector = routes._PhaseCollector()
        with patch("time.perf_counter", return_value=123.0) as clock:
            self.assertEqual(routes._phase_start(collector), 123.0)
        clock.assert_called_once()

    def test_record_inclusive_noops_without_a_collector(self):
        with patch("time.perf_counter") as clock:
            routes._record_inclusive(None, "py:dbscan", 123.0)
        clock.assert_not_called()

    def test_record_inclusive_skips_a_missing_start(self):
        collector = routes._PhaseCollector()
        routes._record_inclusive(collector, "py:dbscan", None)

        self.assertEqual(collector.inclusive, [])


if __name__ == "__main__":
    unittest.main()
