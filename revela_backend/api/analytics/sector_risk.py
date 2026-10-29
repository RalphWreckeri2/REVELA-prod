"""Editable policy scores for the active PSIC display-sector categories."""

import json
import math
import os
from pathlib import Path
import tempfile
import threading


SECTOR_RISK_POLICY_PATH = Path(__file__).with_name("sector_risk_policy.json")
SECTOR_RISK_POLICY_LOCK = threading.Lock()
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
DEFAULT_SECTOR_RISK_POLICY = {
    "version": "psic-sector-risk-v1",
    "fallback_score": 50,
    "categories": {
        "Manufacturing": 90,
        "Construction and utilities": 85,
        "Wholesale and vehicles": 80,
        "Retail": 80,
        "Food and drink": 75,
        "Hospitality, arts and recreation": 75,
        "Transport and storage": 70,
        "Real estate": 60,
        "Finance and professional": 50,
        "Information and communication": 50,
        "Education, health and other services": 40,
        "Agriculture and mining": 30,
    },
}


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
                or not 0 <= score <= 100 or not math.isfinite(score)):
            raise ValueError(f"Sector risk score for {label} must be a finite number between 0 and 100.")
    return policy


def load_sector_risk_policy(path=SECTOR_RISK_POLICY_PATH):
    with open(path, encoding="utf-8") as policy_file:
        return validate_sector_risk_policy(json.load(policy_file))


def reset_sector_risk_policy(path=SECTOR_RISK_POLICY_PATH):
    """Restore the built-in editable-sector defaults and persist them atomically."""
    return update_sector_risk_policy(
        {
            "categories": dict(DEFAULT_SECTOR_RISK_POLICY["categories"]),
            "fallback_score": DEFAULT_SECTOR_RISK_POLICY["fallback_score"],
        },
        path=path,
    )


def update_sector_risk_policy(policy, path=SECTOR_RISK_POLICY_PATH):
    """Validate and atomically persist a complete sector-risk policy."""
    if not isinstance(policy, dict) or set(policy) != {"categories", "fallback_score"}:
        raise ValueError("Sector risk policy must contain categories and fallback_score only.")
    updated = {
        "version": DEFAULT_SECTOR_RISK_POLICY["version"],
        "fallback_score": policy["fallback_score"],
        "categories": policy["categories"],
    }
    validate_sector_risk_policy(updated)
    target = Path(path)
    temporary_path = None
    with SECTOR_RISK_POLICY_LOCK:
        try:
            file_descriptor, temporary_path = tempfile.mkstemp(
                prefix=f"{target.name}.",
                suffix=".tmp",
                dir=target.parent,
                text=True,
            )
            with os.fdopen(file_descriptor, "w", encoding="utf-8") as policy_file:
                json.dump(updated, policy_file, indent=2)
                policy_file.write("\n")
                policy_file.flush()
                os.fsync(policy_file.fileno())
            os.replace(temporary_path, target)
        except OSError:
            if temporary_path is not None:
                try:
                    os.unlink(temporary_path)
                except FileNotFoundError:
                    pass
            raise
    return updated


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
