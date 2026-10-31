"""Dispatch recommendation engine.

Produces rich, data-driven recommendations that tell the user:
  - WHY a barangay is prioritised (score breakdown)
  - WHAT the threat looks like (flag composition, urgency)
  - HOW MANY inspectors to deploy (business-capped, burden-weighted, max 6 total)
  - WHAT TO DO (concrete, ordered action steps)
"""
from typing import Any, Dict, List
from api.analytics.scoring import priority_band, NEUTRAL_SECTOR_SCORE


# ── helpers ──────────────────────────────────────────────────────────────────

def _urgency_label(ops: float) -> str:
    return priority_band(ops)[1]


def _urgency_color(label: str) -> str:
    return {
        "HIGH PRIORITY": "#6366f1",  # Same bands as the WLC priority table
        "STANDARD":      "#0ea5e9",  # Sky blue
        "MONITOR":       "#10b981",  # Emerald
    }.get(label, "#64748b")


def _flag_summary(brgy: Dict) -> str:
    """Human sentence describing the flag composition."""
    parts = []
    red = brgy.get("red_count", 0)
    yellow = brgy.get("yellow_count", 0)
    black = brgy.get("black_count", 0)
    if red:
        parts.append(f"{red} Registration/renewal checks")
    if yellow:
        parts.append(f"{yellow} Suspicious")
    if black:
        parts.append(f"{black} Black-flagged")
    if not parts:
        return "No active flags"
    return ", ".join(parts)


def _score_breakdown(brgy: Dict, weights: Dict[str, float]) -> Dict[str, Any]:
    """Return a dict with each component and its weighted contribution."""
    risk = brgy.get("risk_score", 0)
    sector = brgy.get("sector_score")
    if sector is None:
        sector = NEUTRAL_SECTOR_SCORE
    proximity = brgy.get("proximity_score", 100 - brgy.get("distance_score", 50))
    w1 = weights.get("w1", 0.68)
    w2 = weights.get("w2", 0.07)
    w3 = weights.get("w3", 0.25)
    return {
        "risk":     {"raw": round(risk, 1),     "weight": round(w1 * 100, 1), "contribution": round(w1 * risk, 1)},
        "sector":   {"raw": round(sector, 1),   "weight": round(w2 * 100, 1), "contribution": round(w2 * sector, 1)},
        "distance": {"raw": round(proximity, 1), "weight": round(w3 * 100, 1), "contribution": round(w3 * proximity, 1)},
    }


def _generate_action_steps(brgy: Dict, inspectors: int, urgency: str) -> List[str]:
    """Return concrete, ordered action steps."""
    name = brgy.get("barangayName", "this barangay")
    red = brgy.get("dispatchable_red_count", brgy.get("red_count", 0))
    yellow = brgy.get("dispatchable_yellow_count", brgy.get("yellow_count", 0))
    black = brgy.get("black_count", 0)
    steps = []

    # Step 1 — deployment
    if inspectors > 0:
        steps.append(
            f"Deploy {inspectors} inspector{'s' if inspectors != 1 else ''} to {name}"
        )
    else:
        steps.append(f"Keep {name} in WLC priority order; deployment is deferred until inspectors are available")

    # Step 2 — focus area
    if black:
        steps.append(
            f"Refer {black} black-flagged record{'s' if black != 1 else ''} for administrative review — Black businesses cannot be dispatched for inspection"
        )
    if red:
        steps.append(
            f"Verify registration or permit renewal for {red} red-flagged record{'s' if red != 1 else ''} on-site"
        )
    if yellow:
        steps.append(
            f"Investigate {yellow} suspicious entit{'ies' if yellow != 1 else 'y'} — requires closer inspection to confirm legitimacy"
        )

    # Step 3 — timing
    if inspectors == 0:
        steps.append("Confirm inspector availability before setting a deployment date")
    elif urgency == "HIGH PRIORITY":
        steps.append("Schedule inspections within the next 2 business days")
    elif urgency == "STANDARD":
        steps.append("Schedule inspections within this week")
    else:
        steps.append("Schedule inspections within the next 2 weeks")

    # Step 4 — documentation
    steps.append("Document findings via the Inspection Report module for each visited entity")

    return steps


def _is_dispatch_eligible(brgy: Dict) -> bool:
    dispatchable = brgy.get("dispatchable_count", brgy.get("red_count", 0) + brgy.get("yellow_count", 0))
    businesses = brgy.get("dispatchable_business_count", dispatchable)
    return dispatchable > 0 and int(businesses or 0) > 0


def dispatch_exclusion_reasons(rankings: List[Dict]) -> Dict[Any, str]:
    """Explain why a ranked barangay has no entry in the current dispatch plan."""
    eligible = [row for row in rankings if _is_dispatch_eligible(row)]
    top_three_ids = {row["barangayID"] for row in eligible[:3]}
    reasons = {}

    for row in rankings:
        barangay_id = row["barangayID"]
        if _is_dispatch_eligible(row):
            if barangay_id not in top_three_ids:
                reasons[barangay_id] = "Outside current top-three plan"
            continue

        red = int(row.get("red_count") or 0)
        yellow = int(row.get("yellow_count") or 0)
        black = int(row.get("black_count") or 0)
        if black > 0 and red == 0 and yellow == 0:
            reasons[barangay_id] = "Administrative review — Black only"
        elif red + yellow > 0:
            reasons[barangay_id] = "Targets already assigned"

    return reasons


# ── main entry point ─────────────────────────────────────────────────────────

def generate_recommendations(
    rankings: List[Dict],
    total_inspectors: int,
    weights: Dict[str, float],
) -> List[Dict]:
    """Build rich dispatch recommendations from the ranked barangay list.

    Parameters
    ----------
    rankings : list[dict]
        Barangay ranking dicts (must include ops_score, risk_score, sector_score,
        distance_score, flagged_count, red/yellow/black_count, rank, barangayName).
    total_inspectors : int
        Total available inspectors.  Hard-capped at 6.
    weights : dict
        ``{"w1": float, "w2": float, "w3": float}`` — the normalised WLC weights
        (e.g. 0.68, 0.07, 0.25). Deferred destinations retain their WLC order.
    """
    total_inspectors = max(0, min(int(total_inspectors), 6))

    # Eligibility precedes the top-3 limit; never spend a slot on a flag-free row.
    valid = [b for b in rankings if _is_dispatch_eligible(b)][:3]

    if not valid:
        return []

    capacities = [
        max(0, int(b.get("dispatchable_business_count",
                         b.get("dispatchable_count", b.get("red_count", 0) + b.get("yellow_count", 0))) or 0))
        for b in valid
    ]
    selected = valid[:total_inspectors]
    allocations = [0] * len(valid)
    for index in range(len(selected)):
        allocations[index] = 1

    # Preserve WLC coverage and burden-weighted allocation, but never assign
    # more than one inspector per eligible business in a destination.
    remaining = total_inspectors - len(selected)
    while remaining > 0:
        active = [index for index in range(len(selected))
                  if allocations[index] < capacities[index]]
        if not active:
            break
        burdens = {
            index: max(1, selected[index].get(
                "dispatchable_burden",
                3 * selected[index].get("dispatchable_red_count", selected[index].get("red_count", 0))
                + 2 * selected[index].get("dispatchable_yellow_count", selected[index].get("yellow_count", 0))))
            for index in active
        }
        total_burden = sum(burdens.values())
        shares = {index: remaining * burden / total_burden for index, burden in burdens.items()}
        extras = {
            index: min(capacities[index] - allocations[index], int(share))
            for index, share in shares.items()
        }
        assigned = sum(extras.values())
        for index, extra in extras.items():
            allocations[index] += extra
        remaining -= assigned
        if remaining <= 0:
            break
        active = [index for index in active if allocations[index] < capacities[index]]
        if not active:
            break
        for index in sorted(active, key=lambda i: (-(shares[i] - int(shares[i])), i)):
            if remaining <= 0:
                break
            allocations[index] += 1
            remaining -= 1

    recommendations: List[Dict] = []
    for brgy, inspectors in zip(valid, allocations):

        # ── urgency & scoring ───────────────────────────────────────────────
        ops = brgy.get("ops_score", 0)
        urgency = _urgency_label(ops)
        breakdown = _score_breakdown(brgy, weights)
        action_steps = _generate_action_steps(brgy, inspectors, urgency)
        flags_text = _flag_summary(brgy)

        # ── human-readable recommendation sentence ──────────────────────────
        deployment = (f"Deploy {inspectors} inspector{'s' if inspectors != 1 else ''} to {brgy['barangayName']}"
                      if inspectors else f"Defer deployment to {brgy['barangayName']} until inspectors are available")
        rec_text = (
            f"{urgency} — {deployment}. "
            f"OPS Score: {ops}/100. "
            f"Flags: {flags_text}."
        )

        recommendations.append({
            "barangayID":    brgy["barangayID"],
            "barangayName":  brgy["barangayName"],
            "rank":          brgy["rank"],
            "recommendation": rec_text,
            "ops_score":     ops,
            "urgency":       urgency,
            "urgencyColor":  _urgency_color(urgency),
            "inspectors":    inspectors,
            "allocation_status": "ready" if inspectors else "deferred",
            "flagged_count": brgy.get("flagged_count", 0),
            "dispatchable_count": brgy.get("dispatchable_count", brgy.get("red_count", 0) + brgy.get("yellow_count", 0)),
            "dispatchable_business_count": capacities[len(recommendations)],
            "red_count":     brgy.get("red_count", 0),
            "yellow_count":  brgy.get("yellow_count", 0),
            "black_count":   brgy.get("black_count", 0),
            "flagSummary":   flags_text,
            "scoreBreakdown": breakdown,
            "actionSteps":   action_steps,
            "risk_level":    priority_band(ops)[0],
        })

    return recommendations
