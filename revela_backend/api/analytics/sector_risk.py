"""Editable policy scores for the active PSIC display-sector categories."""

import json
import math
from pathlib import Path


SECTOR_RISK_POLICY_PATH = Path(__file__).with_name("sector_risk_policy.json")
SECTOR_CATEGORIES = (
    "Manufacturing",
    "Construction and utilities",
    "Wholesale and vehicles",
    "Retail",
    "Food and drink",
    "Hospitality, arts and recreation",
    "Transport and storage",
    "Real estate",
    "Finance and professional",
    "Information and communication",
    "Education, health and other services",
    "Agriculture and mining",
)


def validate_sector_risk_policy(policy):
    if not isinstance(policy, dict):
        raise ValueError("Sector risk policy must be a JSON object.")
    if not isinstance(policy.get("version"), str) or not policy["version"].strip():
        raise ValueError("Sector risk policy requires a non-empty version.")
    categories = policy.get("categories")
    if not isinstance(categories, dict) or set(categories) != set(SECTOR_CATEGORIES):
        raise ValueError("Sector risk policy must define exactly the 12 active PSIC display categories.")
    for label, score in {**categories, "fallback_score": policy.get("fallback_score")}.items():
        if (isinstance(score, bool) or not isinstance(score, (int, float))
                or not math.isfinite(score) or not 0 <= score <= 100):
            raise ValueError(f"Sector risk score for {label} must be a finite number between 0 and 100.")
    return policy


def load_sector_risk_policy(path=SECTOR_RISK_POLICY_PATH):
    with open(path, encoding="utf-8") as policy_file:
        return validate_sector_risk_policy(json.load(policy_file))


def weighted_sector_score(category_counts, policy):
    """Return policy score and coverage counts for distinct represented entities."""
    validate_sector_risk_policy(policy)
    if not isinstance(category_counts, dict):
        raise ValueError("Sector category counts must be an object.")

    fallback = policy["fallback_score"]
    total = known = fallback_count = 0
    weighted_total = 0.0
    for label, count in category_counts.items():
        if isinstance(count, bool) or not isinstance(count, int) or count < 0:
            raise ValueError("Sector entity counts must be non-negative integers.")
        if not count:
            continue
        score = policy["categories"].get(label, fallback)
        total += count
        weighted_total += score * count
        if label in policy["categories"]:
            known += count
        else:
            fallback_count += count

    return (
        weighted_total / total if total else fallback,
        total,
        known,
        fallback_count,
    )
