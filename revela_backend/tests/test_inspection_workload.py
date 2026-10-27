from datetime import datetime, timedelta
import sqlite3
import unittest

from api.inspections.workload import build_summary, classify, select_rows, list_page, current_rows, hidden_open_count


AS_OF = datetime(2026, 10, 27, 12)


def row(report_id, status, **values):
    base = dict(reportID=report_id, barangayID=1, verificationStatus=status,
                deadline=None, cycleStart=None, submissionReceivedAt=None,
                resolutionTime=None, irTimestamp=AS_OF)
    return {**base, **values}


def test_summary_list_agreement_and_reassignment_cycle():
    rows = [
        row(1, "Assigned", cycleStart=AS_OF - timedelta(days=16),
            deadline=datetime(2026, 10, 26, 9)),
        row(2, "Reassigned", cycleStart=AS_OF - timedelta(days=2),
            deadline=datetime(2026, 10, 30, 9)),
        row(3, "Assigned"),
        row(4, "Submitted", submissionReceivedAt=AS_OF - timedelta(days=1), resolutionTime=20),
        row(5, "Verified", submissionReceivedAt=AS_OF - timedelta(days=4), resolutionTime=40),
        row(6, "Submitted", submissionReceivedAt=AS_OF - timedelta(days=1), resolutionTime=-1),
        row(7, "Verified", submissionReceivedAt=AS_OF - timedelta(days=31), resolutionTime=90),
        row(8, "In Progress", cycleStart=AS_OF - timedelta(days=1)),
    ]
    summary = build_summary(rows, AS_OF, hidden=2)
    assert summary["open"] == len(select_rows(rows, AS_OF, "open")) == 3
    assert summary["overdue"] == len(select_rows(rows, AS_OF, "overdue")) == 1
    assert summary["oldest_report_id"] == 1
    assert summary["age_groups"] == {"0-3": 1, "4-7": 0, "8-14": 0, "15+": 1}
    assert summary["age_unavailable"] == len(select_rows(rows, AS_OF, "age_unavailable")) == 1
    assert sum(summary["age_groups"].values()) + summary["age_unavailable"] == summary["open"]
    assert summary["missing_deadlines"] == 1
    assert summary["ambiguous_deadlines"] == 2
    assert summary["older_hidden_open_reports"] == 2
    assert summary["resolution_sample_size"] == len(select_rows(rows, AS_OF, "resolution")) == 2
    assert summary["resolution_excluded"] == 1
    assert summary["average_resolution_minutes"] == 30
    assert [r["reportID"] for r in select_rows(rows, AS_OF, "oldest", report_id=1)] == [1]
    assert [r["reportID"] for r in select_rows(rows, AS_OF, "deadline_day", deadline_date=datetime(2026, 10, 26).date())] == [1]
    assert classify(rows[1], AS_OF)["age"] == 2  # latest reassignment, not original dispatch


def test_untrusted_timestamps_do_not_create_an_age_or_resolution():
    rows = [row(1, "Assigned", cycleStart=AS_OF + timedelta(days=1)),
            row(2, "Verified", submissionReceivedAt=None, resolutionTime=10)]
    summary = build_summary(rows, AS_OF)
    assert summary["age_unavailable"] == 1
    assert summary["oldest_report_id"] is None
    assert summary["average_resolution_minutes"] is None
    assert summary["resolution_sample_size"] == 0
    assert summary["missing_submission_received"] == 1


def test_sql_population_pagination_and_duplicate_events():
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    connection.create_function("YEAR", 1, lambda value: int(str(value)[:4]) if value else None)
    connection.create_function("TIMESTAMPDIFF", 3, lambda unit, start, end:
                               int((datetime.fromisoformat(end) - datetime.fromisoformat(start)).total_seconds() // 86400))
    connection.executescript("""
        CREATE TABLE inspection_reports (reportID INTEGER, targetID INTEGER,
          verificationStatus TEXT, deadline TIMESTAMP, irTimestamp TIMESTAMP,
          submissionReceivedAt TIMESTAMP, resolutionTime INTEGER);
        CREATE TABLE geospatial_logs (logID INTEGER, barangayID INTEGER);
        CREATE TABLE inspection_lifecycle_events (eventID INTEGER, reportID INTEGER,
          eventType TEXT, eventTimestamp TIMESTAMP);
        INSERT INTO geospatial_logs VALUES (10,1), (20,1), (30,2);
        INSERT INTO inspection_reports VALUES (1,10,'Assigned',NULL,'2026-10-01 12:00:00',NULL,NULL),
          (2,10,'Reassigned','2026-10-26 08:00:00','2026-10-25 12:00:00',NULL,NULL),
          (3,20,'Submitted',NULL,'2026-10-20 12:00:00','2026-10-27 08:00:00',15),
          (4,30,'Assigned',NULL,'2026-10-26 12:00:00',NULL,NULL);
        INSERT INTO inspection_lifecycle_events VALUES (1,2,'dispatched','2026-10-20 12:00:00'),
          (2,2,'reassigned','2026-10-25 12:00:00'),
          (3,2,'submitted','2026-10-26 12:00:00'),
          (4,2,'reassigned','2026-10-26 16:00:00');
    """)
    class Cursor:
        def __init__(self): self.cursor = connection.cursor()
        def execute(self, sql, params=()):
            values = [value.isoformat(sep=" ") if isinstance(value, datetime) else value for value in params]
            self.cursor.execute(sql.replace("%s", "?").replace("TIMESTAMPDIFF(DAY,", "TIMESTAMPDIFF('DAY',"), values)
        def fetchall(self):
            rows = [dict(row) for row in self.cursor.fetchall()]
            for row in rows:
                for key in ("deadline", "irTimestamp", "submissionReceivedAt", "cycleStart"):
                    if key in row and isinstance(row[key], str): row[key] = datetime.fromisoformat(row[key])
            return rows
        def fetchone(self):
            row = self.cursor.fetchone()
            return dict(row) if row else None
    cursor = Cursor()
    rows = current_rows(cursor)
    assert {r["reportID"] for r in rows} == {2, 3, 4}
    assert hidden_open_count(cursor) == 1
    summary = build_summary(rows, AS_OF, hidden=1)
    assert summary["open"] == 2 and summary["overdue"] == 1
    assert summary["age_groups"]["0-3"] == 1 and summary["age_unavailable"] == 1
    assert summary["resolution_sample_size"] == 1
    total, first = list_page(cursor, AS_OF, "open", page=1, limit=1)
    _, second = list_page(cursor, AS_OF, "open", page=2, limit=1)
    assert total == 2 and set(first + second) == {2, 4}
    overdue_total, overdue_ids = list_page(cursor, AS_OF, "overdue", page=1, limit=20)
    assert overdue_total == summary["overdue"] and overdue_ids == [2]
    assert list_page(cursor, AS_OF, "resolution", 1, 20)[0] == summary["resolution_sample_size"]
    assert list_page(cursor, AS_OF, "age_0-3", 1, 20)[0] == summary["age_groups"]["0-3"]
    assert list_page(cursor, AS_OF, "age_unavailable", 1, 20)[0] == summary["age_unavailable"]
    assert list_page(cursor, AS_OF, "deadline_day", 1, 20, deadline_date=datetime(2026, 10, 26).date())[1] == [2]
    assert list_page(cursor, AS_OF, "oldest", 1, 20)[1] == [2]
    connection.close()


class InspectionWorkloadTests(unittest.TestCase):
    def test_summary_and_reassignment(self):
        test_summary_list_agreement_and_reassignment_cycle()

    def test_missing_timestamps(self):
        test_untrusted_timestamps_do_not_create_an_age_or_resolution()

    def test_sql_selection_and_pagination(self):
        test_sql_population_pagination_and_duplicate_events()
