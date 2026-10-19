#!/usr/bin/env python3
"""Print the expanded WLC/OPS barangay-ranking SQL for EXPLAIN -- no database.

The analytics pipeline builds this one statement at
    api/analytics/routes.py:984-1001
from cursor-free helpers, so its exact text can be reproduced locally. This
script imports only those helpers (api/analytics/filters.py, which itself imports
only api/registry/colors.py). It opens NO database connection and never runs
EXPLAIN itself -- it only prints the SQL to paste into a non-production client.

Usage
-----
    python scripts/explain_analytics_rankings.py
    python scripts/explain_analytics_rankings.py --ladder true
    python scripts/explain_analytics_rankings.py --ladder both --outdir .
    python scripts/explain_analytics_rankings.py --query "barangay_id=3&flag_color=Red"

--ladder controls whether the enforcement_state ladder arms (ladder=True) or the
legacy verified-Orange fallback (ladder=False) are expanded; print both while
the production migration state is unknown. --query accepts a URL query string in
the same shape GET /analytics/all takes; omit it for the no-filter variant.
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from urllib.parse import parse_qsl

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from api.analytics.filters import (  # noqa: E402
    barangay_b_sql,
    geo_on_extra,
    parse_analytics_filters,
    registry_sql,
)
from api.registry.colors import _effective_flag_color_sql  # noqa: E402

_REF_COMMIT = "29d4891"


def _provenance() -> str:
    refs = (
        "api/analytics/routes.py:984-1001 (statement), :996/:998 (joins), "
        ":988-991 (colour columns); api/registry/colors.py:229-249 "
        "(_effective_flag_color_sql), :116-130 (ladder probe); "
        "api/analytics/filters.py:69-112 (registry_sql), :157-160 (geo_on_extra), "
        ":163-169 (barangay_b_sql)"
    )
    try:
        head = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=os.path.join(os.path.dirname(__file__), "..", ".."),
            capture_output=True, text=True, check=True,
        ).stdout.strip()
    except Exception:
        head = _REF_COMMIT
    note = "" if head == _REF_COMMIT else f" (NOTE: HEAD={head}, ref={_REF_COMMIT})"
    return f"ref {_REF_COMMIT}{note}; {refs}"


def build(F, ladder):
    """Reproduce the runtime statement + bound params for one ladder setting."""
    effective_flag_color = _effective_flag_color_sql("g", ladder=ladder)
    geo_on_g, geo_on_g_p = geo_on_extra("g", F, ladder=ladder)
    reg_o, reg_o_p = registry_sql("o", F)
    brgy_b, brgy_b_p = barangay_b_sql(F)
    sql = f"""
        SELECT
            b.barangayID,
            b.barangayName,
            COUNT(DISTINCT CASE WHEN {effective_flag_color} IN ('Red', 'Yellow', 'Black') THEN g.logID END) AS flagged_count,
            COUNT(DISTINCT CASE WHEN {effective_flag_color} = 'Red'    THEN g.logID END) AS red_count,
            COUNT(DISTINCT CASE WHEN {effective_flag_color} = 'Yellow' THEN g.logID END) AS yellow_count,
            COUNT(DISTINCT CASE WHEN {effective_flag_color} = 'Black'  THEN g.logID END) AS black_count,
            AVG(g.latitude)                                          AS avg_lat,
            AVG(g.longitude)                                         AS avg_lng,
            COUNT(DISTINCT o.businessID)                             AS total_registered
        FROM barangays b
        LEFT JOIN geospatial_logs   g ON g.barangayID = b.barangayID 
            AND (g.placeID IS NOT NULL OR g.reportedByUserID IS NOT NULL OR g.flagColor = 'Orange' OR EXISTS (SELECT 1 FROM inspection_reports ir WHERE ir.targetID = g.logID)){geo_on_g}
        LEFT JOIN official_registry o ON o.barangayID = b.barangayID{reg_o}
        WHERE 1=1 {brgy_b}
        GROUP BY b.barangayID, b.barangayName
    """
    return sql, geo_on_g_p + reg_o_p + brgy_b_p


def _literal(value):
    if isinstance(value, bool):
        return "1" if value else "0"
    if isinstance(value, (int, float)):
        return str(value)
    return "'" + str(value).replace("\\", "\\\\").replace("'", "\\'") + "'"


def _substitute(sql, params):
    """Replace the DB-API %s placeholders with literals, positionally."""
    out, it, i = [], iter(params), 0
    while i < len(sql):
        if sql[i] == "%" and sql[i + 1:i + 2] == "s":
            try:
                value = next(it)
            except StopIteration:
                out.append(sql[i:])
                break
            out.append(_literal(value))
            i += 2
        else:
            out.append(sql[i])
            i += 1
    return "".join(out)


def _ladder_arg(value):
    if value == "true":
        return [True]
    if value == "false":
        return [False]
    return [True, False]


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ladder", choices=["true", "false", "both"], default="both")
    parser.add_argument("--query", default="", help="URL query string, e.g. 'flag_color=Red'")
    parser.add_argument(
        "--registration-type-supported", dest="reg_supported",
        choices=["true", "false"], default="true",
        help="Official schema has official_registry.registrationType (dump:266). Default true.",
    )
    parser.add_argument("--outdir", default="", help="Write one .sql file per ladder setting here.")
    args = parser.parse_args(argv)

    F = parse_analytics_filters(dict(parse_qsl(args.query, keep_blank_values=False)))
    F["registration_type_supported"] = (args.reg_supported == "true")
    label = args.query or "none"

    blocks = []
    for ladder in _ladder_arg(args.ladder):
        sql, params = build(F, ladder)
        runnable = _substitute(sql, params)
        header = (
            "-- " + "=" * 70 + "\n"
            "-- REVELA analytics: WLC/OPS barangay-ranking aggregate (TIER 3)\n"
            f"-- provenance: {_provenance()}\n"
            f"-- ladder={ladder}  filters={label}  "
            f"registrationType_supported={F['registration_type_supported']}\n"
            f"-- bound params (positional): {params}\n"
            "-- Paste into a NON-PRODUCTION client only. Use EXPLAIN, never EXPLAIN ANALYZE.\n"
            "-- " + "=" * 70 + "\n"
        )
        block = header + "EXPLAIN FORMAT=JSON\n" + runnable.strip("\n") + "\n;\n"
        blocks.append((ladder, block))

    if args.outdir:
        os.makedirs(args.outdir, exist_ok=True)
        for ladder, block in blocks:
            name = f"explain_rankings_ladder_{str(ladder).lower()}.sql"
            with open(os.path.join(args.outdir, name), "w", encoding="utf-8", newline="\n") as fh:
                fh.write(block)
            print(f"wrote {os.path.join(args.outdir, name)}", file=sys.stderr)
    else:
        for _, block in blocks:
            print(block)


if __name__ == "__main__":
    main()
