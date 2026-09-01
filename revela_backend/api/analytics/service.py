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


def get_wlc_config():
    """Retrieve the current WLC configuration."""
    if not os.path.exists(CONFIG_FILE):
        return DEFAULT_CONFIG
    try:
        with open(CONFIG_FILE, "r") as f:
            return json.load(f)
    except Exception:
        return DEFAULT_CONFIG


def update_wlc_config(new_config):
    """Update the WLC configuration and persist it to a JSON file."""
    current = get_wlc_config()
    current.update(new_config)
    try:
        with open(CONFIG_FILE, "w") as f:
            json.dump(current, f, indent=4)
        return current, None
    except Exception as e:
        return None, str(e)
