"""Editable policy scores for the active PSIC display-sector categories."""

import json
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
    "version": 1,
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
    version = policy.get("version")
    if isinstance(version, bool) or not isinstance(version, int) or version < 1:
        raise ValueError("Sector risk policy version must be a positive integer.")
    categories = policy.get("categories")
    if not isinstance(categories, dict) or set(categories) != set(SECTOR_CATEGORIES):
        raise ValueError("Sector risk policy must define exactly the 12 active PSIC display categories.")
    for label, score in {**categories, "fallback_score": policy.get("fallback_score")}.items():
        if isinstance(score, bool) or not isinstance(score, int) or not 0 <= score <= 100:
            raise ValueError(f"Sector risk score for {label} must be an integer between 0 and 100.")
    if policy["fallback_score"] != DEFAULT_SECTOR_RISK_POLICY["fallback_score"]:
        raise ValueError("The unclassified fallback score is fixed at 50.")
    return policy


def validate_sector_risk_categories(payload):
    """Validate the editable category map without accepting fallback or version edits."""
    if not isinstance(payload, dict) or set(payload) != {"categories"}:
        raise ValueError("Sector policy updates must contain categories only.")
    categories = payload["categories"]
    if not isinstance(categories, dict) or set(categories) != set(SECTOR_CATEGORIES):
        raise ValueError("Sector policy must contain exactly the 12 known PSIC display categories.")
    for label, score in categories.items():
        if isinstance(score, bool) or not isinstance(score, int) or not 0 <= score <= 100:
            raise ValueError(f"Sector risk score for {label} must be an integer between 0 and 100.")
    return dict(categories)


def load_persisted_sector_risk_policy(cursor):
    cursor.execute(
        """SELECT version, fallback_score, categories
           FROM sector_risk_policy
           WHERE policy_id = 1"""
    )
    row = cursor.fetchone()
    if not row:
        raise RuntimeError("The sector risk policy has not been initialized.")
    categories = row["categories"]
    if isinstance(categories, str):
        categories = json.loads(categories)
    return validate_sector_risk_policy({
        "version": int(row["version"]),
        "fallback_score": int(row["fallback_score"]),
        "categories": categories,
    })


def save_persisted_sector_risk_policy(cursor, categories, actor_user_id):
    """Save a new policy revision and its audit row in the caller's transaction."""
    categories = validate_sector_risk_categories({"categories": categories})
    cursor.execute(
        """SELECT version, fallback_score, categories
           FROM sector_risk_policy
           WHERE policy_id = 1
           FOR UPDATE"""
    )
    row = cursor.fetchone()
    if not row:
        raise RuntimeError("The sector risk policy has not been initialized.")
    old_categories = row["categories"]
    if isinstance(old_categories, str):
        old_categories = json.loads(old_categories)
    old_policy = validate_sector_risk_policy({
        "version": int(row["version"]),
        "fallback_score": int(row["fallback_score"]),
        "categories": old_categories,
    })
    new_policy = validate_sector_risk_policy({
        "version": old_policy["version"] + 1,
        "fallback_score": DEFAULT_SECTOR_RISK_POLICY["fallback_score"],
        "categories": categories,
    })
    cursor.execute(
        """INSERT INTO sector_risk_policy_audit
           (version, actor_user_id, old_values, new_values)
           VALUES (%s, %s, %s, %s)""",
        (
            new_policy["version"],
            actor_user_id,
            json.dumps(old_policy, separators=(",", ":")),
            json.dumps(new_policy, separators=(",", ":")),
        ),
    )
    cursor.execute(
        """UPDATE sector_risk_policy
           SET version = %s, fallback_score = %s, categories = %s, updated_by = %s
           WHERE policy_id = 1""",
        (
            new_policy["version"],
            new_policy["fallback_score"],
            json.dumps(new_policy["categories"], separators=(",", ":")),
            actor_user_id,
        ),
    )
    return new_policy


def load_sector_risk_policy_audit(cursor, limit=50):
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 100:
        raise ValueError("Audit limit must be an integer between 1 and 100.")
    cursor.execute(
        """SELECT a.version, a.actor_user_id, u.fullName AS actor_name,
                  a.created_at, a.old_values, a.new_values
           FROM sector_risk_policy_audit a
           LEFT JOIN users u ON u.userID = a.actor_user_id
           ORDER BY a.version DESC, a.audit_id DESC
           LIMIT %s""",
        (limit,),
    )
    rows = cursor.fetchall()
    for row in rows:
        for key in ("old_values", "new_values"):
            if isinstance(row[key], str):
                row[key] = json.loads(row[key])
    return rows


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
        "fallback_score": DEFAULT_SECTOR_RISK_POLICY["fallback_score"],
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
