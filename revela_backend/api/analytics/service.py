import os
import json

CONFIG_FILE = os.path.join(os.path.dirname(__file__), "wlc_config.json")

DEFAULT_CONFIG = {
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


def get_wlc_config():
    """Retrieve the current WLC configuration (in-memory cached)."""
    global _wlc_config_cache
    if _wlc_config_cache is not None:
        return _wlc_config_cache
    if not os.path.exists(CONFIG_FILE):
        _wlc_config_cache = DEFAULT_CONFIG.copy()
        return _wlc_config_cache
    try:
        with open(CONFIG_FILE, "r") as f:
            _wlc_config_cache = json.load(f)
        return _wlc_config_cache
    except Exception:
        _wlc_config_cache = DEFAULT_CONFIG.copy()
        return _wlc_config_cache


def update_wlc_config(new_config):
    """Update the WLC configuration, persist it, and refresh the in-memory cache."""
    global _wlc_config_cache
    # Work on a copy so a failed write doesn't silently corrupt the cache.
    current = dict(get_wlc_config())
    current.update(new_config)
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
    default = DEFAULT_CONFIG.copy()
    try:
        with open(CONFIG_FILE, "w") as f:
            json.dump(default, f, indent=4)
        _wlc_config_cache = default
        return default, None
    except Exception as e:
        return None, str(e)
