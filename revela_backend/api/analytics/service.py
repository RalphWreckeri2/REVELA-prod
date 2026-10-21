import os
import json
import logging
import math
from copy import deepcopy

CONFIG_FILE = os.path.join(os.path.dirname(__file__), "wlc_config.json")

DEFAULT_CONFIG = {
    # Interview-derived policy. Do not recalibrate or redistribute these weights
    # when an input is missing; preserve the configured three-component model.
    "w1_risk": 68,
    "w2_sector": 7,
    "w3_distance": 25,
    "bplo_lat": 13.960413,
    "bplo_lng": 121.114547,
    "sectors": {}
}

# In-memory cache — avoids disk I/O on every analytics request.
# Invalidated explicitly on write/reset so cache is always in sync.
_wlc_config_cache = None


def validate_wlc_config(config):
    """Reject invalid policy inputs before either scoring or persisting them."""
    if not isinstance(config, dict):
        raise ValueError("WLC configuration must be a JSON object.")
    for key in ("w1_risk", "w2_sector", "w3_distance", "bplo_lat", "bplo_lng"):
        value = config.get(key)
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            raise ValueError(f"{key} must be a finite number.")
    weights = [config[key] for key in ("w1_risk", "w2_sector", "w3_distance")]
    if any(value < 0 or value > 100 for value in weights):
        raise ValueError("WLC weights must be between 0 and 100.")
    if not math.isclose(sum(weights), 100, rel_tol=0, abs_tol=0.000001):
        raise ValueError("WLC weights must total 100%.")
    if not -90 <= config["bplo_lat"] <= 90 or not -180 <= config["bplo_lng"] <= 180:
        raise ValueError("BPLO coordinates must be valid latitude and longitude values.")
    sectors = config.get("sectors", {})
    if not isinstance(sectors, dict):
        raise ValueError("Sector scores must be an object keyed by barangay name.")
    for name, score in sectors.items():
        if not isinstance(name, str) or not name.strip():
            raise ValueError("Sector scores require non-empty barangay names.")
        if isinstance(score, bool) or not isinstance(score, (int, float)) or not math.isfinite(score) or not 0 <= score <= 100:
            raise ValueError("Each sector score must be a finite number between 0 and 100.")


def get_wlc_config():
    """Retrieve the current WLC configuration (in-memory cached)."""
    global _wlc_config_cache
    if _wlc_config_cache is not None:
        return _wlc_config_cache
    if not os.path.exists(CONFIG_FILE):
        _wlc_config_cache = deepcopy(DEFAULT_CONFIG)
        return _wlc_config_cache
    try:
        with open(CONFIG_FILE, "r") as f:
            config = {**deepcopy(DEFAULT_CONFIG), **json.load(f)}
        validate_wlc_config(config)
        _wlc_config_cache = config
        return _wlc_config_cache
    except (OSError, ValueError, TypeError):
        logging.getLogger("revela.analytics").warning("Invalid or unreadable WLC policy; using the safe default preset.")
        _wlc_config_cache = deepcopy(DEFAULT_CONFIG)
        return _wlc_config_cache


def update_wlc_config(new_config):
    """Update the WLC configuration, persist it, and refresh the in-memory cache."""
    global _wlc_config_cache
    # Work on a copy so a failed write doesn't silently corrupt the cache.
    if not isinstance(new_config, dict):
        raise ValueError("WLC configuration must be a JSON object.")
    if set(new_config) - set(DEFAULT_CONFIG):
        raise ValueError("Unknown WLC configuration field.")
    current = deepcopy(get_wlc_config())
    current.update(new_config)
    validate_wlc_config(current)
    try:
        with open(CONFIG_FILE, "w") as f:
            json.dump(current, f, indent=4)
        _wlc_config_cache = current  # only update cache after successful write
        return current, None
    except Exception as e:
        return None, str(e)


def reset_wlc_config():
    """Reset WLC configuration to system defaults and refresh the in-memory cache."""
    global _wlc_config_cache
    default = deepcopy(DEFAULT_CONFIG)
    try:
        with open(CONFIG_FILE, "w") as f:
            json.dump(default, f, indent=4)
        _wlc_config_cache = default
        return default, None
    except Exception as e:
        return None, str(e)
