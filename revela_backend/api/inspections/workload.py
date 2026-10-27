"""Current Dispatch population and workload predicates (admin-only callers).

Deadline values are Manila wall time by the existing datetime-local/calendar
contract. Older values have no stored timezone evidence; disclose that explicitly.
Lifecycle timestamps and submission receipt timestamps are written in UTC.
"""
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

OPEN = ("Assigned", "Reassigned")
GROUPS = ("0-3", "4-7", "8-14", "15+")
VIEWS = ("all", "open", "overdue", "oldest", "resolution", "age_0-3",
         "age_4-7", "age_8-14", "age_15+", "age_unavailable", "deadline_missing", "deadline_day")


CURRENT_SELECT = """
        SELECT ir.reportID, ir.targetID AS logID, ir.verificationStatus,
               ir.deadline, ir.irTimestamp, ir.submissionReceivedAt,
               ir.resolutionTime, g.barangayID,
               (SELECT e.eventTimestamp FROM inspection_lifecycle_events e
                WHERE e.reportID = ir.reportID
                  AND e.eventType IN ('dispatched', 'reassigned')
                ORDER BY e.eventID DESC LIMIT 1) AS cycleStart
        FROM inspection_reports ir
        JOIN (SELECT targetID, MAX(reportID) AS maxReportID
              FROM inspection_reports GROUP BY targetID) latest
          ON latest.maxReportID = ir.reportID
        JOIN geospatial_logs g ON g.logID = ir.targetID
    """


def current_rows(cursor):
    """One row per latest target, matching Dispatch's latest-per-target selection."""
    cursor.execute(CURRENT_SELECT)
    return cursor.fetchall()


def list_page(cursor, as_of, view, page, limit, barangay_id=None, report_id=None,
              deadline_date=None, status=None):
    """Database-paginated drill-down using the same current report IDs as summary."""
    where = []
    params = []
    def add(sql, *values):
        where.append(sql)
        params.extend(values)

    if barangay_id is not None: add("assignment.barangayID = %s", barangay_id)
    if report_id is not None: add("assignment.reportID = %s", report_id)
    if status: add("assignment.verificationStatus = %s", status)
    open_sql = "assignment.verificationStatus IN ('Assigned', 'Reassigned')"
    start_sql = "assignment.cycleStart IS NOT NULL AND assignment.cycleStart <= %s"
    age_sql = "TIMESTAMPDIFF(DAY, assignment.cycleStart, %s)"
    if view in ("open", "overdue", "oldest", "age_unavailable", "deadline_missing", "deadline_day") or view.startswith("age_"):
        add(open_sql)
    if view == "overdue":
        add("assignment.deadline IS NOT NULL AND YEAR(assignment.deadline) >= 1000 AND assignment.deadline < %s",
            as_of + timedelta(hours=8))
    if view == "oldest": add(start_sql, as_of)
    if view == "age_unavailable": add("(assignment.cycleStart IS NULL OR assignment.cycleStart > %s)", as_of)
    if view == "deadline_missing": add("assignment.deadline IS NULL")
    if view == "deadline_day":
        add("assignment.deadline >= %s AND assignment.deadline < %s",
            datetime.combine(deadline_date, datetime.min.time()),
            datetime.combine(deadline_date + timedelta(days=1), datetime.min.time()))
    if view.startswith("age_") and view != "age_unavailable":
        add(start_sql, as_of)
        group = view[4:]
        bounds = {"0-3": (0, 4), "4-7": (4, 8), "8-14": (8, 15)}
        if group in bounds:
            low, high = bounds[group]
            add(f"{age_sql} >= %s AND {age_sql} < %s", as_of, low, as_of, high)
        else: add(f"{age_sql} >= 15", as_of)
    if view == "resolution":
        add("assignment.verificationStatus IN ('Submitted', 'Verified')")
        add("assignment.submissionReceivedAt >= %s AND assignment.submissionReceivedAt < %s",
            as_of - timedelta(days=30), as_of)
        add("assignment.resolutionTime IS NOT NULL AND assignment.resolutionTime >= 0")
    base = f"SELECT assignment.* FROM ({CURRENT_SELECT}) assignment"
    if where: base += " WHERE " + " AND ".join(f"({part})" for part in where)
    cursor.execute(f"SELECT COUNT(*) AS n FROM ({base}) filtered", params)
    total = cursor.fetchone()["n"]
    order = ("assignment.cycleStart ASC, assignment.reportID ASC" if view == "oldest"
             else "assignment.irTimestamp DESC, assignment.reportID DESC")
    cursor.execute(base + f" ORDER BY {order} LIMIT %s OFFSET %s",
                   params + [limit, (page - 1) * limit])
    return total, [row["reportID"] for row in cursor.fetchall()]


def hidden_open_count(cursor, barangay_id=None):
    sql = """
        SELECT COUNT(*) AS n FROM inspection_reports ir
        JOIN geospatial_logs g ON g.logID = ir.targetID
        WHERE ir.verificationStatus IN ('Assigned', 'Reassigned', 'In Progress')
          AND EXISTS (SELECT 1 FROM inspection_reports newer
                      WHERE newer.targetID = ir.targetID AND newer.reportID > ir.reportID)
    """
    if barangay_id is not None:
        sql += " AND g.barangayID = %s"
    cursor.execute(sql, (barangay_id,) if barangay_id is not None else ())
    return cursor.fetchone()["n"]


def classify(row, as_of):
    """Pure predicate shared by summary and paginated list; no invented starts."""
    start = row.get("cycleStart")
    open_ = row.get("verificationStatus") in OPEN
    age = (as_of - start).total_seconds() // 86400 if open_ and isinstance(start, datetime) and start <= as_of else None
    deadline = row.get("deadline")
    local_now = as_of.replace(tzinfo=timezone.utc).astimezone(ZoneInfo("Asia/Manila")).replace(tzinfo=None)
    overdue = open_ and isinstance(deadline, datetime) and deadline < local_now
    received = row.get("submissionReceivedAt")
    minutes = row.get("resolutionTime")
    resolved = (row.get("verificationStatus") in ("Submitted", "Verified")
                and isinstance(received, datetime) and as_of - timedelta(days=30) <= received < as_of)
    valid_duration = isinstance(minutes, int) and not isinstance(minutes, bool) and minutes >= 0
    group = ("0-3" if age < 4 else "4-7" if age < 8 else "8-14" if age < 15 else "15+") if age is not None else None
    return dict(open=open_, age=age, group=group, overdue=overdue,
                resolution_window=resolved, valid_duration=valid_duration,
                missing_deadline=open_ and deadline is None,
                ambiguous_deadline=open_ and deadline is not None)


def matches(row, classification, view, *, report_id=None, deadline_date=None):
    if report_id is not None and row["reportID"] != report_id:
        return False
    if view == "open": return classification["open"]
    if view == "overdue": return classification["overdue"]
    if view == "oldest": return classification["open"] and classification["age"] is not None
    if view == "resolution": return classification["resolution_window"] and classification["valid_duration"]
    if view == "deadline_missing": return classification["missing_deadline"]
    if view == "deadline_day":
        return classification["open"] and isinstance(row.get("deadline"), datetime) and row["deadline"].date() == deadline_date
    if view == "age_unavailable": return classification["open"] and classification["age"] is None
    if view.startswith("age_"): return classification["open"] and classification["group"] == view[4:]
    return True


def build_summary(rows, as_of, hidden=0):
    tagged = [(row, classify(row, as_of)) for row in rows]
    open_rows = [(row, info) for row, info in tagged if info["open"]]
    eligible = [(row, info) for row, info in tagged if info["resolution_window"]]
    durations = [row["resolutionTime"] for row, info in eligible if info["valid_duration"]]
    oldest = min(((row, info) for row, info in open_rows if info["age"] is not None),
                 key=lambda pair: (pair[0]["cycleStart"], pair[0]["reportID"]), default=None)
    return {
        "as_of": as_of.isoformat() + "Z", "period_from": (as_of - timedelta(days=30)).isoformat() + "Z",
        "period_to": as_of.isoformat() + "Z",
        "open": len(open_rows), "overdue": sum(info["overdue"] for _, info in open_rows),
        "oldest_open_days": oldest[1]["age"] if oldest else None,
        "oldest_report_id": oldest[0]["reportID"] if oldest else None,
        "average_resolution_minutes": round(sum(durations) / len(durations), 1) if durations else None,
        "resolution_sample_size": len(durations), "resolution_excluded": len(eligible) - len(durations),
        "missing_submission_received": sum(row["verificationStatus"] in ("Submitted", "Verified")
                                           and row.get("submissionReceivedAt") is None for row, _ in tagged),
        "age_groups": {group: sum(info["group"] == group for _, info in open_rows) for group in GROUPS},
        "age_unavailable": sum(info["age"] is None for _, info in open_rows),
        "missing_deadlines": sum(info["missing_deadline"] for _, info in open_rows),
        "invalid_deadlines": sum(row.get("deadline") is not None and not isinstance(row.get("deadline"), datetime) for row, _ in open_rows),
        "ambiguous_deadlines": sum(info["ambiguous_deadline"] for _, info in open_rows),
        "older_hidden_open_reports": hidden,
        "legacy_in_progress": sum(row["verificationStatus"] == "In Progress" for row, _ in tagged),
        "deadline_timezone": "Asia/Manila wall time (historical timezone not recorded)",
    }


def select_rows(rows, as_of, view="all", barangay_id=None, report_id=None, deadline_date=None, status=None):
    return [row for row in rows if (barangay_id is None or row["barangayID"] == barangay_id)
            and (not status or row["verificationStatus"] == status)
            and matches(row, classify(row, as_of), view, report_id=report_id, deadline_date=deadline_date)]
