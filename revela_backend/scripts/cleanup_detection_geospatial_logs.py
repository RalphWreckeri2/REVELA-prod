"""Reconcile detection pins against the official MPDO barangay boundaries."""

import argparse
from collections import Counter
from datetime import date
import json
import os
from pathlib import Path
import re

import dotenv
import MySQLdb
import MySQLdb.cursors
from geopy.distance import geodesic
from shapely.geometry import Point, shape
from shapely.ops import nearest_points, unary_union

from api.utils.barangay_mapping import map_adm4_barangay_ids


BACKEND_DIR = Path(__file__).resolve().parents[1]
BOUNDARY_PATH = BACKEND_DIR / "api" / "utils" / "mataasnakahoy_mpdo_compatible.json"
AUDIT_TABLE = "geospatial_logs_cleanup_audit"
DETECTION_SOURCE = "detection"


def _database_config():
    host = os.getenv("DB_HOST") or os.getenv("MYSQLHOST") or "127.0.0.1"
    port = int(os.getenv("DB_PORT") or os.getenv("MYSQLPORT") or 3306)
    user = os.getenv("DB_USER") or os.getenv("MYSQLUSER") or "revela_user"
    password = os.getenv("DB_PASSWORD") or os.getenv("MYSQLPASSWORD")
    database = os.getenv("DB_NAME") or os.getenv("MYSQLDATABASE")
    if not database:
        raise RuntimeError(
            "Set DB_NAME or MYSQLDATABASE to the intended target database "
            "(Railway uses 'railway')."
        )
    if not password:
        raise RuntimeError("Set DB_PASSWORD before connecting to the target database.")
    return {
        "host": host,
        "port": port,
        "user": user,
        "password": password,
        "database": database,
    }


def _connection(config):
    return MySQLdb.connect(
        host=config["host"],
        port=config["port"],
        user=config["user"],
        passwd=config["password"],
        db=config["database"],
        charset="utf8mb4",
        cursorclass=MySQLdb.cursors.DictCursor,
    )


def load_boundaries(path=BOUNDARY_PATH):
    with Path(path).open("r", encoding="utf-8") as boundary_file:
        geojson = json.load(boundary_file)
    features = geojson.get("features") or []
    boundaries = []
    for feature in features:
        properties = feature.get("properties") or {}
        name = properties.get("ADM4_EN")
        geometry = feature.get("geometry")
        if not name or not geometry:
            raise ValueError("Every boundary feature must have ADM4_EN and geometry.")
        polygon = shape(geometry)
        if polygon.is_empty or not polygon.is_valid:
            raise ValueError(f"Invalid MPDO boundary geometry for {name!r}.")
        boundaries.append((name, polygon))
    if not boundaries:
        raise ValueError("The MPDO boundary GeoJSON contains no features.")
    return boundaries


def map_barangay_ids(boundaries, barangay_rows):
    """Map ADM4_EN names through the shared explicit ID mapping."""
    return map_adm4_barangay_ids(
        (name for name, _ in boundaries),
        barangay_rows,
    )


def read_totals(cursor):
    cursor.execute(
        """SELECT COUNT(*) AS pins,
                  COALESCE(SUM(source = 'detection' AND businessID IS NULL), 0)
                      AS detected_not_in_registry,
                  COALESCE(SUM(flagColor = 'Red'), 0) AS red
           FROM geospatial_logs"""
    )
    row = cursor.fetchone()
    return {key: int(row[key] or 0) for key in ("pins", "detected_not_in_registry", "red")}


def _nearest_distance_meters(point, boundary_union):
    lat, lng = point.y, point.x
    if not (-90 <= lat <= 90 and -180 <= lng <= 180):
        return None
    nearest = nearest_points(point, boundary_union)[1]
    return geodesic((lat, lng), (nearest.y, nearest.x)).meters


def build_plan(cursor, boundaries, ids_by_geojson_name):
    boundary_union = unary_union([polygon for _, polygon in boundaries])
    cursor.execute(
        """SELECT g.logID, g.barangayID, g.businessID, g.reportID,
                  g.latitude, g.longitude, g.flagColor,
                  EXISTS (
                      SELECT 1 FROM inspection_reports ir WHERE ir.targetID = g.logID
                  ) AS has_inspection
           FROM geospatial_logs g
           WHERE g.source = %s AND g.latitude IS NOT NULL AND g.longitude IS NOT NULL
           ORDER BY g.logID""",
        (DETECTION_SOURCE,),
    )

    updates = []
    outside = []
    ambiguous = []
    pair_counts = Counter()
    for row in cursor.fetchall():
        point = Point(float(row["longitude"]), float(row["latitude"]))
        matches = [
            name for name, polygon in boundaries
            if polygon.contains(point)
        ]
        if len(matches) == 1:
            new_barangay_id = ids_by_geojson_name[matches[0]]
            pair_counts[(int(row["barangayID"]), new_barangay_id)] += 1
            if int(row["barangayID"]) != new_barangay_id:
                updates.append({
                    **row,
                    "new_barangay_id": new_barangay_id,
                    "rule": "reassigned_to_strict_mpdo_polygon",
                })
            continue
        if len(matches) > 1:
            ambiguous.append({
                **row,
                "matching_barangays": matches,
            })
            continue

        blockers = []
        if row["businessID"] is not None:
            blockers.append("businessID is not NULL")
        if row["reportID"] is not None:
            blockers.append("reportID is not NULL")
        if row["has_inspection"]:
            blockers.append("an inspection_reports row references targetID")
        outside.append({
            **row,
            "distance_m": _nearest_distance_meters(point, boundary_union),
            "eligible_for_deletion": not blockers,
            "blockers": blockers,
            "rule": "deleted_outside_mpdo_polygon_unlinked_uninspected",
        })

    cursor.execute(
        """SELECT COUNT(*) AS count FROM geospatial_logs
           WHERE source = %s AND (latitude IS NULL OR longitude IS NULL)""",
        (DETECTION_SOURCE,),
    )
    missing_coordinates = int(cursor.fetchone()["count"] or 0)
    deletions = [row for row in outside if row["eligible_for_deletion"]]
    return {
        "updates": updates,
        "outside": outside,
        "deletions": deletions,
        "ambiguous": ambiguous,
        "pair_counts": pair_counts,
        "missing_coordinates": missing_coordinates,
    }


def projected_totals(before, plan):
    deleted = len(plan["deletions"])
    deleted_red = sum(row["flagColor"] == "Red" for row in plan["deletions"])
    deleted_detected_unlinked = sum(
        row["businessID"] is None for row in plan["deletions"]
    )
    return {
        "pins": before["pins"] - deleted,
        "detected_not_in_registry": (
            before["detected_not_in_registry"] - deleted_detected_unlinked
        ),
        "red": before["red"] - deleted_red,
    }


def _table_exists(cursor, table_name):
    cursor.execute(
        """SELECT COUNT(*) AS count
           FROM information_schema.tables
           WHERE table_schema = DATABASE() AND table_name = %s""",
        (table_name,),
    )
    return int(cursor.fetchone()["count"]) > 0


def _ensure_audit_table(cursor):
    cursor.execute(
        f"""CREATE TABLE IF NOT EXISTS `{AUDIT_TABLE}` (
                auditID BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
                logID INT NOT NULL,
                oldBarangayID INT NOT NULL,
                newBarangayID VARCHAR(32) NOT NULL,
                rule VARCHAR(80) NOT NULL,
                changedAt DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                KEY idx_cleanup_audit_log (logID)
            ) ENGINE=InnoDB"""
    )
    cursor.execute(f"SHOW COLUMNS FROM `{AUDIT_TABLE}`")
    actual = {row["Field"] for row in cursor.fetchall()}
    required = {
        "auditID", "logID", "oldBarangayID", "newBarangayID", "rule", "changedAt",
    }
    if not required.issubset(actual):
        raise RuntimeError(
            f"Existing {AUDIT_TABLE} table has an incompatible schema."
        )


def _affected_rows(plan):
    return plan["updates"] + plan["deletions"]


def apply_plan(connection, plan, backup_table):
    rows = _affected_rows(plan)
    if not rows:
        return None
    if not re.fullmatch(r"geospatial_logs_backup_\d{8}", backup_table):
        raise ValueError("Backup table name must use geospatial_logs_backup_YYYYMMDD.")

    cursor = connection.cursor()
    try:
        if _table_exists(cursor, backup_table):
            raise RuntimeError(
                f"Backup table {backup_table} already exists; refusing to overwrite it."
            )
        ids = [row["logID"] for row in rows]
        placeholders = ", ".join(["%s"] * len(ids))
        cursor.execute(
            f"""CREATE TABLE `{backup_table}` AS
                SELECT * FROM geospatial_logs
                WHERE source = %s AND logID IN ({placeholders})""",
            (DETECTION_SOURCE, *ids),
        )
        cursor.execute(f"SELECT COUNT(*) AS count FROM `{backup_table}`")
        if int(cursor.fetchone()["count"]) != len(rows):
            raise RuntimeError("Backup row count did not match the planned changes.")

        _ensure_audit_table(cursor)
        connection.begin()
        try:
            for row in plan["updates"]:
                cursor.execute(
                    """UPDATE geospatial_logs
                       SET barangayID = %s
                       WHERE logID = %s AND source = %s AND barangayID = %s
                         AND latitude = %s AND longitude = %s""",
                    (
                        row["new_barangay_id"], row["logID"], DETECTION_SOURCE,
                        row["barangayID"], row["latitude"], row["longitude"],
                    ),
                )
                if cursor.rowcount != 1:
                    raise RuntimeError(
                        f"Detection pin {row['logID']} changed after the plan was built."
                    )
                cursor.execute(
                    f"""INSERT INTO `{AUDIT_TABLE}`
                        (logID, oldBarangayID, newBarangayID, rule)
                        VALUES (%s, %s, %s, %s)""",
                    (
                        row["logID"], row["barangayID"],
                        str(row["new_barangay_id"]), row["rule"],
                    ),
                )

            for row in plan["deletions"]:
                cursor.execute(
                    """DELETE FROM geospatial_logs
                       WHERE logID = %s AND source = %s AND barangayID = %s
                         AND latitude = %s AND longitude = %s
                         AND businessID IS NULL AND reportID IS NULL
                         AND NOT EXISTS (
                             SELECT 1 FROM inspection_reports ir
                             WHERE ir.targetID = geospatial_logs.logID
                         )""",
                    (
                        row["logID"], DETECTION_SOURCE, row["barangayID"],
                        row["latitude"], row["longitude"],
                    ),
                )
                if cursor.rowcount != 1:
                    raise RuntimeError(
                        f"Detection pin {row['logID']} no longer meets deletion safeguards."
                    )
                cursor.execute(
                    f"""INSERT INTO `{AUDIT_TABLE}`
                        (logID, oldBarangayID, newBarangayID, rule)
                        VALUES (%s, %s, 'deleted', %s)""",
                    (row["logID"], row["barangayID"], row["rule"]),
                )
            connection.commit()
        except Exception:
            connection.rollback()
            raise
    finally:
        cursor.close()
    return backup_table


def _print_totals(label, totals):
    print(
        f"{label}: pins={totals['pins']}, "
        f"detected-not-in-registry={totals['detected_not_in_registry']}, "
        f"Red={totals['red']}"
    )


def _print_plan(plan, before, names_by_id):
    print("Old -> new barangay counts (strictly inside exactly one polygon):")
    if not plan["pair_counts"]:
        print("  (none)")
    for (old_id, new_id), count in sorted(plan["pair_counts"].items()):
        old_name = names_by_id.get(old_id, f"barangayID {old_id}")
        new_name = names_by_id.get(new_id, f"barangayID {new_id}")
        print(
            f"  {old_name} ({old_id}) -> {new_name} ({new_id}): {count}"
        )

    print("Outside every strict polygon (distance is nearest-boundary geodesic):")
    if not plan["outside"]:
        print("  (none)")
    for row in plan["outside"]:
        distance = (
            "unavailable"
            if row["distance_m"] is None
            else f"{row['distance_m']:.1f} m"
        )
        status = (
            "DELETE CANDIDATE"
            if row["eligible_for_deletion"]
            else "LEAVE ALONE: " + "; ".join(row["blockers"])
        )
        print(
            f"  logID={row['logID']} lat={row['latitude']} "
            f"lng={row['longitude']} flagColor={row['flagColor']} "
            f"nearest={distance} — {status}"
        )
    if plan["ambiguous"]:
        print("Pins inside multiple polygons (left unchanged):")
        for row in plan["ambiguous"]:
            print(
                f"  logID={row['logID']} lat={row['latitude']} "
                f"lng={row['longitude']} matches={', '.join(row['matching_barangays'])}"
            )
    print(f"Detection pins without both coordinates (left unchanged): {plan['missing_coordinates']}")
    _print_totals("Before", before)
    _print_totals("Projected after", projected_totals(before, plan))
    print(
        f"Planned changes: {len(plan['updates'])} barangay reassignment(s), "
        f"{len(plan['deletions'])} deletion(s)."
    )


def run_cleanup(connection, *, confirmed=False, today=None):
    cursor = connection.cursor()
    try:
        boundaries = load_boundaries()
        cursor.execute("SELECT barangayID, barangayName FROM barangays")
        ids_by_name, names_by_id = map_barangay_ids(boundaries, cursor.fetchall())
        before = read_totals(cursor)
        plan = build_plan(cursor, boundaries, ids_by_name)
        _print_plan(plan, before, names_by_id)
        if not confirmed:
            print("DRY RUN — no database writes performed.")
            return {"before": before, "after": projected_totals(before, plan), "plan": plan}
        if not _affected_rows(plan):
            print("No changes planned; backup and audit tables were not created.")
            _print_totals("After", read_totals(cursor))
            return {"before": before, "after": before, "plan": plan}

        backup_table = f"geospatial_logs_backup_{(today or date.today()).strftime('%Y%m%d')}"
    finally:
        cursor.close()

    backup_table = apply_plan(connection, plan, backup_table)
    after_cursor = connection.cursor()
    try:
        after = read_totals(after_cursor)
    finally:
        after_cursor.close()
    print(f"Backup table: {backup_table}")
    _print_totals("After", after)
    return {"before": before, "after": after, "plan": plan}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--confirm",
        action="store_true",
        help="Create a dated backup and apply the planned changes.",
    )
    args = parser.parse_args()

    dotenv.load_dotenv(BACKEND_DIR / ".env")
    config = _database_config()
    print(
        f"Target database: host={config['host']} port={config['port']} "
        f"database={config['database']}"
    )
    connection = _connection(config)
    try:
        run_cleanup(connection, confirmed=args.confirm)
    finally:
        connection.close()


if __name__ == "__main__":
    main()
