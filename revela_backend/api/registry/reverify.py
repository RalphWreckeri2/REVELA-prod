"""
api/registry/reverify.py

Re-verify pins that already have coordinates.

Why this exists
---------------
snap_unresolved_pins only fills EMPTY coordinates. Pins that already have coordinates
(a centroid shared by dozens of businesses, old address geocodes, imports with no recorded
source) are never revisited, so the map keeps showing them in the wrong place.
This module revisits exactly those pins, looks each business up again on Google Places,
and moves the pin onto the real place when the match is confident.

Safety rules
------------
* manual / places-verified / approved / rejected rows are never touched
* an explicit CSV coordinate is only revisited when it is stacked (STACK_MIN+ businesses
  on one point), because a stack cannot be right
* a Google place already claimed by another business is not claimed twice
* every attempt is written to registry_pin_history (old + new coordinates), so any move
  can be undone, and recently checked businesses are skipped (no repeated API spend)
* uncertain matches are moved to the candidate but flagged matchStatus='review'
  so the existing review queue shows them to an admin

Cost: one Places Text Search per checked business (plus an optional quality-gated
geocode fallback inside the resolver). The resolver's own daily/monthly caps still apply.
"""
import math
import threading
import traceback
from collections import Counter

STACK_MIN = 3               # businesses on one point (to ~1 m) before it counts as a stack
SKIP_RECENT_DAYS = 30       # do not re-check a business attempted within this many days
VERIFIED_WITHIN_M = 5       # Google place this close to the old pin = old pin was right
MAX_CONSECUTIVE_ERRORS = 5

SUSPECT_COLS = (
    "businessID", "barangayID", "businessName", "businessAddress", "lineOfBusiness",
    "applicationStatus", "coordSource", "matchStatus", "latitude", "longitude",
)

_run_lock = threading.Lock()


def is_running():
    return _run_lock.locked()


# ----------------------------------------------------------------------------
# Pure logic (no database, no network) -- covered by test_reverify.py
# ----------------------------------------------------------------------------
def _as_dict(row, cols=SUSPECT_COLS):
    return dict(row) if isinstance(row, dict) else dict(zip(cols, row))


def _has_coords(row):
    return row.get("latitude") is not None and row.get("longitude") is not None


def stack_key(lat, lng):
    """Round to 5 decimals (~1 m): businesses with the same key share one point."""
    return (round(float(lat), 5), round(float(lng), 5))


def distance_m(a, b):
    """Haversine distance in metres between two (lat, lng) pairs."""
    lat1, lon1, lat2, lon2 = map(math.radians, (float(a[0]), float(a[1]), float(b[0]), float(b[1])))
    h = math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    return 2 * 6371000.0 * math.asin(math.sqrt(h))


def classify_suspect(row, stack_size):
    """Return why this pin looks unreliable, or None if it should be left alone."""
    if not _has_coords(row):
        return None                       # empty coordinates are the Snap feature's job
    src = row.get("coordSource")
    if src in ("manual", "places"):
        return None                       # human-placed or already Places-verified
    if row.get("matchStatus") in ("approved", "rejected"):
        return None
    if stack_size >= STACK_MIN:
        return "stacked"                  # many businesses on one point cannot all be right
    if src == "csv":
        return None                       # trust an explicit, non-stacked CSV coordinate
    if src == "geocode":
        return "address_geocode"          # address-level guess, never checked against Places
    return "no_provenance"                # coordinates with no recorded source


def build_suspects(rows):
    """rows: iterable of dicts/tuples (SUSPECT_COLS). Returns (suspects, stack_sizes)."""
    rows = [_as_dict(r) for r in rows]
    sizes = Counter(stack_key(r["latitude"], r["longitude"]) for r in rows if _has_coords(r))
    suspects = []
    for r in rows:
        if not _has_coords(r):
            continue
        n = sizes[stack_key(r["latitude"], r["longitude"])]
        reason = classify_suspect(r, n)
        if reason:
            suspects.append({**r, "reason": reason, "stackSize": n})
    suspects.sort(key=lambda r: (-r["stackSize"], str(r["businessID"])))   # biggest stacks first
    return suspects, sizes


def summarize(suspects, sizes, skipped_recent=0):
    by_reason = Counter(s["reason"] for s in suspects)
    stacks = [
        {"lat": k[0], "lng": k[1], "businesses": n}
        for k, n in sizes.most_common(5) if n >= STACK_MIN
    ]
    return {
        "total": len(suspects),
        "byReason": dict(by_reason),
        "largestStacks": stacks,
        "skippedRecentlyChecked": skipped_recent,
        "estimatedPlacesCalls": len(suspects),
    }


def plan_outcome(old, new, meta, conflict=False, barangay_ok=True):
    """
    Decide what to do with a lookup result.
      unresolved - Google found nothing usable        -> keep the old pin, log it
      conflict   - place already claimed by another   -> keep the old pin, log it
      verified   - Google place is within a few m of the old pin -> record provenance only
      moved      - confident match in the right barangay -> move registry + map pin
      review     - uncertain match                    -> move to candidate, flag for review
    """
    if new is None or new[0] is None or new[1] is None:
        return "unresolved"
    if conflict:
        return "conflict"
    if old and old[0] is not None and old[1] is not None and distance_m(old, new) < VERIFIED_WITHIN_M:
        return "verified"
    if (meta or {}).get("match_status") == "auto" and barangay_ok:
        return "moved"
    return "review"


# ----------------------------------------------------------------------------
# Database helpers
# ----------------------------------------------------------------------------
_HISTORY_DDL = """
CREATE TABLE IF NOT EXISTS registry_pin_history (
  id BIGINT AUTO_INCREMENT PRIMARY KEY,
  businessID VARCHAR(50) COLLATE utf8mb4_unicode_ci NOT NULL,
  attemptedAt DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  outcome VARCHAR(20) NOT NULL,
  reason VARCHAR(30) NULL,
  stackSize INT NULL,
  oldLat DECIMAL(10,8) NULL, oldLng DECIMAL(11,8) NULL,
  newLat DECIMAL(10,8) NULL, newLng DECIMAL(11,8) NULL,
  placeID VARCHAR(255) COLLATE utf8mb4_unicode_ci NULL,
  score DECIMAL(4,3) NULL,
  KEY idx_pinhist_business (businessID, attemptedAt)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
"""


def _ensure_history_table(cur):
    cur.execute(_HISTORY_DDL)


def _load_rows(cur):
    cur.execute(
        "SELECT " + ", ".join(SUSPECT_COLS) + " FROM official_registry "
        "WHERE latitude IS NOT NULL AND longitude IS NOT NULL"
    )
    return cur.fetchall()


def _recent_ids(cur):
    cur.execute(
        "SELECT DISTINCT businessID FROM registry_pin_history "
        "WHERE attemptedAt > NOW() - INTERVAL %s DAY", (SKIP_RECENT_DAYS,)
    )
    out = set()
    for r in cur.fetchall():
        out.add(r["businessID"] if isinstance(r, dict) else r[0])
    return out


def _claimed_by_other(cur, place_id, business_id):
    if not place_id:
        return False
    cur.execute(
        "SELECT businessID FROM official_registry "
        "WHERE placeID = %s AND placeIDKind = 'poi' AND businessID <> %s LIMIT 1",
        (place_id, business_id),
    )
    return cur.fetchone() is not None


def _barangay_ok(lat, lng, expected_barangay_id):
    """True when the point lies in the business's registered barangay (or cannot be checked)."""
    if expected_barangay_id is None:
        return True
    try:
        from api.flags.service import _get_barangay_id_by_coords
        found = _get_barangay_id_by_coords(lat, lng)
    except Exception:
        return True                       # cannot check -> do not block
    return found is None or int(found) == int(expected_barangay_id)


def _log_attempt(cur, biz, outcome, new=None, place_id=None, score=None):
    cur.execute(
        """INSERT INTO registry_pin_history
           (businessID, outcome, reason, stackSize, oldLat, oldLng, newLat, newLng, placeID, score)
           VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
        (biz["businessID"], outcome, biz.get("reason"), biz.get("stackSize"),
         biz.get("latitude"), biz.get("longitude"),
         new[0] if new else None, new[1] if new else None, place_id, score),
    )


def _update_registry(cur, biz, lat, lng, meta, status):
    cur.execute(
        """UPDATE official_registry SET
               latitude = %s, longitude = %s, coordSource = %s,
               placeID = COALESCE(%s, placeID), placeIDKind = COALESCE(%s, placeIDKind),
               coordFetchedAt = NOW(), matchScore = %s, matchStatus = %s,
               resolveKey = COALESCE(%s, resolveKey)
           WHERE businessID = %s
             AND (coordSource IS NULL OR coordSource <> 'manual')
             AND (matchStatus IS NULL OR matchStatus NOT IN ('approved', 'rejected'))""",
        (lat, lng, meta.get("coord_source") or "places", meta.get("place_id"),
         meta.get("place_id_kind"), meta.get("score"), status, meta.get("resolve_key"),
         biz["businessID"]),
    )
    return cur.rowcount


def _name_is_unique(cur, barangay_id, name):
    """Name-based linking is only safe when no other registry row shares the name."""
    cur.execute(
        "SELECT COUNT(*) AS n FROM official_registry WHERE barangayID = %s AND businessName = %s",
        (barangay_id, name),
    )
    row = cur.fetchone()
    n = row["n"] if isinstance(row, dict) else row[0]
    return int(n) == 1


def _move_pin(cur, service, biz, lat, lng):
    """Move the business's map pin (linked by businessID, or by name for unlinked legacy pins)."""
    cur.execute(
        "UPDATE geospatial_logs SET latitude = %s, longitude = %s WHERE businessID = %s",
        (lat, lng, biz["businessID"]),
    )
    if _name_is_unique(cur, biz["barangayID"], biz["businessName"]):
        cur.execute(
            """UPDATE geospatial_logs SET latitude = %s, longitude = %s, businessID = %s
               WHERE businessID IS NULL AND barangayID = %s AND detectedName = %s
                 AND flagColor <> 'Red'""",
            (lat, lng, biz["businessID"], biz["barangayID"], str(biz["businessName"]).strip()),
        )
    # Keeps colour in sync and seeds a pin if the business has none yet
    service._sync_flag_color(
        cur, biz["barangayID"], biz["businessName"], biz.get("applicationStatus") or "Active",
        lat, lng, biz.get("businessAddress"), business_id=biz["businessID"],
    )


# ----------------------------------------------------------------------------
# Public API
# ----------------------------------------------------------------------------
def preview():
    """Free dry run (no Google calls): what would a re-verify run look at, and why?"""
    from app import mysql
    cur = mysql.connection.cursor()
    try:
        _ensure_history_table(cur)
        rows = _load_rows(cur)
        recent = _recent_ids(cur)
        mysql.connection.commit()
    finally:
        cur.close()
    suspects, sizes = build_suspects(rows)
    active = [s for s in suspects if s["businessID"] not in recent]
    return summarize(active, sizes, skipped_recent=len(suspects) - len(active))


def _emit(hub, stage, pct, moved, failed, same, total, status, error=None, **extra):
    payload = {
        "type": "snap_progress", "mode": "reverify", "stage": stage, "percentage": pct,
        "snapped": moved, "failed": failed, "cached": same, "total": total, "status": status,
    }
    if error:
        payload["error"] = error
    payload.update(extra)
    hub.publish_to_admins(payload)


def run(limit=200):
    """Re-verify up to `limit` suspect pins. Returns (summary, error)."""
    if not _run_lock.acquire(blocking=False):
        return None, "A re-verify run is already in progress."
    try:
        return _run(limit)
    finally:
        _run_lock.release()


def _run(limit):
    from app import mysql
    from api.notifications import hub
    from api.registry import places_resolver, service

    try:
        cur = mysql.connection.cursor()
        try:
            _ensure_history_table(cur)
            rows = _load_rows(cur)
            recent = _recent_ids(cur)
            mysql.connection.commit()
        finally:
            cur.close()

        suspects, _sizes = build_suspects(rows)
        todo = [s for s in suspects if s["businessID"] not in recent][: int(limit)]
        total = len(todo)
        if total == 0:
            msg = "No unreliable pins left to re-verify."
            _emit(hub, "completed", 100, 0, 0, 0, 0, msg)
            return {"total": 0, "message": msg}, None

        _emit(hub, "running", 0, 0, 0, 0, total, f"Re-verifying {total} pins against Google Places...")
        brgy_name_by_id = {v: k for k, v in service._load_barangay_lookup().items()}

        counts = Counter()
        consecutive_errors = 0
        budget_hit = False

        for idx, biz in enumerate(todo):
            try:
                lat, lng, meta = places_resolver.resolve_location(
                    biz["businessName"] or "", biz["businessAddress"] or "",
                    brgy_name_by_id.get(biz["barangayID"], ""),
                    business_id=biz["businessID"], barangay_id=biz["barangayID"],
                    line_of_business=biz["lineOfBusiness"] or "",
                    reserve_geocode=service._reserve_geocode_call,
                    refresh_geocode=False, force=True,
                )
                meta = meta or {}
                if lat is None and meta.get("budget_exhausted"):
                    budget_hit = True
                    break

                old = (biz["latitude"], biz["longitude"])
                new = (float(lat), float(lng)) if lat is not None and lng is not None else None
                cur = mysql.connection.cursor()
                try:
                    conflict = _claimed_by_other(cur, meta.get("place_id"), biz["businessID"]) if new else False
                    ok_brgy = _barangay_ok(lat, lng, biz["barangayID"]) if new else True
                    outcome = plan_outcome(old, new, meta, conflict=conflict, barangay_ok=ok_brgy)

                    if outcome == "verified":
                        _update_registry(cur, biz, lat, lng, meta, meta.get("match_status") or "auto")  # old pin was right
                    elif outcome in ("moved", "review"):
                        status = "auto" if outcome == "moved" else "review"
                        if _update_registry(cur, biz, lat, lng, meta, status):
                            _move_pin(cur, service, biz, lat, lng)
                        else:
                            outcome = "unresolved"                                # locked meanwhile
                    _log_attempt(cur, biz, outcome, new=new, place_id=meta.get("place_id"), score=meta.get("score"))
                    mysql.connection.commit()
                finally:
                    cur.close()
                counts[outcome] += 1
                consecutive_errors = 0
            except Exception:
                traceback.print_exc()
                try:
                    mysql.connection.rollback()
                except Exception:
                    pass
                counts["error"] += 1
                consecutive_errors += 1
                if consecutive_errors >= MAX_CONSECUTIVE_ERRORS:
                    raise RuntimeError("Too many consecutive errors; see server log.")

            if (idx + 1) % 5 == 0 or idx < 5 or idx == total - 1:
                moved = counts["moved"] + counts["review"]
                failed = counts["unresolved"] + counts["conflict"] + counts["error"]
                _emit(hub, "running", min(99, int((idx + 1) / total * 95)), moved, failed,
                      counts["verified"], total,
                      f"Checked {idx + 1}/{total}: {counts['moved']} moved, {counts['review']} to review, "
                      f"{counts['verified']} already right, {failed} not found")

        moved_total = counts["moved"] + counts["review"]
        failed_total = counts["unresolved"] + counts["conflict"] + counts["error"]
        msg = (f"Re-verify done: {counts['moved']} pins moved, {counts['review']} sent to review, "
               f"{counts['verified']} already correct, {failed_total} could not be matched.")
        if budget_hit:
            msg += " Google Places budget reached; run again later to continue (progress is saved)."
        _emit(hub, "completed", 100, moved_total, failed_total, counts["verified"], total, msg, budget_hit=budget_hit)
        hub.publish_to_admins({"type": "registry_updated"})
        return {"total": total, **dict(counts), "budget_hit": budget_hit, "message": msg}, None

    except Exception as e:
        traceback.print_exc()
        err = f"Re-verify failed: {e}"
        try:
            _emit(hub, "completed", 100, 0, 0, 0, 0, err, error=err)
        except Exception:
            pass
        return None, str(e)
