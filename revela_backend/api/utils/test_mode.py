"""
Test Mode: exercise Run Detection and the matcher without spending Google quota.

Two separate mechanisms, deliberately:

1. **Test Mode** bounds a real run — a smaller geographic scope and a per-run
   request cap — so a staging run touches only a slice of the municipality.

2. **The fixture cache** stores the payload of each request that was actually
   made. On a repeat, the cached payload is replayed instead of calling Google.

The accounting rule that makes requirement 5 work:

    A fixture hit NEVER touches `places_api_usage`. No Google request happened,
    so there is nothing to account for.
    A live request ALWAYS reserves a slot first, exactly as in production.

That is why testing no longer requires truncating the usage tables — there is
nothing to truncate. Usage rows only ever describe real Google calls, so the
ledger stays a trustworthy billing record.

Storing fixtures does retain Google-derived content (place id, display name,
coordinates, type, business status). That is the same field set the FieldMask
already requests, but it is a different retention posture from `scan_point_log`,
which deliberately stores only grid coordinates. Fixtures are therefore
opt-in, purgeable, and TTL-bounded by `fixture_ttl_days`.
"""

import hashlib
import json
import os
import threading
import time
from datetime import datetime, timedelta

from app import mysql
from api.models import app_settings


_test_mode_table_ready = False
_test_mode_table_lock = threading.Lock()
_fixture_cleanup_lock = threading.Lock()
_last_fixture_cleanup_at = 0.0
_FIXTURE_CLEANUP_INTERVAL_SECONDS = 3600
_FIXTURE_STORAGE_APPROVAL_ENV = "GOOGLE_PLACES_TEST_FIXTURE_STORAGE_APPROVED"

FIXTURE_TABLE_SCHEMA = """
CREATE TABLE IF NOT EXISTS revela_places_fixtures (
    fixtureKey  VARCHAR(191) NOT NULL PRIMARY KEY,
    fixtureKind VARCHAR(32)  NOT NULL,
    payload     LONGTEXT     NOT NULL,
    createdAt   DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    lastUsedAt  DATETIME     DEFAULT NULL,
    hitCount    INT          NOT NULL DEFAULT 0,
    KEY idx_fixtures_created (createdAt),
    KEY idx_fixtures_kind (fixtureKind)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
"""

SETTINGS_KEYS = (
    "test_mode.enabled",
    "test_mode.fixture_storage_enabled",
    "test_mode.max_requests",
    "test_mode.grid_step_degrees",
    "test_mode.radius_m",
    "test_mode.max_grid_points",
    "test_mode.fixture_policy",
    "test_mode.fixture_ttl_days",
)

#: Only these policy values are accepted; anything else falls back.
POLICIES = ("cache_then_live", "cache_only")

DEFAULTS = {
    "test_mode.enabled": False,
    "test_mode.fixture_storage_enabled": False,
    "test_mode.max_requests": 20,
    "test_mode.grid_step_degrees": 0.009,
    "test_mode.radius_m": 850,
    "test_mode.max_grid_points": 6,
    "test_mode.fixture_policy": "cache_then_live",
    "test_mode.fixture_ttl_days": 14,
}

BOUNDS = {
    "test_mode.max_requests": (1, 120),
    "test_mode.grid_step_degrees": (0.001, 0.011),
    "test_mode.radius_m": (100, 5000),
    "test_mode.max_grid_points": (1, 101),
    "test_mode.fixture_ttl_days": (1, 30),
}


def _ensure_table():
    global _test_mode_table_ready
    if _test_mode_table_ready:
        return
    with _test_mode_table_lock:
        if _test_mode_table_ready:
            return
        cur = mysql.connection.cursor()
        try:
            cur.execute(FIXTURE_TABLE_SCHEMA)
            mysql.connection.commit()
            _test_mode_table_ready = True
        finally:
            cur.close()


class TestModeCacheMiss(Exception):
    """Raised in cache_only mode when a request has no stored fixture."""

    def __init__(self, fixture_key, storage_disabled=False):
        message = (
            "Google Places fixture storage is disabled by server policy. "
            "A cached-only request cannot call Google."
            if storage_disabled else
            "Test Mode is set to 'Cached results only' and this request has "
            "no stored fixture. Switch the policy to 'Cache then call Google' "
            "to record it once, or run the same request again after priming."
        )
        super().__init__(message)
        self.fixture_key = fixture_key


# ── Configuration ─────────────────────────────────────────────────────────────

def _read_bool(value, fallback):
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        return value.strip().lower() in ("1", "true", "yes", "on")
    return fallback


def _read_number(value, fallback, key):
    if value is None:
        return fallback
    try:
        number = float(value)
    except (TypeError, ValueError):
        return fallback
    if key in BOUNDS:
        low, high = BOUNDS[key]
        number = max(low, min(high, number))
    return int(number) if key != "test_mode.grid_step_degrees" else number


def get_config():
    """Current Test Mode settings, merged over the defaults."""
    stored = app_settings.load_all()
    config = {}
    for key, fallback in DEFAULTS.items():
        raw = stored.get(key, fallback)
        if key == "test_mode.enabled":
            config[key] = _read_bool(raw, fallback)
        elif key == "test_mode.fixture_policy":
            config[key] = raw if raw in POLICIES else fallback
        else:
            config[key] = _read_number(raw, fallback, key)
    config["test_mode.fixture_storage_approved"] = (
        os.getenv(_FIXTURE_STORAGE_APPROVAL_ENV) == "1"
    )
    config["test_mode.fixture_storage_enabled"] = (
        config["test_mode.fixture_storage_enabled"]
        and config["test_mode.fixture_storage_approved"]
    )
    return config


def validate_patch(patch):
    """Validate a Test Mode patch. Returns (clean, errors)."""
    errors, clean = [], {}
    for key, raw in patch.items():
        if key not in DEFAULTS:
            errors.append(f"Unknown Test Mode setting: {key}")
            continue
        if key == "test_mode.enabled":
            clean[key] = _read_bool(raw, False)
        elif key == "test_mode.fixture_storage_enabled":
            requested = _read_bool(raw, False)
            if requested and os.getenv(_FIXTURE_STORAGE_APPROVAL_ENV) != "1":
                errors.append(
                    "Google Places fixture storage requires the server-side "
                    f"{_FIXTURE_STORAGE_APPROVAL_ENV}=1 policy approval."
                )
            else:
                clean[key] = requested
        elif key == "test_mode.fixture_policy":
            if raw not in POLICIES:
                errors.append(
                    f"{key} must be one of: {', '.join(POLICIES)}."
                )
            else:
                clean[key] = raw
        else:
            low, high = BOUNDS[key]
            try:
                number = float(raw)
            except (TypeError, ValueError):
                errors.append(f"{key} must be a number.")
                continue
            if key == "test_mode.grid_step_degrees":
                if not (low <= number <= high):
                    errors.append(f"{key} must be between {low} and {high}.")
                    continue
                clean[key] = number
            else:
                if number != int(number):
                    errors.append(f"{key} must be a whole number.")
                    continue
                number = int(number)
                if not (low <= number <= high):
                    errors.append(f"{key} must be between {low} and {high}.")
                    continue
                clean[key] = number
    return clean, errors


def save_config(patch, user_id=None):
    clean, errors = validate_patch(patch)
    if errors:
        return None, "; ".join(errors)
    saved, error = app_settings.save_many(clean, user_id=user_id)
    if error:
        return None, error
    return {"saved": saved, "config": get_config()}, None


def reset_config(user_id=None):
    removed, error = app_settings.delete_many(list(SETTINGS_KEYS))
    if error:
        return None, error
    return {"removed": removed, "config": get_config()}, None


def is_enabled():
    return bool(get_config()["test_mode.enabled"])


# ── Fixture cache ─────────────────────────────────────────────────────────────

def fixture_key(kind, url, params=None, payload=None):
    """
    Stable cache key for one outbound request.

    Includes the full request identity so a changed radius, grid step, or
    endpoint is a different fixture rather than a stale hit.
    """
    material = {
        "format_version": 2,
        "kind": kind,
        "url": url,
        "params": {str(k): str(v) for k, v in sorted((params or {}).items())},
        "payload": payload if payload is None else _canonical(payload),
    }
    blob = json.dumps(material, sort_keys=True, separators=(",", ":"))
    return f"{kind}:{hashlib.sha256(blob.encode('utf-8')).hexdigest()[:40]}"


def _canonical(value):
    return json.loads(json.dumps(value, sort_keys=True, default=str))


def lookup_fixture(key):
    """Return the stored payload for a key, or None. Never raises."""
    try:
        _ensure_table()
    except Exception as exc:
        print(f"[test_mode] fixture table unavailable ({exc})")
        return None
    cur = mysql.connection.cursor()
    try:
        ttl = get_config()["test_mode.fixture_ttl_days"]
        cur.execute(
            "SELECT payload FROM revela_places_fixtures "
            "WHERE fixtureKey = %s "
            "AND createdAt >= DATE_SUB(NOW(), INTERVAL %s DAY)",
            (key, ttl),
        )
        row = cur.fetchone()
        if not row:
            return None
        raw = row["payload"] if isinstance(row, dict) else row[0]
        # Count the hit without charging the usage ledger.
        cur.execute(
            "UPDATE revela_places_fixtures "
            "SET hitCount = hitCount + 1, lastUsedAt = NOW() "
            "WHERE fixtureKey = %s",
            (key,),
        )
        mysql.connection.commit()
        return json.loads(raw)
    except Exception as exc:
        print(f"[test_mode] fixture lookup failed for {key} ({exc})")
        return None
    finally:
        cur.close()


def _minimal_fixture_payload(kind, payload):
    """Keep only fields the detection parser consumes; reject paginated legacy responses."""
    if kind == "nearby":
        if payload.get("next_page_token"):
            return None
        results = []
        for place in payload.get("results", []) or []:
            if not isinstance(place, dict):
                continue
            location = (place.get("geometry") or {}).get("location") or {}
            results.append({
                "place_id": place.get("place_id"),
                "name": place.get("name"),
                "geometry": {"location": {
                    "lat": location.get("lat"),
                    "lng": location.get("lng"),
                }},
                "types": place.get("types") or [],
                "business_status": place.get("business_status"),
                "vicinity": place.get("vicinity"),
            })
        return {"status": payload.get("status"), "results": results}

    if kind == "nearby_new":
        places = []
        for place in payload.get("places", []) or []:
            if not isinstance(place, dict):
                continue
            display_name = place.get("displayName") or {}
            location = place.get("location") or {}
            places.append({
                "id": place.get("id"),
                "displayName": {"text": display_name.get("text")},
                "location": {
                    "latitude": location.get("latitude"),
                    "longitude": location.get("longitude"),
                },
                "primaryType": place.get("primaryType"),
                "businessStatus": place.get("businessStatus"),
            })
        return {"places": places}

    return None


def _cleanup_expired_fixtures(force=False):
    """Periodically delete fixtures beyond the configured retention window."""
    global _last_fixture_cleanup_at
    now = time.monotonic()
    if (
        not force
        and now - _last_fixture_cleanup_at < _FIXTURE_CLEANUP_INTERVAL_SECONDS
    ):
        return 0
    with _fixture_cleanup_lock:
        now = time.monotonic()
        if (
            not force
            and now - _last_fixture_cleanup_at < _FIXTURE_CLEANUP_INTERVAL_SECONDS
        ):
            return 0
        _ensure_table()
        cur = mysql.connection.cursor()
        try:
            cur.execute(
                "DELETE FROM revela_places_fixtures "
                "WHERE createdAt < DATE_SUB(NOW(), INTERVAL %s DAY)",
                (get_config()["test_mode.fixture_ttl_days"],),
            )
            removed = cur.rowcount or 0
            mysql.connection.commit()
            _last_fixture_cleanup_at = now
            return removed
        except Exception:
            mysql.connection.rollback()
            raise
        finally:
            cur.close()


def store_fixture(key, kind, payload):
    """Store a minimal fixture only after explicit server-side policy approval."""
    if not get_config()["test_mode.fixture_storage_enabled"]:
        return False
    minimal_payload = _minimal_fixture_payload(kind, payload)
    if minimal_payload is None:
        return False
    try:
        _cleanup_expired_fixtures()
        _ensure_table()
    except Exception as exc:
        print(f"[test_mode] could not store fixture {key} ({exc})")
        return False
    cur = mysql.connection.cursor()
    try:
        cur.execute(
            "INSERT INTO revela_places_fixtures "
            "    (fixtureKey, fixtureKind, payload) "
            "VALUES (%s, %s, %s) "
            "ON DUPLICATE KEY UPDATE "
            "    payload = VALUES(payload), createdAt = NOW()",
            (key, kind, json.dumps(minimal_payload)),
        )
        mysql.connection.commit()
        return True
    except Exception as exc:
        mysql.connection.rollback()
        print(f"[test_mode] could not store fixture {key} ({exc})")
        return False
    finally:
        cur.close()


class FixtureResponse:
    """
    Minimal stand-in for `requests.Response` so cached payloads flow through the
    same parsing code as live ones. `from_cache` lets callers log the source.
    """

    def __init__(self, payload, status_code=200, from_cache=True):
        self._payload = payload
        self.status_code = status_code
        self.text = json.dumps(payload)
        self.from_cache = from_cache

    def json(self):
        return json.loads(self.text)


def fixture_stats():
    """Counts and age for the admin panel. Never returns stored content."""
    try:
        if get_config()["test_mode.fixture_storage_enabled"]:
            _cleanup_expired_fixtures()
        _ensure_table()
    except Exception as exc:
        print(f"[test_mode] fixture stats unavailable ({exc})")
        return {
            "total": 0, "by_kind": {}, "oldest": None,
            "available": False, "reason": str(exc),
        }
    cur = mysql.connection.cursor()
    try:
        cur.execute(
            "SELECT COUNT(*) AS total, "
            "       SUM(hitCount) AS hits, "
            "       MIN(createdAt) AS oldest, "
            "       MAX(createdAt) AS newest, "
            "       COALESCE(SUM(CHAR_LENGTH(payload)), 0) AS bytes "
            "FROM revela_places_fixtures"
        )
        row = cur.fetchone() or {}
        cur.execute(
            "SELECT fixtureKind AS kind, COUNT(*) AS total "
            "FROM revela_places_fixtures GROUP BY fixtureKind"
        )
        by_kind = {
            (r["kind"] if isinstance(r, dict) else r[0]): (
                r["total"] if isinstance(r, dict) else r[1]
            )
            for r in (cur.fetchall() or [])
        }
    except Exception as exc:
        print(f"[test_mode] fixture stats query failed ({exc})")
        return {
            "total": 0, "by_kind": {}, "oldest": None,
            "available": False, "reason": str(exc),
        }
    finally:
        cur.close()

    def _count(field):
        value = row.get(field) if isinstance(row, dict) else None
        try:
            return int(value or 0)
        except (TypeError, ValueError):
            return 0

    oldest = row.get("oldest") if isinstance(row, dict) else None
    ttl = get_config()["test_mode.fixture_ttl_days"]
    expires = None
    if oldest is not None and isinstance(oldest, datetime):
        expires = (oldest + timedelta(days=ttl)
                   ).isoformat(sep=" ", timespec="seconds")

    return {
        "available": True,
        "total": _count("total"),
        "replay_hits": _count("hits"),
        "approx_bytes": _count("bytes"),
        "by_kind": by_kind,
        "oldest": oldest.isoformat(sep=" ") if isinstance(oldest, datetime) else None,
        "newest": (
            row.get("newest").isoformat(sep=" ")
            if isinstance(row, dict) and isinstance(row.get("newest"), datetime)
            else None
        ),
        "retention_days": ttl,
        "expires_at": expires,
    }


def purge_fixtures(older_than_days=None):
    """Delete fixtures. Defaults to the configured retention window."""
    if older_than_days is None:
        older_than_days = get_config()["test_mode.fixture_ttl_days"]
    try:
        older_than_days = max(0, min(30, int(older_than_days)))
    except (TypeError, ValueError):
        return 0, "Retention window must be a whole number of days."
    try:
        _ensure_table()
    except Exception as exc:
        return 0, f"Fixture storage is unavailable: {exc}"

    cur = mysql.connection.cursor()
    try:
        if older_than_days == 0:
            cur.execute("DELETE FROM revela_places_fixtures")
        else:
            cur.execute(
                "DELETE FROM revela_places_fixtures "
                "WHERE createdAt < DATE_SUB(NOW(), INTERVAL %s DAY)",
                (older_than_days,),
            )
        removed = cur.rowcount or 0
        mysql.connection.commit()
    except Exception as exc:
        mysql.connection.rollback()
        return 0, f"Could not purge fixtures: {exc}"
    finally:
        cur.close()
    return removed, None


def resolve_request(kind, url, params=None, payload=None):
    """
    Decide whether a request should be replayed from cache.

    Returns (cached_response, None) on a hit, or (None, None) to proceed with a
    real, fully-accounted call. Raises TestModeCacheMiss when the operator asked
    for cached results only and nothing is stored.
    """
    if not is_enabled():
        return None, None
    config = get_config()
    key = fixture_key(kind, url, params=params, payload=payload)
    if not config["test_mode.fixture_storage_enabled"]:
        if config["test_mode.fixture_policy"] == "cache_only":
            raise TestModeCacheMiss(key, storage_disabled=True)
        return None, None
    try:
        _cleanup_expired_fixtures()
    except Exception as exc:
        print(f"[test_mode] fixture cleanup failed ({type(exc).__name__})")
    cached = lookup_fixture(key)
    if cached is not None:
        return FixtureResponse(cached), None
    if config["test_mode.fixture_policy"] == "cache_only":
        raise TestModeCacheMiss(key)
    return None, None


def remember_response(kind, url, params, payload, body):
    """Store a live response as a fixture while Test Mode is on."""
    if not is_enabled() or not get_config()["test_mode.fixture_storage_enabled"]:
        return False
    return store_fixture(
        fixture_key(kind, url, params=params, payload=payload), kind, body
    )
