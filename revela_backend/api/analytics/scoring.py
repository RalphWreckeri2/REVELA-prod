"""One explainable WLC model for Analytics, Overview, exports and Map dispatch.

Inputs always cover the municipality's current eligible records. Dashboard
filters are applied AFTER scoring, so neither scores nor municipal ranks change
when a user hides another barangay. Scores express relative inspection priority,
not violation probability or a historically calibrated risk estimate.
"""
import math

from api.analytics.service import validate_wlc_config
from api.analytics.sector_risk import load_sector_risk_policy, weighted_sector_score


MODEL_VERSION = "wlc-v3"
FLAG_WEIGHTS = {"Red": 3, "Yellow": 2, "Black": 4}
NEUTRAL_SECTOR_SCORE = 50


def weighted_burden(row):
    return sum(int(row.get(f"{color.lower()}_count") or 0) * weight
               for color, weight in FLAG_WEIGHTS.items())


def priority_band(score):
    """Shared policy bands, not a statistical classification of violations."""
    if score >= 60:
        return "High", "HIGH PRIORITY", "#6366f1"
    if score >= 30:
        return "Medium", "STANDARD", "#0ea5e9"
    return "Low", "MONITOR", "#10b981"


def haversine_km(lat1, lng1, lat2, lng2):
    dlat, dlng = math.radians(lat2 - lat1), math.radians(lng2 - lng1)
    a = (math.sin(dlat / 2) ** 2 + math.cos(math.radians(lat1))
         * math.cos(math.radians(lat2)) * math.sin(dlng / 2) ** 2)
    return 2 * 6371.0088 * math.asin(math.sqrt(max(0, min(1, a))))


def _model_weights(config):
    enabled = config["w2_sector"] > 0
    # Weights are the interview-derived/admin-saved policy, not data-dependent.
    # Incomplete or constant sector scores must NEVER reweight the WLC model.
    weights = {"w1": config["w1_risk"] / 100,
               "w2": config["w2_sector"] / 100,
               "w3": config["w3_distance"] / 100}
    if not enabled:
        reason = "Sector weight is zero by explicit configuration; other weights are unchanged."
    else:
        reason = (
            "Sector scores use active-flag entities' distinct business/place/log identity "
            "and their matched PSIC display category. Unmatched, unregistered, or "
            "unclassified entities use neutral 50; explicit barangay overrides take "
            "precedence. Configured weights are preserved; no weight is redistributed."
        )
    return weights, enabled, reason


def calculate_rankings(rows, config):
    """Score the FULL municipal cohort, then assign deterministic global ranks."""
    validate_wlc_config(config)
    rows = list(rows)
    weights, sector_enabled, reason = _model_weights(config)
    sector_policy = load_sector_risk_policy()
    maximum = max((weighted_burden(row) for row in rows), default=0)
    rankings = []
    for row in rows:
        counts = {f"{color.lower()}_count": int(row.get(f"{color.lower()}_count") or 0)
                  for color in FLAG_WEIGHTS}
        flagged = sum(counts.values())
        dispatch_red = int(row.get("dispatchable_red_count", counts["red_count"]) or 0)
        dispatch_yellow = int(row.get("dispatchable_yellow_count", counts["yellow_count"]) or 0)
        dispatchable = dispatch_red + dispatch_yellow
        dispatchable_businesses = int(row.get("dispatchable_business_count", dispatchable) or 0)
        burden = weighted_burden(row)
        risk = round(100 * burden / maximum, 1) if maximum else 0.0
        category_counts = row.get("sector_category_counts", {})
        sector, sector_entity_count, sector_known_count, sector_fallback_count = (
            weighted_sector_score(category_counts, sector_policy)
        )
        has_sector_override = row["barangayName"] in config.get("sectors", {})
        if has_sector_override:
            sector = float(config["sectors"][row["barangayName"]])
        sector_source = (
            "configured" if has_sector_override
            else "psic_weighted" if sector_known_count
            else "neutral_fallback"
        )
        lat, lng = row.get("avg_lat"), row.get("avg_lng")
        try:
            lat, lng = float(lat), float(lng)
            located = (math.isfinite(lat) and math.isfinite(lng)
                       and -90 <= lat <= 90 and -180 <= lng <= 180)
        except (TypeError, ValueError, OverflowError):
            located = False
        distance_km = haversine_km(config["bplo_lat"], config["bplo_lng"], lat, lng) if located else None
        distance = round(min(100, distance_km / 20 * 100), 1) if located else 50.0
        proximity = round(100 - distance, 1)
        ops = round(weights["w1"] * risk + weights["w2"] * (sector or 0)
                    + weights["w3"] * proximity, 1) if flagged else 0.0
        ops = max(0.0, min(100.0, ops))
        level, label, color = priority_band(ops)
        total = int(row.get("total_registered") or 0)
        registry_flagged = int(row.get("registry_flagged_count") or 0)
        rankings.append({
            "barangayID": row["barangayID"], "barangayName": row["barangayName"],
            "ops_score": ops, "risk_score": risk, "weighted_burden": burden,
            "sector_score": sector, "distance_score": distance,
            "sector_score_source": sector_source,
            "sector_entity_count": sector_entity_count,
            "sector_known_entity_count": sector_known_count,
            "sector_fallback_entity_count": sector_fallback_count,
            "proximity_score": proximity,
            "distance_km": round(distance_km, 3) if located else None,
            "location_missing": not located, "inspection_required": dispatchable > 0,
            "dispatchable_count": dispatchable,
            "dispatchable_business_count": dispatchable_businesses,
            "dispatchable_red_count": dispatch_red, "dispatchable_yellow_count": dispatch_yellow,
            "dispatchable_burden": 3 * dispatch_red + 2 * dispatch_yellow,
            "flagged_count": flagged, **counts,
            "total_registered": total, "registry_flagged_count": registry_flagged,
            "registry_active_flag_rate": round(registry_flagged / total * 100, 1) if total else None,
            "unregistered_candidate_count": int(row.get("unregistered_candidate_count") or 0),
            "risk_level": level,
            "priority_label": label if flagged else "NO ACTIVE FLAGS",
            "priority_color": color if flagged else "#64748b",
        })
    rankings.sort(key=lambda row: (-row["ops_score"], -row["weighted_burden"],
                                   row["barangayName"].casefold(), row["barangayID"]))
    for rank, row in enumerate(rankings, 1):
        row["rank"] = rank
    model = {
        "version": MODEL_VERSION, "scope": "municipality_current",
        "reference_max_burden": maximum, "flag_weights": dict(FLAG_WEIGHTS),
        "weights": weights,
        "sector_scores_ready": any(row["sector_score_source"] != "neutral_fallback" for row in rankings),
        "sector_enabled": sector_enabled, "sector_note": reason,
        "sector_fallback_score": sector_policy["fallback_score"],
        "sector_fallback_count": sum(row["sector_score_source"] == "neutral_fallback" for row in rankings),
        "sector_entity_count": sum(row["sector_entity_count"] for row in rankings),
        "sector_known_entity_count": sum(row["sector_known_entity_count"] for row in rankings),
        "sector_fallback_entity_count": sum(row["sector_fallback_entity_count"] for row in rankings),
        "sector_policy": sector_policy,
        "sector_count_unit": (
            "unweighted mean across distinct active-flag entities, identified by business ID, "
            "then place ID, then geospatial log ID"
        ),
        "formula": "OPS = W1*Risk + W2*Sector + W3*Proximity",
        "priority_thresholds": {"High": 60, "Medium": 30},
        "location_note": "Straight-line BPLO distance to the mean location of dispatchable Red/Yellow records; missing locations use neutral proximity 50.",
        "eligibility_note": "Black flags remain risk context but cannot be dispatched. Recommendations skip Black-only barangays and targets with Assigned, Reassigned or In Progress reports.",
        "count_unit": "distinct geospatial records; inspector allocation is capped by eligible business identity (business ID, then place ID, then record)",
    }
    return rankings, model


def select_rankings(rankings, filters):
    """Barangay is a display filter; all other dashboard filters are inapplicable."""
    ids = (filters or {}).get("barangay_ids")
    return [row for row in rankings if not ids or row["barangayID"] in ids]
