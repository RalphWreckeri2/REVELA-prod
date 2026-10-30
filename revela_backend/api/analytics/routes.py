import json
import logging
import math
import re
import threading
import traceback
import os
import time
import hashlib
import numpy as np
from collections import Counter
from concurrent.futures import Future
from datetime import datetime, timezone
from flask import Blueprint, current_app, g, has_app_context, jsonify, request
from flask_jwt_extended import get_jwt_identity
from google import genai
from google.genai import types
from app import mysql
from api.middleware.decorators import jwt_required, admin_required
from api.analytics.service import get_wlc_config, update_wlc_config, reset_wlc_config
from api.analytics.sector_risk import (
    DEFAULT_SECTOR_RISK_POLICY,
    load_persisted_sector_risk_policy,
    load_sector_risk_policy_audit,
    save_persisted_sector_risk_policy,
    validate_sector_risk_categories,
)
from api.analytics.scoring import MODEL_VERSION, calculate_rankings, select_rankings
from api.analytics.non_registry import (
    non_registry_monitoring_sql, build_non_registry_monitoring,
    registry_linked_monitoring_sql, build_registry_linked_monitoring,
)
from api.flags.compliance import origin_source_sql, current_confirmation_rows, confirmation_summary
from api.flags.compliance import registry_link_sql
from api.models.detection_runs import (
    _is_missing_stop_metadata_column,
    get_recent_detection_runs,
)
from api.analytics.hotspots import (
    build_hotspot_population_sql,
    cache_hotspots,
    cluster_hotspot_rows,
    count_hotspot_dispositions,
    get_cached_hotspots,
    hotspot_cluster_memberships,
    hotspot_date_window,
    invalidate_hotspots_cache,
    load_barangay_polygons,
    read_hotspot_settings,
    resolve_hotspot_parameters,
)
from api.analytics.filters import (
    parse_analytics_filters,
    registry_sql,
    geo_sql,
    geo_on_extra,
    barangay_b_sql,
    inspection_sql,
    filters_without,
)

# ── Gemini Model Discovery Cache (30-day TTL) ───────────────────────────────
_CACHED_GEMINI_MODEL = "gemini-3.6-flash"
_LAST_MODEL_DISCOVERY_TIME = 0
_DISCOVERY_TTL_SECONDS = 30 * 24 * 3600  # 30 days
SECTOR_RISK_ASSISTANT_GUIDANCE = (
    "Matched PSIC categories use their sector-policy score; flagged entities "
    "without a matched sector use the unclassified fallback of 50; explicit "
    "barangay overrides take precedence. State current sector coverage using "
    "the WLC model's known and total sector entity counts when available. "
    "Sector policy scores are administrative priorities, not measured industry "
    "risk. Do not redistribute the default 68% Risk / 7% Sector / 25% "
    "Proximity weights when sector inputs are missing or constant."
)


def _get_candidate_gemini_models(client, force_refresh=False):
    global _CACHED_GEMINI_MODEL, _LAST_MODEL_DISCOVERY_TIME

    preferred_env = os.environ.get("GEMINI_MODEL")
    if preferred_env:
        return [preferred_env]

    now = time.time()
    # Fast path: use cached working model directly without API discovery latency
    if not force_refresh and _CACHED_GEMINI_MODEL and (now - _LAST_MODEL_DISCOVERY_TIME < _DISCOVERY_TTL_SECONDS):
        return [_CACHED_GEMINI_MODEL, "gemini-3.6-flash", "gemini-2.5-flash", "gemini-2.0-flash", "gemini-1.5-flash"]

    discovered = []
    try:
        for m in client.models.list():
            m_name = (m.name or "").replace("models/", "").strip()
            actions = getattr(m, "supported_actions", None) or []
            if "generateContent" in actions or not actions:
                if m_name and m_name not in discovered:
                    if "flash" in m_name:
                        discovered.insert(0, m_name)
                    elif "gemini" in m_name:
                        discovered.append(m_name)
        _LAST_MODEL_DISCOVERY_TIME = now
        print(
            f"[Gemini] Monthly model auto-discovery completed. Found: {discovered}")
    except Exception as e:
        print(f"[Gemini] Model auto-discovery note: {e}")

    candidates = discovered + [_CACHED_GEMINI_MODEL, "gemini-3.6-flash",
                               "gemini-2.5-flash", "gemini-2.0-flash", "gemini-1.5-flash"]
    return list(dict.fromkeys(candidates))


# ── Analytics Response Cache (60-second TTL) ─────────────────────────────────
# Caches the full _get_all_analytics_inner result keyed by filter hash.
# The Analytics page can opt into stale-while-revalidate; other callers still
# wait for a fresh snapshot. No separate rankings cache or SQL path is added.
_analytics_cache: dict = {}
# Section snapshots share the SAME pipeline/flight as /all. A cold descriptive
# read must not wait for DBSCAN, rankings, and operations to finish.
_ANALYTICS_SECTIONS = ("descriptive", "diagnostic", "prescriptive", "operations")
_ANALYTICS_READ_SECTIONS = ("summary",) + _ANALYTICS_SECTIONS
_analytics_sections: dict = {}
_analytics_failures: dict = {}
_ANALYTICS_CACHE_TTL = 60  # seconds
_ANALYTICS_MAX_STALE_AGE = 15 * 60  # hard limit measured from computed_at
_ANALYTICS_REFRESH_RETRY = 15
_analytics_cache_lock = threading.Lock()
# filter key -> (Future, invalidation generation)
_analytics_refreshes: dict = {}
_analytics_cache_generation = 0
_analytics_background_slot = threading.BoundedSemaphore(1)

# ── Cache/latency instrumentation ─────────────────────────────────────────────
# Misses/inflight count actual computations, not coalesced waiting requests.
_analytics_metrics = {"hits": 0, "misses": 0}
_analytics_inflight = 0
_analytics_metrics_lock = threading.Lock()
_analytics_log = logging.getLogger("revela.analytics")


# ── Pipeline phase instrumentation (measurement only) ────────────────────────
# Enabled with REVELA_ANALYTICS_PHASES=1. When off, the cursor proxy is never
# installed and the timing helpers skip the clock read entirely, so behavior
# and overhead are unchanged. phases_sum_ms counts ONLY exclusive,
# non-overlapping leaf spans
# (the timed SQL calls). Inclusive spans enclose other timed work and are logged
# for context but never summed, so nothing is double-counted.
#
# Each SQL span is named for the query it ran, not its position in the request:
#   kpi.*              headline counts (total/active/expired/... businesses)
#   descriptive.*      Tier 1 aggregates
#   diagnostic.*       Tier 2 aggregates, including DBSCAN and Moran's I
#   prescriptive.*     rankings and inspector count
#   operations.*       Tier 4 aggregates
#   schema:*           conditional schema probes run before the queries
# The same name appears on every request even when filters skip conditional
# queries and change the execution order.


def _phases_enabled():
    return os.getenv("REVELA_ANALYTICS_PHASES", "").strip().lower() in (
        "1", "true", "yes", "on")


def _telemetry_request_id():
    """Reuse the correlation id emitted by request_telemetry ([req] id=...)."""
    if has_app_context():
        return getattr(g, "_revela_id", None) or "-"
    return "-"


class _PhaseCollector:
    """Per-request span recorder for the analytics pipeline."""

    def __init__(self):
        self.exclusive = []   # (name, dur_ms) leaf spans, the only addends
        self.inclusive = []   # (name, dur_ms) parent spans, context only

    def add_exclusive(self, name, dur_ms):
        self.exclusive.append((name, dur_ms))

    def add_inclusive(self, name, dur_ms):
        self.inclusive.append((name, dur_ms))

    def exclusive_sum_ms(self):
        return sum(d for _, d in self.exclusive)


def _sql_fingerprint(sql):
    """Order-independent fallback name for SQL executed without a label.

    An explicit label is preferred everywhere in this pipeline. This exists so
    an unlabelled call still names the same query on every run instead of
    inheriting a position-dependent sql#N number.
    """
    normalized = " ".join(str(sql).split())
    return "sql:unlabeled.%s" % hashlib.sha256(
        normalized.encode("utf-8")).hexdigest()[:8]


class _TimedCursor:
    """Cursor proxy that times each execute() as an exclusive, named leaf span.

    Every other attribute is forwarded to the wrapped cursor unchanged, so the
    pipeline behaves exactly as before. SQL run through a cursor the pipeline
    does not own (e.g. get_recent_detection_runs) intentionally bypasses this
    proxy and is captured only as an inclusive span.
    """

    def __init__(self, cursor, collector, label=None):
        self._cursor = cursor
        self._collector = collector
        self._label = label

    def labeled(self, label):
        """Return a proxy that names the SQL its wrapped helpers execute."""
        return _TimedCursor(self._cursor, self._collector, label=label)

    def execute(self, *args, label=None, **kwargs):
        t0 = time.perf_counter()
        try:
            return self._cursor.execute(*args, **kwargs)
        finally:
            self._collector.add_exclusive(
                label or self._label or _sql_fingerprint(
                    args[0] if args else ""),
                (time.perf_counter() - t0) * 1000.0,
            )

    def __getattr__(self, name):
        return getattr(self._cursor, name)


_NO_PARAMS = object()


def _execute(cursor, label, sql, params=_NO_PARAMS):
    """Run SQL, naming its phase span when timing is active.

    When the REVELA_ANALYTICS_PHASES gate is off, ``cursor`` is the raw DB
    cursor and the label is simply ignored, so the disabled path is unchanged.
    """
    if isinstance(cursor, _TimedCursor):
        if params is _NO_PARAMS:
            return cursor.execute(sql, label=label)
        return cursor.execute(sql, params, label=label)
    if params is _NO_PARAMS:
        return cursor.execute(sql)
    return cursor.execute(sql, params)


def _labeled(cursor, label):
    """Name the SQL a shared helper (schema probes) executes on this cursor."""
    if isinstance(cursor, _TimedCursor):
        return cursor.labeled(label)
    return cursor


def _phase_start(collector):
    """Return a start timestamp, or None when the collector is inactive.

    Returning None when the gate is off means the disabled path performs no
    clock read at all, so an off gate is exactly zero-overhead rather than
    merely log-free.
    """
    if collector is None:
        return None
    return time.perf_counter()


def _record_inclusive(collector, name, t0):
    if collector is None or t0 is None:
        return
    collector.add_inclusive(name, (time.perf_counter() - t0) * 1000.0)


def _log_analytics_phases(collector, wall_ms, key):
    """Emit the phase summary. Called from a finally, so it survives failures."""
    if collector is None:
        return
    total = collector.exclusive_sum_ms()
    coverage = (total / wall_ms) if wall_ms else 0.0
    _analytics_log.info(
        "[analytics-phases] req_id=%s key=%s phases_sum_ms=%.1f wall_ms=%.1f "
        "coverage=%.3f exclusive=%s",
        _telemetry_request_id(),
        key[:8],
        total,
        wall_ms,
        coverage,
        ",".join("%s=%.1f" % (n, d) for n, d in collector.exclusive) or "-",
    )
    if collector.inclusive:
        _analytics_log.info(
            "[analytics-phases] req_id=%s key=%s inclusive=%s",
            _telemetry_request_id(),
            key[:8],
            ",".join("%s=%.1f" % (n, d) for n, d in collector.inclusive),
        )


def _log_analytics_cache(state, inflight, inner_ms, key):
    """Emit one cache decision line. Only a key prefix is logged, never filters."""
    with _analytics_metrics_lock:
        hits = _analytics_metrics["hits"]
        misses = _analytics_metrics["misses"]
    _analytics_log.info(
        "[analytics-cache] req_id=%s state=%s inflight=%d inner_ms=%.1f key=%s hits=%d misses=%d",
        _telemetry_request_id(),
        state,
        inflight,
        inner_ms,
        key[:8],
        hits,
        misses,
    )


def _analytics_cache_key(F: dict) -> str:
    """Stable MD5 key derived from the analytics filter dict."""
    return hashlib.md5(
        json.dumps(F, sort_keys=True, default=str).encode()
    ).hexdigest()


def invalidate_analytics_cache():
    """Clear the full analytics cache (call after data-mutating operations)."""
    global _analytics_cache_generation
    with _analytics_cache_lock:
        _analytics_cache.clear()
        _analytics_sections.clear()
        _analytics_failures.clear()
        _analytics_cache_generation += 1
        # Reserve active flights until their queries finish, but do not publish
        # or satisfy fresh reads from a result computed before invalidation.
    invalidate_hotspots_cache()


def init_analytics_cache_invalidation(app):
    """Invalidate once after a data-writing HTTP operation, including quota pauses."""
    @app.after_request
    def invalidate_after_write(response):
        if request.method not in ("POST", "PUT", "PATCH", "DELETE"):
            return response
        if not (200 <= response.status_code < 300 or response.status_code == 429):
            return response
        blueprint = request.blueprint
        if blueprint == "analytics":
            changes_data = request.path in (
                "/api/analytics/wlc-config",
                "/api/analytics/wlc-config/reset",
                "/api/analytics/sector-policy",
                "/api/analytics/sector-policy/reset",
            )
        else:
            changes_data = blueprint in ("registry", "flags", "inspections", "users")
            if request.path in (
                "/api/flags/location-search", "/api/flags/reverse-geocode",
                "/api/flags/cancel-detection", "/api/registry/cancel", "/api/registry/reset-quota",
            ):
                changes_data = False
        if changes_data:
            invalidate_analytics_cache()
        return response


def _analytics_section_payload(data, section):
    # Summary is a projection of the SAME KPI work, never a second SQL path.
    if section == "summary":
        kpis = data.get("descriptive", {}).get("kpis")
        return {"kpis": kpis} if kpis is not None else None
    return data.get(section)


def _finish_analytics_refresh(key, flight, entry=None, error=None):
    future, generation = flight
    with _analytics_cache_lock:
        if generation == _analytics_cache_generation:
            if error is None and entry["status_code"] == 200:
                _analytics_cache[key] = entry
                _analytics_failures.pop(key, None)
                # Also supports callers/tests that supply a complete snapshot
                # without the pipeline's intermediate publication hooks.
                sections = _analytics_sections.setdefault(key, {})
                for section in _ANALYTICS_READ_SECTIONS:
                    payload = _analytics_section_payload(entry["data"], section)
                    if payload is not None:
                        published = sections.get(section, {})
                        sections[section] = {
                            **entry, "data": {section: payload},
                            **({"computed_at": published["computed_at"]}
                               if published.get("flight") is flight else {}),
                        }
            elif key in _analytics_cache:
                _analytics_cache[key] = {
                    **_analytics_cache[key],
                    "refresh_failed": True,
                    "retry_after": time.time() + _ANALYTICS_REFRESH_RETRY,
                }
            if error is not None or (entry and entry["status_code"] != 200):
                _analytics_failures[key] = time.time() + _ANALYTICS_REFRESH_RETRY
                for section_entry in _analytics_sections.get(key, {}).values():
                    section_entry["refresh_failed"] = True
        if _analytics_refreshes.get(key) is flight:
            del _analytics_refreshes[key]
    if error is None:
        future.set_result(entry)
    else:
        future.set_exception(error)


def _compute_analytics_snapshot(F, key, flight):
    """Run the unchanged pipeline once, with a thread-local app context/cursor."""
    global _analytics_inflight
    collector = _PhaseCollector() if _phases_enabled() else None
    g._analytics_phases = collector
    g._analytics_section_context = (key, flight[1])
    with _analytics_metrics_lock:
        _analytics_metrics["misses"] += 1
        _analytics_inflight += 1
        inflight = _analytics_inflight
    started = time.perf_counter()
    g._analytics_section_started = started
    entry = error = None
    try:
        data, status_code = _get_all_analytics_inner(F)
        entry = {"data": dict(
            data), "status_code": status_code, "ts": time.time()}
    except Exception as exc:
        error = exc
        _analytics_log.exception("Analytics refresh failed key=%s", key[:8])
    finally:
        g.pop("_analytics_section_context", None)
        elapsed = (time.perf_counter() - started) * 1000.0
        with _analytics_metrics_lock:
            _analytics_inflight -= 1
        try:
            _log_analytics_phases(collector, elapsed, key)
            _log_analytics_cache("refresh", inflight, elapsed, key)
        finally:
            _finish_analytics_refresh(key, flight, entry, error)


def _publish_analytics_section(section, data):
    """Publish finished work only; never expose a half-built/mutating payload."""
    context = getattr(g, "_analytics_section_context", None) if has_app_context() else None
    if context is None:
        return
    key, generation = context
    computed_at = time.time()
    with _analytics_cache_lock:
        if generation != _analytics_cache_generation:
            return
        _analytics_sections.setdefault(key, {})[section] = {
            "data": {section: data}, "status_code": 200, "ts": computed_at,
            "computed_at": datetime.fromtimestamp(computed_at, timezone.utc).isoformat(),
            "flight": _analytics_refreshes.get(key),
        }
    _analytics_log.info(
        "[analytics-section] key=%s section=%s ready_ms=%.1f", key[:8], section,
        (time.perf_counter() - getattr(g, "_analytics_section_started", time.perf_counter())) * 1000,
    )


def _get_analytics_section(F, section):
    """Nonblocking section read, coalesced with startup warming and /all reads."""
    key = _analytics_cache_key(F)
    background = deferred = False
    with _analytics_cache_lock:
        full = _analytics_cache.get(key)
        entry = _analytics_sections.get(key, {}).get(section)
        if entry is None and full:
            payload = _analytics_section_payload(full["data"], section)
            if payload is not None:
                entry = {**full, "data": {section: payload}}
        fresh = entry and not _analytics_snapshot_metadata(entry)["stale"]
        flight = _analytics_refreshes.get(key)
        retry_after = _analytics_failures.get(key, 0)
        if not fresh and flight is None and time.time() >= retry_after:
            background = _analytics_background_slot.acquire(blocking=False)
            deferred = not background
            if background:
                flight = (Future(), _analytics_cache_generation)
                _analytics_refreshes[key] = flight
    if background:
        _start_analytics_background_refresh(
            current_app._get_current_object(), F, key, flight)
    if entry:
        data, status = _analytics_snapshot_data(entry, key, deferred, prefer_full=False)
        # _analytics_snapshot_data normally prefers the latest complete cache.
        # A section read still returns only the requested tier.
        return {k: v for k, v in data.items()
                if k in (section, "analytics_cache", "error")}, status
    failed = time.time() < _analytics_failures.get(key, 0)
    return {
        **({"error": "Analytics refresh failed. Please retry."} if failed else {}),
        "analytics_cache": {
            "loading": not failed, "refreshing": bool(flight) and not failed,
            "refresh_deferred": deferred, "refresh_failed": failed,
            "retry_after_seconds": _ANALYTICS_REFRESH_RETRY if failed else 1,
        },
    }, 503 if failed else 202


def _background_analytics_refresh(app, F, key, flight):
    try:
        # flask_mysqldb creates/closes a separate connection for this context.
        # Never copy the request/JWT context, g, or an existing cursor.
        with app.app_context():
            _compute_analytics_snapshot(F, key, flight)
    except Exception as exc:
        _analytics_log.exception(
            "Analytics background refresh failed key=%s", key[:8])
        if not flight[0].done():
            _finish_analytics_refresh(key, flight, error=exc)
    finally:
        _analytics_background_slot.release()


def _start_analytics_background_refresh(app, F, key, flight):
    """Shared launcher for startup warming and request-driven revalidation."""
    try:
        threading.Thread(
            target=_background_analytics_refresh,
            args=(app, dict(F), key, flight),
            daemon=True,
        ).start()
    except Exception as exc:
        _analytics_log.exception(
            "Could not start Analytics refresh key=%s", key[:8])
        _finish_analytics_refresh(key, flight, error=exc)
        _analytics_background_slot.release()
        return False
    return True


def start_analytics_cache_warmup(app):
    """Best-effort, nonblocking default snapshot warm-up, once per active flight.

    Parse the empty filters just like /all: hashing {} directly would use a
    different key. Reserve the same flight/slot as page requests before starting
    a thread, so either startup or an early request owns the computation, never
    both. Existing valid snapshots stay available while a refresh runs.
    """
    F = parse_analytics_filters({})
    key = _analytics_cache_key(F)
    with _analytics_cache_lock:
        if key in _analytics_refreshes:
            return False
        cached = _analytics_cache.get(key)
        if cached:
            if ((time.time() - cached["ts"]) < _ANALYTICS_CACHE_TTL
                    and not _analytics_snapshot_metadata(cached)["expired"]):
                return False
            if time.time() < cached.get("retry_after", 0):
                return False
        if not _analytics_background_slot.acquire(blocking=False):
            return False
        flight = (Future(), _analytics_cache_generation)
        _analytics_refreshes[key] = flight
    return _start_analytics_background_refresh(app, F, key, flight)


def _analytics_snapshot_metadata(entry):
    computed_at = entry.get("computed_at") or entry["data"].get(
        "prescriptive", {}).get("rankings_computed_at")
    if not computed_at:
        computed_at = datetime.fromtimestamp(
            entry["ts"], timezone.utc).isoformat()
    try:
        computed = datetime.fromisoformat(computed_at)
        age = time.time() - computed.timestamp() if computed.tzinfo else None
        # datetime rounds the cache's float timestamp to microseconds. On
        # coarse-resolution clocks an immediate read can therefore appear a
        # fraction of a microsecond in the future, not an invalid snapshot.
        if age is not None and -0.001 < age < 0:
            age = 0
    except (TypeError, ValueError, OverflowError):
        age = None
    expired = age is None or age < 0 or age > _ANALYTICS_MAX_STALE_AGE
    return {
        "computed_at": computed_at,
        "age_seconds": age,
        "max_stale_seconds": _ANALYTICS_MAX_STALE_AGE,
        "expired": expired,
        "stale": expired or (time.time() - entry["ts"]) >= _ANALYTICS_CACHE_TTL,
    }


def _analytics_snapshot_data(entry, key, deferred=False, *, prefer_full=True):
    with _analytics_cache_lock:
        latest = _analytics_cache.get(key)
        if prefer_full and entry["status_code"] == 200 and latest and latest["ts"] >= entry["ts"]:
            entry = latest
        refreshing = key in _analytics_refreshes
    data = dict(entry["data"])
    if entry["status_code"] != 200:
        return data, entry["status_code"]
    metadata = _analytics_snapshot_metadata(entry)
    metadata.update({
        "refreshing": metadata["stale"] and refreshing,
        "refresh_deferred": metadata["stale"] and deferred,
        "refresh_failed": metadata["stale"] and not refreshing and entry.get("refresh_failed", False),
        "retry_after_seconds": max(1, math.ceil(
            entry.get("retry_after", _analytics_failures.get(key, 0)) - time.time())),
    })
    if metadata["expired"]:
        # Keep the timestamp/status, not the expired rankings, charts or KPIs.
        return {
            "error": "Analytics snapshot is expired or its computation time cannot be verified. "
                     "Rankings older than 15 minutes are hidden until refreshed.",
            "analytics_cache": metadata,
        }, 503
    data["analytics_cache"] = metadata
    return data, 200


def _get_cached_analytics(F, *, allow_stale=False):
    """Existing process-local cache with per-filter single-flight and age cap."""
    key = _analytics_cache_key(F)
    while True:
        owner = deferred = background = False
        with _analytics_cache_lock:
            cached = _analytics_cache.get(key)
            fresh = (cached and (time.time() - cached["ts"]) < _ANALYTICS_CACHE_TTL
                     and not _analytics_snapshot_metadata(cached)["expired"])
            flight = _analytics_refreshes.get(key)
            if not fresh and flight is None:
                if cached and allow_stale:
                    if time.time() >= cached.get("retry_after", 0):
                        background = _analytics_background_slot.acquire(
                            blocking=False)
                        deferred = not background
                        owner = background
                else:
                    owner = True
                if owner:
                    flight = (Future(), _analytics_cache_generation)
                    _analytics_refreshes[key] = flight
        if fresh or (cached and allow_stale):
            if background:
                _start_analytics_background_refresh(
                    current_app._get_current_object(), F, key, flight)
            with _analytics_metrics_lock:
                _analytics_metrics["hits"] += 1
            _log_analytics_cache("hit" if fresh else "stale", 0, 0.0, key)
            return _analytics_snapshot_data(cached, key, deferred)
        if owner:
            _compute_analytics_snapshot(F, key, flight)
        entry = flight[0].result()
        with _analytics_cache_lock:
            if flight[1] != _analytics_cache_generation:
                continue
        return _analytics_snapshot_data(entry, key)


def _registry_has_registration_type(cursor):
    cursor.execute(
        """
        SELECT COUNT(*) AS column_count
        FROM information_schema.COLUMNS
        WHERE TABLE_SCHEMA = DATABASE()
          AND TABLE_NAME = 'official_registry'
          AND COLUMN_NAME = 'registrationType'
        """
    )
    row = cursor.fetchone()
    return bool(row and row["column_count"])


# The derived-colour SQL builders now live in api/registry/colors.py so that
# api/registry/service.py can reuse the exact expression the Map reports
# without importing this blueprint (google-genai / scikit-learn). They are
# re-exported here under their original names, so every existing caller below
# and tests/test_analytics_registry_compat.py are unaffected.
from api.registry.colors import (  # noqa: E402,F401
    FIRST_WARNING_LEVEL,
    _color_case_sql,
    _effective_flag_color_sql,
    _pin_state_column_sql,
    registry_row_color_sql,
    _registry_column_sql,
    _verified_orange_sql,
    ladder_columns_available,
)


analytics_bp = Blueprint("analytics", __name__)


@analytics_bp.route("/all", methods=["GET"])
@jwt_required()
def get_all_analytics():
    try:
        F = parse_analytics_filters(request.args)
        section = request.args.get("section")
        if section:
            if section not in _ANALYTICS_READ_SECTIONS:
                return jsonify({"error": "Unknown analytics section."}), 400
            data, status_code = _get_analytics_section(F, section)
            if section == "summary" and status_code == 200:
                # Unread rollover state belongs to this user, outside the cache.
                data["summary"] = {**data["summary"], "new_year_rollover": _new_year_rollover_info()}
            return jsonify(data), status_code
        data, status_code = _get_cached_analytics(
            F, allow_stale=request.args.get("stale_while_revalidate") == "1")

        data["new_year_rollover"] = _new_year_rollover_info()
        return jsonify(data), status_code
    except Exception:
        current_app.logger.exception("Failed to load analytics")
        return jsonify({"error": "Failed to load analytics"}), 500


@analytics_bp.route("/hotspots", methods=["GET"])
@jwt_required()
def get_analytics_hotspots():
    """Return date-scoped groups of eligible effective-Red detection pins."""
    date_preset = (request.args.get("date_preset") or "all").strip().lower()
    try:
        start, end = hotspot_date_window(date_preset)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400

    cursor = mysql.connection.cursor()
    try:
        settings = read_hotspot_settings(cursor)
        parameters, fallbacks = resolve_hotspot_parameters(settings)
        date_key = (
            start.isoformat() if start else None,
            end.isoformat() if end else None,
        )
        cache_key = (
            date_preset, date_key, parameters["eps_m"],
            parameters["min_samples"], tuple(sorted(fallbacks.items())),
        )
        cached = get_cached_hotspots(cache_key)
        if cached is not None:
            return jsonify(cached), 200

        ladder = ladder_columns_available(cursor)
        effective_flag = _effective_flag_color_sql("g", ladder=ladder)
        population_sql, population_params = build_hotspot_population_sql(
            effective_flag,
            registry_link_sql("g"),
            start,
            end,
        )
        cursor.execute(population_sql, population_params)
        population_rows = list(cursor.fetchall() or [])

        cursor.execute(
            "SELECT barangayID, barangayName FROM barangays ORDER BY barangayID"
        )
        barangay_rows = list(cursor.fetchall() or [])
        try:
            cursor.execute(
                "SELECT startedAt, status, stopReason FROM detection_runs "
                "ORDER BY startedAt DESC, runID DESC LIMIT 1"
            )
        except Exception as error:
            if not _is_missing_stop_metadata_column(error):
                raise
            cursor.execute(
                "SELECT startedAt, status FROM detection_runs "
                "ORDER BY startedAt DESC, runID DESC LIMIT 1"
            )
            latest_run = cursor.fetchone()
            if latest_run:
                latest_run["stopReason"] = None
        else:
            latest_run = cursor.fetchone()
    except Exception:
        current_app.logger.exception("Failed to load analytics hotspots")
        return jsonify({"error": "Failed to load analytics hotspots"}), 500
    finally:
        cursor.close()

    try:
        clusters, totals = cluster_hotspot_rows(
            population_rows,
            parameters,
            load_barangay_polygons(barangay_rows),
        )
        latest_run_date = latest_run["startedAt"] if latest_run else None
        if hasattr(latest_run_date, "strftime"):
            latest_run_date = latest_run_date.strftime("%Y-%m-%dT%H:%M:%SZ")
        date_window = {
            "start": start.isoformat() if start else None,
            "end": end.isoformat() if end else None,
        }
        response = {
            "date_preset": date_preset,
            "date_window": date_window,
            "parameters_used": parameters,
            "parameter_fallbacks": fallbacks,
            "population": count_hotspot_dispositions(population_rows),
            "clusters": clusters,
            "totals": {
                **totals,
                "cluster_count": len(clusters),
            },
            "last_detection_run": ({
                "date": latest_run_date,
                "status": latest_run["status"],
                "stop_reason": latest_run.get("stopReason"),
            } if latest_run else None),
        }
    except Exception:
        current_app.logger.exception("Failed to aggregate analytics hotspots")
        return jsonify({"error": "Failed to aggregate analytics hotspots"}), 500
    cache_hotspots(cache_key, response)
    return jsonify(response), 200


def _barangay_overview_label(value, max_length=32):
    label = " ".join(str(value or "Unknown").strip().split()).title()
    if len(label) <= max_length:
        return label
    return label[:max_length - 1].rstrip() + "…"


def _barangay_overview_dimension(rows, limit=None):
    counts = {}
    for row in rows:
        label = _barangay_overview_label(row["category"])
        counts[label] = counts.get(label, 0) + int(row["count"] or 0)

    ordered = sorted(counts.items(), key=lambda item: (-item[1], item[0].casefold()))
    if limit is not None and len(ordered) > limit:
        kept = ordered[:limit]
        kept.append(("Others", sum(count for _, count in ordered[limit:])))
        ordered = kept

    return [
        {
            "value": label,
            "label": label,
            "short_label": (
                "Others" if label == "Others"
                else _barangay_overview_label(label)
            ),
            "count": count,
        }
        for label, count in ordered
    ]


@analytics_bp.route("/barangay-overview", methods=["GET"])
@jwt_required()
def get_barangay_overview():
    """Return all barangay map aggregates without running the full analytics pipeline."""
    cursor = mysql.connection.cursor()
    try:
        filters = parse_analytics_filters(request.args)
        filters["display_sector"] = (
            str(request.args.get("display_sector") or "").strip() or None
        )
        filters["barangay_ids"] = None
        filters["registration_type_supported"] = True
        registry_where, registry_params = registry_sql("o", filters)
        line_of_business_key = (
            str(request.args.get("line_of_business_key") or "").strip() or None
        )
        line_of_business_filter = ""
        line_of_business_params = []
        if line_of_business_key:
            registry_line_expression = (
                "CONVERT(LOWER(REGEXP_REPLACE(COALESCE(o.lineOfBusiness, ''), "
                "'[^A-Za-z0-9]', '')) USING utf8mb4) "
                "COLLATE utf8mb4_unicode_ci"
            )
            line_of_business_filter = f"""
                AND EXISTS (
                    SELECT 1
                    FROM registry_sector_map lob_map
                    JOIN psic_active_version active_version
                      ON active_version.singleton_id = 1
                     AND lob_map.source_version = active_version.source_version
                    JOIN psic_lines primary_line
                      ON primary_line.psic_line_id = lob_map.primary_psic_line_id
                     AND primary_line.source_version = active_version.source_version
                    WHERE lob_map.normalized_line_of_business =
                          {registry_line_expression}
                      AND lob_map.match_status IN ('matched', 'combo')
                      AND CONVERT(
                              primary_line.normalized_line_of_business
                              USING utf8mb4
                          ) COLLATE utf8mb4_unicode_ci =
                          CONVERT(%s USING utf8mb4) COLLATE utf8mb4_unicode_ci
                )
            """
            line_of_business_params.append(line_of_business_key)
        registry_where += line_of_business_filter
        registry_params = registry_params + line_of_business_params
        ladder = ladder_columns_available(cursor)
        geo_where, geo_params = geo_sql("g", filters, ladder=ladder)
        inspection_where, inspection_params = inspection_sql("ir", filters)

        cursor.execute(
            "SELECT barangayID, barangayName FROM barangays ORDER BY barangayID"
        )
        barangay_rows = cursor.fetchall()
        barangays = {
            int(row["barangayID"]): {
                "barangayID": int(row["barangayID"]),
                "barangayName": row["barangayName"],
                "registry_total": 0,
                "registry": {
                    "business_size": [],
                    "business_type": [],
                    "registration_type": [],
                    "display_sector": [],
                },
                "pins": {
                    "registered_on_map": 0,
                    "detected_not_in_registry": 0,
                    "detection_with_business_id": 0,
                    "added_by_inspector": 0,
                    "other_source": 0,
                    "total": 0,
                },
                "pins_without_location": 0,
                "inspections": {
                    "pending": 0,
                    "waiting_for_review": 0,
                    "verified": 0,
                    "total": 0,
                    "outcomes": {"Green": 0, "Yellow": 0, "Red": 0},
                },
            }
            for row in barangay_rows
        }

        cursor.execute(
            "SELECT COUNT(*) AS total FROM official_registry o WHERE 1=1"
            + registry_where,
            registry_params,
        )
        registry_total = int(cursor.fetchone()["total"] or 0)
        cursor.execute(
            """
            SELECT o.barangayID, COUNT(*) AS total
            FROM official_registry o
            WHERE 1=1
            """ + registry_where + """
            GROUP BY o.barangayID
            """,
            registry_params,
        )
        registry_totals_by_barangay = cursor.fetchall()
        for row in registry_totals_by_barangay:
            barangay = barangays.get(row["barangayID"])
            if barangay:
                barangay["registry_total"] = int(row["total"] or 0)

        dimension_columns = (
            ("business_size", "businessSize", None),
            ("business_type", "businessType", None),
            ("registration_type", "registrationType", None),
        )
        overall_registry_dimensions = {}
        for response_key, column, limit in dimension_columns:
            cursor.execute(
                f"""
                SELECT o.barangayID,
                       COALESCE(NULLIF(TRIM(o.{column}), ''), 'Unknown') AS category,
                       COUNT(*) AS count
                FROM official_registry o
                WHERE 1=1 {registry_where}
                GROUP BY o.barangayID, category
                """,
                registry_params,
            )
            dimension_rows = cursor.fetchall()
            overall_registry_dimensions[response_key] = _barangay_overview_dimension(
                dimension_rows, limit=limit
            )
            rows_by_barangay = {}
            for row in dimension_rows:
                rows_by_barangay.setdefault(row["barangayID"], []).append(row)
            for barangay_id, barangay in barangays.items():
                barangay["registry"][response_key] = _barangay_overview_dimension(
                    rows_by_barangay.get(barangay_id, []), limit=limit
                )

        cursor.execute(
            """SELECT display_sector_key,
                      MIN(display_sector_label) AS display_sector_label,
                      MIN(sort_order) AS sort_order
               FROM display_sector
               WHERE is_active = 1 AND display_sector_key IS NOT NULL
                 AND display_sector_label IS NOT NULL
               GROUP BY display_sector_key
               ORDER BY MIN(sort_order), MIN(display_sector_label)"""
        )
        display_sector_options = [
            {
                "value": row["display_sector_key"],
                "label": row["display_sector_label"],
            }
            for row in cursor.fetchall()
        ]
        cursor.execute(
            f"""
            SELECT primary_line.normalized_line_of_business AS value,
                   MIN(primary_line.line_of_business) AS description,
                   sector_map.display_sector_key AS sector_key,
                   COUNT(*) AS count
            FROM official_registry o
            JOIN registry_sector_map sector_map
              ON sector_map.normalized_line_of_business =
                 CONVERT(
                     LOWER(REGEXP_REPLACE(COALESCE(o.lineOfBusiness, ''), '[^A-Za-z0-9]', ''))
                     USING utf8mb4
                 ) COLLATE utf8mb4_unicode_ci
             AND sector_map.match_status IN ('matched', 'combo')
            JOIN psic_active_version active_version
              ON active_version.singleton_id = 1
             AND sector_map.source_version = active_version.source_version
            JOIN psic_lines primary_line
              ON primary_line.psic_line_id = sector_map.primary_psic_line_id
             AND primary_line.source_version = active_version.source_version
            WHERE 1=1 {registry_sql("o", filters)[0]}
            GROUP BY primary_line.normalized_line_of_business,
                     sector_map.display_sector_key
            ORDER BY sector_map.display_sector_key,
                     MIN(primary_line.line_of_business)
            """,
            registry_sql("o", filters)[1],
        )
        line_of_business_options = [
            {
                "value": row["value"],
                "label": (
                    f"{str(row['description'] or row['value']).strip().title()} "
                    f"({int(row['count'] or 0):,})"
                ),
                "sector_key": row["sector_key"],
                "count": int(row["count"] or 0),
            }
            for row in cursor.fetchall()
        ]
        cursor.execute(
            f"""
            SELECT o.barangayID,
                   COALESCE(rsm.display_sector_key, 'unmapped') AS category,
                   COALESCE(rsm.display_sector_label, 'Needs classification') AS label,
                   COUNT(*) AS count
            FROM official_registry o
            LEFT JOIN registry_sector_map rsm
              ON rsm.normalized_line_of_business =
                 CONVERT(
                     LOWER(REGEXP_REPLACE(COALESCE(o.lineOfBusiness, ''), '[^A-Za-z0-9]', ''))
                     USING utf8mb4
                 ) COLLATE utf8mb4_unicode_ci
             AND rsm.match_status IN ('matched', 'combo')
            WHERE 1=1 {registry_where}
            GROUP BY o.barangayID, category, label
            """,
            registry_params,
        )
        sector_rows = cursor.fetchall()
        sectors_by_barangay = {}
        overall_sector_counts = {}
        sector_labels = {}
        for row in sector_rows:
            key = row["category"]
            count = int(row["count"] or 0)
            sector_labels[key] = row["label"]
            overall_sector_counts[key] = overall_sector_counts.get(key, 0) + count
            sectors_by_barangay.setdefault(row["barangayID"], {})[key] = (
                sectors_by_barangay.get(row["barangayID"], {}).get(key, 0) + count
            )

        def sector_breakdown(counts):
            ordered = sorted(
                counts.items(),
                key=lambda item: (-item[1], sector_labels[item[0]].casefold()),
            )
            return [
                {
                    "value": key,
                    "label": sector_labels[key],
                    "short_label": sector_labels[key],
                    "count": count,
                }
                for key, count in ordered
            ]

        overall_registry_dimensions["display_sector"] = sector_breakdown(
            overall_sector_counts
        )
        for barangay_id, barangay in barangays.items():
            barangay["registry"]["display_sector"] = sector_breakdown(
                sectors_by_barangay.get(barangay_id, {})
            )

        cursor.execute(
            f"""
            SELECT g.barangayID,
                   COUNT(g.logID) AS total,
                   SUM(CASE WHEN g.source IN ('registry', 'registry_detected')
                            THEN 1 ELSE 0 END) AS registered_on_map,
                   SUM(CASE WHEN g.source = 'detection' AND g.businessID IS NULL
                            THEN 1 ELSE 0 END) AS detected_not_in_registry,
                   SUM(CASE WHEN g.source = 'detection' AND g.businessID IS NOT NULL
                            THEN 1 ELSE 0 END) AS detection_with_business_id,
                   SUM(CASE WHEN g.source = 'manual'
                            THEN 1 ELSE 0 END) AS added_by_inspector,
                   SUM(CASE WHEN g.source IS NULL
                                 OR g.source NOT IN
                                    ('registry', 'registry_detected', 'detection', 'manual')
                            THEN 1 ELSE 0 END) AS other_source,
                   SUM(CASE WHEN g.latitude IS NULL OR g.longitude IS NULL
                            THEN 1 ELSE 0 END) AS pins_without_location
            FROM geospatial_logs g
            WHERE 1=1 {geo_where}
            GROUP BY g.barangayID
            """,
            geo_params,
        )
        pin_rows = cursor.fetchall()
        overall_pin_counts = {
            key: 0
            for key in (
                "registered_on_map",
                "detected_not_in_registry",
                "detection_with_business_id",
                "added_by_inspector",
                "other_source",
                "total",
                "pins_without_location",
            )
        }
        for row in pin_rows:
            for key in overall_pin_counts:
                overall_pin_counts[key] += int(row[key] or 0)
            barangay = barangays.get(row["barangayID"])
            if not barangay:
                continue
            for key in (
                "registered_on_map",
                "detected_not_in_registry",
                "detection_with_business_id",
                "added_by_inspector",
                "other_source",
                "total",
            ):
                barangay["pins"][key] = int(row[key] or 0)
            barangay["pins_without_location"] = int(
                row["pins_without_location"] or 0
            )

        cursor.execute(
            f"""
            SELECT g.barangayID,
                   COUNT(DISTINCT CASE
                       WHEN ir.verificationStatus IN
                            ('Assigned', 'Reassigned', 'In Progress')
                         OR COALESCE(NULLIF(TRIM(ir.verificationStatus), ''),
                                     'Unassigned')
                            NOT IN ('Assigned', 'Reassigned', 'In Progress',
                                    'Submitted', 'Verified')
                       THEN ir.reportID END) AS pending,
                   COUNT(DISTINCT CASE
                       WHEN ir.verificationStatus = 'Submitted'
                       THEN ir.reportID END) AS waiting_for_review,
                   COUNT(DISTINCT CASE
                       WHEN ir.verificationStatus = 'Verified'
                       THEN ir.reportID END) AS verified,
                   COUNT(DISTINCT ir.reportID) AS total,
                   COUNT(DISTINCT CASE
                       WHEN ir.verificationStatus = 'Verified'
                        AND ir.inspectionResult = 'Green'
                       THEN ir.reportID END) AS outcome_green,
                   COUNT(DISTINCT CASE
                       WHEN ir.verificationStatus = 'Verified'
                        AND ir.inspectionResult = 'Yellow'
                       THEN ir.reportID END) AS outcome_yellow,
                   COUNT(DISTINCT CASE
                       WHEN ir.verificationStatus = 'Verified'
                        AND ir.inspectionResult = 'Red'
                       THEN ir.reportID END) AS outcome_red
            FROM inspection_reports ir
            JOIN geospatial_logs g ON ir.targetID = g.logID
            WHERE 1=1 {geo_where} {inspection_where}
            GROUP BY g.barangayID
            """,
            geo_params + inspection_params,
        )
        inspection_rows = cursor.fetchall()
        overall_inspection_counts = {
            key: 0
            for key in (
                "pending",
                "waiting_for_review",
                "verified",
                "total",
                "outcome_green",
                "outcome_yellow",
                "outcome_red",
            )
        }
        for row in inspection_rows:
            for key in overall_inspection_counts:
                overall_inspection_counts[key] += int(row[key] or 0)
            barangay = barangays.get(row["barangayID"])
            if not barangay:
                continue
            inspections = barangay["inspections"]
            inspections["pending"] = int(row["pending"] or 0)
            inspections["waiting_for_review"] = int(
                row["waiting_for_review"] or 0
            )
            inspections["verified"] = int(row["verified"] or 0)
            inspections["total"] = int(row["total"] or 0)
            inspections["outcomes"] = {
                "Green": int(row["outcome_green"] or 0),
                "Yellow": int(row["outcome_yellow"] or 0),
                "Red": int(row["outcome_red"] or 0),
            }

        rows = list(barangays.values())
        overall = {
            "barangayID": None,
            "barangayName": "All barangays",
            "registry_total": registry_total,
            "registry": overall_registry_dimensions,
            "pins": {
                key: overall_pin_counts[key]
                for key in (
                    "registered_on_map",
                    "detected_not_in_registry",
                    "detection_with_business_id",
                    "added_by_inspector",
                    "other_source",
                    "total",
                )
            },
            "pins_without_location": overall_pin_counts["pins_without_location"],
            "inspections": {
                key: overall_inspection_counts[key]
                for key in (
                    "pending",
                    "waiting_for_review",
                    "verified",
                    "total",
                )
            },
        }
        overall["inspections"]["outcomes"] = {
            "Green": overall_inspection_counts["outcome_green"],
            "Yellow": overall_inspection_counts["outcome_yellow"],
            "Red": overall_inspection_counts["outcome_red"],
        }
        overall["registry_unassigned"] = registry_total - sum(
            row["registry_total"] for row in rows
        )
        overall["pins_unassigned"] = overall_pin_counts["total"] - sum(
            row["pins"]["total"] for row in rows
        )
        overall["inspections_unassigned"] = overall_inspection_counts["total"] - sum(
            row["inspections"]["total"] for row in rows
        )
        return jsonify({
            "barangays": rows,
            "overall": overall,
            "display_sectors": display_sector_options,
            "line_of_business_options": line_of_business_options,
        }), 200
    except Exception:
        current_app.logger.exception("Failed to load barangay overview")
        return jsonify({"error": "Failed to load barangay overview"}), 500
    finally:
        cursor.close()


def _new_year_rollover_info():
    """Per-user unread notification; never stored in a shared snapshot."""
    uid = int(get_jwt_identity())
    cursor = mysql.connection.cursor()
    try:
        cursor.execute(
            """
            SELECT id, body FROM revela_notifications
            WHERE recipientUserId = %s AND type = 'new_year_rollover' AND readAt IS NULL
            ORDER BY id DESC LIMIT 1
            """,
            (uid,)
        )
        notif = cursor.fetchone()
    finally:
        cursor.close()
    if not notif:
        return None
    m = re.search(r"Welcome to (\d+)!.*?marked (\d+) active", notif["body"], re.DOTALL)
    return {
        "detected": True,
        "count": int(m.group(2)) if m else 0,
        "year": int(m.group(1)) if m else datetime.now().year,
        "notification_id": notif["id"],
    }


def _rankings_split_enabled():
    """Opt-in gate for the candidate split ranking aggregate (default off)."""
    return os.getenv("REVELA_ANALYTICS_RANKINGS_SPLIT", "").strip().lower() in (
        "1", "true", "yes", "on")


# The actionable-pin predicate, shared by the original ON clause and the split
# subquery so the two forms cannot drift.
_PIN_ACTIONABLE_SQL = (
    "(g.placeID IS NOT NULL OR g.reportedByUserID IS NOT NULL "
    "OR g.flagColor = 'Orange' "
    "OR EXISTS (SELECT 1 FROM inspection_reports ir WHERE ir.targetID = g.logID))"
)


def _no_open_inspection_sql(alias="g"):
    return f"""NOT EXISTS (
        SELECT 1 FROM inspection_reports pending
        WHERE pending.targetID = {alias}.logID
          AND pending.verificationStatus IN ('Assigned', 'Reassigned', 'In Progress')
    )"""


def _dispatchable_business_identity_sql(alias, color, no_open, registry_business_id=None):
    registry_business_id = registry_business_id or _registry_column_sql(alias, "businessID")
    return f"""CASE WHEN {color} IN ('Red', 'Yellow') AND {no_open} THEN
        COALESCE(
            CONCAT('business:', CAST(COALESCE({registry_business_id}, {alias}.businessID) AS CHAR)),
            CONCAT('place:', CAST({alias}.placeID AS CHAR)),
            CONCAT('log:', CAST({alias}.logID AS CHAR))
        )
    END"""


def _barangay_rankings_sql(effective_flag_color, geo_on_g, geo_on_g_p,
                            reg_o, reg_o_p, brgy_b, brgy_b_p):
    """Shipped form: aggregates over the geospatial x registry fan-out."""
    no_open = _no_open_inspection_sql()
    dispatchable_business = _dispatchable_business_identity_sql(
        "g", effective_flag_color, no_open)
    active_location = f"""{effective_flag_color} IN ('Red', 'Yellow') AND {no_open}
        AND g.latitude BETWEEN -90 AND 90 AND g.longitude BETWEEN -180 AND 180"""
    sql = f"""
        SELECT
            b.barangayID,
            b.barangayName,
            COUNT(DISTINCT CASE WHEN {effective_flag_color} IN ('Red', 'Yellow', 'Black') THEN g.logID END) AS flagged_count,
            COUNT(DISTINCT CASE WHEN {effective_flag_color} = 'Red'    THEN g.logID END) AS red_count,
            COUNT(DISTINCT CASE WHEN {effective_flag_color} = 'Yellow' THEN g.logID END) AS yellow_count,
            COUNT(DISTINCT CASE WHEN {effective_flag_color} = 'Black'  THEN g.logID END) AS black_count,
            COUNT(DISTINCT CASE WHEN {effective_flag_color} = 'Red' AND {no_open}
                  THEN g.logID END) AS dispatchable_red_count,
            COUNT(DISTINCT CASE WHEN {effective_flag_color} = 'Yellow' AND {no_open}
                  THEN g.logID END) AS dispatchable_yellow_count,
            COUNT(DISTINCT {dispatchable_business}) AS dispatchable_business_count,
            AVG(CASE WHEN {active_location} THEN g.latitude END)     AS avg_lat,
            AVG(CASE WHEN {active_location} THEN g.longitude END)    AS avg_lng,
            COUNT(DISTINCT CASE WHEN {effective_flag_color} = 'Red'
                AND {_registry_column_sql('g', 'businessID')} IS NULL THEN g.logID END) AS unregistered_candidate_count,
            COUNT(DISTINCT o.businessID)                             AS total_registered
        FROM barangays b
        LEFT JOIN geospatial_logs   g ON g.barangayID = b.barangayID
            AND {_PIN_ACTIONABLE_SQL}{geo_on_g}
        LEFT JOIN official_registry o ON o.barangayID = b.barangayID{reg_o}
        WHERE 1=1 {brgy_b}
        GROUP BY b.barangayID, b.barangayName
    """
    return sql, geo_on_g_p + reg_o_p + brgy_b_p


def _barangay_rankings_sql_split(effective_flag_color, geo_on_g, geo_on_g_p,
                                 reg_o, reg_o_p, brgy_b, brgy_b_p):
    """Candidate: aggregate geospatial and registry per barangay, then join.

    STATUS: candidate only, DEFAULT-OFF and runtime-UNVERIFIED.  Reachable only
    when REVELA_ANALYTICS_RANKINGS_SPLIT is set (see _rankings_split_enabled);
    the shipped path stays _barangay_rankings_sql.  Value parity passes on the
    SQLite harness.  The previously reviewed EXPLAIN, and the checked-in
    scripts/explain_rankings_split_ladder_true.sql snapshot, describe the
    EARLIER split shape from before the inner eff_color table below, so they are
    NOT evidence for this revision.  This shape has no MySQL plan or runtime
    comparison yet - keep it gated off until both exist.  Do not flip the
    default here.

    Multiplicity proof.  Let a barangay hold G actionable geo rows and R
    registry rows (after filters).  The shipped query joins them into G*R rows
    (G rows when R=0, R rows when G=0, via LEFT JOIN), then:
      * COUNT(DISTINCT g.logID) sees each logID once per registry row, so
        DISTINCT cancels the registry multiplicity exactly;
      * The conditional active-flag AVG repeats each eligible coordinate pair
        the same number of times, so its mean is unchanged;
      * COUNT(DISTINCT o.businessID) sees each businessID once per geo row, so
        DISTINCT cancels the geo multiplicity exactly.
    Aggregating g and o separately therefore yields identical values, while the
    effective-colour expression is evaluated once per geo row instead of once
    per fanned-out row.  Empty sides collapse to 0 / NULL exactly like a LEFT
    JOIN because of the COALESCE around each aggregate.

    Single-evaluation guard.  {effective_flag_color} is a large CASE carrying
    correlated official_registry/enforcement_state lookups, and it appears in
    counts and two location averages; written directly against geospatial_logs
    MySQL expands it repeatedly per geo row. The inner derived table selects it
    once as eff_color; its GROUP BY on the geospatial_logs primary key (logID)
    is intended to make the derived table non-mergeable under MySQL's
    derived-table rules, so eff_color would be materialized once per actionable
    geo row and the outer aggregates read that plain column. Grouping by
    the primary key keeps one row per geo row, so values are unchanged.  MySQL
    materialization and the actual evaluation count are UNVERIFIED: they must be
    confirmed by this shape's own EXPLAIN (and the estimate not assumed here).
    """
    sql = f"""
        SELECT
            b.barangayID,
            b.barangayName,
            COALESCE(ga.flagged_count, 0)    AS flagged_count,
            COALESCE(ga.red_count, 0)        AS red_count,
            COALESCE(ga.yellow_count, 0)     AS yellow_count,
            COALESCE(ga.black_count, 0)      AS black_count,
            COALESCE(ga.dispatchable_red_count, 0) AS dispatchable_red_count,
            COALESCE(ga.dispatchable_yellow_count, 0) AS dispatchable_yellow_count,
            COALESCE(ga.dispatchable_business_count, 0) AS dispatchable_business_count,
            ga.avg_lat                       AS avg_lat,
            ga.avg_lng                       AS avg_lng,
            COALESCE(ga.unregistered_candidate_count, 0) AS unregistered_candidate_count,
            COALESCE(oa.total_registered, 0) AS total_registered
        FROM barangays b
        LEFT JOIN (
            SELECT
                c.barangayID,
                COUNT(DISTINCT CASE WHEN c.eff_color IN ('Red', 'Yellow', 'Black') THEN c.logID END) AS flagged_count,
                COUNT(DISTINCT CASE WHEN c.eff_color = 'Red'    THEN c.logID END) AS red_count,
                COUNT(DISTINCT CASE WHEN c.eff_color = 'Yellow' THEN c.logID END) AS yellow_count,
                COUNT(DISTINCT CASE WHEN c.eff_color = 'Black'  THEN c.logID END) AS black_count,
                COUNT(DISTINCT CASE WHEN c.eff_color = 'Red' AND c.no_open_inspection
                    THEN c.logID END) AS dispatchable_red_count,
                COUNT(DISTINCT CASE WHEN c.eff_color = 'Yellow' AND c.no_open_inspection
                    THEN c.logID END) AS dispatchable_yellow_count,
                COUNT(DISTINCT {_dispatchable_business_identity_sql(
                    'c', 'c.eff_color', 'c.no_open_inspection', 'c.registry_business_id'
                )}) AS dispatchable_business_count,
                AVG(CASE WHEN c.eff_color IN ('Red', 'Yellow') AND c.no_open_inspection
                    AND c.latitude BETWEEN -90 AND 90 AND c.longitude BETWEEN -180 AND 180
                    THEN c.latitude END) AS avg_lat,
                AVG(CASE WHEN c.eff_color IN ('Red', 'Yellow') AND c.no_open_inspection
                    AND c.latitude BETWEEN -90 AND 90 AND c.longitude BETWEEN -180 AND 180
                    THEN c.longitude END) AS avg_lng,
                COUNT(DISTINCT CASE WHEN c.eff_color = 'Red'
                    AND c.registry_business_id IS NULL THEN c.logID END) AS unregistered_candidate_count
            FROM (
                SELECT
                    g.logID,
                    g.barangayID,
                    {effective_flag_color} AS eff_color,
                    {_registry_column_sql('g', 'businessID')} AS registry_business_id,
                    {_no_open_inspection_sql()} AS no_open_inspection,
                    g.businessID,
                    g.placeID,
                    g.latitude,
                    g.longitude
                FROM geospatial_logs g
                WHERE {_PIN_ACTIONABLE_SQL}{geo_on_g}
                GROUP BY g.logID
            ) c
            GROUP BY c.barangayID
        ) ga ON ga.barangayID = b.barangayID
        LEFT JOIN (
            SELECT
                o.barangayID,
                COUNT(DISTINCT o.businessID) AS total_registered
            FROM official_registry o
            WHERE 1=1{reg_o}
            GROUP BY o.barangayID
        ) oa ON oa.barangayID = b.barangayID
        WHERE 1=1 {brgy_b}
    """
    return sql, geo_on_g_p + reg_o_p + brgy_b_p


def _prescriptive_registry_sql(ladder):
    """Both sides of the rate use the SAME canonical registry population.

    No pin join: repeated logs cannot inflate the numerator. Pending/Expired/
    Black states are review signals, not proof of a violation. Registry-only
    businesses are included, and unknown/unregistered candidates are not.
    """
    color = registry_row_color_sql("o", ladder=ladder)
    return f"""
        SELECT b.barangayID,
               COUNT(DISTINCT o.businessID) AS total_registered,
               COUNT(DISTINCT CASE WHEN {color} IN ('Red', 'Yellow', 'Black')
                     THEN o.businessID END) AS registry_flagged_count
        FROM barangays b
        LEFT JOIN official_registry o ON o.barangayID = b.barangayID
        GROUP BY b.barangayID
    """


def _prescriptive_sector_sql(effective_flag_color):
    """Count active-flag entities by their canonical PSIC display category."""
    return f"""
        SELECT c.barangayID,
               rsm.display_sector_label AS sector_category,
               COUNT(DISTINCT COALESCE(
                   CASE WHEN c.registry_business_id IS NOT NULL
                       THEN CONCAT('business:', CAST(c.registry_business_id AS CHAR)) END,
                   CASE WHEN c.businessID IS NOT NULL
                       THEN CONCAT('business:', CAST(c.businessID AS CHAR)) END,
                   CASE WHEN c.placeID IS NOT NULL
                       THEN CONCAT('place:', CAST(c.placeID AS CHAR)) END,
                   CONCAT('log:', CAST(c.logID AS CHAR))
               )) AS entity_count
        FROM (
            SELECT g.logID, g.barangayID,
                   {effective_flag_color} AS eff_color,
                   {_registry_column_sql('g', 'businessID')} AS registry_business_id,
                   g.businessID, g.placeID
            FROM geospatial_logs g
            WHERE {_PIN_ACTIONABLE_SQL}
        ) c
        LEFT JOIN official_registry r
          ON r.businessID = COALESCE(c.registry_business_id, c.businessID)
        LEFT JOIN registry_sector_map rsm
          ON rsm.normalized_line_of_business =
             CONVERT(
                 LOWER(REGEXP_REPLACE(COALESCE(r.lineOfBusiness, ''), '[^A-Za-z0-9]', ''))
                 USING utf8mb4
             ) COLLATE utf8mb4_unicode_ci
         AND rsm.match_status IN ('matched', 'combo')
        WHERE c.eff_color IN ('Red', 'Yellow', 'Black')
        GROUP BY c.barangayID, rsm.display_sector_label
    """


def _load_prescriptive_rows(cur, effective_flag_color, ladder):
    """One municipal input/scoring path for Analytics and Map dispatch."""
    builder = _barangay_rankings_sql_split if _rankings_split_enabled() else _barangay_rankings_sql
    # All dashboard filters deliberately stay OUT of the operational model.
    # Registry metrics come from the next, separate aggregate. Disable this
    # builder's legacy registry join so evaluating the colour/coordinates never
    # pays the geo x registry fan-out. This does NOT enable the candidate split.
    sql, params = builder(effective_flag_color, "", [], " AND 1=0", [], "", [])
    _execute(cur, "prescriptive.barangay_rankings", sql, params)
    rows = list(cur.fetchall())
    _execute(cur, "prescriptive.registry_active_flags", _prescriptive_registry_sql(ladder))
    registry = {row["barangayID"]: row for row in cur.fetchall()}
    _execute(cur, "prescriptive.sector_risk", _prescriptive_sector_sql(effective_flag_color))
    sector_categories = {}
    for sector_row in cur.fetchall():
        categories = sector_categories.setdefault(sector_row["barangayID"], {})
        categories[sector_row["sector_category"]] = int(sector_row["entity_count"] or 0)
    for row in rows:
        row.update(registry.get(row["barangayID"], {}))
        row["sector_category_counts"] = sector_categories.get(row["barangayID"], {})
    return rows


def _load_prescriptive_rankings(cur, effective_flag_color, ladder, config):
    rows = _load_prescriptive_rows(cur, effective_flag_color, ladder)
    sector_policy = load_persisted_sector_risk_policy(cur)
    return calculate_rankings(rows, config, sector_policy)


_PRESCRIPTIVE_WORKFORCE_SQL = """
    SELECT COUNT(*) AS active_count,
           COALESCE(SUM(CASE WHEN NOT EXISTS (
               SELECT 1 FROM inspection_reports pending
               WHERE pending.userID = u.userID
                 AND pending.verificationStatus IN ('Assigned', 'Reassigned', 'In Progress')
           ) THEN 1 ELSE 0 END), 0) AS available_count
    FROM users u WHERE u.userRole = 'Inspector' AND u.isActive = 1
"""


def _diagnostic_registry_match_sql():
    return """
        SELECT TRIM(businessName) AS normalized_name,
               barangayID,
               MIN(businessID) AS businessID,
               COUNT(DISTINCT businessID) AS match_count
        FROM official_registry
        GROUP BY TRIM(businessName), barangayID
    """


def _diagnostic_registry_match_join(registry_match_sql):
    return f"""LEFT JOIN ({registry_match_sql}) rm
            ON g.businessID IS NULL
           AND rm.normalized_name = TRIM(g.detectedName)
           AND rm.barangayID = g.barangayID"""


def _diagnostic_category_risk_sql(effective_flag_color, registry_match_sql, geo_g, reg_o):
    match_join = _diagnostic_registry_match_join(registry_match_sql)
    return f"""
        SELECT
            COALESCE(NULLIF(TRIM(o.lineOfBusiness), ''), 'Unspecified sector') AS category,
            COUNT(DISTINCT o.businessID) AS flagged_count
        FROM geospatial_logs g
        {match_join}
        JOIN official_registry o
          ON o.businessID = COALESCE(
              g.businessID,
              CASE WHEN rm.match_count = 1 THEN rm.businessID END
          )
        WHERE {effective_flag_color} != 'Green'
          AND (g.placeID IS NOT NULL OR g.reportedByUserID IS NOT NULL
               OR g.flagColor = 'Orange'
               OR EXISTS (SELECT 1 FROM inspection_reports ir WHERE ir.targetID = g.logID))
          {geo_g} {reg_o}
        GROUP BY category
        ORDER BY flagged_count DESC
        LIMIT 10
    """


def _diagnostic_category_linkage_sql(effective_flag_color, registry_match_sql, geo_g):
    match_join = _diagnostic_registry_match_join(registry_match_sql)
    return f"""
        SELECT COUNT(DISTINCT g.logID) AS total_flagged_records,
               COUNT(DISTINCT CASE
                   WHEN direct_registry.businessID IS NOT NULL OR rm.match_count = 1
                   THEN g.logID END) AS linked_records,
               COUNT(DISTINCT CASE
                   WHEN direct_registry.businessID IS NULL AND rm.match_count IS NULL
                   THEN g.logID END) AS unlinked_records,
               COUNT(DISTINCT CASE
                   WHEN direct_registry.businessID IS NULL AND rm.match_count > 1
                   THEN g.logID END) AS ambiguous_records
        FROM geospatial_logs g
        {match_join}
        LEFT JOIN official_registry direct_registry ON direct_registry.businessID = g.businessID
        WHERE {effective_flag_color} != 'Green'
          AND (g.placeID IS NOT NULL OR g.reportedByUserID IS NOT NULL
               OR g.flagColor = 'Orange'
               OR EXISTS (SELECT 1 FROM inspection_reports ir WHERE ir.targetID = g.logID))
          {geo_g}
    """


def _build_prescriptive_section(cur, effective_flag_color, ladder, config, filters):
    from api.analytics.dispatch import generate_recommendations

    municipal_rankings, model = _load_prescriptive_rankings(cur, effective_flag_color, ladder, config)
    _execute(cur, "prescriptive.active_inspectors", _PRESCRIPTIVE_WORKFORCE_SQL)
    workforce = cur.fetchone() or {}
    available = int(workforce.get("available_count") or 0)
    recommendations = generate_recommendations(municipal_rankings, available, model["weights"])
    allocation_capacity = min(6, available)
    allocated = sum(recommendation["inspectors"] for recommendation in recommendations)
    model["ignored_filters"] = [key for key, value in (filters or {}).items()
                                if value and key != "barangay_ids"]
    return {
        "rankings": select_rankings(municipal_rankings, filters),
        "rankings_computed_at": datetime.now(timezone.utc).isoformat(),
        "wlc_config": config, "model": model,
        "dispatch_recommendations": select_rankings(recommendations, filters),
        "workforce": {
            "active_inspectors": int(workforce.get("active_count") or 0),
            "available_inspectors": available,
            "allocation_capacity": allocation_capacity,
            "allocated_inspectors": allocated,
            "unallocated_inspectors": max(0, allocation_capacity - allocated),
            "allocation_rule": "Maximum one inspector per eligible business; allocations are limited to the top three eligible WLC-ranked barangays.",
            "availability_rule": "Active inspectors without Assigned, Reassigned or In Progress reports; shift/leave availability is not recorded.",
        },
    }


def _get_all_analytics_inner(F=None):
    """
    Run all analytics queries and return (data_dict, status_code).
    Returns a plain dict so the result can be cached and mutated by the
    caller before serialisation — avoids the earlier pattern of calling
    jsonify() here and then get_json() in the route to re-inflate it.
    """
    if F is None:
        F = {}
    # check_and_expire_old_permits is now handled by APScheduler (app.py).
    # It is no longer called inline so reads don't pay write-operation cost.
    raw_cur = mysql.connection.cursor()
    # Per-request span collector, installed by the caller via flask.g. When the
    # REVELA_ANALYTICS_PHASES gate is off this is None and the raw cursor is used
    # unchanged, so behavior and overhead match the previous code.
    phases = getattr(g, "_analytics_phases",
                     None) if has_app_context() else None
    cur = _TimedCursor(raw_cur, phases) if phases is not None else raw_cur

    Fx = dict(F or {})
    Fx["registration_type_supported"] = _registry_has_registration_type(
        _labeled(cur, "schema:official_registry.registration_type"))
    reg_all, reg_all_p = registry_sql("official_registry", Fx)
    reg_no_status, reg_no_status_p = registry_sql(
        "official_registry", filters_without(Fx, "application_status"))
    reg_o, reg_o_p = registry_sql("o", Fx)
    reg_r, reg_r_p = registry_sql("r", Fx)
    # One colour rule for every query below, including the colour filters.
    # ladder_columns_available() is False until the ladder migration has run,
    # which leaves the SQL as it was before.
    ladder = ladder_columns_available(
        _labeled(cur, "schema:enforcement_state.ladder_columns"))
    effective_flag_color = _effective_flag_color_sql("g", ladder=ladder)
    registry_flag_color = registry_row_color_sql("r", ladder=ladder)
    geo_g, geo_g_p = geo_sql("g", Fx, ladder=ladder)
    geo_g2, geo_g2_p = geo_sql("g2", Fx, ladder=ladder)
    geo_on_g, geo_on_g_p = geo_on_extra("g", Fx, ladder=ladder)
    brgy_b, brgy_b_p = barangay_b_sql(Fx)
    insp_ir, insp_ir_p = inspection_sql("ir", Fx)

    # ── WLC config ────────────────────────────────────────────────────────────
    config = get_wlc_config()

    # ══════════════════════════════════════════════════════════════════════════
    # TIER 1 — DESCRIPTIVE
    # ══════════════════════════════════════════════════════════════════════════

    _execute(
        cur,
        "kpi.total_businesses",
        "SELECT COUNT(*) AS n FROM official_registry WHERE 1=1" + reg_all,
        reg_all_p,
    )
    total_businesses = cur.fetchone()["n"]

    # Status KPIs use the full applied registry filter set, including an applied
    # permit status. That keeps the KPI strip and the barangay/status chart on
    # one population: when a status is selected, both show that one status.
    _execute(
        cur,
        "kpi.active_count",
        "SELECT COUNT(*) AS n FROM official_registry WHERE applicationStatus = 'Active'"
        + reg_all,
        reg_all_p,
    )
    active_count = cur.fetchone()["n"]

    _execute(
        cur,
        "kpi.expired_count",
        "SELECT COUNT(*) AS n FROM official_registry WHERE applicationStatus = 'Expired'"
        + reg_all,
        reg_all_p,
    )
    expired_count = cur.fetchone()["n"]

    _execute(
        cur,
        "kpi.closed_count",
        "SELECT COUNT(*) AS n FROM official_registry WHERE applicationStatus = 'Closed'"
        + reg_all,
        reg_all_p,
    )
    closed_count = cur.fetchone()["n"]

    _execute(
        cur,
        "kpi.pending_count",
        "SELECT COUNT(*) AS n FROM official_registry WHERE applicationStatus = 'Pending'"
        + reg_all,
        reg_all_p,
    )
    pending_count = cur.fetchone()["n"]

    _execute(
        cur,
        "kpi.revoked_count",
        "SELECT COUNT(*) AS n FROM official_registry WHERE applicationStatus = 'Revoked'"
        + reg_all,
        reg_all_p,
    )
    revoked_count = cur.fetchone()["n"]

    _execute(
        cur,
        "kpi.current_year_registered",
        "SELECT COUNT(*) AS n, YEAR(CURDATE()) AS reporting_year FROM official_registry WHERE YEAR(lastRenewalDate) = YEAR(CURDATE())"
        + reg_all,
        reg_all_p,
    )
    current_year_row = cur.fetchone()
    current_year_registered_count = current_year_row["n"]

    _execute(
        cur,
        "kpi.upcoming_year_renewal",
        "SELECT COUNT(*) AS n FROM official_registry WHERE ((YEAR(lastRenewalDate) = YEAR(CURDATE()) AND applicationStatus = 'Active') OR YEAR(lastRenewalDate) = YEAR(CURDATE()) + 1)"
        + reg_all,
        reg_all_p,
    )
    upcoming_year_renewal_count = cur.fetchone()["n"]

    new_registration_count = 0
    renewal_registration_count = 0
    if Fx["registration_type_supported"]:
        _execute(
            cur,
            "kpi.new_registration",
            "SELECT COUNT(*) AS n FROM official_registry WHERE registrationType = 'New'"
            + reg_all,
            reg_all_p,
        )
        new_registration_count = cur.fetchone()["n"]

        _execute(
            cur,
            "kpi.renewal_registration",
            "SELECT COUNT(*) AS n FROM official_registry WHERE registrationType = 'Renewal'"
            + reg_all,
            reg_all_p,
        )
        renewal_registration_count = cur.fetchone()["n"]

    current_year_count = current_year_registered_count

    compliance_rate = round(
        (active_count / total_businesses * 100), 1) if total_businesses else 0

    kpis = {
        "total_businesses": total_businesses, "active_count": active_count,
        "expired_count": expired_count, "closed_count": closed_count,
        "pending_count": pending_count, "revoked_count": revoked_count,
        "new_registration_count": new_registration_count,
        "renewal_registration_count": renewal_registration_count,
        "current_year_count": current_year_registered_count,
        "current_year_registered_count": current_year_registered_count,
        "upcoming_year_renewal_count": upcoming_year_renewal_count,
        "compliance_rate": compliance_rate,
        "reporting_year": current_year_row.get("reporting_year"),
    }
    # The registry aggregates are ready before the map/registry reconciliation
    # below. Publish them now so Overview does not wait on total_flagged.
    _publish_analytics_section("summary", {"kpis": kpis})

    _execute(
        cur,
        "kpi.total_flagged",
        f"""SELECT COUNT(*) AS n
        FROM (
            SELECT g.logID AS id
            FROM geospatial_logs g
            WHERE {effective_flag_color} != 'Green' {geo_g}

            UNION ALL

            SELECT r.businessID AS id
            FROM official_registry r
            WHERE {registry_flag_color} != 'Green'
              AND NOT EXISTS (
                  SELECT 1 FROM geospatial_logs g2
                  WHERE (g2.businessID IS NOT NULL AND g2.businessID = r.businessID)
                     OR (g2.placeID IS NOT NULL AND g2.placeID = r.placeID
                         AND (g2.businessID IS NULL OR g2.businessID = r.businessID))
                     OR (g2.businessID IS NULL AND g2.detectedName = r.businessName
                         AND g2.barangayID = r.barangayID)
              ) {reg_r}
        ) AS map_non_green""",
        geo_g_p + reg_r_p,
    )
    total_flagged = cur.fetchone()["n"]
    kpis["total_flagged"] = total_flagged
    # The map-location count completes the summary; readers still share the
    # same filter-scoped pipeline, cache flight, and invalidation.
    _publish_analytics_section("summary", {"kpis": kpis})

    # Enforcement progress — unified across official_registry and geospatial_logs
    _execute(cur, "descriptive.enforcement_progress", f"""
        SELECT
            b.barangayName,
            COUNT(DISTINCT CASE WHEN combined.flagColor = 'Green'  THEN combined.id END) AS green_count,
            COUNT(DISTINCT CASE WHEN combined.flagColor = 'Red'    THEN combined.id END) AS red_count,
            COUNT(DISTINCT CASE WHEN combined.flagColor = 'Yellow' THEN combined.id END) AS yellow_count,
            COUNT(DISTINCT CASE WHEN combined.flagColor = 'Black'  THEN combined.id END) AS black_count,
            COUNT(DISTINCT CASE WHEN combined.flagColor = 'Orange' THEN combined.id END) AS orange_count,
            COUNT(DISTINCT CASE WHEN combined.flagColor = 'Purple' THEN combined.id END) AS purple_count
        FROM barangays b
        LEFT JOIN (
            SELECT
                g.logID AS id,
                g.barangayID,
                {effective_flag_color} AS flagColor
            FROM geospatial_logs g
            WHERE 1=1 {geo_on_g}

            UNION ALL

            SELECT
                -CAST(2147483648 + r.registryOrdinal AS SIGNED) AS id,
                r.barangayID,
                {registry_flag_color} AS flagColor
            FROM (
                SELECT official_registry.*,
                       ROW_NUMBER() OVER (ORDER BY businessID) AS registryOrdinal
                FROM official_registry
            ) r
            WHERE NOT EXISTS (
                SELECT 1 FROM geospatial_logs g2
                WHERE (g2.businessID IS NOT NULL AND g2.businessID = r.businessID)
                   OR (g2.placeID IS NOT NULL AND g2.placeID = r.placeID
                       AND (g2.businessID IS NULL OR g2.businessID = r.businessID))
                   OR (g2.businessID IS NULL AND g2.detectedName = r.businessName
                       AND g2.barangayID = r.barangayID)
            ){reg_r}
        ) AS combined ON combined.barangayID = b.barangayID
        WHERE 1=1 {brgy_b}
        GROUP BY b.barangayID, b.barangayName
        ORDER BY b.barangayName
    """, geo_on_g_p + reg_r_p + brgy_b_p)
    enforcement_progress = [
        {
            "barangayName": row["barangayName"],
            "green_count":  row["green_count"] or 0,
            "red_count":    row["red_count"] or 0,
            "yellow_count": row["yellow_count"] or 0,
            "black_count":  row["black_count"] or 0,
            "orange_count": row["orange_count"] or 0,
            "purple_count": row["purple_count"] or 0,
        }
        for row in cur.fetchall()
    ]

    # Sectoral distribution
    _execute(cur, "descriptive.sectoral_distribution", f"""
        SELECT COALESCE(lineOfBusiness, 'Unclassified') AS sector, COUNT(*) AS count
        FROM official_registry
        WHERE 1=1 {reg_all}
        GROUP BY lineOfBusiness
        ORDER BY count DESC
    """, reg_all_p)
    sectoral_distribution = [
        {"sector": row["sector"], "count": row["count"]}
        for row in cur.fetchall()
    ]

    # Nature per barangay
    _execute(cur, "descriptive.nature_per_barangay", f"""
        SELECT COALESCE(b.barangayName, 'Unknown') AS barangayName, COALESCE(o.lineOfBusiness, 'Unclassified') AS nature, COUNT(*) AS count
        FROM official_registry o
        LEFT JOIN barangays b ON o.barangayID = b.barangayID
        WHERE 1=1 {reg_o}
        GROUP BY b.barangayName, nature
        ORDER BY b.barangayName ASC, count DESC
    """, reg_o_p)

    nature_per_barangay_raw = cur.fetchall()

    # Process into a format suitable for stacked bar chart: [{barangayName: 'Brgy 1', 'Retail': 10, 'Food': 5}, ...]
    nature_per_barangay_dict = {}
    for row in nature_per_barangay_raw:
        brgy = row["barangayName"]
        nature = row["nature"]
        count = row["count"]
        if brgy not in nature_per_barangay_dict:
            nature_per_barangay_dict[brgy] = {"barangayName": brgy}
        nature_per_barangay_dict[brgy][nature] = count

    nature_per_barangay = list(nature_per_barangay_dict.values())

    # Registry businesses by barangay and permit status. The LEFT JOIN keeps
    # every barangay visible at zero, while reg_o applies the same registry
    # filters as the status KPIs. Each businessID is counted once.
    _execute(cur, "descriptive.registry_by_barangay_status", f"""
        SELECT
            b.barangayID,
            b.barangayName,
            COUNT(CASE WHEN o.applicationStatus = 'Active'  THEN o.businessID END) AS active,
            COUNT(CASE WHEN o.applicationStatus = 'Pending' THEN o.businessID END) AS pending,
            COUNT(CASE WHEN o.applicationStatus = 'Expired' THEN o.businessID END) AS expired,
            COUNT(CASE WHEN o.applicationStatus = 'Closed'  THEN o.businessID END) AS closed,
            COUNT(CASE WHEN o.applicationStatus = 'Revoked' THEN o.businessID END) AS revoked,
            COUNT(o.businessID) AS total
        FROM barangays b
        LEFT JOIN official_registry o
          ON o.barangayID = b.barangayID {reg_o}
        WHERE 1=1 {brgy_b}
        GROUP BY b.barangayID, b.barangayName
        ORDER BY b.barangayName
    """, reg_o_p + brgy_b_p)
    registry_by_barangay_status = [
        {
            "barangayID": row["barangayID"],
            "barangayName": row["barangayName"],
            "active": row["active"] or 0,
            "pending": row["pending"] or 0,
            "expired": row["expired"] or 0,
            "closed": row["closed"] or 0,
            "revoked": row["revoked"] or 0,
            "total": row["total"] or 0,
        }
        for row in cur.fetchall()
    ]

    _execute(cur, "descriptive.registry_size_by_barangay", f"""
        SELECT
            b.barangayName,
            COALESCE(NULLIF(TRIM(o.businessSize), ''), 'Unknown') AS size_label,
            COUNT(o.businessID) AS count
        FROM barangays b
        LEFT JOIN official_registry o
          ON o.barangayID = b.barangayID {reg_o}
        WHERE 1=1 {brgy_b}
        GROUP BY b.barangayID, b.barangayName, size_label
        ORDER BY b.barangayName, count DESC
    """, reg_o_p + brgy_b_p)
    registry_size_by_barangay = [
        {
            "barangayName": row["barangayName"],
            "size_label": row["size_label"],
            "count": row["count"] or 0,
        }
        for row in cur.fetchall()
    ]

    # Business size
    _execute(cur, "descriptive.business_size_dist", f"""
        SELECT COALESCE(businessSize, 'Unknown') AS size_label, COUNT(*) AS count
        FROM official_registry
        WHERE 1=1 {reg_all}
        GROUP BY businessSize
        ORDER BY count DESC
    """, reg_all_p)
    business_size_dist = [
        {"size_label": row["size_label"], "count": row["count"]}
        for row in cur.fetchall()
    ]

    # Business type (Legal Structure)
    _execute(cur, "descriptive.business_type_dist", f"""
        SELECT COALESCE(businessType, 'Unknown') AS type_label, COUNT(*) AS count
        FROM official_registry
        WHERE 1=1 {reg_all}
        GROUP BY businessType
        ORDER BY count DESC
    """, reg_all_p)
    business_type_dist = [
        {"type_label": row["type_label"], "count": row["count"]}
        for row in cur.fetchall()
    ]

    # Registration lifecycle is optional in registry schemas predating this field.
    registration_type_dist = []
    if Fx["registration_type_supported"]:
        _execute(cur, "descriptive.registration_type_dist", f"""
            SELECT COALESCE(registrationType, 'Unspecified') AS type_label, COUNT(*) AS count
            FROM official_registry
            WHERE 1=1 {reg_all}
            GROUP BY registrationType
            ORDER BY count DESC
        """, reg_all_p)
        registration_type_dist = [
            {"type_label": row["type_label"], "count": row["count"]}
            for row in cur.fetchall()
        ]

    # Compliance by Business Size
    _execute(cur, "descriptive.compliance_by_size", f"""
        SELECT COALESCE(businessSize, 'Unknown') AS size_label,
               SUM(CASE WHEN applicationStatus = 'Active' THEN 1 ELSE 0 END) AS active_count,
               SUM(CASE WHEN applicationStatus != 'Active' THEN 1 ELSE 0 END) AS inactive_count
        FROM official_registry
        WHERE 1=1 {reg_all}
        GROUP BY businessSize
    """, reg_all_p)
    compliance_by_size = [
        {
            "size_label": row["size_label"],
            "active_count": row["active_count"] or 0,
            "inactive_count": row["inactive_count"] or 0
        }
        for row in cur.fetchall()
    ]

    # Compliance timeline
    _execute(cur, "descriptive.compliance_timeline", f"""
        SELECT
            DATE_FORMAT(lastRenewalDate, '%%Y-%%m') AS month,
            SUM(CASE WHEN applicationStatus = 'Active'  THEN 1 ELSE 0 END) AS active_count,
            SUM(CASE WHEN applicationStatus != 'Active' THEN 1 ELSE 0 END) AS non_active_count
        FROM official_registry
        WHERE lastRenewalDate >= DATE_SUB(NOW(), INTERVAL 12 MONTH)
        {reg_no_status}
        GROUP BY month
        ORDER BY month
    """, reg_no_status_p)
    compliance_timeline = [
        {
            "month":            row["month"],
            "active_count":     row["active_count"] or 0,
            "non_active_count": row["non_active_count"] or 0,
        }
        for row in cur.fetchall()
    ]

    # Audit summary
    _execute(cur, "descriptive.audit_summary", f"""
        SELECT COUNT(*) AS n FROM inspection_reports ir
        JOIN geospatial_logs g ON ir.targetID = g.logID
        WHERE 1=1 {insp_ir} {geo_g}
    """, insp_ir_p + geo_g_p)
    total_inspections = cur.fetchone()["n"]

    # Inspection reports by barangay and current status. This is the same
    # pin-linked report population as audit_summary: one row per target pin,
    # one distinct reportID per report, and no lifecycle-event or assignment
    # counts. The LEFT JOINs keep all barangays visible at zero.
    _execute(cur, "descriptive.inspection_by_barangay_status", f"""
        SELECT
            b.barangayID,
            b.barangayName,
            COUNT(DISTINCT CASE WHEN ir.verificationStatus = 'Assigned'    THEN ir.reportID END) AS assigned,
            COUNT(DISTINCT CASE WHEN ir.verificationStatus = 'Reassigned'  THEN ir.reportID END) AS reassigned,
            COUNT(DISTINCT CASE WHEN ir.verificationStatus = 'In Progress' THEN ir.reportID END) AS in_progress,
            COUNT(DISTINCT CASE WHEN ir.verificationStatus = 'Submitted'   THEN ir.reportID END) AS submitted,
            COUNT(DISTINCT CASE WHEN ir.verificationStatus = 'Verified'    THEN ir.reportID END) AS verified,
            COUNT(DISTINCT CASE
                WHEN COALESCE(NULLIF(TRIM(ir.verificationStatus), ''), 'Unassigned')
                     NOT IN ('Assigned', 'Reassigned', 'In Progress', 'Submitted', 'Verified')
                THEN ir.reportID END) AS unassigned,
            COUNT(DISTINCT ir.reportID) AS total
        FROM barangays b
        LEFT JOIN geospatial_logs g
          ON g.barangayID = b.barangayID {geo_on_g}
        LEFT JOIN inspection_reports ir
          ON ir.targetID = g.logID {insp_ir}
        WHERE 1=1 {brgy_b}
        GROUP BY b.barangayID, b.barangayName
        ORDER BY b.barangayName
    """, geo_on_g_p + insp_ir_p + brgy_b_p)
    inspection_by_barangay_status = [
        {
            "barangayID": row["barangayID"],
            "barangayName": row["barangayName"],
            "assigned": row["assigned"] or 0,
            "reassigned": row["reassigned"] or 0,
            "in_progress": row["in_progress"] or 0,
            "submitted": row["submitted"] or 0,
            "verified": row["verified"] or 0,
            "unassigned": row["unassigned"] or 0,
            "total": row["total"] or 0,
        }
        for row in cur.fetchall()
    ]

    _execute(cur, "descriptive.inspection_outcome_by_barangay", f"""
        SELECT
            b.barangayID,
            b.barangayName,
            ir.inspectionResult AS outcome,
            COUNT(DISTINCT ir.reportID) AS count
        FROM barangays b
        LEFT JOIN geospatial_logs g
          ON g.barangayID = b.barangayID {geo_on_g}
        LEFT JOIN inspection_reports ir
          ON ir.targetID = g.logID {insp_ir}
         AND ir.verificationStatus = 'Verified'
         AND ir.inspectionResult IN ('Green', 'Yellow', 'Red')
        WHERE 1=1 {brgy_b}
        GROUP BY b.barangayID, b.barangayName, ir.inspectionResult
        HAVING ir.inspectionResult IS NOT NULL
        ORDER BY b.barangayName, ir.inspectionResult
    """, geo_on_g_p + insp_ir_p + brgy_b_p)
    inspection_outcome_by_barangay = [
        {
            "barangayID": row["barangayID"],
            "barangayName": row["barangayName"],
            "outcome": row["outcome"],
            "count": row["count"] or 0,
        }
        for row in cur.fetchall()
    ]

    _execute(cur, "descriptive.verified_reports_without_outcome", f"""
        SELECT COUNT(DISTINCT ir.reportID) AS n
        FROM inspection_reports ir
        JOIN geospatial_logs g ON ir.targetID = g.logID
        WHERE ir.verificationStatus = 'Verified'
          AND (ir.inspectionResult IS NULL
               OR ir.inspectionResult NOT IN ('Green', 'Yellow', 'Red'))
          {insp_ir} {geo_g}
    """, insp_ir_p + geo_g_p)
    verified_reports_without_outcome = cur.fetchone()["n"] or 0

    # The Descriptive report population is pin-linked. Count reports that
    # cannot be attributed to a barangay so the chart can disclose them rather
    # than silently folding in the Operations LEFT JOIN population.
    _execute(cur, "descriptive.unlinked_inspection_reports", f"""
        SELECT COUNT(DISTINCT ir.reportID) AS n
        FROM inspection_reports ir
        LEFT JOIN geospatial_logs g ON ir.targetID = g.logID
        WHERE g.logID IS NULL {insp_ir}
    """, insp_ir_p)
    unlinked_inspection_reports = cur.fetchone()["n"] or 0

    _execute(cur, "descriptive.inspection_result_breakdown", f"""
        SELECT ir.inspectionResult, COUNT(*) AS count
        FROM inspection_reports ir
        JOIN geospatial_logs g ON ir.targetID = g.logID
        WHERE ir.inspectionResult IS NOT NULL AND ir.verificationStatus = 'Verified' {insp_ir} {geo_g}
        GROUP BY ir.inspectionResult
    """, insp_ir_p + geo_g_p)
    result_breakdown = [
        {"inspectionResult": row["inspectionResult"], "count": row["count"]}
        for row in cur.fetchall()
    ]
    _execute(cur, "descriptive.submitted_result_breakdown", f"""
        SELECT ir.inspectionResult, COUNT(*) AS count
        FROM inspection_reports ir
        JOIN geospatial_logs g ON ir.targetID = g.logID
        WHERE ir.inspectionResult IS NOT NULL AND ir.verificationStatus = 'Submitted' {insp_ir} {geo_g}
        GROUP BY ir.inspectionResult
    """, insp_ir_p + geo_g_p)
    submitted_result_breakdown = list(cur.fetchall())

    _execute(cur, "descriptive.inspection_workflow", f"""
        SELECT
            COUNT(DISTINCT CASE WHEN ir.verificationStatus = 'Submitted' THEN ir.reportID END) AS awaiting_verification,
            COUNT(DISTINCT CASE WHEN ir.verificationStatus = 'Verified' THEN ir.reportID END) AS verified_reports,
            COUNT(DISTINCT CASE WHEN ir.verificationStatus = 'Submitted' AND ir.inspectionResult = 'Green'
                  THEN ir.reportID END) AS submitted_green
        FROM inspection_reports ir
        JOIN geospatial_logs g ON ir.targetID = g.logID
        WHERE 1=1 {insp_ir} {geo_g}
    """, insp_ir_p + geo_g_p)
    workflow = cur.fetchone() or {}
    confirmed = confirmation_summary(current_confirmation_rows(
        cur, ladder=ladder, barangay_ids=Fx.get("barangay_ids")))

    # Share Map/report membership and verified-compliance evidence, rather than
    # treating a missing businessID or a Green colour alone as classification.
    monitoring_sql, monitoring_params = non_registry_monitoring_sql(
        Fx, ladder=ladder,
        source_sql=origin_source_sql("g", _labeled(cur, "schema:geospatial_logs.source")),
    )
    _execute(cur, "descriptive.non_registry_monitoring", monitoring_sql, monitoring_params)
    non_registry_monitoring = build_non_registry_monitoring(cur.fetchall(), Fx)

    linked_monitoring_sql, linked_monitoring_params = registry_linked_monitoring_sql(
        Fx, ladder=ladder,
        source_sql=origin_source_sql("g", _labeled(cur, "schema:geospatial_logs.source")),
    )
    _execute(cur, "descriptive.registry_linked_monitoring", linked_monitoring_sql, linked_monitoring_params)
    registry_linked_monitoring = build_registry_linked_monitoring(cur.fetchall(), Fx)

    descriptive = {
        "kpis": kpis,
        "enforcement_progress": enforcement_progress,
        "nature_per_barangay": nature_per_barangay,
        "registry_by_barangay_status": registry_by_barangay_status,
        "registry_size_by_barangay": registry_size_by_barangay,
        "inspection_by_barangay_status": inspection_by_barangay_status,
        "inspection_outcome_by_barangay": inspection_outcome_by_barangay,
        "sectoral_distribution": sectoral_distribution,
        "business_size_dist": business_size_dist,
        "business_type_dist": business_type_dist,
        "registration_type_dist": registration_type_dist,
        "compliance_by_size": compliance_by_size,
        "compliance_timeline": compliance_timeline,
        "audit_summary": {"total_inspections": total_inspections,
                           "total_reports": total_inspections,
                           "unlinked_reports": unlinked_inspection_reports,
                           "verified_reports": workflow.get("verified_reports", 0),
                           "submitted_green": workflow.get("submitted_green", 0),
                           "verified_reports_without_outcome": verified_reports_without_outcome,
                           "result_breakdown": result_breakdown,
                           "submitted_result_breakdown": submitted_result_breakdown,
                           "workflow": workflow},
        "confirmed_compliance": confirmed,
        "non_registry_monitoring": non_registry_monitoring,
        "registry_linked_monitoring": registry_linked_monitoring,
    }
    _publish_analytics_section("descriptive", descriptive)

    # ══════════════════════════════════════════════════════════════════════════
    # TIER 2 — DIAGNOSTIC
    # ══════════════════════════════════════════════════════════════════════════

    # Barangay risk heatmap
    _execute(cur, "diagnostic.barangay_risk", f"""
        SELECT
            b.barangayID,
            b.barangayName,
            COUNT(DISTINCT CASE WHEN {effective_flag_color} != 'Green' THEN g.logID END) AS flagged_count,
            COUNT(DISTINCT CASE WHEN {effective_flag_color} = 'Red'    THEN g.logID END) AS red_count,
            COUNT(DISTINCT CASE WHEN {effective_flag_color} = 'Yellow' THEN g.logID END) AS yellow_count,
            COUNT(DISTINCT CASE WHEN {effective_flag_color} = 'Black'  THEN g.logID END) AS black_count,
            COUNT(DISTINCT CASE WHEN {effective_flag_color} = 'Orange' THEN g.logID END) AS orange_count,
            COUNT(DISTINCT CASE WHEN {effective_flag_color} = 'Purple' THEN g.logID END) AS purple_count
        FROM barangays b
        LEFT JOIN geospatial_logs g ON g.barangayID = b.barangayID 
            AND (g.placeID IS NOT NULL OR g.reportedByUserID IS NOT NULL OR g.flagColor = 'Orange' OR EXISTS (SELECT 1 FROM inspection_reports ir WHERE ir.targetID = g.logID)){geo_on_g}
        WHERE 1=1 {brgy_b}
        GROUP BY b.barangayID, b.barangayName
        ORDER BY flagged_count DESC
    """, geo_on_g_p + brgy_b_p)
    barangay_risk_data = [
        {
            "barangayID":    row["barangayID"],
            "barangayName":  row["barangayName"],
            "flagged_count": row["flagged_count"] or 0,
            "red_count":     row["red_count"] or 0,
            "yellow_count":  row["yellow_count"] or 0,
            "black_count":   row["black_count"] or 0,
            "orange_count":  row["orange_count"] or 0,
            "purple_count":  row["purple_count"] or 0,
        }
        for row in cur.fetchall()
    ]

    high_risk_barangays = sum(
        1 for r in barangay_risk_data
        if r["red_count"] > 0 or r["flagged_count"] >= 5
    )

    # Attribute by valid businessID first; otherwise require one unique
    # trimmed-name + barangay match. Linkage summary uses these same rules.
    registry_match_sql = _diagnostic_registry_match_sql()
    _execute(
        cur, "diagnostic.category_risk_drivers",
        _diagnostic_category_risk_sql(
            effective_flag_color, registry_match_sql, geo_g, reg_o),
        geo_g_p + reg_o_p,
    )
    flagged_by_sector = list(cur.fetchall())

    _execute(cur, "diagnostic.sector_denominators", f"""
        SELECT COALESCE(NULLIF(TRIM(lineOfBusiness), ''), 'Unspecified sector') AS category,
               COUNT(DISTINCT businessID) AS total_registered
        FROM official_registry
        WHERE 1=1 {reg_all}
        GROUP BY category
    """, reg_all_p)
    sector_denominators = {
        row["category"]: int(row["total_registered"] or 0)
        for row in cur.fetchall()
    }
    category_risk_drivers = []
    for row in flagged_by_sector:
        category = row["category"]
        flagged_count = int(row["flagged_count"] or 0)
        total_registered = sector_denominators.get(category, 0)
        category_risk_drivers.append({
            "category": category,
            "flagged_count": flagged_count,
            "total_registered": total_registered,
            "non_green_rate": round(flagged_count / total_registered * 100, 1) if total_registered else 0,
        })

    _execute(
        cur, "diagnostic.category_linkage",
        _diagnostic_category_linkage_sql(
            effective_flag_color, registry_match_sql, geo_g),
        geo_g_p,
    )
    linkage_row = cur.fetchone() or {}
    total_flagged_records = int(linkage_row.get("total_flagged_records") or 0)
    linked_records = int(linkage_row.get("linked_records") or 0)
    category_linkage_summary = {
        "total_flagged_records": total_flagged_records,
        "linked_records": linked_records,
        "unlinked_records": int(linkage_row.get("unlinked_records") or 0),
        "ambiguous_records": int(linkage_row.get("ambiguous_records") or 0),
        "linkage_rate": round(linked_records / total_flagged_records * 100, 1) if total_flagged_records else 0,
    }

    # Weekly red-flag trend
    _execute(cur, "diagnostic.flag_trend", f"""
        SELECT
            DATE_FORMAT(
                DATE_SUB(g.detectedDate, INTERVAL WEEKDAY(g.detectedDate) DAY),
                '%%Y-%%m-%%d'
            ) AS week_start,
            COUNT(DISTINCT CASE WHEN {effective_flag_color} = 'Red' THEN g.logID END) AS new_red_flags
        FROM geospatial_logs g
        WHERE g.detectedDate >= DATE_SUB(NOW(), INTERVAL 8 WEEK) 
          AND (g.placeID IS NOT NULL OR g.reportedByUserID IS NOT NULL OR g.flagColor = 'Orange' OR EXISTS (SELECT 1 FROM inspection_reports ir WHERE ir.targetID = g.logID)) {geo_g}
        GROUP BY week_start
        ORDER BY week_start
    """, geo_g_p)
    flag_trend = [
        {"week_start": str(row["week_start"]),
         "new_red_flags": row["new_red_flags"] or 0}
        for row in cur.fetchall()
    ]

    # DBSCAN Hotspot Intelligence
    dbscan_insight = "There is not enough location data to identify nearby groups of flagged records."
    dbscan_clusters = []
    _dbscan_t0 = _phase_start(phases)
    try:
        parameters, _ = resolve_hotspot_parameters(read_hotspot_settings(cur))
        dbscan_settings = (
            f"DBSCAN settings: Haversine eps={parameters['eps_m']:g} m, "
            f"min_samples={parameters['min_samples']}."
        )
        population_sql, population_params = build_hotspot_population_sql(
            effective_flag_color,
            registry_link_sql("g"),
            None,
            None,
            extra_where_sql=geo_g,
            extra_params=geo_g_p,
        )
        _execute(
            cur, "diagnostic.dbscan_hotspots", population_sql, population_params
        )
        hotspot_data = list(cur.fetchall() or [])
        _execute(
            cur,
            "diagnostic.dbscan_barangays",
            "SELECT barangayID, barangayName FROM barangays ORDER BY barangayID",
        )
        barangay_rows = list(cur.fetchall() or [])
        hotspot_groups, _ = cluster_hotspot_rows(
            hotspot_data,
            parameters,
            load_barangay_polygons(barangay_rows),
        )
        memberships, primary_cluster_id = hotspot_cluster_memberships(
            hotspot_data, hotspot_groups
        )

        for row in hotspot_data:
            if row.get("disposition") != "eligible":
                continue
            cluster_id = memberships[int(row["logID"])]
            detected_date = row.get("detectedDate")
            dbscan_clusters.append({
                "log_id": int(row["logID"]),
                "detected_name": row.get("detectedName"),
                "detected_date": (
                    detected_date.strftime("%Y-%m-%d %H:%M")
                    if detected_date else None
                ),
                "flag_color": row.get("flagColor"),
                "lat": float(row["latitude"]),
                "lng": float(row["longitude"]),
                "cluster": cluster_id,
                "is_primary": cluster_id == primary_cluster_id and cluster_id != -1,
                "barangay": row.get("barangayName") or "Unknown Area",
            })

        if hotspot_groups:
            largest_group = hotspot_groups[0]
            dominant_barangay = "Unknown Area"
            if largest_group["per_barangay"]:
                dominant_barangay = max(
                    largest_group["per_barangay"],
                    key=lambda row: row["count"],
                )["barangay_name"]
            dbscan_insight = (
                f"Largest nearby group: {largest_group['size']} eligible "
                f"effective-Red detection pins around {dominant_barangay}. "
                f"{dbscan_settings} Consider "
                "prioritizing this area for inspection; proximity alone does "
                "not confirm a violation."
            )
        elif dbscan_clusters:
            dbscan_insight = (
                "No nearby groups of eligible effective-Red detection pins "
                f"were found. {dbscan_settings}"
            )
        else:
            dbscan_insight = (
                "There is not enough eligible effective-Red detection-pin "
                f"location data to form a group. {dbscan_settings}"
            )
    except Exception as e:
        print(f"DBSCAN Error: {e}")
        dbscan_insight = "Hotspot detection temporarily unavailable."
    finally:
        # Inclusive span (it encloses a timed SQL leaf): logged, never summed.
        _record_inclusive(phases, "py:dbscan", _dbscan_t0)

    # Moran's I Proxy (Spatial Autocorrelation)
    morans_insight = "There is not enough data to compare risk patterns across barangays."
    morans_data = {"points": [], "threshold": 0}
    _morans_t0 = _phase_start(phases)
    try:
        _execute(cur, "diagnostic.morans_barangay_spatial", f"""
            SELECT 
                b.barangayName,
                AVG(g.latitude) as lat,
                AVG(g.longitude) as lng,
                COUNT(DISTINCT CASE WHEN {effective_flag_color} IN ('Red', 'Black') THEN g.logID END) as severe_count
            FROM barangays b
            JOIN geospatial_logs g ON b.barangayID = g.barangayID 
                AND (g.placeID IS NOT NULL OR g.reportedByUserID IS NOT NULL OR g.flagColor = 'Orange' OR EXISTS (SELECT 1 FROM inspection_reports ir WHERE ir.targetID = g.logID)){geo_on_g}
            WHERE g.latitude IS NOT NULL AND g.longitude IS NOT NULL {brgy_b}
            GROUP BY b.barangayID, b.barangayName
        """, geo_on_g_p + brgy_b_p)
        brgy_spatial = cur.fetchall()

        if len(brgy_spatial) >= 4:
            import numpy as np

            points = [
                {'name': r['barangayName'], 'lat': float(r['lat']), 'lng': float(
                    r['lng']), 'risk': float(r['severe_count'])}
                for r in brgy_spatial if r['lat'] and r['lng']
            ]

            if len(points) >= 4:
                risk_values = [p['risk'] for p in points]
                threshold = np.percentile(risk_values, 75) if sum(
                    risk_values) > 0 else 0

                morans_data["threshold"] = float(threshold)
                morans_data["points"] = [
                    {"barangay": p['name'], "risk": p['risk'], "is_high_risk": bool(
                        p['risk'] > threshold and p['risk'] > 0)}
                    for p in points
                ]

                high_risk_points = [
                    p for p in points if p['risk'] > threshold and p['risk'] > 0]

                if len(high_risk_points) >= 2:
                    all_lat = np.mean([p['lat'] for p in points])
                    all_lng = np.mean([p['lng'] for p in points])
                    hr_lat = np.mean([p['lat'] for p in high_risk_points])
                    hr_lng = np.mean([p['lng'] for p in high_risk_points])

                    ns = "Northern" if hr_lat > all_lat else "Southern"
                    ew = "Eastern" if hr_lng > all_lng else "Western"

                    def haversine(lat1, lon1, lat2, lon2):
                        R = 6371
                        dLat, dLon = np.radians(
                            lat2 - lat1), np.radians(lon2 - lon1)
                        a = np.sin(dLat/2)**2 + np.cos(np.radians(lat1)) * \
                            np.cos(np.radians(lat2)) * np.sin(dLon/2)**2
                        return R * 2 * np.arctan2(np.sqrt(a), np.sqrt(1-a))

                    all_dists = [haversine(points[i]['lat'], points[i]['lng'], points[j]['lat'], points[j]['lng'])
                                 for i in range(len(points)) for j in range(i+1, len(points))]
                    hr_dists = [haversine(high_risk_points[i]['lat'], high_risk_points[i]['lng'], high_risk_points[j]['lat'], high_risk_points[j]['lng'])
                                for i in range(len(high_risk_points)) for j in range(i+1, len(high_risk_points))]

                    avg_all = np.mean(all_dists)
                    avg_hr = np.mean(hr_dists) if hr_dists else 0

                    if 0 < avg_hr < (avg_all * 0.85):
                        morans_insight = f"Several higher-risk barangays are relatively close together, mainly in the {ns}-{ew} area. This is a geographic screening signal, not evidence of a shared cause."
                    elif avg_hr > (avg_all * 1.15):
                        morans_insight = "Higher-risk barangays are spread farther apart than average, so no single regional group stands out."
                    else:
                        morans_insight = "Higher-risk barangays are neither notably close together nor unusually spread out."
                else:
                    morans_insight = "There is not enough difference in flagged-record counts to identify a regional pattern."
    except Exception as e:
        print(f"Moran's I Proxy Error: {e}")
        morans_insight = "Regional pattern analysis temporarily unavailable."
    finally:
        # Inclusive span (it encloses a timed SQL leaf): logged, never summed.
        _record_inclusive(phases, "py:morans", _morans_t0)

    _scan_t0 = _phase_start(phases)
    try:
        scan_history = get_recent_detection_runs()
    finally:
        _record_inclusive(phases, "py:get_recent_detection_runs", _scan_t0)
    diagnostic = {
        "scan_history": scan_history, "barangay_risk_data": barangay_risk_data,
        "category_risk_drivers": category_risk_drivers,
        "category_linkage_summary": category_linkage_summary,
        "flag_trend": flag_trend, "dbscan_insight": dbscan_insight,
        "morans_insight": morans_insight, "dbscan_clusters": dbscan_clusters,
        "morans_data": morans_data,
    }
    _publish_analytics_section("diagnostic", diagnostic)

    # ══════════════════════════════════════════════════════════════════════════
    # TIER 3 — PRESCRIPTIVE (WLC / OPS)
    # ══════════════════════════════════════════════════════════════════════════

    prescriptive = _build_prescriptive_section(cur, effective_flag_color, ladder, config, F)
    _publish_analytics_section("prescriptive", prescriptive)

    # ══════════════════════════════════════════════════════════════════════════
    # TIER 4 — OPERATIONS
    # ══════════════════════════════════════════════════════════════════════════

    # 1. Inspector Leaderboard
    # Driven FROM users (LEFT JOIN reports) so EVERY active inspector appears —
    # including those with zero assigned/reported tasks. The old INNER-JOIN-
    # from-reports version silently omitted idle inspectors, which made the
    # AI assistant under-count the workforce. Filter fragments live in the ON
    # clauses so date/status filters don't re-inner-join and hide them again.
    _execute(cur, "operations.inspector_leaderboard", f"""
        SELECT 
            u.userID, 
            u.fullName, 
            COUNT(ir.reportID) as total_assigned, 
            SUM(CASE WHEN ir.verificationStatus IN ('Verified', 'Submitted') THEN 1 ELSE 0 END) as total_submitted,
            SUM(CASE WHEN ir.verificationStatus = 'Verified' THEN 1 ELSE 0 END) as total_verified,
            SUM(CASE WHEN ir.verificationStatus IN ('Verified', 'Submitted') THEN 1 ELSE 0 END) as total_completed,
            AVG(ir.resolutionTime) as avg_resolution_time,
            (SELECT COUNT(*) FROM geospatial_logs g2 WHERE g2.reportedByUserID = u.userID AND g2.flagColor = 'Yellow'{geo_g2}) as yellow_flags_reported
        FROM users u
        LEFT JOIN inspection_reports ir ON ir.userID = u.userID{insp_ir}
        LEFT JOIN geospatial_logs g ON ir.targetID = g.logID{geo_g}
        WHERE u.userRole = 'Inspector' AND u.isActive = 1
        GROUP BY u.userID
        ORDER BY total_verified DESC, total_submitted DESC
    """, geo_g2_p + insp_ir_p + geo_g_p)
    inspector_stats = list(cur.fetchall())
    for stat in inspector_stats:
        if stat["avg_resolution_time"] is not None:
            stat["avg_resolution_time"] = float(stat["avg_resolution_time"])
        else:
            stat["avg_resolution_time"] = 0.0

    _execute(cur, "operations.inspector_status_counts", f"""
        SELECT
            u.userID,
            u.fullName,
            COUNT(CASE
                WHEN COALESCE(NULLIF(TRIM(ir.verificationStatus), ''), 'Unassigned')
                     IN ('Assigned', 'Reassigned', 'In Progress', 'Unassigned')
                     AND g.logID IS NOT NULL
                THEN ir.reportID END) AS pending,
            COUNT(CASE WHEN ir.verificationStatus = 'Submitted' AND g.logID IS NOT NULL THEN ir.reportID END) AS awaiting_review,
            COUNT(CASE WHEN ir.verificationStatus = 'Verified' AND g.logID IS NOT NULL THEN ir.reportID END) AS verified
        FROM users u
        LEFT JOIN inspection_reports ir ON ir.userID = u.userID{insp_ir}
        LEFT JOIN geospatial_logs g ON ir.targetID = g.logID{geo_g}
        WHERE u.userRole = 'Inspector'
        GROUP BY u.userID
        ORDER BY (pending + awaiting_review + verified) DESC, u.fullName
    """, insp_ir_p + geo_g_p)
    inspector_status_counts = list(cur.fetchall())

    # 2. Inspection Status Breakdown
    _execute(cur, "operations.inspection_status_breakdown", f"""
        SELECT COALESCE(ir.verificationStatus, 'Unassigned') as status, COUNT(ir.reportID) as count
        FROM inspection_reports ir
        LEFT JOIN geospatial_logs g ON ir.targetID = g.logID
        WHERE 1=1 {insp_ir} {geo_g}
        GROUP BY ir.verificationStatus
    """, insp_ir_p + geo_g_p)
    status_breakdown = list(cur.fetchall())

    # 3. Inspection Timeline
    _execute(cur, "operations.inspection_timeline", f"""
        SELECT DATE(ir.irTimestamp) as date, COUNT(ir.reportID) as count
        FROM inspection_reports ir
        LEFT JOIN geospatial_logs g ON ir.targetID = g.logID
        WHERE 1=1 {insp_ir} {geo_g}
        GROUP BY DATE(ir.irTimestamp)
        ORDER BY date ASC
    """, insp_ir_p + geo_g_p)
    timeline_rows = list(cur.fetchall())
    inspection_timeline = []
    for row in timeline_rows:
        inspection_timeline.append({
            "date": row["date"].strftime("%Y-%m-%d") if row["date"] else None,
            "count": row["count"]
        })

    _execute(cur, "operations.inspection_status_timeline", f"""
        SELECT
            DATE(ir.irTimestamp) AS date,
            COUNT(DISTINCT CASE WHEN ir.verificationStatus = 'Submitted' THEN ir.reportID END) AS submitted,
            COUNT(DISTINCT CASE WHEN ir.verificationStatus = 'Verified' THEN ir.reportID END) AS verified
        FROM inspection_reports ir
        LEFT JOIN geospatial_logs g ON ir.targetID = g.logID
        WHERE 1=1 {insp_ir} {geo_g}
        GROUP BY DATE(ir.irTimestamp)
        ORDER BY date ASC
    """, insp_ir_p + geo_g_p)
    inspection_status_timeline = [
        {
            "date": row["date"].strftime("%Y-%m-%d") if row["date"] else None,
            "submitted": row["submitted"] or 0,
            "verified": row["verified"] or 0,
        }
        for row in cur.fetchall()
    ]

    cur.close()
    operations = {
        "inspector_stats": inspector_stats, "status_breakdown": status_breakdown,
        "inspection_timeline": inspection_timeline,
        "inspector_status_counts": inspector_status_counts,
        "inspection_status_timeline": inspection_status_timeline,
    }
    _publish_analytics_section("operations", operations)

    return {
        "applied_filters": Fx,
        # new_year_rollover is intentionally omitted here — it is user-specific
        # (unread flag) and is appended by the get_all_analytics route after
        # checking revela_notifications for the requesting user.
        "descriptive": {**descriptive, "kpis": {
            **descriptive["kpis"], "high_risk_barangays": high_risk_barangays,
        }},
        "diagnostic": diagnostic,
        "prescriptive": prescriptive,
        "operations": operations,
    }, 200


@analytics_bp.route("/demographic-reports", methods=["GET"])
@jwt_required()
def get_demographic_reports():
    """Return official-registry-backed data used by Export Reports and its exports."""
    cur = mysql.connection.cursor()
    try:
        filters = parse_analytics_filters(request.args)
        filters["registration_type_supported"] = _registry_has_registration_type(
            cur)
        reg_all, reg_all_params = registry_sql("o", filters)

        cur.execute(
            "SELECT COUNT(*) AS n FROM official_registry o WHERE 1=1" + reg_all,
            reg_all_params,
        )
        total_businesses = cur.fetchone()["n"]

        cur.execute(
            """
            SELECT
                SUM(applicationStatus = 'Active') AS active_count,
                SUM(applicationStatus = 'Expired') AS expired_count,
                SUM(applicationStatus = 'Closed') AS closed_count,
                SUM(applicationStatus = 'Pending') AS pending_count,
                SUM(applicationStatus = 'Revoked') AS revoked_count
            FROM official_registry o
            WHERE 1=1
            """ + reg_all,
            reg_all_params,
        )
        status_counts = cur.fetchone()
        status_counts = {
            key: status_counts[key] or 0
            for key in (
                "active_count",
                "expired_count",
                "closed_count",
                "pending_count",
                "revoked_count",
            )
        }

        cur.execute(
            """
            SELECT COUNT(*) AS n
            FROM official_registry o
            WHERE YEAR(lastRenewalDate) = YEAR(CURDATE())
            """ + reg_all,
            reg_all_params,
        )
        current_year_count = cur.fetchone()["n"]

        cur.execute(
            """
            SELECT COUNT(*) AS n
            FROM official_registry o
            WHERE (
                (YEAR(lastRenewalDate) = YEAR(CURDATE()) AND applicationStatus = 'Active')
                OR YEAR(lastRenewalDate) = YEAR(CURDATE()) + 1
            )
            """ + reg_all,
            reg_all_params,
        )
        upcoming_year_renewal_count = cur.fetchone()["n"]

        registration_type_dist = []
        new_registration_count = 0
        renewal_registration_count = 0
        if filters["registration_type_supported"]:
            cur.execute(
                """
                SELECT COALESCE(registrationType, 'Unspecified') AS type_label,
                       COUNT(*) AS count
                FROM official_registry o
                WHERE 1=1
                """ + reg_all + """
                GROUP BY registrationType
                ORDER BY count DESC
                """,
                reg_all_params,
            )
            registration_type_dist = [
                {"type_label": row["type_label"], "count": row["count"]}
                for row in cur.fetchall()
            ]
            cur.execute(
                """
                SELECT
                    SUM(registrationType = 'New') AS new_count,
                    SUM(registrationType = 'Renewal') AS renewal_count
                FROM official_registry o
                WHERE 1=1
                """ + reg_all,
                reg_all_params,
            )
            registration_counts = cur.fetchone()
            new_registration_count = registration_counts["new_count"] or 0
            renewal_registration_count = registration_counts["renewal_count"] or 0

        cur.execute(
            """
            SELECT COALESCE(businessSize, 'Unknown') AS size_label, COUNT(*) AS count
            FROM official_registry o
            WHERE 1=1
            """ + reg_all + """
            GROUP BY businessSize
            ORDER BY count DESC
            """,
            reg_all_params,
        )
        business_size_dist = [
            {"size_label": row["size_label"], "count": row["count"]}
            for row in cur.fetchall()
        ]

        cur.execute(
            """
            SELECT COALESCE(businessType, 'Unknown') AS type_label, COUNT(*) AS count
            FROM official_registry o
            WHERE 1=1
            """ + reg_all + """
            GROUP BY businessType
            ORDER BY count DESC
            """,
            reg_all_params,
        )
        business_type_dist = [
            {"type_label": row["type_label"], "count": row["count"]}
            for row in cur.fetchall()
        ]

        cur.execute(
            """
            SELECT COALESCE(lineOfBusiness, 'Unclassified') AS sector, COUNT(*) AS count
            FROM official_registry o
            WHERE 1=1
            """ + reg_all + """
            GROUP BY lineOfBusiness
            ORDER BY count DESC
            """,
            reg_all_params,
        )
        sectoral_distribution = [
            {"sector": row["sector"], "count": row["count"]}
            for row in cur.fetchall()
        ]

        cur.execute(
            """
            SELECT COALESCE(b.barangayName, 'Unknown') AS barangayName,
                   COUNT(*) AS total
            FROM official_registry o
            LEFT JOIN barangays b ON o.barangayID = b.barangayID
            WHERE 1=1
            """ + reg_all + """
            GROUP BY b.barangayName
            ORDER BY b.barangayName
            """,
            reg_all_params,
        )
        nature_per_barangay = [
            {"barangayName": row["barangayName"], "total": row["total"]}
            for row in cur.fetchall()
        ]

        cur.execute(
            """
            SELECT COALESCE(businessSize, 'Unknown') AS size_label,
                   SUM(CASE WHEN applicationStatus = 'Active' THEN 1 ELSE 0 END) AS active_count,
                   SUM(CASE WHEN applicationStatus <> 'Active' THEN 1 ELSE 0 END) AS inactive_count
            FROM official_registry o
            WHERE 1=1
            """ + reg_all + """
            GROUP BY businessSize
            """,
            reg_all_params,
        )
        compliance_by_size = [
            {
                "size_label": row["size_label"],
                "active_count": row["active_count"] or 0,
                "inactive_count": row["inactive_count"] or 0,
            }
            for row in cur.fetchall()
        ]

        cur.execute(
            """
            SELECT DATE_FORMAT(lastRenewalDate, '%%Y-%%m') AS month,
                   SUM(CASE WHEN applicationStatus = 'Active' THEN 1 ELSE 0 END) AS active_count,
                   SUM(CASE WHEN applicationStatus <> 'Active' THEN 1 ELSE 0 END) AS non_active_count
            FROM official_registry o
            WHERE lastRenewalDate >= DATE_SUB(NOW(), INTERVAL 12 MONTH)
            """ + reg_all + """
            GROUP BY month
            ORDER BY month
            """,
            reg_all_params,
        )
        compliance_timeline = [
            {
                "month": row["month"],
                "active_count": row["active_count"] or 0,
                "non_active_count": row["non_active_count"] or 0,
            }
            for row in cur.fetchall()
        ]

        active_count = status_counts["active_count"]
        confirmed = confirmation_summary(current_confirmation_rows(
            cur, ladder=ladder_columns_available(cur),
            barangay_ids=filters.get("barangay_ids")))
        return jsonify({
            "data_source": "official_registry",
            "descriptive": {
                "kpis": {
                    "total_businesses": total_businesses,
                    **status_counts,
                    "new_registration_count": new_registration_count,
                    "renewal_registration_count": renewal_registration_count,
                    "current_year_count": current_year_count,
                    "current_year_registered_count": current_year_count,
                    "upcoming_year_renewal_count": upcoming_year_renewal_count,
                    "compliance_rate": round(
                        active_count / total_businesses * 100, 1
                    ) if total_businesses else 0,
                },
                "registration_type_available": filters["registration_type_supported"],
                "business_size_dist": business_size_dist,
                "business_type_dist": business_type_dist,
                "registration_type_dist": registration_type_dist,
                "sectoral_distribution": sectoral_distribution,
                "nature_per_barangay": nature_per_barangay,
                "compliance_by_size": compliance_by_size,
                "compliance_timeline": compliance_timeline,
                "confirmed_compliance": confirmed,
            },
        }), 200
    except Exception:
        current_app.logger.exception("Failed to load demographic report data")
        return jsonify({"error": "Failed to load demographic report data"}), 500
    finally:
        cur.close()


@analytics_bp.route("/filter-metadata", methods=["GET"])
@jwt_required()
def analytics_filter_metadata():
    """Distinct values for analytics filter controls (registry, flags, inspections)."""
    from app import mysql

    cur = mysql.connection.cursor()
    cur.execute(
        """
        SELECT DISTINCT applicationStatus AS v FROM official_registry
        WHERE applicationStatus IS NOT NULL AND TRIM(applicationStatus) <> ''
        ORDER BY applicationStatus
        """
    )
    application_statuses = [r["v"] for r in cur.fetchall()]

    cur.execute(
        """
        SELECT DISTINCT lineOfBusiness AS v FROM official_registry
        WHERE lineOfBusiness IS NOT NULL AND TRIM(lineOfBusiness) <> ''
        ORDER BY lineOfBusiness
        LIMIT 500
        """
    )
    lines_of_business = [r["v"] for r in cur.fetchall()]

    cur.execute(
        """
        SELECT DISTINCT businessType AS v FROM official_registry
        WHERE businessType IS NOT NULL AND TRIM(businessType) <> ''
        ORDER BY businessType
        LIMIT 500
        """
    )
    business_types = [r["v"] for r in cur.fetchall()]

    cur.execute(
        """
        SELECT DISTINCT businessSize AS v FROM official_registry
        WHERE businessSize IS NOT NULL AND TRIM(businessSize) <> ''
        ORDER BY businessSize
        """
    )
    business_sizes = [r["v"] for r in cur.fetchall()]

    registration_types = []
    if _registry_has_registration_type(cur):
        cur.execute(
            """
            SELECT DISTINCT registrationType AS v FROM official_registry
            WHERE registrationType IS NOT NULL AND TRIM(registrationType) <> ''
            ORDER BY registrationType
            """
        )
        registration_types = [r["v"] for r in cur.fetchall()]

    cur.execute(
        """
        SELECT DISTINCT inspectionResult AS v FROM inspection_reports
        WHERE inspectionResult IS NOT NULL AND TRIM(inspectionResult) <> ''
        ORDER BY inspectionResult
        """
    )
    inspection_results = [r["v"] for r in cur.fetchall()]

    cur.execute(
        """
        SELECT DISTINCT verificationStatus AS v FROM inspection_reports
        WHERE verificationStatus IS NOT NULL AND TRIM(verificationStatus) <> ''
        ORDER BY verificationStatus
        """
    )
    verification_statuses = [r["v"] for r in cur.fetchall()]

    cur.close()

    return jsonify({
        "flag_colors": ["Green", "Yellow", "Red", "Black", "Orange", "Purple"],
        "application_statuses": application_statuses,
        "lines_of_business": lines_of_business,
        "business_types": business_types,
        "business_sizes": business_sizes,
        "registration_types": registration_types,
        "inspection_results": inspection_results,
        "verification_statuses": verification_statuses,
    }), 200


# ─────────────────────────────────────────────────────────────────────────────
@analytics_bp.route("/ops-rankings", methods=["GET"])
@jwt_required()
def get_ops_rankings_only():
    """Lightweight endpoint to fetch real-time OPS priority rankings for the Maps/Dispatch UI."""
    cur = None
    try:
        cur = mysql.connection.cursor()
        ladder = ladder_columns_available(cur)
        effective_flag_color = _effective_flag_color_sql(
            "g", ladder=ladder)
        rankings, model = _load_prescriptive_rankings(cur, effective_flag_color, ladder, get_wlc_config())
        return jsonify({"data": rankings, "model": model}), 200
    except Exception:
        current_app.logger.exception("Failed to load OPS rankings")
        return jsonify({"error": "Failed to load OPS rankings"}), 500
    finally:
        if cur is not None:
            cur.close()


# ─────────────────────────────────────────────────────────────────────────────
@analytics_bp.route("/wlc-config", methods=["GET"])
@jwt_required()
def get_config():
    return jsonify(get_wlc_config()), 200


@analytics_bp.route("/wlc-config", methods=["PUT"])
@admin_required()
def update_config():
    data = request.get_json(silent=True)
    if not data:
        return jsonify({"error": "No configuration data provided."}), 400
    try:
        updated_config, error = update_wlc_config(data)
    except ValueError as error:
        return jsonify({"error": str(error)}), 400
    if error:
        return jsonify({"error": error}), 500
    return jsonify({"message": "WLC configuration updated successfully.", "data": updated_config}), 200


@analytics_bp.route("/wlc-config/reset", methods=["POST"])
@admin_required()
def reset_config_endpoint():
    updated_config, error = reset_wlc_config()
    if error:
        return jsonify({"error": error}), 500
    return jsonify({"message": "WLC configuration reset to default successfully.", "data": updated_config}), 200


@analytics_bp.route("/sector-policy", methods=["GET"])
@jwt_required()
def get_sector_policy():
    cur = mysql.connection.cursor()
    try:
        policy = load_persisted_sector_risk_policy(cur)
        return jsonify({
            "data": policy,
            "defaults": DEFAULT_SECTOR_RISK_POLICY,
        }), 200
    except Exception:
        current_app.logger.exception("Failed to load sector risk policy")
        return jsonify({"error": "Failed to load sector risk policy."}), 500
    finally:
        cur.close()


@analytics_bp.route("/sector-policy", methods=["PUT"])
@admin_required()
def update_sector_policy():
    data = request.get_json(silent=True)
    if data is None:
        return jsonify({"error": "Sector risk policy data is required."}), 400
    try:
        categories = validate_sector_risk_categories(data)
    except ValueError as error:
        return jsonify({"error": str(error)}), 400
    cur = mysql.connection.cursor()
    try:
        mysql.connection.begin()
        updated_policy = save_persisted_sector_risk_policy(
            cur, categories, int(get_jwt_identity())
        )
        mysql.connection.commit()
    except Exception:
        mysql.connection.rollback()
        current_app.logger.exception("Failed to persist sector risk policy")
        return jsonify({"error": "Failed to save sector risk policy."}), 500
    finally:
        cur.close()
    return jsonify({
        "message": "Sector risk policy updated successfully.",
        "data": updated_policy,
    }), 200


@analytics_bp.route("/sector-policy/reset", methods=["POST"])
@admin_required()
def reset_sector_policy():
    cur = mysql.connection.cursor()
    try:
        mysql.connection.begin()
        updated_policy = save_persisted_sector_risk_policy(
            cur,
            DEFAULT_SECTOR_RISK_POLICY["categories"],
            int(get_jwt_identity()),
        )
        mysql.connection.commit()
    except Exception:
        mysql.connection.rollback()
        current_app.logger.exception("Failed to reset sector risk policy")
        return jsonify({"error": "Failed to reset sector risk policy."}), 500
    finally:
        cur.close()
    return jsonify({
        "message": "Sector risk policy reset to defaults successfully.",
        "data": updated_policy,
    }), 200


@analytics_bp.route("/sector-policy/audit", methods=["GET"])
@admin_required()
def get_sector_policy_audit():
    try:
        limit = int(request.args.get("limit", 50))
    except ValueError as error:
        return jsonify({"error": str(error)}), 400
    cur = mysql.connection.cursor()
    try:
        rows = load_sector_risk_policy_audit(cur, limit)
        return jsonify({"data": rows}), 200
    except ValueError as error:
        return jsonify({"error": str(error)}), 400
    except Exception:
        current_app.logger.exception("Failed to load sector risk policy audit history")
        return jsonify({"error": "Failed to load sector risk policy audit history."}), 500
    finally:
        cur.close()


@analytics_bp.route("/sector-policy/preview", methods=["POST"])
@admin_required()
def preview_sector_policy():
    data = request.get_json(silent=True)
    if data is None:
        return jsonify({"error": "Sector policy preview data is required."}), 400
    try:
        categories = validate_sector_risk_categories(data)
    except ValueError as error:
        return jsonify({"error": str(error)}), 400

    cur = mysql.connection.cursor()
    try:
        ladder = ladder_columns_available(cur)
        effective_flag_color = _effective_flag_color_sql("g", ladder=ladder)
        current_policy = load_persisted_sector_risk_policy(cur)
        candidate_policy = {
            "version": current_policy["version"] + 1,
            "fallback_score": DEFAULT_SECTOR_RISK_POLICY["fallback_score"],
            "categories": categories,
        }
        rows = _load_prescriptive_rows(cur, effective_flag_color, ladder)
        current_rankings = calculate_rankings(
            rows, get_wlc_config(), current_policy
        )
        candidate_rankings = calculate_rankings(
            rows, get_wlc_config(), candidate_policy
        )
        old_by_id = {row["barangayID"]: row for row in current_rankings}
        new_by_id = {row["barangayID"]: row for row in candidate_rankings}
        selected_ids = {
            row["barangayID"] for row in current_rankings[:8]
        } | {
            row["barangayID"] for row in candidate_rankings[:8]
        }
        preview_rows = []
        for barangay_id in selected_ids:
            old = old_by_id[barangay_id]
            new = new_by_id[barangay_id]
            preview_rows.append({
                "barangayID": barangay_id,
                "barangayName": new["barangayName"],
                "old_ops": old["ops_score"],
                "old_rank": old["rank"],
                "new_ops": new["ops_score"],
                "new_rank": new["rank"],
            })
        preview_rows.sort(key=lambda row: (row["new_rank"], row["old_rank"]))
        return jsonify({
            "current_version": current_policy["version"],
            "proposed_version": candidate_policy["version"],
            "model_version": MODEL_VERSION,
            "rows": preview_rows,
        }), 200
    except Exception:
        current_app.logger.exception("Failed to preview sector risk policy")
        return jsonify({"error": "Failed to preview sector risk policy."}), 500
    finally:
        cur.close()


@analytics_bp.route("/chat", methods=["POST"])
@jwt_required()
def analytics_chat():
    data = request.get_json()
    chart_id = data.get("chartId")
    chart_data = data.get("data")
    messages = data.get("messages", [])
    user_query = data.get("userQuery")

    if not user_query:
        return jsonify({"error": "User query is required"}), 400

    gemini_api_key = os.environ.get("GEMINI_API_KEY")
    if not gemini_api_key:
        return jsonify({"error": "GEMINI_API_KEY is not configured in the backend environment."}), 500

    client = genai.Client(api_key=gemini_api_key)

    # ── Summarize global dashboard data so the LLM gets digestible context ──
    if chart_id == "global_dashboard" and isinstance(chart_data, dict):
        summary_parts = []

        # KPIs
        kpis = chart_data.get("kpis", {})
        if kpis:
            summary_parts.append(f"KPIs: {json.dumps(kpis)}")

        # Geographic (barangay breakdown) – all barangays
        geo = chart_data.get("geographic", [])
        if geo:
            try:
                sorted_geo = sorted(geo, key=lambda x: sum(v for k, v in x.items(
                ) if k != "barangay" and isinstance(v, (int, float))), reverse=True)
            except Exception:
                sorted_geo = geo
            summary_parts.append(
                f"All Barangays (by business volume, highest first): {json.dumps(sorted_geo)}")

        # Sectoral (business lines) – all sectors
        sectors = chart_data.get("sectoral", [])
        if sectors:
            try:
                sorted_sectors = sorted(sectors, key=lambda x: x.get(
                    "count", x.get("value", 0)), reverse=True)
            except Exception:
                sorted_sectors = sectors
            summary_parts.append(
                f"All Business Sectors (by count, highest first): {json.dumps(sorted_sectors)}")

        # Business sizes
        sizes = chart_data.get("size", [])
        if sizes:
            summary_parts.append(
                f"Business Size Distribution: {json.dumps(sizes)}")

        # Legal structure
        legal = chart_data.get("legalStructure", [])
        if legal:
            summary_parts.append(
                f"Business Legal Structure: {json.dumps(legal)}")

        # Compliance by size
        comp_size = chart_data.get("complianceBySize", [])
        if comp_size:
            summary_parts.append(
                f"Compliance by Business Size: {json.dumps(comp_size)}")

        # Compliance timeline
        timeline = chart_data.get("complianceTimeline", [])
        if timeline:
            summary_parts.append(
                f"Compliance Timeline (12 months): {json.dumps(timeline)}")

        # Enforcement / Flag breakdown (aggregate totals across all barangays)
        enforcement = chart_data.get("enforcement", [])
        if enforcement:
            total_green = sum(b.get("green_count", 0) for b in enforcement)
            total_red = sum(b.get("red_count", 0) for b in enforcement)
            total_yellow = sum(b.get("yellow_count", 0) for b in enforcement)
            total_black = sum(b.get("black_count", 0) for b in enforcement)
            total_orange = sum(b.get("orange_count", 0) for b in enforcement)
            flag_summary = {
                "green_flags": total_green,
                "yellow_flags": total_yellow,
                "red_flags": total_red,
                "black_flags": total_black,
                "orange_flags": total_orange,
                "total_non_green_flags": total_red + total_yellow + total_black + total_orange
            }
            summary_parts.append(
                f"Flag Color Breakdown (system-wide totals): {json.dumps(flag_summary)}")
            # Also include top flagged barangays
            flagged_barangays = [b for b in enforcement if (b.get("red_count", 0) + b.get(
                "yellow_count", 0) + b.get("black_count", 0) + b.get("orange_count", 0)) > 0]
            if flagged_barangays:
                flagged_barangays.sort(key=lambda x: x.get("red_count", 0) + x.get(
                    "yellow_count", 0) + x.get("black_count", 0) + x.get("orange_count", 0), reverse=True)
                summary_parts.append(
                    f"Barangays with non-green flags: {json.dumps(flagged_barangays[:10])}")

        spatial = chart_data.get("spatialDiagnostics", {})
        if spatial:
            nearby = spatial.get("nearbyFlaggedGroups", {})
            if nearby:
                summary_parts.append(
                    "Nearby flagged spatial groups (DBSCAN; analysisAvailable=false means insufficient/unavailable data, "
                    "not a finding of zero groups; group count is the number of spatial groups, "
                    "recordCount is the number of geospatial records in that group, not distinct businesses): "
                    f"{json.dumps(nearby)}"
                )
            severe_by_barangay = spatial.get("severeFlagsByBarangay", {})
            if severe_by_barangay:
                summary_parts.append(
                    "Severe flags by barangay (analysisAvailable=false means unavailable, not zero flags; "
                    "distinct geospatial record counts, not spatial groups; "
                    "highCountBarangayCount is the number of barangays strictly above the chart benchmark): "
                    f"{json.dumps(severe_by_barangay)}"
                )

        # Audit summary
        audit = chart_data.get("audit", {})
        if audit:
                summary_parts.append(
                    f"Inspection/Audit Summary (total_reports counts all reports; result_breakdown counts admin-verified reports only; workflow separates submitted from verified): {json.dumps(audit)}")
        confirmed = chart_data.get("confirmedCompliance", {})
        if confirmed:
            summary_parts.append(
                "Current Green businesses with qualifying confirmation history, classified once by their latest valid source (office confirmation is not an inspection; this is not the entire Green registry census): "
                f"{json.dumps(confirmed)}")

        # Barangay risk data (diagnostic) – top 10
        brgy_risk = chart_data.get("barangayRisk", [])
        if brgy_risk:
            summary_parts.append(
                "Top barangay non-Green flagged-record totals (all non-Green colors; "
                "separate from the Red/Black geolocated severe-flags chart and from OPS rankings): "
                f"{json.dumps(brgy_risk[:10])}")

        # Sector status metrics use only unique registry matches.
        category_risk_drivers = chart_data.get("categoryRiskDrivers", [])
        category_linkage = chart_data.get("categoryLinkageSummary", {})
        if category_risk_drivers:
            summary_parts.append(
                "Registry-linked non-Green records by sector (current status, not confirmed violations): "
                f"{json.dumps(category_risk_drivers)}")
        if category_linkage:
            summary_parts.append(
                "Flagged-record registry linkage summary (unique trimmed-name + barangay matches): "
                f"{json.dumps(category_linkage)}")

        # Detection scan history is municipality-wide and independent of dashboard filters.
        scan_history = chart_data.get("scanHistory", [])
        if scan_history:
            summary_parts.append(
                "Detection Scan History (municipality-wide): "
                f"{json.dumps(scan_history)}. Scan yield is new flags divided by raw Places results checked; "
                "it is not classification accuracy, and partial runs are incomplete and not directly comparable."
            )

        # ── PRESCRIPTIVE TIER ──

        # OPS/WLC Rankings (sorted by ops_score descending)
        ops_rankings = chart_data.get("opsRankings", [])
        if ops_rankings:
            # Include key fields only to keep concise
            slim_rankings = [{
                "rank": r.get("rank"),
                "barangay": r.get("barangayName"),
                "ops_score": r.get("ops_score"),
                "risk_score": r.get("risk_score"),
                "sector_score": r.get("sector_score"),
                "distance_score": r.get("distance_score"),
                "risk_level": r.get("risk_level"),
                "flagged_count": r.get("flagged_count"),
                "dispatchable_count": r.get("dispatchable_count"),
                "registry_active_flag_rate": r.get("registry_active_flag_rate"),
                "unregistered_candidate_count": r.get("unregistered_candidate_count"),
            } for r in ops_rankings]
            summary_parts.append(
                f"OPS Priority Rankings (WLC-based municipal ranks; the displayed list may be barangay-filtered): {json.dumps(slim_rankings)}")

        # WLC Config (weights)
        wlc_config = chart_data.get("wlcConfig", {})
        if wlc_config:
            summary_parts.append(
                f"WLC Weight Configuration: {json.dumps(wlc_config)}")
        wlc_model = chart_data.get("wlcModel", {})
        if wlc_model:
            summary_parts.append(f"WLC model (configured weights are applied unchanged; sector input coverage is disclosed separately): {json.dumps(wlc_model)}")
        workforce = chart_data.get("dispatchWorkforce", {})
        if workforce:
            summary_parts.append(f"Dispatch workforce availability: {json.dumps(workforce)}")

        # Dispatch Recommendations
        dispatch = chart_data.get("dispatchRecommendations", [])
        if dispatch:
            summary_parts.append(
                f"Dispatch Recommendations: {json.dumps(dispatch[:10])}")

        # ── OPERATIONS TIER ──

        # Inspector stats
        inspector_stats = chart_data.get("inspectorStats", [])
        if inspector_stats:
            summary_parts.append(
                f"Inspector Performance Stats (this list includes ALL active "
                f"inspectors — entries with zero assigned tasks are idle, not "
                f"missing): {json.dumps(inspector_stats)}"
            )
            summary_parts.append(
                f"Total active inspectors: {len(inspector_stats)}"
            )

        # Status breakdown
        status_breakdown = chart_data.get("statusBreakdown", [])
        if status_breakdown:
            summary_parts.append(
                f"Inspection Status Breakdown: {json.dumps(status_breakdown)}")

        # Inspection timeline
        insp_timeline = chart_data.get("inspectionTimeline", [])
        if insp_timeline:
            summary_parts.append(
                f"Inspection Timeline (monthly): {json.dumps(insp_timeline)}")

        data_context = "\n".join(
            summary_parts) if summary_parts else "No data available."

        system_message = (
            "You are the REVELA AI Analyst — the built-in analytics assistant for REVELA.\n\n"

            "## About REVELA\n"
            "REVELA is a Geospatial Business Intelligence System for Compliance Monitoring and Non-Registered Business Detection. "
            "It is a web-based platform used by the Business Permits and Licensing Office (BPLO) of a "
            "local government unit (municipality) in the Philippines (Mataansnakahoy, Batangas). It digitizes the management of "
            "business permits, regulatory compliance, and enforcement operations.\n\n"

            "## Key Domain Concepts\n"
            "- **Official Registry**: The master list of all businesses registered in the municipality. "
            "Each business has an application status: Active (permit is current), Expired (permit lapsed and was not renewed), "
            "Closed (business voluntarily closed), Revoked (permit was revoked by the LGU), or Pending (application is being processed).\n"
            "- **Barangays**: The smallest administrative division in the Philippines. Businesses are grouped by barangay.\n"
            "- **Business Size**: Classified as Micro, Small, Medium, or Large based on asset size per Philippine DTI standards.\n"
            "- **Lines of Business**: The industry or trade a business operates in (e.g., 'Retail selling', 'Renting or leasing').\n"
            "- **Flag System**: Businesses can be flagged with color-coded flags during inspections or reviews:\n"
            "  - Green = Fully compliant\n"
            "  - Yellow = Suspected of being unregistered, needs attention\n"
            "  - Red = Registration or permit-renewal verification needed, not a confirmed violation\n"
            "  - Black = Critical / ordered to cease operations\n"
            "  - Orange = Under investigation or special monitoring\n"
            "  - Purple = Confirmed closed or permanently abandoned establishment\n"
            "- **Compliance Rate**: Percentage of businesses with Active status out of total registered.\n"
            "- **Inspections**: Field inspections conducted by municipal inspectors. A business may have zero inspections "
            "if it has not yet been scheduled — this is normal, especially for newly registered businesses or if the "
            "inspection program is still being rolled out.\n"
            "- **Compliance by Size**: Shows how many Active vs Non-Active businesses exist per size category. "
            "'Non-Active' includes Expired, Closed, and Pending — it does NOT necessarily mean the business is violating rules, unless the status is Revoked (which means the business is a notorious offender).\n"
            "- **Compliance Timeline**: Monthly trend of active vs non-active business counts over the past 12 months.\n"
            "- **Barangay Risk**: Diagnostic data showing which barangays have the highest concentration of non-compliant businesses.\n"
            "- **Registry-linked status by sector**: Current non-Green records with a unique registry match, shown against registry counts; this is not a confirmed-violation rate. Unlinked and ambiguous records have no sector attribution.\n"
            "- **Detection Scan History**: Municipality-wide completed and partial scan attempts. Scan yield is a raw operational measure, not classification accuracy.\n"
            "- **OPS Score (Operational Priority Score)**: A composite score (0-100) computed using WLC (Weighted Linear Combination) "
            "that ranks barangays by inspection priority. Higher score = higher priority for dispatching inspectors.\n"
            "- **WLC Weights**: The OPS score is computed from three weighted sub-scores:\n"
            "  - Risk Score (w1): 100*(3*Red + 2*Yellow + 4*Black)/largest municipal weighted flag burden; zero if no flags exist\n"
            f"  - Sector Score (w2): {SECTOR_RISK_ASSISTANT_GUIDANCE}\n"
            "  - Proximity Score (w3): 100 minus normalized straight-line BPLO distance, using active-flag locations; missing locations use neutral proximity 50\n"
            "  - OPS = w1*Risk + w2*Sector + w3*Proximity using effective weights. It is a relative priority score, NOT violation probability. Barangay display filters preserve municipal ranks; other dashboard filters do not change operational scores\n"
            "- **Registry active-flag rate**: Unique current Red/Yellow/Black registry businesses / all registry businesses; null means N/A. Not a confirmed non-compliance rate. Unregistered candidates are a separate count\n"
            "- **Risk Level**: Derived from OPS score — High (>=60), Medium (>=30), Low (<30)\n"
            "- **Dispatch Recommendations**: Deterministic WLC-ranked plans, not AI-generated allocations. High priority starts at OPS 60, Standard at 30, Monitor below 30. Only currently free inspectors are allocated (maximum six). Deferred plans have zero inspectors; never invent staffing or promise a deployment date for them. Black-only barangays and already-assigned targets are skipped: dispatchable_count must be positive for a new field plan. Black flags are administrative risk context, never an authorization for redispatch\n"
            "- **Nearby flagged records (DBSCAN)**: Uses eligible geospatial log records with effective Red flag, detection origin, coordinates, no businessID, and no registry link. This is the shared population used by Analytics and Map cluster views. Each dot and group size counts detection records, not distinct businesses. Uses Haversine distance and the shared configurable parameters (default eps=50 m, min_samples=3 including the point itself); the actual settings are included in dbscan_insight. Connected neighborhoods can extend beyond eps end-to-end, and groups may cross barangay boundaries. Isolated eligible records are noise, not clusters. The number of groups is not the number of records in a group\n"
            "- **Severe flags by barangay**: Separately counts distinct eligible geospatial log IDs with effective Red or Black flags and coordinates, grouped within barangay boundaries. Its dashed benchmark is NumPy's 75th percentile (default linear interpolation) of those counts across geolocated barangays; at least four such barangays are required, and only positive counts strictly above the benchmark are highlighted. A high count is not a spatial group\n"
            "- **Filters for these two spatial charts**: DBSCAN applies selected barangay, effective flag-color, and detection-date filters to eligible effective-Red detection pins; a selected flag color further narrows the effective-Red input. The separate severe-flags chart counts effective Red or Black records and also applies those geospatial filters. Registry/business and inspection filters do not affect these calculations\n"
            "- **Unavailable chart data**: In spatialDiagnostics, analysisAvailable=false means the corresponding chart could not be calculated from sufficient available data; do not present empty arrays or zero counts as evidence that there were no groups or severe flags\n"
            "- **Keep spatial measures distinct**: Spatial-group count, records per group, number of above-benchmark barangays, and OPS/WLC inspection-priority rankings are different measures. OPS rankings are not calculated from the number of DBSCAN groups or from the chart's above-benchmark count. Neither proximity nor a high count proves a violation or its cause\n"
            "- **Inspector Stats**: Performance metrics for individual inspectors (inspections completed, resolution time, etc.).\n"
            "- **Inspection Status Breakdown**: Distribution of inspection statuses (Pending, In Progress, Completed, etc.).\n\n"

            "## Important Guidelines\n"
            "- Do NOT flag zero inspections as an anomaly — inspections are conducted on a rolling schedule and many businesses may not have been inspected yet.\n"
            "- 'Non-Active' in compliance charts means the business status is not 'Active' — it includes Expired, Closed, and Pending. Do not confuse this with violations unless the status is Revoked (which means the business is a notorious offender).\n"
            "- ALWAYS respect the numerical 'rank' exactly as provided in the OPS Priority Rankings and Dispatch Recommendations. Do NOT re-order barangays yourself (e.g. do not promote a lower-ranked barangay above a higher-ranked one just because of flag colors). Follow the exact WLC-computed ranking order.\n"
            "- When discussing compliance, frame it in terms of permit renewal and regulatory status, not moral judgments.\n"
            "- Be helpful to BPLO staff — suggest actionable next steps like 'consider prioritizing inspections in Barangay X' or 'the high proportion of Micro businesses suggests focusing outreach on small enterprise compliance'.\n"
            "- Use Filipino-friendly language when appropriate (e.g., barangay, BPLO).\n\n"

            "## Dashboard Data\n"
            f"{data_context}\n\n"
            "Answer questions concisely, professionally, and accurately based ONLY on this data. "
            "Use specific numbers to support your answers. "
            "If asked about trends or insights, provide actionable recommendations relevant to BPLO operations."
        )
    else:
        # Single chart mode (legacy)
        system_message = (
            f"You are the REVELAsys Analytics AI Assistant. "
            f"You help users understand their business registry and enforcement data. "
            f"The user is asking about the '{chart_id}' chart. "
            f"Here is the JSON data for this chart: {chart_data}. "
            f"Answer their questions concisely, professionally, and accurately based ONLY on this data."
        )

    try:
        contents = []
        for msg in messages:
            role = "user" if msg.get("role") == "user" else "model"
            content_text = msg.get("content", "")
            if content_text:
                contents.append(types.Content(
                    role=role,
                    parts=[types.Part.from_text(text=content_text)]
                ))

        contents.append(types.Content(
            role="user",
            parts=[types.Part.from_text(text=user_query)]
        ))

        global _CACHED_GEMINI_MODEL

        models_to_try = _get_candidate_gemini_models(
            client, force_refresh=False)
        response = None
        last_error = None

        for m in models_to_try:
            try:
                response = client.models.generate_content(
                    model=m,
                    contents=contents,
                    config=types.GenerateContentConfig(
                        system_instruction=system_message,
                        temperature=0.4,
                        max_output_tokens=2048,
                    )
                )
                if response and response.text:
                    _CACHED_GEMINI_MODEL = m
                    break
            except Exception as me:
                print(f"[Gemini] Model '{m}' failed: {me}")
                last_error = me
                continue

        # If cached candidates failed (e.g. model version expired), force refresh discovery once and retry
        if not response or not response.text:
            refreshed_models = _get_candidate_gemini_models(
                client, force_refresh=True)
            for m in refreshed_models:
                if m in models_to_try:
                    continue
                try:
                    response = client.models.generate_content(
                        model=m,
                        contents=contents,
                        config=types.GenerateContentConfig(
                            system_instruction=system_message,
                            temperature=0.4,
                            max_output_tokens=2048,
                        )
                    )
                    if response and response.text:
                        _CACHED_GEMINI_MODEL = m
                        print(
                            f"[Gemini] Switched and cached new active model: '{m}'")
                        break
                except Exception as me:
                    last_error = me
                    continue

        if not response or not response.text:
            raise last_error or Exception(
                "No response returned by the Gemini AI model.")

        return jsonify({
            "response": response.text
        }), 200
    except Exception as e:
        traceback.print_exc()
        return jsonify({"error": f"AI Assistant Error: {str(e)}"}), 500
