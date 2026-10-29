"""Load a versioned BPLO PSIC workbook and materialize current registry matches."""

import argparse
import hashlib
import os
from collections import Counter
from pathlib import Path

import MySQLdb
import MySQLdb.cursors
import dotenv

from api.analytics.sector_mapping import (
    decompose_registry_activity,
    display_sector_for_major,
    read_psic_workbook,
    seed_display_sector_rows,
    sync_registry_sector_values,
)


BACKEND_DIR = Path(__file__).resolve().parents[1]
DEFAULT_WORKBOOK = BACKEND_DIR / "data" / "No. Of Business Per Line of Business (1).xlsx"


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


def _registry_values_with_counts(cursor):
    cursor.execute(
        """SELECT BINARY lineOfBusiness AS line_of_business,
                  COUNT(*) AS registry_rows
           FROM official_registry
           GROUP BY BINARY lineOfBusiness"""
    )
    values = []
    for row in cursor.fetchall():
        value = row["line_of_business"]
        if isinstance(value, bytes):
            value = value.decode("utf-8")
        values.append((value, int(row["registry_rows"] or 0)))
    return values


def preview_master(cursor, lines, source_version):
    """Classify registry values from workbook/default data without sector tables or writes."""
    cursor.execute("SELECT COUNT(*) AS total FROM official_registry")
    total_registry_rows = int(cursor.fetchone()["total"] or 0)
    registry_values = _registry_values_with_counts(cursor)
    display_sectors = {}
    for line in lines:
        mapping = display_sector_for_major(line["major_type_clean"])
        if mapping:
            display_sectors[line["normalized_major_type"]] = {
                "display_sector_key": mapping[0],
                "display_sector_label": mapping[1],
            }

    outcome_values = Counter()
    display_sector_rows = Counter()
    combo_values = []
    for raw_value, row_count in registry_values:
        result = decompose_registry_activity(raw_value, lines, display_sectors)
        outcome_values[result["status"]] += 1
        if result["status"] in ("matched", "combo"):
            display_sector_rows[result["primary_sector_label"]] += row_count
        else:
            display_sector_rows["Needs classification"] += row_count
        if result["status"] == "combo":
            spanning_sectors = []
            for matched_line in result["lines"]:
                sector = display_sectors.get(matched_line["normalized_major_type"])
                label = sector["display_sector_label"] if sector else "Needs classification"
                if label not in spanning_sectors:
                    spanning_sectors.append(label)
            combo_values.append({
                "value": raw_value,
                "rows": row_count,
                "primary_sector": result["primary_sector_label"],
                "sectors": spanning_sectors,
            })

    return {
        "version": source_version,
        "master_lines": len(lines),
        "registry_values": len(registry_values),
        "registry_rows": total_registry_rows,
        "outcomes": dict(outcome_values),
        "display_sector_rows": dict(display_sector_rows),
        "combo_values": combo_values,
    }


def load_master(workbook_path, *, dry_run=False, confirmed=False, connection=None):
    if not dry_run and not confirmed:
        raise RuntimeError("Persistent PSIC loading requires the --confirm flag.")
    workbook_path = Path(workbook_path)
    if not workbook_path.is_file():
        raise FileNotFoundError(f"PSIC workbook not found: {workbook_path}")
    version = hashlib.sha256(workbook_path.read_bytes()).hexdigest()[:32]
    lines = read_psic_workbook(workbook_path, version)
    if not lines:
        raise ValueError("The PSIC workbook contains no usable activity lines.")

    owns_connection = connection is None
    if owns_connection:
        dotenv.load_dotenv(BACKEND_DIR / ".env")
        connection = _connection(_database_config())
    cursor = connection.cursor()
    try:
        if dry_run:
            return preview_master(cursor, lines, version)

        cursor.executemany(
            """INSERT IGNORE INTO psic_lines
                   (source_version, source_row_number, major_type_raw, major_type_clean,
                    normalized_major_type, division, `group`, `class`, line_of_business,
                    normalized_line_of_business, source_total)
               VALUES (%(source_version)s, %(source_row_number)s, %(major_type_raw)s,
                       %(major_type_clean)s, %(normalized_major_type)s, %(division)s,
                       %(group)s, %(class)s, %(line_of_business)s,
                       %(normalized_line_of_business)s, %(source_total)s)""",
            lines,
        )
        major_types = {
            (
                row["major_type_raw"], row["major_type_clean"],
                row["normalized_major_type"],
            )
            for row in lines
        }
        seed_display_sector_rows(cursor, version, sorted(major_types))
        cursor.execute(
            """INSERT INTO psic_active_version (singleton_id, source_version)
               VALUES (1, %s)
               ON DUPLICATE KEY UPDATE source_version = VALUES(source_version),
                   activated_at = CURRENT_TIMESTAMP""",
            (version,),
        )
        values = [
            value for value, _ in _registry_values_with_counts(cursor)
            if value is not None and str(value).strip()
        ]
        outcomes = sync_registry_sector_values(cursor, values)
        connection.commit()
        return {
            "version": version,
            "master_lines": len(lines),
            "registry_values": len(values),
            "match_outcomes": dict(outcomes),
        }
    except Exception:
        if not dry_run:
            connection.rollback()
        raise
    finally:
        cursor.close()
        if owns_connection:
            connection.close()


def _print_result(result, dry_run):
    if dry_run:
        print(f"DRY RUN — no database writes performed. PSIC version: {result['version']}")
        print(f"Master lines: {result['master_lines']}")
        print(
            f"Registry rows: {result['registry_rows']}; distinct lineOfBusiness values: "
            f"{result['registry_values']}"
        )
        print("Distinct-value outcomes:")
        for status in ("matched", "combo", "ambiguous", "unmatched"):
            print(f"  {status}: {result['outcomes'].get(status, 0)}")
        print("Registry rows by primary display sector:")
        for label, count in sorted(result["display_sector_rows"].items()):
            print(f"  {label}: {count}")
        print(f"  TOTAL: {result['registry_rows']}")
        print("Combo values and their display sectors:")
        if not result["combo_values"]:
            print("  (none)")
        for combo in result["combo_values"]:
            sectors = ", ".join(combo["sectors"])
            print(
                f"  {combo['value']} (rows={combo['rows']}; "
                f"primary={combo['primary_sector']}): {sectors}"
            )
        return

    print(
        "Loaded PSIC version {version}: {master_lines} lines; "
        "classified {registry_values} registry values ({match_outcomes}).".format(**result)
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workbook", default=str(DEFAULT_WORKBOOK))
    operation = parser.add_mutually_exclusive_group(required=True)
    operation.add_argument(
        "--dry-run",
        action="store_true",
        help="Read the workbook and registry, print classification outcomes, and write nothing.",
    )
    operation.add_argument(
        "--confirm",
        action="store_true",
        help="Confirm that this command may persist the PSIC master and registry mappings.",
    )
    args = parser.parse_args()
    dotenv.load_dotenv(BACKEND_DIR / ".env")
    config = _database_config()
    print(
        f"Target database: host={config['host']} port={config['port']} "
        f"database={config['database']}"
    )
    result = load_master(
        args.workbook,
        dry_run=args.dry_run,
        confirmed=args.confirm,
    )
    _print_result(result, args.dry_run)


if __name__ == "__main__":
    main()
