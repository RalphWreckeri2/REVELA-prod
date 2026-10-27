#!/usr/bin/env python3
"""Read-only export of the barangay-level OPS inputs for the sensitivity notebook.

What this script does
---------------------
1. Opens the configured MySQL database in a READ ONLY, consistent-snapshot
   transaction. It never writes, updates, or migrates anything.
2. Runs the SAME SQL and the SAME scoring function the Analytics page uses:
   ``api.analytics.routes._load_prescriptive_rankings`` ->
   ``api.analytics.scoring.calculate_rankings``.
   The effective-colour expression comes from
   ``api.registry.colors._effective_flag_color_sql`` and the dispatchable
   counts / mean coordinates come from ``routes._barangay_rankings_sql``.
   The stored ``geospatial_logs.flagColor`` column is NOT used as a filter.
3. Adds ``production_ops`` and ``production_rank`` from that same scoring
   function so the notebook can verify parity before running the grid.
4. Writes a barangay-level CSV plus a ``.sql`` audit file and a ``.meta.json``
   summary. Nothing is written to the database.

Usage
-----
    cd revela_backend
    .venv/Scripts/python.exe "../analytical performance/export_ops_snapshot.py" \
        --out "../analytical performance/ops_sensitivity_input.csv"

The connection settings come from ``revela_backend/.env`` via ``config.py``.
Run it on the machine that can reach the production database. If you only have
a MySQL dump, restore it into a scratch database, point DB_NAME at that scratch
database, and run this script there.

Weights come from ``revela_backend/api/analytics/wlc_config.json`` on the
machine running this script - the same file the Flask process reads. Run the
export from the checkout that matches the deployment, and confirm the Analytics
page shows the same weights, before trusting the parity columns.

Read-only guarantees
--------------------
* ``SET SESSION TRANSACTION READ ONLY`` and
  ``START TRANSACTION WITH CONSISTENT SNAPSHOT, READ ONLY`` are issued before
  any query. A stray write would fail instead of modifying data.
* Only SELECT statements are executed, all through the production helpers.
* The script ends with ROLLBACK and closes the connection.
* It does not call ``create_app()``, so the permit-expiry scheduler and the
  analytics cache warm-up never start.
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import sys
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1] / "revela_backend"
sys.path.insert(0, str(BACKEND))

# config.py loads revela_backend/.env for DB credentials. Resolve it after
# adding the backend directory to sys.path so static analyzers don't flag the
# dynamically located module as an unresolved import.
from importlib import import_module  # noqa: E402

Config = import_module("config").Config

routes = import_module("api.analytics.routes")
analytics_service = import_module("api.analytics.service")
CONFIG_FILE = analytics_service.CONFIG_FILE
get_wlc_config = analytics_service.get_wlc_config
MODEL_VERSION = import_module("api.analytics.scoring").MODEL_VERSION
registry_colors = import_module("api.registry.colors")
_effective_flag_color_sql = registry_colors._effective_flag_color_sql
ladder_columns_available = registry_colors.ladder_columns_available
reset_ladder_column_cache = registry_colors.reset_ladder_column_cache

BASELINE_WEIGHTS = {"w1_risk": 68, "w2_sector": 7, "w3_distance": 25}

CSV_COLUMNS = [
    # required by the notebook
    "barangay_id",
    "barangay_name",
    "red_count",
    "yellow_count",
    "black_count",
    "avg_lat",
    "avg_lng",
    # sector + BPLO
    "sector_score",
    "sector_score_source",
    "bplo_lat",
    "bplo_lng",
    # cross-checks / dispatch eligibility
    "flagged_count",
    "dispatchable_red_count",
    "dispatchable_yellow_count",
    "dispatchable_business_count",
    "open_inspection_excluded",
    # parity
    "production_ops",
    "production_rank",
    # interpretation context (not used by the notebook)
    "weighted_burden",
    "risk_score",
    "distance_score",
    "proximity_score",
    "distance_km",
]


def _clean(value):
    """Make a DB value CSV-friendly without changing its meaning."""
    if isinstance(value, Decimal):
        return float(value)
    return value


def _connect_read_only():
    import MySQLdb
    from MySQLdb.cursors import DictCursor

    conn = MySQLdb.connect(
        host=Config.MYSQL_HOST,
        port=Config.MYSQL_PORT,
        user=Config.MYSQL_USER,
        passwd=Config.MYSQL_PASSWORD or "",
        db=Config.MYSQL_DB,
        charset="utf8mb4",
        cursorclass=DictCursor,
        connect_timeout=15,
    )
    cur = conn.cursor()
    cur.execute("SET NAMES utf8mb4 COLLATE utf8mb4_unicode_ci")
    cur.execute("SET SESSION TRANSACTION READ ONLY")
    # One consistent view for both production queries.
    cur.execute("START TRANSACTION WITH CONSISTENT SNAPSHOT, READ ONLY")
    try:  # long exports must not be killed by a short server timeout
        cur.execute("SET SESSION MAX_EXECUTION_TIME = 600000")
    except Exception:
        pass
    return conn, cur


def collect_from_cursor(cur, config, ladder):
    """Run the production ranking path on an already-open read-only cursor.

    Kept separate from the MySQL connection so the exact same code can be
    exercised against a restored dump or a test harness.

    This mirrors ``routes._load_prescriptive_rankings`` line for line, except
    that the raw aggregate rows are retained: the ranking dicts returned by
    ``calculate_rankings`` do not carry ``avg_lat``/``avg_lng``, and the
    notebook needs the same coordinates production scored.
    """
    scoring = import_module("api.analytics.scoring")
    calculate_rankings = scoring.calculate_rankings

    effective_flag_color = _effective_flag_color_sql("g", ladder=ladder)
    builder = (
        routes._barangay_rankings_sql_split
        if routes._rankings_split_enabled()
        else routes._barangay_rankings_sql
    )
    sql, params = builder(effective_flag_color, "", [], " AND 1=0", [], "", [])
    registry_sql = routes._prescriptive_registry_sql(ladder)

    cur.execute(sql, params)
    raw_rows = list(cur.fetchall())
    cur.execute(registry_sql)
    registry = {row["barangayID"]: row for row in cur.fetchall()}
    for row in raw_rows:
        row.update(registry.get(row["barangayID"], {}))
    rankings, model = calculate_rankings(raw_rows, config)

    raw_by_id = {row["barangayID"]: row for row in raw_rows}
    sql_bundle = (
        "-- REVELA OPS snapshot export (read only)\n"
        "-- Generated by analytical performance/export_ops_snapshot.py\n"
        "-- Builder: %s\n"
        "SET SESSION TRANSACTION READ ONLY;\n"
        "START TRANSACTION WITH CONSISTENT SNAPSHOT, READ ONLY;\n\n"
        "-- 1. Barangay aggregates (effective colours, actionable pins, "
        "dispatchable counts, mean dispatchable coordinates)\n%s;\n\n"
        "-- 2. Registry coverage per barangay\n%s;\n\n"
        "ROLLBACK;\n"
        % (builder.__name__, sql, registry_sql)
    )
    return rankings, model, raw_by_id, sql_bundle


def _read_db_wlc_config(cur):
    """Read the legacy DB table only to document that it is unused."""
    try:
        cur.execute("SELECT * FROM wlc_config")
        row = cur.fetchone()
        if not row:
            return None
        return {key: _clean(value) for key, value in row.items()}
    except Exception as exc:  # table may not exist in a restored dump
        return {"error": f"{type(exc).__name__}: {exc}"}


def build_rows(rankings, config, raw_by_id):
    """Map production ranking dicts to the notebook's CSV columns."""
    rows = []
    for rank_row in rankings:
        raw = raw_by_id.get(rank_row["barangayID"], {})
        red = int(rank_row.get("red_count") or 0)
        yellow = int(rank_row.get("yellow_count") or 0)
        black = int(rank_row.get("black_count") or 0)
        disp_red = int(rank_row.get("dispatchable_red_count") or 0)
        disp_yellow = int(rank_row.get("dispatchable_yellow_count") or 0)
        # Counts only include actionable pins, so zero dispatchable Red/Yellow
        # with a non-zero Red/Yellow total means every one of those records is
        # held by an open Assigned/Reassigned/In Progress report.
        open_excluded = (red + yellow > 0) and (disp_red + disp_yellow == 0)
        rows.append(
            {
                "barangay_id": rank_row["barangayID"],
                "barangay_name": rank_row["barangayName"],
                "red_count": red,
                "yellow_count": yellow,
                "black_count": black,
                "flagged_count": int(rank_row.get("flagged_count") or 0),
                "sector_score": float(rank_row.get("sector_score") if rank_row.get("sector_score") is not None else 50),
                "sector_score_source": rank_row.get("sector_score_source", ""),
                "avg_lat": _clean(raw.get("avg_lat")),
                "avg_lng": _clean(raw.get("avg_lng")),
                "bplo_lat": float(config["bplo_lat"]),
                "bplo_lng": float(config["bplo_lng"]),
                "dispatchable_red_count": disp_red,
                "dispatchable_yellow_count": disp_yellow,
                "dispatchable_business_count": int(rank_row.get("dispatchable_business_count") or 0),
                "open_inspection_excluded": open_excluded,
                "production_ops": float(rank_row["ops_score"]),
                "production_rank": int(rank_row["rank"]),
                "weighted_burden": int(rank_row.get("weighted_burden") or 0),
                "risk_score": float(rank_row.get("risk_score") or 0),
                "distance_score": float(rank_row.get("distance_score") or 0),
                "proximity_score": float(rank_row.get("proximity_score") or 0),
                "distance_km": _clean(rank_row.get("distance_km")),
            }
        )
    return rows


def _validate(rows):
    """Fail loudly instead of exporting a CSV the notebook cannot trust."""
    problems = []
    if not rows:
        problems.append("The export returned zero barangays.")
    names = [row["barangay_name"] for row in rows]
    ids = [row["barangay_id"] for row in rows]
    if len(set(ids)) != len(ids):
        problems.append("Duplicate barangay_id values in the export.")
    if len(set(names)) != len(names):
        problems.append("Duplicate barangay_name values in the export.")
    for row in rows:
        total = row["red_count"] + row["yellow_count"] + row["black_count"]
        if total != row["flagged_count"]:
            problems.append(
                f"{row['barangay_name']}: flagged_count {row['flagged_count']} "
                f"!= red+yellow+black {total}."
            )
        if row["dispatchable_business_count"] > 0 and (
            row["dispatchable_red_count"] +
                row["dispatchable_yellow_count"] == 0
        ):
            problems.append(
                f"{row['barangay_name']}: dispatchable businesses reported with "
                "zero dispatchable Red/Yellow records."
            )
    ranks = [row["production_rank"] for row in rows]
    if sorted(ranks) != list(range(1, len(rows) + 1)):
        problems.append("production_rank is not a unique 1..N sequence.")
    if problems:
        raise SystemExit(
            "Export aborted; the snapshot failed validation:\n  - "
            + "\n  - ".join(problems)
        )


def _write_csv(path, rows):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_COLUMNS)
        writer.writeheader()
        for row in rows:
            writer.writerow(
                {key: ("" if row[key] is None else row[key])
                 for key in CSV_COLUMNS}
            )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--out",
        default=str(Path(__file__).with_name("ops_sensitivity_input.csv")),
        help="CSV destination (default: next to this script).",
    )
    args = parser.parse_args()
    out_path = Path(args.out).resolve()

    config = get_wlc_config()
    reset_ladder_column_cache()

    conn, cur = _connect_read_only()
    try:
        ladder = ladder_columns_available(cur)
        rankings, model, raw_by_id, sql_bundle = collect_from_cursor(
            cur, config, ladder)
        db_config = _read_db_wlc_config(cur)
    finally:
        try:
            conn.rollback()
        finally:
            conn.close()

    rows = build_rows(rankings, config, raw_by_id)
    _validate(rows)
    _write_csv(out_path, rows)

    sql_path = out_path.with_suffix(".sql")
    sql_path.write_text(sql_bundle, encoding="utf-8")

    totals = {
        "barangays": len(rows),
        "red": sum(row["red_count"] for row in rows),
        "yellow": sum(row["yellow_count"] for row in rows),
        "black": sum(row["black_count"] for row in rows),
        "dispatch_eligible": sum(
            1
            for row in rows
            if row["dispatchable_red_count"] + row["dispatchable_yellow_count"] > 0
            and row["dispatchable_business_count"] > 0
            and not row["open_inspection_excluded"]
        ),
    }

    config_path = Path(CONFIG_FILE)
    meta = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "database": {
            "host": Config.MYSQL_HOST,
            "port": Config.MYSQL_PORT,
            "name": Config.MYSQL_DB,
            "transaction": "READ ONLY, consistent snapshot",
        },
        "production_config": {
            "source": str(config_path),
            "source_mtime": datetime.fromtimestamp(
                config_path.stat().st_mtime, tz=timezone.utc
            ).isoformat()
            if config_path.exists()
            else None,
            "weights_percent": {
                key: config[key] for key in ("w1_risk", "w2_sector", "w3_distance")
            },
            "bplo": {"lat": config["bplo_lat"], "lng": config["bplo_lng"]},
            "configured_sector_scores": len(config.get("sectors") or {}),
        },
        "unused_db_wlc_config_row": db_config,
        "scoring": {
            "model_version": MODEL_VERSION,
            "builder": "split" if routes._rankings_split_enabled() else "shipped",
            "ladder_columns_available": bool(ladder),
            "reference_max_burden": model.get("reference_max_burden"),
            "sector_fallback_count": model.get("sector_fallback_count"),
        },
        "totals": totals,
        "csv": str(out_path),
        "sql": str(sql_path),
    }
    meta_path = out_path.with_suffix(".meta.json")
    meta_path.write_text(json.dumps(
        meta, indent=2, default=str), encoding="utf-8")

    print(
        f"Database: {Config.MYSQL_HOST}:{Config.MYSQL_PORT}/{Config.MYSQL_DB}")
    print(
        "Production weights (wlc_config.json): "
        f"{config['w1_risk']}/{config['w2_sector']}/{config['w3_distance']}"
    )
    if any(
        float(config[key]) != float(value) for key, value in BASELINE_WEIGHTS.items()
    ):
        print(
            "\nWARNING: the running configuration does not match the notebook's "
            "0.68/0.07/0.25 baseline. The export is still faithful to production, "
            "but the notebook parity check will fail and stop the grid. Reconcile "
            "the weights before interpreting sensitivity results."
        )
    if db_config and "error" not in db_config:
        print(
            "Unused DB table wlc_config row: "
            f"{db_config.get('w1_risk')}/{db_config.get('w2_sector')}/"
            f"{db_config.get('w3_distance')} "
            "(not read by the scoring code; shown for reconciliation only)."
        )
    print(
        f"Barangays: {totals['barangays']}, Red: {totals['red']}, "
        f"Yellow: {totals['yellow']}, Black: {totals['black']}, "
        f"dispatch-eligible: {totals['dispatch_eligible']}"
    )
    print(f"CSV:  {out_path}")
    print(f"SQL:  {sql_path}")
    print(f"Meta: {meta_path}")


if __name__ == "__main__":
    main()
