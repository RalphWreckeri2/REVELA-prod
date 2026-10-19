"""Measurement-only instrumentation for the analytics pipeline.

The phase summary must never fabricate work: ``phases_sum_ms`` is the sum of
exclusive, non-overlapping leaf spans only. Inclusive parent spans (those that
enclose other timed work) are logged for context and deliberately excluded, so
``coverage = phases_sum_ms / wall_ms`` stays <= 1.0 unless spans are
double-counted or mis-correlated.

Every SQL leaf carries a stable query label (for example
``diagnostic.barangay_risk``) rather than a position-dependent ``sql#N``, so the
same query can be compared across requests even when conditional queries make
the execution order differ.
"""
import ast
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
        self.calls = []
        self.closed = False

    def execute(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        self.executed.append((args[0], args[1] if len(args) > 1 else None))
        return len(self.executed)

    def fetchall(self):
        return [{"ok": 1}]

    def close(self):
        self.closed = True


class PhaseCollectorTests(unittest.TestCase):

    def test_sum_counts_only_exclusive_spans(self):
        collector = routes._PhaseCollector()
        collector.add_exclusive("kpi.total_businesses", 10.0)
        collector.add_exclusive("kpi.active_count", 20.0)
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

        cur.execute("SELECT 1", label="kpi.total_businesses")
        cur.execute("SELECT 2", ("p",), label="kpi.active_count")

        self.assertEqual([name for name, _ in collector.exclusive],
                         ["kpi.total_businesses", "kpi.active_count"])
        self.assertTrue(all(dur >= 0 for _, dur in collector.exclusive))
        # Parameters reach the wrapped cursor unchanged.
        self.assertEqual(raw.executed, [("SELECT 1", None),
                                        ("SELECT 2", ("p",))])
        # Non-timed attributes are forwarded to the wrapped cursor unchanged.
        self.assertEqual(cur.fetchall(), [{"ok": 1}])
        cur.close()
        self.assertTrue(raw.closed)


class SqlLabelTests(unittest.TestCase):
    """The log name must identify the query, not its position in the request."""

    def _names(self, cur, collector):
        return [name for name, _ in collector.exclusive]

    def test_label_identifies_the_query_even_when_order_changes(self):
        first = routes._PhaseCollector()
        cur = routes._TimedCursor(_FakeCursor(), first)
        routes._execute(cur, "kpi.total_businesses", "SELECT 1")
        routes._execute(cur, "diagnostic.barangay_risk", "SELECT 2")

        second = routes._PhaseCollector()
        cur = routes._TimedCursor(_FakeCursor(), second)
        routes._execute(cur, "diagnostic.barangay_risk", "SELECT 2")
        routes._execute(cur, "kpi.total_businesses", "SELECT 1")

        # Same names in both runs, even though the second reversed the order.
        self.assertEqual(set(self._names(cur, first)),
                         set(self._names(cur, second)))

    def test_schema_probe_helpers_inherit_the_probe_label(self):
        collector = routes._PhaseCollector()
        cur = routes._TimedCursor(_FakeCursor(), collector)

        probe = routes._labeled(
            cur, "schema:enforcement_state.ladder_columns")
        probe.execute("SELECT COLUMN_NAME FROM information_schema.COLUMNS")

        self.assertEqual(self._names(cur, collector),
                         ["schema:enforcement_state.ladder_columns"])

    def test_unlabeled_sql_still_gets_a_stable_name(self):
        collector = routes._PhaseCollector()
        cur = routes._TimedCursor(_FakeCursor(), collector)

        cur.execute("SELECT 1\n  FROM dual")
        cur.execute("SELECT 1 FROM dual")
        cur.execute("SELECT 2 FROM dual")

        first, second, third = self._names(cur, collector)
        # Whitespace does not change the identity of the query.
        self.assertEqual(first, second)
        self.assertNotEqual(second, third)
        self.assertTrue(first.startswith("sql:unlabeled."))

    def test_raw_cursor_gets_no_label_keyword(self):
        raw = _FakeCursor()

        routes._execute(raw, "kpi.total_businesses", "SELECT 1")
        routes._execute(raw, "kpi.active_count", "SELECT 2", ("x",))

        self.assertEqual(raw.executed, [("SELECT 1", None),
                                        ("SELECT 2", ("x",))])
        # The raw cursor sees the same call shape as before: no label kwarg.
        self.assertEqual(raw.calls[0], (("SELECT 1",), {}))
        self.assertEqual(raw.calls[1], (("SELECT 2", ("x",)), {}))


class AllAnalyticsSqlLabelCoverageTests(unittest.TestCase):
    """Every SQL call in the /analytics/all pipeline is explicitly labelled."""

    def _pipeline(self):
        with open(routes.__file__, encoding="utf-8") as handle:
            tree = ast.parse(handle.read())
        return next(
            node for node in tree.body
            if isinstance(node, ast.FunctionDef)
            and node.name == "_get_all_analytics_inner")

    def _string_arg(self, call, index):
        if len(call.args) <= index:
            return None
        arg = call.args[index]
        if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
            return arg.value
        return None

    def test_every_sql_call_is_labelled_and_labels_are_unique(self):
        pipeline = self._pipeline()
        labels = []
        bare_execute = []

        for node in ast.walk(pipeline):
            if not isinstance(node, ast.Call):
                continue
            if isinstance(node.func, ast.Name) and node.func.id == "_execute":
                labels.append(self._string_arg(node, 1))
            elif isinstance(node.func, ast.Name) and node.func.id == "_labeled":
                labels.append(self._string_arg(node, 1))
            elif (isinstance(node.func, ast.Attribute)
                  and node.func.attr == "execute"):
                bare_execute.append(getattr(node, "lineno", None))

        self.assertTrue(labels, "no labelled SQL calls found in the pipeline")
        self.assertNotIn(None, labels)
        self.assertEqual(
            len(labels), len(set(labels)),
            "SQL labels must be unique and stable across requests",
        )
        self.assertEqual(
            bare_execute, [],
            "every SQL call in _get_all_analytics_inner must go through "
            "_execute or _labeled so it has a stable log name",
        )
        # The two schema probes are conditional setup work, not result queries,
        # and they must be traceable too. The registration-type queries are
        # conditional on that probe, and keep their names when they do run.
        self.assertIn("schema:official_registry.registration_type", labels)
        self.assertIn("schema:enforcement_state.ladder_columns", labels)
        self.assertIn("kpi.new_registration", labels)
        self.assertIn("descriptive.registration_type_dist", labels)
        self.assertIn("diagnostic.dbscan_hotspots", labels)
        self.assertIn("diagnostic.morans_barangay_spatial", labels)


class PhaseLoggingTests(unittest.TestCase):

    def test_log_line_carries_req_id_and_coverage(self):
        collector = routes._PhaseCollector()
        collector.add_exclusive("kpi.total_businesses", 30.0)
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
        # The exclusive list names the query, not a sequence number.
        self.assertIn("exclusive=kpi.total_businesses=30.0", joined)
        self.assertNotIn("sql#", joined)
        # The inclusive parent is reported separately, never inside the sum.
        self.assertIn("py:dbscan=5.0", joined)

    def test_coverage_above_one_is_visible_as_a_bug_signal(self):
        collector = routes._PhaseCollector()
        collector.add_exclusive("kpi.total_businesses", 20.0)

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
