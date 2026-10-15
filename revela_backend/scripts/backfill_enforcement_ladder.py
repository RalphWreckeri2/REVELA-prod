#!/usr/bin/env python3
"""Backfill geospatial_logs.source, official_registry.warningLevel and blackLocked.

DRY RUN BY DEFAULT. Nothing is written unless you pass --apply, and even then
only after you have read the dry-run output.

    python scripts/backfill_enforcement_ladder.py            # dry run
    python scripts/backfill_enforcement_ladder.py --apply    # writes

Why this is a dry run first, and why it guesses nothing
-------------------------------------------------------
Every value here is inferred from data that does not record the truth:

  * A pin's businessID may have been attached by reconcile months after a scan
    created the pin. Labelling that pin 'registry' because it now carries a
    businessID invents history. The mapping below is the best available
    reading, not a fact.

  * An Orange pin with no verified Orange inspection behind it has no
    defensible warning level. A level of 0 would clear a warning that may
    never have been recorded; a level of 1 would invent one. These are NOT
    guessed. They are printed for you to decide, one line each.

  * A Black pin with no registry row, or a Revoked permit with no Black pin,
    has no row to write to, or nothing to lock. These are printed and left
    alone.

Safe to re-run
--------------
The script only writes values that differ from what is already there, so
running it twice changes nothing the second time. It also refuses to run at
all if the ladder or source columns are missing, rather than half-applying.

Ordering matters
----------------
Run this AFTER migrations/20261015_01 and 20261016_01, and AFTER
20261017_01. Run it BEFORE the Orange fallback is removed from the shared
colour rule (Phase 3B Part 3) - after that, an Orange pin whose warningLevel
is still 0 renders as whatever its permit status says, and the Orange history
that warningLevel was standing in for disappears with it.
"""
import argparse
import os
import sys
from pathlib import Path

import pymysql

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

REQUIRED_COLUMNS = {
    "official_registry": (
        "warningLevel", "blackLocked", "blackDispatchUnlocked",
    ),
    "geospatial_logs": ("source",),
}

MAX_WARNING_LEVEL = 3


def load_env(path: Path) -> dict:
    values = {}
    if not path.exists():
        return values
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


# ── the three plans ──────────────────────────────────────────────────────────

def plan_source(cursor):
    """(label, sql, params) for geospatial_logs.source.

    Order matters: the first matching arm wins, so the most specific reading is
    tried first. An inspector report beats everything, because a report is a
    person saying where they are - a stronger signal than any column.
    """
    return [
        (
            "inspector report",
            """SELECT logID, detectedName, barangayID FROM geospatial_logs
               WHERE reportedByUserID IS NOT NULL AND source <> 'manual'""",
        ),
        (
            "registry + Google (businessID and placeID)",
            """SELECT logID, detectedName, barangayID FROM geospatial_logs
               WHERE reportedByUserID IS NULL
                 AND businessID IS NOT NULL AND placeID IS NOT NULL
                 AND source <> 'registry_detected'""",
        ),
        (
            "registry only (businessID)",
            """SELECT logID, detectedName, barangayID FROM geospatial_logs
               WHERE reportedByUserID IS NULL
                 AND businessID IS NOT NULL AND placeID IS NULL
                 AND source <> 'registry'""",
        ),
        (
            "detection only (placeID)",
            """SELECT logID, detectedName, barangayID FROM geospatial_logs
               WHERE reportedByUserID IS NULL
                 AND businessID IS NULL AND placeID IS NOT NULL
                 AND source <> 'detection'""",
        ),
        (
            "unknown (nothing to go on)",
            """SELECT logID, detectedName, barangayID FROM geospatial_logs
               WHERE reportedByUserID IS NULL
                 AND businessID IS NULL AND placeID IS NULL
                 AND source <> 'unknown'""",
        ),
    ]


SOURCE_VALUE_FOR_LABEL = {
    "inspector report": "manual",
    "registry + Google (businessID and placeID)": "registry_detected",
    "registry only (businessID)": "registry",
    "detection only (placeID)": "detection",
    "unknown (nothing to go on)": "unknown",
}


def plan_warning_level(cursor):
    """Registered rows whose warningLevel does not match their Orange history.

    The level is the count of Verified Orange inspections on the row's pins,
    capped at 3. An Orange pin with no verified history behind it is left
    alone and reported separately: there is no defensible value to write.
    """
    return """SELECT r.businessID, r.businessName, r.warningLevel AS current_level,
                  COALESCE(MAX(v.cnt), 0) AS orange_count
           FROM official_registry r
           JOIN geospatial_logs g
             ON g.businessID = r.businessID
           LEFT JOIN (
               SELECT g2.businessID AS bid, COUNT(*) AS cnt
               FROM geospatial_logs g2
               JOIN inspection_reports ir
                 ON ir.targetType = 'geospatial_log' AND ir.targetID = g2.logID
                AND ir.verificationStatus = 'Verified'
                AND ir.inspectionResult = 'Orange'
               WHERE g2.businessID IS NOT NULL
               GROUP BY g2.businessID
           ) v ON v.bid = r.businessID
           WHERE r.applicationStatus IS NOT NULL
           GROUP BY r.businessID, r.businessName, r.warningLevel
           HAVING current_level <> LEAST(orange_count, %s)
              AND orange_count > 0"""


def plan_unguessable_orange(cursor):
    """Orange pins whose business has no verified Orange inspection.

    Not written to. Printed for review, because the only defensible values are
    'this was never really an Orange' and 'a warning was issued and lost the
    record', and only a human can say which.
    """
    return """SELECT DISTINCT g.logID, g.detectedName, g.barangayID
           FROM geospatial_logs g
           JOIN official_registry r ON r.businessID = g.businessID
           WHERE g.flagColor = 'Orange'
             AND NOT EXISTS (
                 SELECT 1 FROM inspection_reports ir
                 WHERE ir.targetType = 'geospatial_log'
                   AND ir.targetID = g.logID
                   AND ir.verificationStatus = 'Verified'
                   AND ir.inspectionResult = 'Orange'
             )"""


def plan_black_lock(cursor):
    """Rows with a Black pin and a linked registry row, not yet locked."""
    return """SELECT DISTINCT r.businessID, r.businessName
           FROM official_registry r
           JOIN geospatial_logs g ON g.businessID = r.businessID
           WHERE g.flagColor = 'Black' AND r.blackLocked = 0"""


def plan_unlinked_black(cursor):
    """Black pins with no registry row. Nothing to lock; listed only."""
    return """SELECT g.logID, g.detectedName, g.barangayID
           FROM geospatial_logs g
           WHERE g.flagColor = 'Black' AND g.businessID IS NULL"""


def plan_revoked_without_black(cursor):
    """Revoked permits with no Black pin. Listed only; nothing is changed."""
    return """SELECT r.businessID, r.businessName
           FROM official_registry r
           WHERE r.applicationStatus IN ('Revoked', 'Blacklisted')
             AND r.blackLocked = 0
             AND NOT EXISTS (
                 SELECT 1 FROM geospatial_logs g
                 WHERE g.businessID = r.businessID AND g.flagColor = 'Black'
             )"""


# ── preflight ────────────────────────────────────────────────────────────────

def missing_columns(cursor):
    missing = []
    for table, columns in REQUIRED_COLUMNS.items():
        placeholders = ", ".join(["%s"] * len(columns))
        cursor.execute(
            "SELECT COLUMN_NAME FROM information_schema.COLUMNS "
            "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = %s "
            f"  AND COLUMN_NAME IN ({placeholders})",
            (table, *columns),
        )
        found = {row[0] for row in cursor.fetchall() or ()}
        for column in columns:
            if column not in found:
                missing.append(f"{table}.{column}")
    return missing


# ── reporting ────────────────────────────────────────────────────────────────

def _rows(cursor):
    return [dict(row) for row in cursor.fetchall() or ()]


def report(conn, cursor, apply_changes, summary):
    """Print the plan. Writes only when apply_changes is True."""
    out = print

    out("")
    out("=" * 72)
    out("  ENFORCEMENT LADDER BACKFILL" + ("  --  APPLYING" if apply_changes
                                          else "  --  DRY RUN, nothing written"))
    out("=" * 72)

    # ── source ─────────────────────────────────────────────────────────────
    out("")
    out("-- geospatial_logs.source " + "-" * 46)
    out("   Coalesced pins may be mislabelled: a pin created by a scan and")
    out("   linked to the registry later by reconcile will read 'registry'.")
    source_total = 0
    for label, sql in plan_source(cursor):
        cursor.execute(sql)
        rows = _rows(cursor)
        out("")
        out(f"   {label}: {len(rows)} pin(s)")
        if apply_changes:
            value = SOURCE_VALUE_FOR_LABEL[label]
            cursor.executemany(
                "UPDATE geospatial_logs SET source = %s WHERE logID = %s",
                [(value, row["logID"]) for row in rows])
        elif rows:
            for row in rows[:10]:
                out(f"       #{row['logID']:<8} {row['detectedName']}")
            if len(rows) > 10:
                out(f"       ... and {len(rows) - 10} more")
        source_total += len(rows)
    summary["source"] = source_total

    # ── warningLevel ───────────────────────────────────────────────────────
    out("")
    out("-- official_registry.warningLevel " + "-" * 38)
    out(f"   Level = verified Orange inspections on the row's pins, capped at "
        f"{MAX_WARNING_LEVEL}.")
    cursor.execute(plan_warning_level(cursor), (MAX_WARNING_LEVEL,))
    levels = _rows(cursor)
    for row in levels:
        out(f"       {row['businessID']:<16} {row['businessName'][:34]:<34}"
            f" level {row['current_level']} -> {min(row['orange_count'], MAX_WARNING_LEVEL)}")
        if apply_changes:
            cursor.execute(
                "UPDATE official_registry SET warningLevel = %s "
                "WHERE businessID = %s",
                (min(row["orange_count"], MAX_WARNING_LEVEL),
                 row["businessID"]))
    summary["warningLevel"] = len(levels)
    if not levels:
        out("       nothing to change")

    cursor.execute(plan_unguessable_orange(cursor))
    unguessed = _rows(cursor)
    out("")
    out(f"   !! NOT GUESSED -- {len(unguessed)} Orange pin(s) with no verified")
    out("      Orange inspection behind them. Their warningLevel is left at 0.")
    out("      Review these by hand:")
    for row in unguessed[:20]:
        out(f"       #{row['logID']:<8} {row['detectedName']}")
    if len(unguessed) > 20:
        out(f"       ... and {len(unguessed) - 20} more")
    if not unguessed:
        out("       none")
    summary["unguessed_orange"] = len(unguessed)

    # ── blackLocked ────────────────────────────────────────────────────────
    out("")
    out("-- official_registry.blackLocked " + "-" * 39)
    cursor.execute(plan_black_lock(cursor))
    locks = _rows(cursor)
    for row in locks:
        out(f"       {row['businessID']:<16} {row['businessName'][:34]}")
        if apply_changes:
            cursor.execute(
                "UPDATE official_registry SET blackLocked = 1 "
                "WHERE businessID = %s", (row["businessID"],))
    summary["blackLocked"] = len(locks)
    if not locks:
        out("       nothing to lock")

    cursor.execute(plan_unlinked_black(cursor))
    unlinked = _rows(cursor)
    out("")
    out(f"   -- LISTED, NOT CHANGED: {len(unlinked)} Black pin(s) with no "
        "registry row.")
    for row in unlinked[:20]:
        out(f"       #{row['logID']:<8} {row['detectedName']}")
    if len(unlinked) > 20:
        out(f"       ... and {len(unlinked) - 20} more")
    summary["unlinked_black"] = len(unlinked)

    cursor.execute(plan_revoked_without_black(cursor))
    revoked = _rows(cursor)
    out("")
    out(f"   -- LISTED, NOT CHANGED: {len(revoked)} Revoked/Blacklisted permit(s) "
        "with no Black pin.")
    for row in revoked[:20]:
        out(f"       {row['businessID']:<16} {row['businessName'][:34]}")
    if len(revoked) > 20:
        out(f"       ... and {len(revoked) - 20} more")
    summary["revoked_without_black"] = len(revoked)

    # ── summary ────────────────────────────────────────────────────────────
    out("")
    out("=" * 72)
    out("  SUMMARY" + ("  (written)" if apply_changes else "  (nothing written)"))
    out("=" * 72)
    out(f"   source pins relabelled ............ {summary['source']}")
    out(f"   warningLevel rows set ............ {summary['warningLevel']}")
    out(f"   Orange pins NOT guessed (listed) . {summary['unguessed_orange']}")
    out(f"   blackLocked rows set ............. {summary['blackLocked']}")
    out(f"   Black pins with no registry row .. {summary['unlinked_black']}  (listed)")
    out(f"   Revoked permits with no Black pin . {summary['revoked_without_black']}  (listed)")
    out("")
    if not apply_changes:
        out("   This was a DRY RUN. Nothing was written.")
        out("   Re-run with --apply once you have read the output above.")
    else:
        out("   Done. Re-running changes nothing: only differing values are written.")
    out("")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true",
                        help="Actually write. Without this, nothing is written.")
    args = parser.parse_args()

    env = load_env(PROJECT_ROOT / ".env")
    host = env.get("DB_HOST", os.getenv("DB_HOST", "127.0.0.1"))
    port = int(env.get("DB_PORT", os.getenv("DB_PORT", "3306")))
    user = env.get("DB_USER", os.getenv("DB_USER"))
    password = env.get("DB_PASSWORD", os.getenv("DB_PASSWORD"))
    database = env.get("DB_NAME", os.getenv("DB_NAME", "revela_db"))

    if not user or not password:
        raise SystemExit("MySQL credentials are not configured in .env")

    conn = pymysql.connect(
        host=host, port=port, user=user, password=password, database=database,
        autocommit=False, cursorclass=pymysql.cursors.DictCursor,
    )
    try:
        with conn.cursor() as cursor:
            missing = missing_columns(cursor)
            if missing:
                raise SystemExit(
                    "Refusing to run. These columns do not exist:\n  "
                    + "\n  ".join(missing)
                    + "\n\nApply the ladder and source migrations first.")

            summary = {}
            report(conn, cursor, args.apply, summary)

        if args.apply:
            conn.commit()
            print("Committed.")
        else:
            conn.rollback()
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
