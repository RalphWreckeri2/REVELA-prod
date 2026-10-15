"""Phase 1, Part 2: the enforcement-ladder colour rule.

Two things are checked, and they are checked without mocking the colour
logic.

1. status_to_color() in pure Python. Every combination of registry status,
   warning level and Black lock, against an expectation table written out
   literally here rather than imported from the module under test.

2. _effective_flag_color_sql() executed for real by SQLite. Following the
   technique used by tests/test_analytics_flag_colour_filter.py and
   tests/test_inspection_eligibility_gate.py: SQLite cannot bind a correlated
   reference inside a subquery ORDER BY, which MySQL allows and this expression
   already relies on, so only the correlated registry column lookups are
   substituted with the value a database would supply. Every CASE arm, the
   precedence, and the ELSE <stored colour> fallback are the shipped bytes.

The previous implementation of colors.py is embedded verbatim below as
_PREVIOUS_COLORS_SOURCE so the "behaves identically" claims are checked against
the real old code rather than against a paraphrase of it.
"""
from api.registry.colors import (
    _effective_flag_color_sql,
    ladder_columns_available,
    reset_ladder_column_cache,
    status_to_color,
)
import os
import re
import sqlite3
import sys
import unittest
from unittest.mock import MagicMock

sys.path.insert(0, os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..")))


# ── The previous colors.py, verbatim from git HEAD ────────────────────────────
# Used only as an oracle for "did this change anything it should not have?".
_PREVIOUS_COLORS_SOURCE = '''
"""Shared SQL builders for the derived (registry-authoritative) flag colour.

These two functions used to live in api/analytics/routes.py. They were moved
here verbatim so that api/registry/service.py can reuse the exact expression
the Map already uses, without importing the analytics blueprint (which pulls in
google-genai and scikit-learn at import time).

Nothing in this module may gain imports. It must stay dependency-free so both
readers can import it cheaply and without side effects.

Both builders return a SQL expression STRING. They take the alias of the
geospatial_logs relation to read from and emit no bind parameters.

Precedence implemented by _effective_flag_color_sql:
    verified-Orange inspection > Revoked/Blacklisted > Closed > Pending > stored pin colour
The stored geospatial_logs.flagColor is used only when the pin has no
registry match, which is the only case where the registry cannot speak.
"""


def _verified_orange_sql(alias="g"):
    registry_match = f"""(
        (r_chk.businessID IS NOT NULL AND {alias}.businessID IS NOT NULL
            AND r_chk.businessID = {alias}.businessID)
        OR ({alias}.placeID IS NOT NULL AND r_chk.placeID = {alias}.placeID
            AND ({alias}.businessID IS NULL OR r_chk.businessID = {alias}.businessID))
        OR ({alias}.businessID IS NULL
            AND r_chk.barangayID = {alias}.barangayID
            AND r_chk.businessName = {alias}.detectedName)
    )"""
    return f"""(
        EXISTS (
            SELECT 1 FROM inspection_reports ir
            WHERE ir.targetType = 'geospatial_log'
              AND ir.targetID = {alias}.logID
              AND ir.verificationStatus = 'Verified'
              AND ir.inspectionResult = 'Orange'
        )
        AND (
            NOT EXISTS (
                SELECT 1 FROM official_registry r_chk
                WHERE {registry_match}
            )
            OR EXISTS (
                SELECT 1 FROM official_registry r_chk
                WHERE {registry_match}
                  AND r_chk.applicationStatus = 'Expired'
            )
        )
    )"""


def _effective_flag_color_sql(alias="g"):
    registry_status = f"""(
        SELECT r_chk.applicationStatus
        FROM official_registry r_chk
        WHERE (
            (r_chk.businessID IS NOT NULL AND {alias}.businessID IS NOT NULL
                AND r_chk.businessID = {alias}.businessID)
            OR ({alias}.placeID IS NOT NULL AND r_chk.placeID = {alias}.placeID
                AND ({alias}.businessID IS NULL OR r_chk.businessID = {alias}.businessID))
            OR ({alias}.businessID IS NULL
                AND r_chk.barangayID = {alias}.barangayID
                AND r_chk.businessName = {alias}.detectedName)
        )
        ORDER BY (r_chk.businessID = {alias}.businessID) DESC,
                 (r_chk.placeID = {alias}.placeID) DESC
        LIMIT 1
    )"""
    return f"""CASE
        WHEN { _verified_orange_sql(alias) } THEN 'Orange'
        WHEN {registry_status} = 'Active' THEN 'Green'
        WHEN {registry_status} = 'Expired' THEN 'Red'
        WHEN {registry_status} IN ('Revoked', 'Blacklisted') THEN 'Black'
        WHEN {registry_status} = 'Closed' THEN 'Purple'
        WHEN {registry_status} = 'Pending' THEN 'Yellow'
        ELSE {alias}.flagColor
    END"""
'''


def _previous_effective_flag_color_sql(alias="g"):
    namespace = {}
    exec(compile(_PREVIOUS_COLORS_SOURCE, "previous_colors.py", "exec"),
         namespace)
    return namespace["_effective_flag_color_sql"](alias)


# ── An oracle independent of the module under test ────────────────────────────

#: Deliberately not imported from api.registry.colors.
EXPECTED_STATUS_COLOR = {
    "Active": "Green",
    "Pending": "Yellow",
    "Expired": "Red",
    "Revoked": "Black",
    "Blacklisted": "Black",
    "Closed": "Purple",
}

ALL_STATUSES = ("Active", "Pending", "Expired", "Revoked",
                "Blacklisted", "Closed", "Something New", None)

ALL_WARNING_LEVELS = (0, 1, 2, 3)


def expected_color(status, warning_level=0, black_locked=False):
    """Black > Orange > status, written out independently of the code."""
    if black_locked or status in ("Revoked", "Blacklisted"):
        return "Black"
    if int(warning_level) >= 1:
        return "Orange"
    return EXPECTED_STATUS_COLOR.get(status, "Yellow")


# ── 1. Pure Python ────────────────────────────────────────────────────────────


class StatusToColorTests(unittest.TestCase):

    def test_every_combination_of_status_warning_level_and_lock(self):
        for status in ALL_STATUSES:
            for level in ALL_WARNING_LEVELS:
                for locked in (False, True):
                    with self.subTest(status=status, warning_level=level,
                                      black_locked=locked):
                        self.assertEqual(
                            status_to_color(status, warning_level=level,
                                            black_locked=locked),
                            expected_color(status, level, locked),
                        )

    def test_black_beats_orange_at_level_three(self):
        self.assertEqual(
            status_to_color("Active", warning_level=3, black_locked=True),
            "Black")
        # And a lock with no warning at all.
        self.assertEqual(
            status_to_color("Closed", warning_level=0, black_locked=True),
            "Black")

    def test_orange_beats_non_black_statuses_at_level_one(self):
        for status in ALL_STATUSES:
            with self.subTest(status=status):
                self.assertEqual(status_to_color(status, warning_level=1),
                                 "Black" if status in ("Revoked", "Blacklisted") else "Orange")

    def test_unknown_status_falls_back_to_yellow(self):
        self.assertEqual(status_to_color("Something New"), "Yellow")
        self.assertEqual(status_to_color(None), "Yellow")
        self.assertEqual(status_to_color(""), "Yellow")

    def test_level_zero_and_null_do_not_produce_orange(self):
        for level in (0, None, "", "0", False, "not a number"):
            with self.subTest(warning_level=level):
                self.assertEqual(status_to_color("Active", warning_level=level),
                                 "Green")

    def test_string_levels_from_a_driver_are_accepted(self):
        self.assertEqual(status_to_color(
            "Active", warning_level="2"), "Orange")

    def test_agrees_with_the_existing_registry_python_mapping(self):
        """api/registry/service.py still carries the old status-only table.

        With no warning and no lock the new function must not change a single
        answer, otherwise the registry write paths and the Map would disagree.
        """
        from api.registry import service

        for status, colour in EXPECTED_STATUS_COLOR.items():
            with self.subTest(status=status):
                self.assertEqual(status_to_color(status),
                                 service._status_to_flag_color(status))
        self.assertEqual(status_to_color("Something New"),
                         service._status_to_flag_color("Something New"))


# ── 2. The shipped SQL, executed by SQLite ────────────────────────────────────

_STATUS_LOOKUP = re.compile(
    r"\(\s*SELECT\s+r_chk\.applicationStatus.*?LIMIT\s+1\s*\)", re.DOTALL)
_LOCK_LOOKUP = re.compile(
    r"\(\s*SELECT\s+es\.blackLocked.*?LIMIT\s+1\s*\)", re.DOTALL)
_WARNING_LOOKUP = re.compile(
    r"\(\s*SELECT\s+es\.warningLevel.*?LIMIT\s+1\s*\)", re.DOTALL)


def _connection():
    con = sqlite3.connect(":memory:")
    # The fixture deliberately has NO warningLevel and NO blackLocked column.
    # That is the point: the default expression must not need them.
    con.executescript("""
        CREATE TABLE geospatial_logs (
            logID INTEGER, businessID TEXT, placeID TEXT, barangayID INTEGER,
            detectedName TEXT, flagColor TEXT);
        CREATE TABLE official_registry (
            businessID TEXT, barangayID INTEGER, businessName TEXT,
            applicationStatus TEXT, placeID TEXT);
        CREATE TABLE enforcement_state (
            subjectType TEXT, subjectID TEXT, warningLevel INTEGER,
            blackLocked INTEGER);
        CREATE TABLE inspection_reports (
            targetType TEXT, targetID INTEGER, verificationStatus TEXT,
            inspectionResult TEXT);
    """)
    return con


def _substitute(expression, *, status, warning_level=None, black_locked=None):
    """Replace the correlated registry lookups with literal values.

    This is the same substitution the two existing colour tests perform, plus
    the two new ladder lookups. The CASE arms themselves are untouched.
    """
    status_replacement = "NULL" if status is None else "'%s'" % status
    lock_replacement = "NULL" if black_locked is None else (
        "1" if black_locked else "0")
    warning_replacement = "NULL" if warning_level is None else str(
        int(warning_level))

    expression, status_count = _STATUS_LOOKUP.subn(status_replacement,
                                                   expression)
    expression, lock_count = _LOCK_LOOKUP.subn(lock_replacement, expression)
    expression, warning_count = _WARNING_LOOKUP.subn(warning_replacement,
                                                     expression)

    if status_count != 5:
        raise AssertionError(
            "expected 5 registry-status lookups, found %d; the shared builder "
            "changed shape" % status_count)
    if (lock_count, warning_count) not in ((0, 0), (2, 2)):
        raise AssertionError(
            "ladder lookups should be both absent or both present, got "
            "blackLocked=%d warningLevel=%d" % (lock_count, warning_count))
    return expression


def _run_expression(expression, *, status, warning_level, black_locked,
                    verified_orange, stored_colour):
    """Execute any shipped expression for one fixture row and return the colour.

    This is the SQLite substitution technique from
    tests/test_analytics_flag_colour_filter.py: only the correlated registry
    column lookups are replaced. The CASE arms, their order and the
    ELSE <stored colour> fallback are executed as shipped.
    """
    con = _connection()
    try:
        con.execute(
            "INSERT INTO geospatial_logs VALUES (?,?,?,?,?,?)",
            (1, "BIZ-1", None, 7, "ACME STORE", stored_colour))
        if status is not None:
            con.execute(
                "INSERT INTO official_registry VALUES (?,?,?,?,?)",
                ("BIZ-1", 7, "ACME STORE", status, None))
            con.execute(
                "INSERT INTO enforcement_state VALUES (?,?,?,?)",
                ("business", "BIZ-1", warning_level, black_locked))
        else:
            con.execute(
                "INSERT INTO enforcement_state VALUES (?,?,?,?)",
                ("geospatial_log", "1", warning_level, black_locked))
        if verified_orange:
            con.execute(
                "INSERT INTO inspection_reports VALUES (?,?,?,?)",
                ("geospatial_log", 1, "Verified", "Orange"))
        con.commit()

        expression = _substitute(expression, status=status,
                                 warning_level=warning_level,
                                 black_locked=black_locked)
        row = con.execute(
            f"SELECT ({expression}) FROM geospatial_logs g").fetchone()
        return row[0]
    finally:
        con.close()


def _shipped_color(*, status, warning_level=None, black_locked=None,
                   verified_orange=False, stored_colour="Green", ladder=False):
    """Run the currently shipped expression for one row."""
    return _run_expression(
        _effective_flag_color_sql("g", ladder=ladder),
        status=status, warning_level=warning_level, black_locked=black_locked,
        verified_orange=verified_orange, stored_colour=stored_colour)


class DefaultExpressionTests(unittest.TestCase):
    """ladder=False: what every reader ships today."""

    def test_orange_shows_on_an_active_row_with_a_verified_orange_report(self):
        """The intended Phase 1 change.

        Previously the verified-Orange predicate also required the registry row
        to be Expired, so an Active business with a verified Orange inspection
        rendered Green.
        """
        self.assertEqual(
            _shipped_color(status="Active", verified_orange=True),
            "Orange")
        # ...and without the report it is still Green.
        self.assertEqual(_shipped_color(status="Active"), "Green")

    def test_expired_still_goes_orange_with_a_verified_report(self):
        self.assertEqual(
            _shipped_color(status="Expired", verified_orange=True), "Orange")

    def test_unregistered_pin_with_a_verified_report_is_still_orange(self):
        self.assertEqual(
            _shipped_color(status=None, verified_orange=True), "Orange")

    def test_status_mapping_is_untouched_without_a_verified_orange_report(self):
        for status, colour in EXPECTED_STATUS_COLOR.items():
            with self.subTest(status=status):
                self.assertEqual(_shipped_color(status=status), colour)

    def test_unknown_status_falls_back_to_the_stored_pin_colour(self):
        self.assertEqual(
            _shipped_color(status="Something New", stored_colour="Red"), "Red")
        self.assertEqual(_shipped_color(status=None, stored_colour="Purple"),
                         "Purple")

    def test_default_expression_never_references_the_new_columns(self):
        """This is what makes an unmigrated database safe.

        MySQL raises "Unknown column" when a statement names a column that
        does not exist, so the default builder must not mention them at all.
        """
        expression = _effective_flag_color_sql("g")
        self.assertNotIn("warningLevel", expression)
        self.assertNotIn("blackLocked", expression)
        # And the ladder flag actually does add them.
        self.assertIn("warningLevel",
                      _effective_flag_color_sql("g", ladder=True))
        self.assertIn(
            "blackLocked", _effective_flag_color_sql("g", ladder=True))


class BehaviourIsUnchangedTests(unittest.TestCase):
    """Compare the shipped expression against the previous implementation."""

    def _previous(self, *, status, verified_orange, stored_colour="Green"):
        return _run_expression(
            _previous_effective_flag_color_sql("g"),
            status=status, warning_level=0, black_locked=0,
            verified_orange=verified_orange, stored_colour=stored_colour)

    def _current_default(self, *, status, verified_orange,
                         stored_colour="Green"):
        return _shipped_color(status=status, verified_orange=verified_orange,
                              stored_colour=stored_colour)

    def test_identical_for_every_status_without_a_verified_orange_report(self):
        for status in ALL_STATUSES:
            with self.subTest(status=status):
                self.assertEqual(
                    self._current_default(
                        status=status, verified_orange=False),
                    self._previous(status=status, verified_orange=False))

    def test_identical_for_every_status_at_warning_zero_and_lock_zero(self):
        """The ladder arms must be inert at 0 even when ladder=True."""
        for status in ALL_STATUSES:
            with self.subTest(status=status):
                self.assertEqual(
                    _shipped_color(status=status, warning_level=0,
                                   black_locked=0, ladder=True),
                    self._previous(status=status, verified_orange=False))

    def test_identical_for_expired_and_unregistered_with_a_verified_report(self):
        for status in ("Expired", None):
            with self.subTest(status=status):
                self.assertEqual(
                    self._current_default(status=status,
                                          verified_orange=True),
                    self._previous(status=status, verified_orange=True))

    def test_the_only_divergence_is_a_registered_row_with_a_verified_report(self):
        """Pin down exactly what changed, so nothing else can drift in later.

        The old predicate let a verified Orange report through only when the
        registry row was Expired or absent. So the divergence is precisely:
        a verified report, a registry row that exists, and a status that is
        not Expired.
        """
        for status in ALL_STATUSES:
            for verified in (False, True):
                diverges = verified and status is not None \
                    and status not in ("Expired", "Revoked", "Blacklisted")
                with self.subTest(status=status, verified_orange=verified):
                    now = self._current_default(status=status,
                                                verified_orange=verified)
                    before = self._previous(status=status,
                                            verified_orange=verified)
                    if diverges:
                        self.assertNotEqual(now, before)
                        self.assertEqual(now, "Orange")
                    else:
                        self.assertEqual(now, before)


class LadderExpressionTests(unittest.TestCase):
    """ladder=True: the Phase 2 precedence, Black > Orange > status."""

    def test_black_lock_beats_everything(self):
        for status in ALL_STATUSES:
            for level in ALL_WARNING_LEVELS:
                with self.subTest(status=status, warning_level=level):
                    self.assertEqual(
                        _shipped_color(status=status, warning_level=level,
                                       black_locked=True, ladder=True),
                        "Black")

    def test_black_lock_beats_orange_at_level_three(self):
        self.assertEqual(
            _shipped_color(status="Active", warning_level=3, black_locked=True,
                           ladder=True),
            "Black")

    def test_warning_level_one_or_more_beats_non_black_status(self):
        for status in ALL_STATUSES:
            for level in (1, 2, 3):
                with self.subTest(status=status, warning_level=level):
                    self.assertEqual(
                        _shipped_color(status=status, warning_level=level,
                                       ladder=True),
                        "Black" if status in ("Revoked", "Blacklisted") else "Orange")

    def test_pending_warning_and_clear_ignore_old_verified_orange_history(self):
        self.assertEqual(
            _shipped_color(status="Pending", warning_level=1, ladder=True),
            "Orange")
        self.assertEqual(
            _shipped_color(status="Pending", warning_level=0, ladder=True,
                           verified_orange=True, stored_colour="Orange"),
            "Yellow")
        self.assertNotIn("inspection_reports",
                         _effective_flag_color_sql("g", ladder=True))

    def test_revoked_beats_a_warning_in_both_database_versions(self):
        for ladder in (False, True):
            with self.subTest(ladder=ladder):
                self.assertEqual(
                    _shipped_color(status="Revoked", warning_level=1,
                                   verified_orange=True, ladder=ladder),
                    "Black")

    def test_no_warning_means_the_status_still_rules(self):
        for status, colour in EXPECTED_STATUS_COLOR.items():
            with self.subTest(status=status):
                self.assertEqual(
                    _shipped_color(status=status, warning_level=0,
                                   black_locked=0, ladder=True),
                    colour)

    def test_null_new_columns_behave_exactly_like_zero(self):
        for status, colour in EXPECTED_STATUS_COLOR.items():
            with self.subTest(status=status):
                self.assertEqual(
                    _shipped_color(status=status, warning_level=None,
                                   black_locked=None, ladder=True),
                    colour)

    def test_a_pin_with_no_registry_row_is_not_warned_or_locked(self):
        self.assertEqual(
            _shipped_color(status=None, warning_level=None, black_locked=None,
                           stored_colour="Red", ladder=True),
            "Red")

    def test_ladder_agrees_with_the_python_function(self):
        """The SQL and the pure-Python twin must never disagree.

        Only for statuses the SQL actually maps. With no registry row the SQL
        falls through to ELSE g.flagColor and returns the stored pin colour,
        which the Python function has no equivalent of; see the dedicated test
        below.
        """
        for status in EXPECTED_STATUS_COLOR:
            for level in ALL_WARNING_LEVELS:
                for locked in (False, True):
                    with self.subTest(status=status, warning_level=level,
                                      black_locked=locked):
                        self.assertEqual(
                            _shipped_color(status=status, warning_level=level,
                                           black_locked=locked, ladder=True),
                            status_to_color(status, warning_level=level,
                                            black_locked=locked),
                        )

    def test_the_documented_python_sql_divergence_for_unmatched_pins(self):
        """Only the SQL has a stored pin colour to fall back to.

        An unrecognised status is Yellow in Python, but the SQL keeps the
        stored pin colour. Recorded here so it stays a decision, not a bug.
        """
        self.assertEqual(status_to_color(None), "Yellow")
        self.assertEqual(status_to_color("Something New"), "Yellow")
        self.assertEqual(
            _shipped_color(status=None, stored_colour="Red", ladder=True),
            "Red")
        self.assertEqual(
            _shipped_color(status="Something New", stored_colour="Purple",
                           ladder=True),
            "Purple")

    def test_ladder_reads_both_columns_from_the_same_registry_row(self):
        """Every lookup must rank candidate rows identically.

        Each column is fetched by its own correlated subquery, so they only
        describe the same business if they all apply the same ORDER BY and
        LIMIT. The status lookup is emitted once per CASE arm, hence five.
        """
        expression = _effective_flag_color_sql("g", ladder=True)
        self.assertEqual(expression.count("SELECT es.blackLocked"), 2)
        self.assertEqual(expression.count("SELECT es.warningLevel"), 2)
        self.assertEqual(expression.count("SELECT r_chk.applicationStatus"), 5)

        ranking = "(r_chk.businessID = g.businessID) DESC"
        self.assertEqual(expression.count(ranking), 7)
        self.assertEqual(expression.count(ranking) + 2,
                         expression.count("LIMIT 1"))


# ── 3. The column probe ───────────────────────────────────────────────────────


class LadderColumnProbeTests(unittest.TestCase):

    def setUp(self):
        reset_ladder_column_cache()
        self.addCleanup(reset_ladder_column_cache)

    def _cursor(self, found):
        cursor = MagicMock()
        cursor.fetchall.return_value = [(name,) for name in found]
        return cursor

    def test_reports_missing_before_the_migration_has_run(self):
        self.assertFalse(ladder_columns_available(self._cursor([])))

    def test_reports_missing_when_only_one_column_exists(self):
        self.assertFalse(ladder_columns_available(
            self._cursor(["warningLevel"])))
        self.assertFalse(ladder_columns_available(
            self._cursor(["blackLocked"])))

    def test_reports_present_once_both_columns_exist(self):
        self.assertTrue(
            ladder_columns_available(self._cursor(["warningLevel", "blackLocked"])))

    def test_reads_the_row_shape_the_running_app_actually_produces(self):
        """config.py sets MYSQL_CURSORCLASS = "DictCursor".

        Every reader passes mysql.connection.cursor(), so the rows that reach
        this probe in production are mappings, not tuples, and row[0] raises
        KeyError: 0 - which took the whole Analytics page down with a 500 on
        every request. These cursor mocks answer the mapping shape, because the
        tuple shape is the one no production connection ever produces.
        """
        for rows, expected in (
            ([], False),
            ([{"COLUMN_NAME": "warningLevel"}], False),
            ([{"COLUMN_NAME": n} for n in
              ("warningLevel", "blackLocked")], True),
        ):
            with self.subTest(rows=rows):
                reset_ladder_column_cache()
                cursor = MagicMock()
                cursor.fetchall.return_value = rows
                self.assertEqual(ladder_columns_available(cursor), expected)

    def test_the_probe_is_cached(self):
        first = self._cursor([])
        self.assertFalse(ladder_columns_available(first))
        first.execute.assert_called_once()

        # A second call must not re-query, even though the answer could differ.
        second = self._cursor(["warningLevel", "blackLocked"])
        self.assertFalse(ladder_columns_available(second))
        second.execute.assert_not_called()

        reset_ladder_column_cache()
        self.assertTrue(ladder_columns_available(second))
