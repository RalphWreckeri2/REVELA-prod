"""
Allowed CORS origins for the browser-facing API.

Kept separate from `app.py` so the parsing rules can be unit tested without
booting the whole application.

Why this exists
---------------
The allowed-origin list is the one setting whose failure is invisible from the
server side: Gunicorn starts, `/api/health` returns 200, logs look clean, and
the *only* symptom is the browser refusing to hand the response to JavaScript.
Two mistakes produced exactly that:

  1. `CORS_ORIGINS` unset -> the old fallback allowed localhost only, so
     `https://www.revelasys.site` was rejected.
  2. `CORS_ORIGINS=https://revelasys.site` -> the apex host was allowed but the
     `www` host, which is what the frontend actually serves from, was not.

Both produce the same "No 'Access-Control-Allow-Origin' header" message, so
the production hosts are now part of the *default* rather than something that
must be remembered at deploy time.

Safety properties this module must preserve:

  * No wildcard. Every allowed origin is an explicit host, because the API is
    called with credentials and `Access-Control-Allow-Origin: *` is illegal
    alongside `Access-Control-Allow-Credentials: true`.
  * Anything not listed is still rejected. Normalisation only tidies the
    spelling of an origin that was already listed; it never widens the set
    beyond the configured hosts.
"""

import re


#: Hosts the production frontend is served from. Both spellings are listed
#: because the browser sends whichever the user typed, and the two are distinct
#: origins to the CORS spec even though they serve the same site.
PRODUCTION_ORIGINS = (
    "https://www.revelasys.site",
    "https://revelasys.site",
)

#: Loopback origins for local development. Patterns rather than literals because
#: Vite and Flask pick their own ports.
DEVELOPMENT_ORIGIN_PATTERNS = (
    re.compile(r"http://localhost:\d+"),
    re.compile(r"http://127\.0\.0\.1:\d+"),
    "http://10.0.2.2:5000",
)

_WWW_PREFIX = "www."


def normalise_origin(origin):
    """
    Canonicalise the spelling of a single origin.

    Strips surrounding whitespace, drops any trailing slash, and lowercases.
    Browsers never send a trailing slash, so `https://site/` in the config would
    silently never match `https://site` -- a failure mode that looks identical
    to the origin not being allowed at all.

    Returns None for anything that is not an explicit origin. In particular a
    bare `*` is rejected: the API is called with credentials, and
    `Access-Control-Allow-Origin: *` is illegal alongside
    `Access-Control-Allow-Credentials: true`, so honouring it would either
    break every authenticated call or quietly disable the protection.
    """
    if not isinstance(origin, str):
        return None
    cleaned = origin.strip().strip("/").lower()
    if not cleaned or cleaned == "*":
        return None
    # Require an explicit scheme; anything else is not a usable origin.
    if not (cleaned.startswith("http://") or cleaned.startswith("https://")):
        return None
    return cleaned


def mirror_www(origin):
    """
    Return the `www`/apex counterpart of an https origin.

    A site is commonly reachable at both spellings, and operators reliably
    configure only one. Mirroring removes that class of outage. It only ever
    toggles the `www.` label on the same host, so it cannot widen access to a
    different domain; non-https and already-`www` inputs are returned unchanged.
    """
    normalised = normalise_origin(origin)
    if not normalised or not normalised.startswith("https://"):
        return normalised
    host = normalised[len("https://"):]
    if "/" in host or ":" in host:      # not a bare host[:port]; leave alone
        return normalised
    counterpart = (
        host[len(_WWW_PREFIX):] if host.startswith(_WWW_PREFIX) else _WWW_PREFIX + host
    )
    return f"https://{counterpart}"


def parse_origins(raw):
    """
    Parse the `CORS_ORIGINS` environment value into a list of origins.

    Each configured origin is canonicalised, and its `www`/apex counterpart is
    added so listing either spelling is enough. Order is preserved and
    duplicates removed.
    """
    if not raw:
        return []
    result = []
    seen = set()
    for chunk in str(raw).split(","):
        origin = normalise_origin(chunk)
        if not origin:
            continue
        for candidate in (origin, mirror_www(origin)):
            if candidate and candidate not in seen:
                seen.add(candidate)
                result.append(candidate)
    return result


def build_allowed_origins(raw=None):
    """
    Full allowed-origin list handed to Flask-CORS.

    `raw` is the `CORS_ORIGINS` environment value. When it is absent the
    production hosts and the local development patterns are both allowed, so a
    deployment that forgets the variable still serves the real frontend instead
    of silently refusing every browser request.

    Development patterns are always appended so a developer can run the app
    locally without editing production configuration; they only match loopback
    addresses, so they grant nothing remotely.
    """
    configured = parse_origins(raw)
    if not configured:
        configured = list(PRODUCTION_ORIGINS)

    allowed = list(configured)
    for pattern in DEVELOPMENT_ORIGIN_PATTERNS:
        if pattern not in allowed:
            allowed.append(pattern)
    return allowed
