"""
Query-parameter helpers for GET /analytics/all.

Registry filters apply to official_registry-backed aggregates.
Geospatial filters apply to geospatial_logs-backed aggregates.
Inspection filters apply to inspection_reports (joined through geospatial_logs for barangay / detection date).
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple


def _split_ids(raw: Optional[str]) -> List[int]:
    if not raw or not str(raw).strip():
        return []
    out: List[int] = []
    for part in str(raw).split(","):
        part = part.strip()
        if not part:
            continue
        try:
            out.append(int(part))
        except ValueError:
            continue
    return out


def _strip(val: Optional[str]) -> Optional[str]:
    if val is None:
        return None
    s = str(val).strip()
    return s if s else None


def parse_analytics_filters(args) -> Dict[str, Any]:
    """Parse Flask request.args into a plain dict (JSON-serializable for echo)."""
    barangay_ids = _split_ids(args.get("barangay_ids"))
    single = args.get("barangay_id")
    if single not in (None, "", "null"):
        try:
            bid = int(single)
            if bid not in barangay_ids:
                barangay_ids = [bid] + barangay_ids
        except (TypeError, ValueError):
            pass

    return {
        "barangay_ids": barangay_ids or None,
        "application_status": _strip(args.get("application_status")),
        "line_of_business": _strip(args.get("line_of_business")),
        "business_type": _strip(args.get("business_type")),
        "business_size": _strip(args.get("business_size")),
        "renewal_from": _strip(args.get("renewal_from")),
        "renewal_to": _strip(args.get("renewal_to")),
        "flag_color": _strip(args.get("flag_color")),
        "detected_from": _strip(args.get("detected_from")),
        "detected_to": _strip(args.get("detected_to")),
        "inspection_result": _strip(args.get("inspection_result")),
        "verification_status": _strip(args.get("verification_status")),
        "inspection_from": _strip(args.get("inspection_from")),
        "inspection_to": _strip(args.get("inspection_to")),
    }


def registry_sql(alias: str, F: Dict[str, Any]) -> Tuple[str, List[Any]]:
    """Fragment for AND ... after WHERE 1=1 (registry table alias)."""
    parts: List[str] = []
    params: List[Any] = []

    bids = F.get("barangay_ids")
    if bids:
        parts.append(f"{alias}.barangayID IN ({','.join(['%s'] * len(bids))})")
        params.extend(bids)

    if F.get("application_status"):
        parts.append(f"{alias}.applicationStatus = %s")
        params.append(F["application_status"])

    if F.get("line_of_business"):
        parts.append(f"{alias}.lineOfBusiness = %s")
        params.append(F["line_of_business"])

    if F.get("business_type"):
        parts.append(f"{alias}.businessType = %s")
        params.append(F["business_type"])

    if F.get("business_size"):
        parts.append(f"{alias}.businessSize = %s")
        params.append(F["business_size"])

    if F.get("renewal_from"):
        parts.append(f"{alias}.lastRenewalDate >= %s")
        params.append(F["renewal_from"])

    if F.get("renewal_to"):
        parts.append(f"{alias}.lastRenewalDate <= %s")
        params.append(F["renewal_to"])

    if not parts:
        return "", []
    return " AND " + " AND ".join(parts), params


def geo_sql(alias: str, F: Dict[str, Any]) -> Tuple[str, List[Any]]:
    """Fragment for AND ... (geospatial_logs alias)."""
    parts: List[str] = []
    params: List[Any] = []

    bids = F.get("barangay_ids")
    if bids:
        parts.append(f"{alias}.barangayID IN ({','.join(['%s'] * len(bids))})")
        params.extend(bids)

    if F.get("flag_color"):
        parts.append(f"{alias}.flagColor = %s")
        params.append(F["flag_color"])

    if F.get("detected_from"):
        parts.append(f"{alias}.detectedDate >= %s")
        params.append(F["detected_from"])

    if F.get("detected_to"):
        parts.append(f"{alias}.detectedDate <= %s")
        dt = F["detected_to"]
        ds = str(dt)
        if len(ds) == 10 and " " not in ds:
            dt = f"{ds} 23:59:59"
        params.append(dt)

    if not parts:
        return "", []
    return " AND " + " AND ".join(parts), params


def geo_on_extra(alias: str, F: Dict[str, Any]) -> Tuple[str, List[Any]]:
    """Same as geo_sql but starts with AND for appending to JOIN ... ON ..."""
    frag, params = geo_sql(alias, F)
    return frag, params


def barangay_b_sql(F: Dict[str, Any]) -> Tuple[str, List[Any]]:
    """Filter barangays dimension table alias b."""
    bids = F.get("barangay_ids")
    if not bids:
        return "", []
    ph = ",".join(["%s"] * len(bids))
    return f" AND b.barangayID IN ({ph})", list(bids)


def inspection_sql(alias: str, F: Dict[str, Any]) -> Tuple[str, List[Any]]:
    parts: List[str] = []
    params: List[Any] = []

    if F.get("inspection_result"):
        parts.append(f"{alias}.inspectionResult = %s")
        params.append(F["inspection_result"])

    if F.get("verification_status"):
        parts.append(f"{alias}.verificationStatus = %s")
        params.append(F["verification_status"])

    if F.get("inspection_from"):
        parts.append(f"{alias}.irTimestamp >= %s")
        params.append(F["inspection_from"])

    if F.get("inspection_to"):
        parts.append(f"{alias}.irTimestamp <= %s")
        dt = F["inspection_to"]
        ds = str(dt)
        if len(ds) == 10 and " " not in ds:
            dt = f"{ds} 23:59:59"
        params.append(dt)

    if not parts:
        return "", []
    return " AND " + " AND ".join(parts), params


def filters_without(F: Dict[str, Any], *omit: str) -> Dict[str, Any]:
    """Shallow copy with listed keys cleared (for compound SQL where status is fixed elsewhere)."""
    out = dict(F)
    for k in omit:
        out[k] = None
    return out
