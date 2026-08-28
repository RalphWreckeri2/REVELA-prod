"""Dispatch recommendation engine.

Produces rich, data-driven recommendations that tell the user:
  - WHY a barangay is prioritised (score breakdown)
  - WHAT the threat looks like (flag composition, urgency)
  - HOW MANY inspectors to deploy (proportional allocation, max 6 total)
  - WHAT TO DO (concrete, ordered action steps)
"""
from typing import Any, Dict, List


# ── helpers ──────────────────────────────────────────────────────────────────

def _urgency_label(ops: float) -> str:
    if ops >= 70:
        return "TOP PRIORITY"
    if ops >= 50:
        return "HIGH PRIORITY"
    if ops >= 30:
        return "STANDARD"
    return "MONITOR"


def _urgency_color(label: str) -> str:
    return {
        "TOP PRIORITY":  "#6366f1",  # Indigo
        "HIGH PRIORITY": "#8b5cf6",  # Violet
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
        parts.append(f"{red} Unregistered")
    if yellow:
        parts.append(f"{yellow} Suspicious")
    if black:
        parts.append(f"{black} Violations")
    if not parts:
        return "No active flags"
    return ", ".join(parts)


def _score_breakdown(brgy: Dict, weights: Dict[str, float]) -> Dict[str, Any]:
    """Return a dict with each component and its weighted contribution."""
    risk = brgy.get("risk_score", 0)
    sector = brgy.get("sector_score", 50)
    distance = brgy.get("distance_score", 50)
    w1 = weights.get("w1", 0.40)
    w2 = weights.get("w2", 0.40)
    w3 = weights.get("w3", 0.20)
    return {
        "risk":     {"raw": round(risk, 1),     "weight": round(w1 * 100), "contribution": round(w1 * risk, 1)},
        "sector":   {"raw": round(sector, 1),   "weight": round(w2 * 100), "contribution": round(w2 * sector, 1)},
        "distance": {"raw": round(100 - distance, 1), "weight": round(w3 * 100), "contribution": round(w3 * (100 - distance), 1)},
    }


def _generate_action_steps(brgy: Dict, inspectors: int, urgency: str) -> List[str]:
    """Return concrete, ordered action steps."""
    name = brgy.get("barangayName", "this barangay")
    red = brgy.get("red_count", 0)
    yellow = brgy.get("yellow_count", 0)
    black = brgy.get("black_count", 0)
    steps = []

    # Step 1 — deployment
    if inspectors > 0:
        steps.append(
            f"Deploy {inspectors} inspector{'s' if inspectors != 1 else ''} to {name}"
        )

    # Step 2 — focus area
    if black:
        steps.append(
            f"Prioritize {black} entit{'ies' if black != 1 else 'y'} with known violations — these require immediate enforcement action"
        )
    if red:
        steps.append(
            f"Verify {red} potentially unregistered entit{'ies' if red != 1 else 'y'} — confirm business registration status on-site"
        )
    if yellow:
        steps.append(
            f"Investigate {yellow} suspicious entit{'ies' if yellow != 1 else 'y'} — requires closer inspection to confirm legitimacy"
        )

    # Step 3 — timing
    if urgency == "TOP PRIORITY":
        steps.append("Schedule inspections within the next 2 business days")
    elif urgency == "HIGH PRIORITY":
        steps.append("Schedule inspections within this week")
    else:
        steps.append("Schedule inspections within the next 2 weeks")

    # Step 4 — documentation
    steps.append("Document findings via the Inspection Report module for each visited entity")

    return steps


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
        (e.g. 0.40, 0.40, 0.20).
    """
    total_inspectors = min(total_inspectors, 6)

    # Only recommend for top-3 barangays that actually have flags
    top_3 = rankings[:3]
    valid = [b for b in top_3 if b.get("flagged_count", 0) > 0]

    if not valid:
        return []

    # Total non-green flags across ALL barangays (for proportion)
    total_all_flags = sum(r.get("flagged_count", 0) for r in rankings) or 1
    # Total flags across the valid top-3 only (for inspector split)
    top_flags = sum(b.get("flagged_count", 0) for b in valid) or 1

    recommendations: List[Dict] = []
    available = total_inspectors

    for i, brgy in enumerate(valid):
        # ── inspector allocation ────────────────────────────────────────────
        if i == len(valid) - 1:
            inspectors = available
        else:
            inspectors = max(
                1,
                round((brgy["flagged_count"] / top_flags) * total_inspectors),
            )
            remaining_slots = len(valid) - 1 - i
            inspectors = min(inspectors, available - remaining_slots)
        inspectors = min(inspectors, 6)
        available -= inspectors

        # ── urgency & scoring ───────────────────────────────────────────────
        ops = brgy.get("ops_score", 0)
        urgency = _urgency_label(ops)
        breakdown = _score_breakdown(brgy, weights)
        action_steps = _generate_action_steps(brgy, inspectors, urgency)
        flags_text = _flag_summary(brgy)

        # ── human-readable recommendation sentence ──────────────────────────
        rec_text = (
            f"{urgency} — Deploy {inspectors} inspector{'s' if inspectors != 1 else ''} to "
            f"{brgy['barangayName']}. "
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
            "flagged_count": brgy.get("flagged_count", 0),
            "red_count":     brgy.get("red_count", 0),
            "yellow_count":  brgy.get("yellow_count", 0),
            "black_count":   brgy.get("black_count", 0),
            "flagSummary":   flags_text,
            "scoreBreakdown": breakdown,
            "actionSteps":   action_steps,
            "risk_level":    brgy.get("risk_level", "Low"),
        })

    return recommendations
