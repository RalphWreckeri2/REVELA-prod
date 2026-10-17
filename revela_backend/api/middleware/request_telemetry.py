"""Behavior-neutral request telemetry for the REVELA API.

Emits one structured line per request so the duration of a single slow call
(for example ``/api/analytics/all``) can be separated from browser-side
queueing. It also owns the shared ``revela`` logger namespace that the
analytics-cache and SSE-hub counters log through, so all three measurements
land in one stream.

Design constraints:

  * No request bodies, headers, tokens, query values or personal data are
    logged. Only the route, method, status, duration, size and a random id.
  * Response bodies are never touched; streaming (SSE) responses are not
    materialised, so the logged duration for a stream is time-to-first-byte.
  * Idempotent: safe to call once per application-factory invocation,
    including the repeated ``create_app()`` calls the CORS tests make.

Environment knobs (all optional):

  * ``REVELA_LOG_LEVEL``       - level for the ``revela`` logger (default INFO)
  * ``REVELA_SLOW_REQUEST_MS`` - duration at/above which a request is logged at
                                 WARNING as well (default 1500 ms)
"""

import logging
import os
import re
import sys
import time
import uuid

from flask import g, request

_LOGGER_NAME = "revela"
_CONFIGURED = False

_DEFAULT_SLOW_MS = 1500.0

#: A client-supplied correlation id is accepted only if it looks like a simple
#: token, so a crafted header cannot forge or inject log lines. The frontend
#: does not send one yet; the id is then generated server-side.
_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,40}$")


def get_logger(suffix=None):
    """Return the shared ``revela`` logger, or one of its children."""
    if suffix:
        return logging.getLogger("%s.%s" % (_LOGGER_NAME, suffix))
    return logging.getLogger(_LOGGER_NAME)


def configure_logging():
    """Ensure telemetry lines reach stdout once, at INFO, without duplicates."""
    global _CONFIGURED
    if _CONFIGURED:
        return
    logger = logging.getLogger(_LOGGER_NAME)
    if not logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s")
        )
        logger.addHandler(handler)
    logger.setLevel(os.getenv("REVELA_LOG_LEVEL", "INFO").upper())
    # Own the output so records are not also bubbled to the root logger.
    logger.propagate = False
    _CONFIGURED = True


def _slow_threshold_ms():
    try:
        return float(os.getenv("REVELA_SLOW_REQUEST_MS", _DEFAULT_SLOW_MS))
    except (TypeError, ValueError):
        return _DEFAULT_SLOW_MS


def _request_id():
    supplied = request.headers.get("X-Request-ID", "")
    if supplied and _ID_RE.match(supplied):
        return supplied
    return uuid.uuid4().hex[:12]


def init_app(app):
    """Register request timing hooks on ``app``. Call once per app factory."""
    configure_logging()
    logger = get_logger("request")
    slow_ms = _slow_threshold_ms()

    @app.before_request
    def _telemetry_start():
        g._revela_start = time.perf_counter()
        g._revela_id = _request_id()

    @app.after_request
    def _telemetry_end(response):
        start = getattr(g, "_revela_start", None)
        request_id = getattr(g, "_revela_id", None) or "-"
        # Echo the id so a slow DevTools entry can be matched to a log line.
        response.headers["X-Request-ID"] = request_id
        if start is None:
            return response

        duration_ms = (time.perf_counter() - start) * 1000.0
        rule = request.url_rule.rule if request.url_rule else request.path
        size = response.content_length
        streamed = 1 if response.is_streamed else 0
        message = (
            "[req] id=%s method=%s route=%s status=%s dur_ms=%.1f bytes=%s stream=%d"
        )
        args = (
            request_id,
            request.method,
            rule,
            response.status_code,
            duration_ms,
            size if size is not None else "-",
            streamed,
        )
        if duration_ms >= slow_ms:
            logger.warning(message, *args)
        else:
            logger.info(message, *args)
        return response
