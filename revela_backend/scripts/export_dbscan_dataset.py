"""Export an auditable, privacy-minimized snapshot of the objective DBSCAN input.

The export query runs in an explicitly read-only MySQL transaction. It writes
only one CSV and one metadata JSON into a required directory outside the repo.
"""

import argparse
import csv
from datetime import date, datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile


BACKEND_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_ROOT.parent
CSV_COLUMNS = (
    "record_key",
    "latitude",
    "longitude",
    "effective_color",
    "source",
    "registry_linked",
    "barangayID",
    "detected_date",
)
COORDINATE_QUANTUM = Decimal("0.00001")


def _library_versions():
    from importlib.metadata import PackageNotFoundError, version

    versions = {}
    for package in (
        "mysqlclient",
        "numpy",
        "scikit-learn",
        "shapely",
    ):
        try:
            versions[package] = version(package)
        except PackageNotFoundError:
            versions[package] = None
    versions["python"] = sys.version.split()[0]
    return versions


def _git_metadata():
    def git(*args):
        return subprocess.run(
            ["git", *args],
            cwd=REPO_ROOT,
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
        ).stdout.strip()

    commit = git("rev-parse", "HEAD")
    dirty = bool(git("status", "--porcelain"))
    source_hashes = {}
    for relative_path in (
        "revela_backend/api/analytics/hotspots.py",
        "revela_backend/api/registry/colors.py",
        "revela_backend/api/flags/compliance.py",
        "revela_backend/api/utils/barangay_mapping.py",
    ):
        content = (REPO_ROOT / relative_path).read_bytes()
        source_hashes[relative_path] = hashlib.sha256(content).hexdigest()
    return {
        "code_commit": commit,
        "working_tree_dirty": dirty,
        "source_sha256": source_hashes,
    }


def _coordinate_text(value):
    rounded = Decimal(str(value)).quantize(
        COORDINATE_QUANTUM,
        rounding=ROUND_HALF_UP,
    )
    return f"{rounded:.5f}"


def _duplicate_summary(records, coordinate_getter):
    counts = {}
    for record in records:
        key = coordinate_getter(record)
        counts[key] = counts.get(key, 0) + 1
    duplicate_groups = sum(count > 1 for count in counts.values())
    duplicate_extra_records = sum(count - 1 for count in counts.values() if count > 1)
    return {
        "duplicate_coordinate_groups": duplicate_groups,
        "duplicate_extra_records": duplicate_extra_records,
    }


def _serialize_date(value):
    if isinstance(value, (datetime, date)):
        return value.isoformat(sep=" ") if isinstance(value, datetime) else value.isoformat()
    return str(value) if value is not None else ""


def _output_paths(output_dir, timestamp):
    stamp = timestamp.strftime("%Y%m%dT%H%M%SZ")
    return (
        output_dir / f"dbscan_objective_{stamp}.csv",
        output_dir / f"dbscan_objective_{stamp}.metadata.json",
    )


def export_dataset(args):
    sys.path.insert(0, str(BACKEND_ROOT))

    from dotenv import dotenv_values
    import MySQLdb
    from MySQLdb.cursors import DictCursor
    from shapely.geometry import Point, mapping
    from shapely.ops import unary_union

    from api.analytics.hotspots import (
        HOTSPOT_EARTH_RADIUS_M,
        HOTSPOT_POPULATION_OBJECTIVE,
        build_hotspot_population_sql,
        cluster_hotspot_rows,
        count_hotspot_dispositions,
        load_barangay_polygons,
        read_hotspot_settings,
        resolve_hotspot_parameters,
        hotspot_cluster_memberships,
    )
    from api.flags.compliance import registry_link_sql
    from api.registry.colors import (
        _effective_flag_color_sql,
        ladder_columns_available,
        reset_ladder_column_cache,
    )

    output_dir = Path(args.output_dir).expanduser().resolve()
    try:
        output_dir.relative_to(REPO_ROOT)
    except ValueError:
        pass
    else:
        raise ValueError(f"Output directory must be outside the repository: {output_dir}")
    output_dir.mkdir(parents=True, exist_ok=True)

    env_values = dotenv_values(args.env_file)

    def config_value(*names, default=None):
        for name in names:
            value = os.environ.get(name) or env_values.get(name)
            if value:
                return value
        return default

    host = config_value("DB_HOST", "MYSQLHOST")
    user = config_value("DB_USER", "MYSQLUSER")
    password = config_value("DB_PASSWORD", "MYSQLPASSWORD")
    database = config_value("DB_NAME", "MYSQLDATABASE", default="revela_db")
    port = int(config_value("DB_PORT", "MYSQLPORT", default="3306"))
    if not host or not user or password is None:
        raise ValueError(
            "The selected env file must provide DB_HOST/DB_USER/DB_PASSWORD "
            "(or their MYSQL* equivalents)."
        )

    connection = MySQLdb.connect(
        host=host,
        port=port,
        user=user,
        passwd=password,
        db=database,
        charset="utf8mb4",
        cursorclass=DictCursor,
        connect_timeout=15,
    )
    try:
        reset_ladder_column_cache()
        with connection.cursor() as cursor:
            cursor.execute("START TRANSACTION WITH CONSISTENT SNAPSHOT, READ ONLY")
            settings = read_hotspot_settings(cursor)
            parameters, fallbacks = resolve_hotspot_parameters(settings)
            ladder = ladder_columns_available(cursor)
            effective_flag_sql = _effective_flag_color_sql("g", ladder=ladder)
            linked_sql = registry_link_sql("g")
            population_sql, population_params = build_hotspot_population_sql(
                effective_flag_sql,
                linked_sql,
                None,
                None,
                population=HOTSPOT_POPULATION_OBJECTIVE,
                flags=parameters["flags"],
                include_sensitive_fields=False,
                include_legacy_evidence=True,
            )
            cursor.execute(population_sql, population_params)
            population_rows = list(cursor.fetchall() or [])

            cursor.execute(
                "SELECT barangayID, barangayName FROM barangays ORDER BY barangayID"
            )
            barangay_rows = list(cursor.fetchall() or [])
            polygons = load_barangay_polygons(barangay_rows)

            eligible_rows = sorted(
                (
                    row for row in population_rows
                    if row.get("disposition") == "eligible"
                ),
                key=lambda row: int(row["logID"]),
            )
            for row in eligible_rows:
                latitude = float(row["latitude"])
                longitude = float(row["longitude"])
                if not (-90 <= latitude <= 90 and -180 <= longitude <= 180):
                    raise ValueError(
                        f"Invalid coordinate range for eligible logID={row['logID']}."
                    )

            clusters, totals = cluster_hotspot_rows(
                population_rows,
                parameters,
                polygons,
            )
            memberships, _ = hotspot_cluster_memberships(
                population_rows,
                clusters,
            )
            key_by_log_id = {
                int(row["logID"]): f"record_{index:06d}"
                for index, row in enumerate(eligible_rows, start=1)
            }
            canonical_cluster_by_original = {}
            app_membership = {}
            next_cluster_label = 0
            for row in eligible_rows:
                log_id = int(row["logID"])
                original_label = memberships[log_id]
                if original_label == -1:
                    app_membership[key_by_log_id[log_id]] = -1
                    continue
                if original_label not in canonical_cluster_by_original:
                    canonical_cluster_by_original[original_label] = next_cluster_label
                    next_cluster_label += 1
                app_membership[key_by_log_id[log_id]] = (
                    canonical_cluster_by_original[original_label]
                )

            now = datetime.now(timezone.utc)
            csv_path, metadata_path = _output_paths(output_dir, now)
            if csv_path.exists() or metadata_path.exists():
                raise FileExistsError(
                    "Refusing to overwrite an existing DBSCAN export."
                )

            export_records = []
            legacy_evidence_by_key = {}
            for row in eligible_rows:
                record_key = key_by_log_id[int(row["logID"])]
                export_records.append({
                    "record_key": record_key,
                    "latitude": _coordinate_text(row["latitude"]),
                    "longitude": _coordinate_text(row["longitude"]),
                    "effective_color": row["flagColor"],
                    "source": row.get("source") or "unknown",
                    "registry_linked": bool(row.get("registry_linked")),
                    "barangayID": None,
                    "detected_date": _serialize_date(row.get("detectedDate")),
                })
                polygon = next(
                    (
                        item for item in polygons
                        if item["geometry"].contains(
                            Point(
                                float(row["longitude"]),
                                float(row["latitude"]),
                            )
                        )
                    ),
                    None,
                )
                if polygon is not None:
                    export_records[-1]["barangayID"] = polygon["barangay_id"]
                legacy_evidence_by_key[record_key] = bool(
                    row.get("legacy_evidence_eligible")
                )

            with connection.cursor() as cursor:
                eligible_ids = [int(row["logID"]) for row in eligible_rows]
                if eligible_ids:
                    placeholders = ", ".join(["%s"] * len(eligible_ids))
                    cursor.execute(
                        "SELECT COUNT(DISTINCT reportID) AS report_count "
                        "FROM inspection_reports "
                        f"WHERE targetID IN ({placeholders})",
                        eligible_ids,
                    )
                    inspection_report_count = int(
                        cursor.fetchone()["report_count"] or 0
                    )
                else:
                    inspection_report_count = 0

            population_counts = count_hotspot_dispositions(
                population_rows,
                population=HOTSPOT_POPULATION_OBJECTIVE,
                flags=parameters["flags"],
            )
            exported_by_color = {}
            exported_by_source = {}
            for record in export_records:
                color = record["effective_color"]
                source = record["source"]
                exported_by_color[color] = exported_by_color.get(color, 0) + 1
                exported_by_source[source] = exported_by_source.get(source, 0) + 1

            exact_duplicates = _duplicate_summary(
                eligible_rows,
                lambda row: (str(row["latitude"]), str(row["longitude"])),
            )
            rounded_duplicates = _duplicate_summary(
                export_records,
                lambda row: (row["latitude"], row["longitude"]),
            )
            boundary = unary_union([item["geometry"] for item in polygons])
            metadata = {
                "extraction_timestamp_utc": now.isoformat(),
                **_git_metadata(),
                "population_rules": {
                    "name": HOTSPOT_POPULATION_OBJECTIVE,
                    "effective_flags": parameters["flags"],
                    "effective_flag_source": (
                        "hotspots.flags setting"
                        if parameters["sources"]["flags"] == "setting"
                        else "repository default"
                    ),
                    "source_rule": "Any source is included.",
                    "coordinate_rule": (
                        "Both coordinates are required; rows with either "
                        "coordinate missing are excluded."
                    ),
                    "registry_rule": (
                        "Registry-linked records and records with business IDs "
                        "are allowed."
                    ),
                    "evidence_gate": "None.",
                    "ordering": "Eligible input rows are ordered by logID before clustering.",
                    "coordinate_export": (
                        "Latitude and longitude are rounded to five decimal places."
                    ),
                    "barangay_assignment": (
                        "Assigned by strict polygon containment; null means "
                        "outside all mapped barangay polygons or on a boundary."
                    ),
                },
                "parameters_used": parameters,
                "parameter_fallbacks": fallbacks,
                "population_counts": population_counts,
                "exported_row_count": len(export_records),
                "exported_rows_by_color": dict(sorted(exported_by_color.items())),
                "exported_rows_by_source": dict(sorted(exported_by_source.items())),
                "exclusions_by_reason": population_counts["excluded_by_reason"],
                "coordinate_duplicates": {
                    "database_precision": exact_duplicates,
                    "rounded_csv_coordinates": rounded_duplicates,
                },
                "application_reference": {
                    "algorithm": "scikit-learn DBSCAN",
                    "neighbor_search": "ball_tree",
                    "metric": parameters["metric"],
                    "earth_radius_m": HOTSPOT_EARTH_RADIUS_M,
                    "application_totals": totals,
                    "cluster_count": len(clusters),
                    "membership_by_record_key": app_membership,
                    "legacy_evidence_eligible_by_record_key": legacy_evidence_by_key,
                },
                "snapshot_context": {
                    "effective_black_rows_exported": exported_by_color.get("Black", 0),
                    "inspection_reports_targeting_exported_records": (
                        inspection_report_count
                    ),
                    "ground_truth_labels_available": False,
                },
                "municipal_boundary_geojson": mapping(boundary),
                "library_versions": _library_versions(),
            }

            with tempfile.TemporaryDirectory(
                prefix=".dbscan-export-",
                dir=output_dir,
            ) as temporary:
                temporary_dir = Path(temporary)
                temporary_csv = temporary_dir / csv_path.name
                temporary_metadata = temporary_dir / metadata_path.name
                with temporary_csv.open(
                    "w",
                    encoding="utf-8",
                    newline="",
                ) as output_file:
                    writer = csv.DictWriter(output_file, fieldnames=CSV_COLUMNS)
                    writer.writeheader()
                    writer.writerows(export_records)
                csv_sha256 = hashlib.sha256(temporary_csv.read_bytes()).hexdigest()
                metadata["csv_sha256"] = csv_sha256
                temporary_metadata.write_text(
                    json.dumps(metadata, indent=2, ensure_ascii=False) + "\n",
                    encoding="utf-8",
                )
                os.replace(temporary_csv, csv_path)
                os.replace(temporary_metadata, metadata_path)
    finally:
        connection.rollback()
        connection.close()

    return csv_path, metadata_path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--env-file",
        required=True,
        help="Explicit env file with read-only database credentials.",
    )
    parser.add_argument(
        "--output-dir",
        required=True,
        help="Existing or new export directory outside the repository.",
    )
    args = parser.parse_args()
    csv_path, metadata_path = export_dataset(args)
    print(f"CSV: {csv_path}")
    print(f"Metadata: {metadata_path}")


if __name__ == "__main__":
    main()
