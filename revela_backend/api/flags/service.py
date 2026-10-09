from api.models.detection_runs import (
    get_monthly_detection_count,
    create_detection_run,
    update_detection_run_status,
    get_detection_quota_info,
)
import math
import numpy as np
from sklearn.cluster import DBSCAN
import os
import random
import time
import threading
import requests as http
import json
from geopy.distance import geodesic
from app import mysql
from shapely import prepare
from shapely.affinity import scale
from shapely.geometry import shape, Point
from api.utils.cancellation import is_cancelled, set_cancel
from api.notifications import hub
from api.utils.name_match import address_similarity, name_match, parse_name
from api.utils.places_quota import read_usage, reserve_usage_slot

GOOGLE_MAPS_API_KEY = os.getenv("GOOGLE_MAPS_API_KEY")

# ── Places API cost guard ─────────────────────────────────────────────────────
# Hard daily ceilings, stored in MySQL so they survive restarts and multiple workers.
# Tune via env vars on Railway without redeploying code.
#

PLACES_MONTHLY_CAP = int(os.getenv("PLACES_MONTHLY_CAP", "2000"))
PLACES_DAILY_CAP = int(os.getenv("PLACES_DAILY_CAP", "1000"))
PLACES_KINDS = ("nearby",)
NEW_NEARBY_DAILY_CAP = int(os.getenv("NEW_NEARBY_DAILY_CAP", "0"))
NEW_NEARBY_MONTHLY_CAP = int(os.getenv("NEW_NEARBY_MONTHLY_CAP", "0"))
NEW_NEARBY_URL = "https://places.googleapis.com/v1/places:searchNearby"
NEW_NEARBY_FIELD_MASK = (
    "places.id,places.displayName,places.location,"
    "places.primaryType,places.businessStatus"
)
NEW_NEARBY_EXCLUDED_TYPES = (
    "place_of_worship", "school", "primary_school", "secondary_school",
    "university", "local_government_office", "city_hall", "courthouse",
    "fire_station", "police_station", "post_office", "library", "cemetery",
    "park", "transit_station", "bus_station", "subway_station",
    "train_station", "light_rail_station",
)
RUN_DETECTION_MAX_SECONDS = max(
    1, int(os.getenv("RUN_DETECTION_MAX_SECONDS", "90"))
)
RUN_DETECTION_MAX_REQUESTS = max(
    1, int(os.getenv("RUN_DETECTION_MAX_REQUESTS", "120"))
)


def _env_positive_float(name, default, minimum):
    """
    Parse a tunable float env var, falling back to the default when unusable.

    A grid step drives `while lat <= max_lat: lat += step`, so a zero or
    negative value would never terminate. Garbage input must not raise at
    import time either, because this module is imported during app startup.
    """
    try:
        return max(minimum, float(os.getenv(name, default)))
    except (TypeError, ValueError):
        print(
            f"[Run Detection] Ignoring invalid {name}; using {default}.")
        return default


RUN_DETECTION_NEARBY_API = os.getenv(
    "RUN_DETECTION_NEARBY_API", "legacy"
).strip().lower()
_nearby_request_lock = threading.Lock()
_nearby_last_request_at = 0.0
_places_run_state = threading.local()


class PlacesBudgetExceeded(Exception):
    def __init__(self, message, reason="skipped_quota"):
        super().__init__(message)
        self.reason = reason


_budget_tables_ready = False


def _ensure_budget_tables():
    """Create the guard tables once per server process (not on every call)."""
    global _budget_tables_ready
    if _budget_tables_ready:
        return
    cur = mysql.connection.cursor()
    try:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS places_api_usage (
                usageDate    DATE        NOT NULL,
                kind         VARCHAR(20) NOT NULL,
                requestCount INT         NOT NULL DEFAULT 0,
                PRIMARY KEY (usageDate, kind)
            ) ENGINE=InnoDB
        """)

        # Checkpoints for a multi-day scan. Stores ONLY our own grid coordinates + a timestamp.
        # No Google content (names, addresses, ratings, coordinates of places) is stored here.
        cur.execute("""
            CREATE TABLE IF NOT EXISTS scan_point_log (
                pointKey    VARCHAR(64) NOT NULL PRIMARY KEY,
                completedAt DATETIME    NOT NULL
            ) ENGINE=InnoDB
        """)
        # Cleanly purge obsolete cache table if it existed from previous version
        cur.execute("DROP TABLE IF EXISTS places_nearby_cache")
        mysql.connection.commit()
        _budget_tables_ready = True      # only set after everything succeeded
    finally:
        cur.close()


# First day of the current month. NOTE: no '%' characters on purpose. MySQLdb runs
# `query % args` whenever args are passed, so a literal '%Y-%m' in a query would raise
# "ValueError: unsupported format character".
_MONTH_KEY = "DATE_SUB(CURDATE(), INTERVAL DAYOFMONTH(CURDATE()) - 1 DAY)"


def _reserve_places_call(kind):
    """Reserve a legacy Nearby Search call, preserving its existing ledger rows."""
    _ensure_budget_tables()
    try:
        allowed, reason = reserve_usage_slot(
            mysql.connection, "month", "day",
            PLACES_MONTHLY_CAP, PLACES_DAILY_CAP,
        )
    except Exception as exc:
        print(
            f"[Run Detection] legacy_nearby reservation failed closed: {exc}")
        raise PlacesBudgetExceeded(
            "Legacy Nearby Search usage ledger is unavailable; no request was sent."
        ) from exc
    if not allowed:
        raise PlacesBudgetExceeded(
            f"Legacy Nearby Search {reason.replace('_', ' ')} "
            f"(daily {PLACES_DAILY_CAP}, monthly {PLACES_MONTHLY_CAP}).",
            reason=reason,
        )


def _places_get(kind, url, **kwargs):
    """Every Google Places HTTP call in this module must go through here."""
    _reserve_places_call(kind)
    calls = getattr(_places_run_state, "calls", None)
    if calls is not None:
        calls["legacy_nearby"] += 1
        query_kind = getattr(_places_run_state, "query_kind", "initial")
        calls[f"legacy_nearby_{query_kind}"] += 1
    return http.get(url, **kwargs)


def get_places_usage_today():
    _ensure_budget_tables()
    cur = mysql.connection.cursor()
    try:
        m_used = _places_usage_count(cur, "month")
        d_used = _places_usage_count(cur, "day", today=True)

        from api.registry.service import (
            GEOCODE_DAILY_CAP,
            GEOCODE_MONTHLY_CAP,
            get_geocode_remaining_month,
            get_geocode_remaining_today,
        )
        geo_remaining_day = get_geocode_remaining_today()
        geo_remaining_month = get_geocode_remaining_month()
        geo_info = {
            "cap": GEOCODE_DAILY_CAP,
            "remaining": geo_remaining_day,
            "used": max(0, GEOCODE_DAILY_CAP - geo_remaining_day),
            "monthly_cap": GEOCODE_MONTHLY_CAP,
            "monthly_remaining": geo_remaining_month,
            "used_month": max(0, GEOCODE_MONTHLY_CAP - geo_remaining_month),
        }

        from api.registry.places_resolver import (
            TS_DAILY_CAP, TS_MONTHLY_CAP, PD_DAILY_CAP, PD_MONTHLY_CAP,
        )
        text_search = read_usage(
            mysql.connection, "imp_ts_month", "imp_ts_day")
        details = read_usage(mysql.connection, "imp_pd_month", "imp_pd_day")
        nearby_new = read_usage(
            mysql.connection, "new_nearby_month", "new_nearby_day"
        )
        nearby_legacy = {
            "enabled": True,
            "used_today": d_used,
            "daily_cap": PLACES_DAILY_CAP,
            "daily_remaining": max(0, PLACES_DAILY_CAP - d_used),
            "used_month": m_used,
            "monthly_cap": PLACES_MONTHLY_CAP,
            "monthly_remaining": max(0, PLACES_MONTHLY_CAP - m_used),
            "daily_quota_exceeded": d_used >= PLACES_DAILY_CAP,
            "monthly_quota_exceeded": m_used >= PLACES_MONTHLY_CAP,
        }
        nearby_new_status = {
            "enabled": (
                NEW_NEARBY_DAILY_CAP > 0 and NEW_NEARBY_MONTHLY_CAP > 0
            ),
            "used_today": nearby_new["day"],
            "daily_cap": NEW_NEARBY_DAILY_CAP,
            "daily_remaining": max(0, NEW_NEARBY_DAILY_CAP - nearby_new["day"]),
            "used_month": nearby_new["month"],
            "monthly_cap": NEW_NEARBY_MONTHLY_CAP,
            "monthly_remaining": max(
                0, NEW_NEARBY_MONTHLY_CAP - nearby_new["month"]
            ),
            "daily_quota_exceeded": (
                NEW_NEARBY_DAILY_CAP > 0
                and nearby_new["day"] >= NEW_NEARBY_DAILY_CAP
            ),
            "monthly_quota_exceeded": (
                NEW_NEARBY_MONTHLY_CAP > 0
                and nearby_new["month"] >= NEW_NEARBY_MONTHLY_CAP
            ),
        }
        active_nearby_usage = (
            nearby_new_status
            if _nearby_api_mode() == "new"
            else nearby_legacy
        )

        return {
            "month": {
                "used": m_used,
                "cap": PLACES_MONTHLY_CAP,
                "remaining": max(0, PLACES_MONTHLY_CAP - m_used),
            },
            "monthly": {
                "used": m_used,
                "cap": PLACES_MONTHLY_CAP,
                "remaining": max(0, PLACES_MONTHLY_CAP - m_used),
            },
            "today": {
                "used": d_used,
                "cap": PLACES_DAILY_CAP,
                "remaining": max(0, PLACES_DAILY_CAP - d_used),
            },
            "geocode": geo_info,
            "text_search_month": {
                "used": text_search["month"],
                "cap": TS_MONTHLY_CAP,
                "remaining": max(0, TS_MONTHLY_CAP - text_search["month"]),
                "monthly_quota_exceeded": text_search["month"] >= TS_MONTHLY_CAP,
            },
            "text_search_day": {
                "used": text_search["day"],
                "cap": TS_DAILY_CAP,
                "remaining": max(0, TS_DAILY_CAP - text_search["day"]),
                "daily_quota_exceeded": text_search["day"] >= TS_DAILY_CAP,
            },
            "monthly_quota_exceeded": text_search["month"] >= TS_MONTHLY_CAP,
            "place_details_day": {
                "used": details["day"],
                "cap": PD_DAILY_CAP,
                "remaining": max(0, PD_DAILY_CAP - details["day"]),
                "daily_quota_exceeded": details["day"] >= PD_DAILY_CAP,
            },
            "place_details_month": {
                "used": details["month"],
                "cap": PD_MONTHLY_CAP,
                "remaining": max(0, PD_MONTHLY_CAP - details["month"]),
                "monthly_quota_exceeded": details["month"] >= PD_MONTHLY_CAP,
            },
            "nearby_search_mode": _nearby_api_mode(),
            "nearby_search_legacy": nearby_legacy,
            "nearby_search_new": nearby_new_status,
            "nearby_search_active": active_nearby_usage,
        }
    finally:
        cur.close()


def _places_usage_count(cur, kind, today=False):
    if today:
        cur.execute(
            "SELECT requestCount AS c FROM places_api_usage WHERE usageDate = CURDATE() AND kind = %s",
            (kind,),
        )
    else:
        cur.execute(
            f"SELECT requestCount AS c FROM places_api_usage WHERE usageDate = {_MONTH_KEY} AND kind = %s",
            (kind,),
        )
    row = cur.fetchone()
    return int((row.get("c") if isinstance(row, dict) else row[0]) or 0) if row else 0


def _completed_points_this_cycle():
    """
    Grid points already finished since the last COMPLETED scan (so a scan interrupted by the
    daily budget resumes instead of restarting). Our own grid keys only.
    """
    cur = mysql.connection.cursor()
    try:
        cur.execute("""
            SELECT pointKey FROM scan_point_log
            WHERE completedAt > COALESCE(
                    (SELECT MAX(completedAt) FROM detection_runs WHERE status IN ('completed', 'completed_with_gaps', 'reset')),
                    '1970-01-01')
              AND completedAt > NOW() - INTERVAL 30 DAY
        """)
        return {(r["pointKey"] if isinstance(r, dict) else r[0]) for r in cur.fetchall()}
    finally:
        cur.close()


def _mark_point_done(point_key):
    cur = mysql.connection.cursor()
    try:
        cur.execute("""
            INSERT INTO scan_point_log (pointKey, completedAt) VALUES (%s, NOW())
            ON DUPLICATE KEY UPDATE completedAt = NOW()
        """, (point_key,))
        mysql.connection.commit()
    finally:
        cur.close()


def _unmark_points(point_keys):
    if not point_keys:
        return
    cur = mysql.connection.cursor()
    try:
        marks = ",".join(["%s"] * len(point_keys))
        cur.execute(
            f"DELETE FROM scan_point_log WHERE pointKey IN ({marks})", tuple(point_keys))
        mysql.connection.commit()
    finally:
        cur.close()


# ── GeoJSON Loading ───────────────────────────────────────────────────────────
MATAASNAKAHOY_GEOJSON_PATH = os.path.join(
    os.path.dirname(__file__), '..', 'utils', 'mataasnakahoy.json')
_BARANGAY_POLYGONS = {}

if os.path.exists(MATAASNAKAHOY_GEOJSON_PATH):
    with open(MATAASNAKAHOY_GEOJSON_PATH, 'r', encoding='utf-8') as f:
        _geojson_data = json.load(f)
        for feature in _geojson_data.get('features', []):
            b_name = feature.get('properties', {}).get('ADM4_EN')
            if b_name:
                poly = shape(feature.get('geometry'))
                _BARANGAY_POLYGONS[b_name] = poly

# ── Municipality spatial config ───────────────────────────────────────────────
# Cross-referencing threshold: POI must be within this distance of a registry
# entry to be considered a match (Green). Otherwise it becomes a Red Flag.
THRESHOLD_M = 20

# ── STRICT BOUNDARY FILTER ────────────────────────────────────────────────────
# Hard bounding box for Mataasnakahoy, Batangas.
# Any POI returned by Google Places outside this box is immediately discarded
# before cross-referencing — this is what prevents businesses from other
# municipalities from appearing as false Red Flags.
#
# These coordinates were derived from OSM boundary data for Mataasnakahoy.
# Adjust ±0.005° if edge barangays are being clipped.
_BOUNDARY_GEOJSON = {
    "type": "Polygon",
    "coordinates": [[[121.0129562, 13.9894427], [121.0334058, 13.9780567], [121.083046, 13.9612673], [121.0851663, 13.9589584], [121.0853326, 13.9589818], [121.0854185, 13.9590131], [121.085515, 13.9590677], [121.0855767, 13.9591172], [121.0856491, 13.9591719], [121.0857162, 13.9592083], [121.0858101, 13.9592421], [121.0859603, 13.9592526], [121.0861132, 13.9592421], [121.0862017, 13.95925], [121.0863867, 13.9592421], [121.0866094, 13.9592994], [121.0867193, 13.9593385], [121.0868481, 13.959328], [121.0869956, 13.9593254], [121.0872075, 13.9593385], [121.087406, 13.9593072], [121.0875857, 13.9592656], [121.0876715, 13.9592786], [121.0877869, 13.9592994], [121.0879183, 13.9592942], [121.0880926, 13.9592656], [121.0882241, 13.959263], [121.0883152, 13.9592786], [121.0884118, 13.9592812], [121.0884923, 13.9592708], [121.0886183, 13.9592578], [121.0887122, 13.9592604], [121.0891038, 13.9593098], [121.0892031, 13.9593124], [121.0892862, 13.9593124], [121.0894525, 13.9592838], [121.0895517, 13.9592838], [121.0896537, 13.9592916], [121.089761, 13.9592734], [121.089828, 13.9592447], [121.0899112, 13.9592135], [121.0900265, 13.9591875], [121.0901338, 13.9591901], [121.0902652, 13.9591953], [121.0903618, 13.9592005], [121.0904771, 13.9591797], [121.0905549, 13.9591484], [121.0906219, 13.959099], [121.0906461, 13.9590469], [121.0906702, 13.9590027], [121.0907614, 13.958909], [121.0908499, 13.9588413], [121.0909358, 13.958784], [121.0910162, 13.9587372], [121.0911638, 13.9586591], [121.0912442, 13.9586044], [121.0913381, 13.9585159], [121.0914078, 13.9584326], [121.091432, 13.9583467], [121.0914534, 13.9582894], [121.0915178, 13.9582374], [121.0915849, 13.9582244], [121.0916975, 13.958266], [121.0917753, 13.9582816], [121.0919148, 13.9582973], [121.0919926, 13.9582946], [121.0920811, 13.958266], [121.0921964, 13.9581931], [121.0922769, 13.9581359], [121.0924137, 13.9580604], [121.0925317, 13.9580057], [121.0926014, 13.9579589], [121.0926712, 13.957873], [121.0926953, 13.9578157], [121.0927436, 13.9577766], [121.0927919, 13.9577636], [121.0930949, 13.9576881], [121.0931647, 13.9577064], [121.0932532, 13.957748], [121.0933202, 13.9577897], [121.0933793, 13.9578053], [121.0935831, 13.957735], [121.0936421, 13.9576751], [121.0937548, 13.9576049], [121.0938701, 13.9575658], [121.0939693, 13.9575346], [121.0940739, 13.9574747], [121.0941383, 13.9573992], [121.0942268, 13.9573654], [121.0943583, 13.9573419], [121.0944575, 13.9573602], [121.0945353, 13.9573862], [121.094597, 13.957394], [121.094656, 13.957394], [121.0947418, 13.9573758], [121.0948357, 13.9573315], [121.0949323, 13.9572717], [121.0950047, 13.9572326], [121.0951227, 13.9571832], [121.0952193, 13.9571285], [121.0953185, 13.9570608], [121.0954177, 13.9569671], [121.0954794, 13.9568994], [121.0955384, 13.9568213], [121.0956082, 13.9567511], [121.0957074, 13.9566704], [121.0957745, 13.9566287], [121.0960373, 13.9564543], [121.0960937, 13.9564205], [121.0963377, 13.9563059], [121.0964289, 13.9562825], [121.0965764, 13.9562435], [121.0967025, 13.9562122], [121.0967669, 13.9562096], [121.0968259, 13.9562044], [121.0969037, 13.9561446], [121.09696, 13.9560847], [121.0969976, 13.9560508], [121.0970432, 13.9560144], [121.0971397, 13.955991], [121.0972202, 13.9560014], [121.0973087, 13.9560248], [121.0974026, 13.9560482], [121.097483, 13.956043], [121.097585, 13.9560014], [121.0976708, 13.9559441], [121.0977459, 13.955827], [121.0978505, 13.9557489], [121.0979658, 13.9556682], [121.0981107, 13.9555875], [121.0982636, 13.9554756], [121.0984004, 13.9553688], [121.0985559, 13.9552257], [121.0986873, 13.9551268], [121.0987705, 13.9550565], [121.0988456, 13.9549446], [121.0988912, 13.95483], [121.0989368, 13.9547597], [121.099028, 13.9546608], [121.0991299, 13.9546244], [121.0992023, 13.9546322], [121.0993257, 13.954627], [121.0994813, 13.9546296], [121.0996744, 13.95464], [121.0998353, 13.9546478], [121.0999721, 13.9546895], [121.1000714, 13.9547311], [121.1002243, 13.9547363], [121.1003691, 13.9547051], [121.1005193, 13.9547051], [121.1007822, 13.9545905], [121.1009645, 13.9545281], [121.1011255, 13.954476], [121.1012489, 13.9544708], [121.1014312, 13.9544656], [121.1016136, 13.9544187], [121.1017531, 13.9543615], [121.1019194, 13.9542782], [121.102075, 13.9541897], [121.1022359, 13.9541116], [121.1023593, 13.9539918], [121.1024451, 13.9538929], [121.1025149, 13.9538617], [121.102649, 13.9537628], [121.1027563, 13.9536534], [121.1027985, 13.9536195], [121.1028796, 13.9535545], [121.1029869, 13.9534452], [121.1031693, 13.953315], [121.1031961, 13.9532578], [121.1032309, 13.9532205], [121.1032981, 13.9531484], [121.1034536, 13.9530495], [121.1035824, 13.9530287], [121.1036628, 13.9529766], [121.1037326, 13.952909], [121.1038291, 13.9528673], [121.1039364, 13.9528621], [121.1040491, 13.9528465], [121.1041456, 13.9528829], [121.1042958, 13.9528725], [121.1043817, 13.9528205], [121.1045211, 13.952758], [121.1046767, 13.9526851], [121.1047894, 13.9526695], [121.1052024, 13.9525758], [121.1053365, 13.9525341], [121.1054653, 13.952456], [121.1056209, 13.9524352], [121.1057657, 13.9523884], [121.1059052, 13.9523936], [121.1060111, 13.9523735], [121.1061412, 13.9523675], [121.1062753, 13.9522634], [121.1063826, 13.952227], [121.1065221, 13.9521541], [121.1066186, 13.952076], [121.1067259, 13.9520031], [121.1068439, 13.9519875], [121.1069727, 13.9519354], [121.1070853, 13.9518729], [121.1071712, 13.9518313], [121.1073911, 13.951774], [121.107654, 13.9516178], [121.1077291, 13.9515892], [121.1078337, 13.9515423], [121.1079946, 13.9514929], [121.1080885, 13.9514304], [121.1081448, 13.9513836], [121.1083031, 13.9512768], [121.108346, 13.9512586], [121.1084452, 13.9512013], [121.108515, 13.9512066], [121.1086223, 13.9511909], [121.1086893, 13.9511285], [121.1087725, 13.9510894], [121.1088824, 13.9510816], [121.1089629, 13.9510452], [121.1090273, 13.9510009], [121.1091399, 13.9509827], [121.1092338, 13.9509541], [121.1093518, 13.9509176], [121.1095208, 13.9509046], [121.1097676, 13.9508786], [121.1098963, 13.9509098], [121.1100572, 13.9509619], [121.1102664, 13.9510504], [121.1103523, 13.9511337], [121.11054, 13.9511857], [121.1107063, 13.951217], [121.1108243, 13.951243], [121.1109477, 13.9512586], [121.1110657, 13.9513003], [121.1111623, 13.9514148], [121.1112857, 13.9514825], [121.1113715, 13.9515554], [121.1114037, 13.9517011], [121.1114319, 13.9517865], [121.1129326, 13.95224], [121.1131686, 13.951446], [121.114507, 13.9519146], [121.1148236, 13.9511287], [121.1151212, 13.9502931], [121.1152741, 13.9498662], [121.1155819, 13.9490909], [121.1161729, 13.9493221], [121.1178983, 13.9499757], [121.1184774, 13.9501925], [121.1162246, 13.9555322], [121.1178599, 13.957298], [121.1250034, 13.9606593], [121.1146071, 13.9917159], [121.114502, 13.9920299], [121.1144212, 13.9922302], [121.1142898, 13.9923629], [121.1141396, 13.992441], [121.1139759, 13.9924826], [121.1135146, 13.9925529], [121.1133671, 13.9925945], [121.113241, 13.992657], [121.1131578, 13.9927507], [121.1130988, 13.9928626], [121.113013, 13.9931229], [121.1129433, 13.9932816], [121.1128253, 13.9934404], [121.1124143, 13.9937466], [121.1115539, 13.9943877], [121.1114278, 13.9945361], [121.1113795, 13.9947053], [121.1113796, 13.9948431], [121.1114064, 13.995002], [121.1116504, 13.9957567], [121.1116987, 13.9959363], [121.1116987, 13.9960742], [121.1116867, 13.9962031], [121.1116545, 13.9963072], [121.1116116, 13.9963891], [121.1115351, 13.9964594], [121.1114386, 13.9965063], [121.1113071, 13.9965323], [121.1108538, 13.9965713], [121.1107626, 13.9966078], [121.1106514, 13.9966689], [121.1104917, 13.9968212], [121.1103952, 13.9969695], [121.1100733, 13.9976097], [121.1099499, 13.9977971], [121.1098105, 13.9979533], [121.1094967, 13.998263], [121.1093491, 13.9984347], [121.1092365, 13.9985883], [121.1091748, 13.9987002], [121.1091185, 13.998846], [121.1089897, 13.9994107], [121.1089039, 13.9995668], [121.108759, 13.9996657], [121.1082306, 13.9998739], [121.1080751, 13.9999312], [121.1079141, 14.0000223], [121.1076459, 14.0001915], [121.1074153, 14.0003112], [121.1071753, 14.0003774], [121.1068815, 14.0003841], [121.1062136, 14.0002383], [121.1055565, 14.0001915], [121.104902, 14.0002019], [121.1044407, 14.0003788], [121.1040544, 14.0006911], [121.1039974, 14.0007464], [121.1037218, 14.0010139], [121.1034536, 14.0013886], [121.1031961, 14.0018987], [121.1031103, 14.0023984], [121.1030352, 14.0029605], [121.1031103, 14.0034498], [121.1029601, 14.0038454], [121.1026704, 14.0042201], [121.1026258, 14.0042801], [121.1026101, 14.0043529], [121.10259, 14.0044244], [121.1025538, 14.0045012], [121.1025564, 14.0045819], [121.1025766, 14.0046352], [121.1025497, 14.0046821], [121.1025055, 14.004738], [121.1024666, 14.0048213], [121.102417, 14.0048708], [121.1023486, 14.0049371], [121.1022681, 14.0050035], [121.1021957, 14.0050217], [121.1021098, 14.0050425], [121.1020763, 14.005062], [121.10202, 14.0051167], [121.1019824, 14.0051831], [121.1019006, 14.0052806], [121.1018725, 14.0053574], [121.1018483, 14.0054433], [121.1018202, 14.0055084], [121.1017491, 14.0056268], [121.1017317, 14.0057114], [121.1016941, 14.0057738], [121.1016807, 14.0058649], [121.1016646, 14.0059586], [121.1016552, 14.0060432], [121.1016713, 14.0061199], [121.1017022, 14.0061954], [121.1017062, 14.0062917], [121.1016659, 14.0063841], [121.1016405, 14.0064583], [121.1016425, 14.0064849], [121.1015815, 14.0065656], [121.1015104, 14.0066372], [121.1014882, 14.0066977], [121.1014876, 14.0067582], [121.1014507, 14.0068389], [121.1014178, 14.0069078], [121.1013575, 14.0070269], [121.1013146, 14.0071154], [121.1012609, 14.0072039], [121.1012314, 14.0072976], [121.1011228, 14.0074004], [121.1010504, 14.007455], [121.1009565, 14.0075305], [121.1008915, 14.0076072], [121.1008787, 14.0076762], [121.1008506, 14.0077387], [121.100805, 14.0078285], [121.1007929, 14.0078805], [121.1007728, 14.0079625], [121.1007647, 14.0080139], [121.1007447, 14.0080971], [121.1007077, 14.0081349], [121.1006729, 14.0081837], [121.1006226, 14.0082221], [121.1005716, 14.0082546], [121.1005059, 14.0082839], [121.100463, 14.0083268], [121.1004362, 14.0083698], [121.1003919, 14.0084127], [121.100349, 14.0084446], [121.1003067, 14.0084875], [121.1002658, 14.0085142], [121.1002068, 14.0085441], [121.1001646, 14.0085702], [121.100127, 14.0085968], [121.1001002, 14.0086144], [121.1000519, 14.0086495], [121.0999996, 14.0086599], [121.0999574, 14.0086508], [121.0999024, 14.0086469], [121.0998125, 14.0086547], [121.0997455, 14.008684], [121.0996731, 14.0087283], [121.0996228, 14.0087718], [121.0995698, 14.0088044], [121.099486, 14.008848], [121.0993887, 14.0088974], [121.0993157, 14.008915], [121.0992151, 14.008915], [121.0991091, 14.0089241], [121.0990474, 14.0089501], [121.0989904, 14.0090028], [121.0989583, 14.009064], [121.098914, 14.0091024], [121.0988429, 14.0091258], [121.0987584, 14.0091349], [121.0986713, 14.0091824], [121.0986196, 14.0092286], [121.0985553, 14.0092689], [121.098511, 14.0093066], [121.0984661, 14.0093288], [121.0984265, 14.0093483], [121.098399, 14.0093776], [121.0983615, 14.0094042], [121.0983326, 14.0094192], [121.0982676, 14.0094316], [121.0982025, 14.0094342], [121.0981281, 14.0094595], [121.0980671, 14.0094693], [121.0979618, 14.0094576], [121.0978706, 14.0094498], [121.0977955, 14.0094576], [121.0977104, 14.0094745], [121.0976299, 14.0094771], [121.097585, 14.0094732], [121.097528, 14.0094628], [121.0972611, 14.0093925], [121.0971746, 14.0093782], [121.0971082, 14.0093756], [121.0970512, 14.009386], [121.0969996, 14.0093886], [121.0969292, 14.0093769], [121.096899, 14.0093711], [121.0968567, 14.0093704], [121.0967997, 14.009386], [121.0967588, 14.0094003], [121.0967106, 14.0094146], [121.0966368, 14.0094316], [121.0965832, 14.0094303], [121.0965376, 14.009412], [121.0965067, 14.0093951], [121.096445, 14.0093626], [121.0963277, 14.0093424], [121.0962325, 14.0093593], [121.0961654, 14.0093684], [121.0960977, 14.0093541], [121.0960414, 14.0093307], [121.095979, 14.0093034], [121.095924, 14.0092917], [121.0958717, 14.0092949], [121.0957758, 14.0093346], [121.0956484, 14.0093743], [121.0955706, 14.0094042], [121.0955431, 14.0094329], [121.0955378, 14.0094934], [121.0955485, 14.0095578], [121.0955686, 14.0096202], [121.0955934, 14.0096775], [121.0956223, 14.0097354], [121.0956712, 14.0098024], [121.0957242, 14.009861], [121.0957745, 14.0098948], [121.0958228, 14.0099156], [121.0958657, 14.0099351], [121.0958938, 14.0099572], [121.0959547, 14.0100036], [121.0960709, 14.0101563], [121.0961486, 14.0102865], [121.0961757, 14.0103572], [121.0961795, 14.0104374], [121.0961567, 14.0105272], [121.0961149, 14.0105835], [121.0960608, 14.0106335], [121.0958752, 14.010768], [121.0957604, 14.0108378], [121.0956649, 14.0108746], [121.09516, 14.0110236], [121.0950583, 14.0110483], [121.0949392, 14.0110719], [121.094827, 14.0111212], [121.0947551, 14.0111536], [121.0946721, 14.0111966], [121.0946156, 14.0112312], [121.0945561, 14.0112565], [121.0944924, 14.0112773], [121.0944186, 14.0113001], [121.0943207, 14.0113196], [121.0942048, 14.0113384], [121.0941457, 14.011356], [121.0940941, 14.0113788], [121.0940585, 14.011414], [121.0940284, 14.0114756], [121.0940109, 14.0114914], [121.0129562, 13.9894427]]]
}
_MUNICIPALITY_BOUNDARY = shape(_BOUNDARY_GEOJSON)
_MUNICIPALITY_WITH_TOLERANCE = _MUNICIPALITY_BOUNDARY.buffer(0.0005)
prepare(_MUNICIPALITY_WITH_TOLERANCE)
_METERS_PER_DEGREE_LAT = 111_320.0
_METERS_PER_DEGREE_LNG = _METERS_PER_DEGREE_LAT * math.cos(math.radians(13.98))
_MUNICIPALITY_WITH_TOLERANCE_METERS = scale(
    _MUNICIPALITY_WITH_TOLERANCE,
    xfact=_METERS_PER_DEGREE_LNG,
    yfact=_METERS_PER_DEGREE_LAT,
    origin=(0, 0),
)


def _within_municipality(lat: float, lng: float) -> bool:
    """Polygon test with tight 0.0005° (~55m) buffer for border road tolerance without spilling into Lipa/Balete."""
    if lat is None or lng is None:
        return False
    return _MUNICIPALITY_WITH_TOLERANCE.contains(Point(lng, lat))


def _normalize_business_name(name: str) -> str:
    tokens, _ = parse_name(name)
    return " ".join(tokens)


def _name_similarity(
    name1: str,
    name2: str,
    reg_line: str = '',
    poi_types: tuple = (),
    reg_type: str = '',
) -> float:
    score, _ = name_match(
        name1, name2, reg_line=reg_line, poi_types=poi_types, reg_type=reg_type
    )
    return score


def _match_poi_to_registry(
    poi_name,
    poi_lat,
    poi_lng,
    registry,
    poi_barangay_id=None,
    poi_types=(),
    poi_address='',
):
    """
    Tiered Decision Matrix for matching a candidate POI to official registry entries:
    - Auto: compatible category, score >= 0.80, and within 300 m; without coordinates,
      require same barangay plus strong address agreement.
    - Review: plausible score >= 0.55 with no hard category conflict, or competing candidates.
    - No Match: weak/single-token-only name, hard category conflict, or score < 0.55.
      Address or proximity alone never establishes identity.
    Returns (matched_entry, distance_meters, similarity_score, match_status)
    """
    best_match = None
    best_dist = float("inf")
    best_score = 0.0
    best_status = "no_match"
    candidate_scores = []

    for entry in registry:
        sim, match_reason = name_match(
            entry.get("businessName", ""),
            poi_name,
            reg_line=entry.get("businessLine", ""),
            reg_type=entry.get("businessType", ""),
            poi_types=poi_types,
        )
        if match_reason in ("category_conflict", "weak_name", "no_shared_name"):
            continue
        # Strict cutoff: under 0.55 is rejected regardless of proximity
        if sim < 0.55:
            continue

        address_score = address_similarity(
            entry.get("businessAddress", ""), poi_address
        )
        reg_lat = entry.get("latitude")
        reg_lng = entry.get("longitude")
        reg_b_id = entry.get("barangayID")
        same_barangay = (reg_b_id is None) or (
            poi_barangay_id is None) or (reg_b_id == poi_barangay_id)

        dist = None
        if reg_lat is not None and reg_lng is not None:
            try:
                dist = geodesic((poi_lat, poi_lng),
                                (float(reg_lat), float(reg_lng))).meters
            except Exception:
                dist = None

        supported_score = min(
            1.0,
            sim + (0.05 if address_score >= 0.6 else 0.0),
        )
        candidate_scores.append((entry.get("businessID"), supported_score))
        if match_reason == "soft_category_conflict":
            status = "review"
        elif supported_score >= 0.80:
            if dist is not None:
                status = "auto" if dist <= 300.0 else "review"
            else:
                status = (
                    "auto"
                    if same_barangay and address_score >= 0.75
                    else "review"
                )
        else:
            status = "review"

        # Candidate selection priority:
        # 1. Prefer 'auto' over 'review'
        # 2. Prefer higher similarity score
        # 3. Prefer smaller geographical distance
        is_better = False
        if best_match is None:
            is_better = True
        elif status == "auto" and best_status != "auto":
            is_better = True
        elif status == best_status:
            if supported_score > best_score + 0.01:
                is_better = True
            elif abs(supported_score - best_score) <= 0.01:
                cur_dist = dist if dist is not None else float("inf")
                if cur_dist < best_dist:
                    is_better = True

        if is_better:
            best_match = entry
            best_dist = dist if dist is not None else 0.0
            best_score = supported_score
            best_status = status

    competing_match = any(
        business_id != best_match.get("businessID")
        and score >= best_score - 0.05
        for business_id, score in candidate_scores
    ) if best_match else False
    if competing_match and best_status == "auto":
        best_status = "review"

    return best_match, best_dist, best_score, best_status


_place_types_column_ready = False
_place_types_schema_lock = threading.Lock()


def _ensure_place_types_column():
    global _place_types_column_ready
    if _place_types_column_ready:
        return

    with _place_types_schema_lock:
        if _place_types_column_ready:
            return
        cursor = mysql.connection.cursor()
        try:
            cursor.execute(
                "SHOW COLUMNS FROM geospatial_logs LIKE 'placeTypes'")
            if not cursor.fetchone():
                cursor.execute(
                    "ALTER TABLE geospatial_logs ADD COLUMN placeTypes JSON NULL AFTER nearestLandmark"
                )
                mysql.connection.commit()
            _place_types_column_ready = True
        finally:
            cursor.close()


def _decode_place_types(value):
    if isinstance(value, (list, tuple, set)):
        return tuple(sorted(str(item) for item in value if item))
    if not value:
        return ()
    try:
        parsed = json.loads(value) if isinstance(value, str) else value
    except (TypeError, ValueError):
        return ()
    if not isinstance(parsed, (list, tuple, set)):
        return ()
    return tuple(sorted(str(item) for item in parsed if item))


def _match_registry_to_google(
    place_id,
    business_id,
    detected_name,
    target_color='Green',
    lat=None,
    lng=None,
    barangay_id=None,
    match_score=None,
    match_status=None,
    poi_types=(),
    poi_address=None,
):
    """
    Updates or inserts the geospatial log for an existing registry business 
    with its official Google Maps Place ID and dynamic status-based flag color.
    Also backfills discovered GPS coordinates into official_registry if unlocked.
    Cleans up any redundant unpositioned baseline logs for this business.
    """
    serialized_types = json.dumps(
        sorted(set(poi_types))) if poi_types else None
    cursor = mysql.connection.cursor()

    if match_status is None:
        if match_score is not None:
            match_status = "auto" if float(match_score) >= 0.80 else "review"
        else:
            match_status = "auto"

    # 1. Query current official_registry metadata before updating
    is_locked = False
    reg_lat = None
    reg_lng = None
    if business_id:
        cursor.execute("""
            SELECT coordSource, matchStatus, latitude, longitude
            FROM official_registry
            WHERE businessID = %s
        """, (business_id,))
        reg_row = cursor.fetchone()
        if reg_row:
            src = (reg_row.get("coordSource") or "").strip().lower()
            m_stat = (reg_row.get("matchStatus") or "").strip().lower()
            if src == "manual" or m_stat == "approved":
                is_locked = True
                reg_lat = reg_row.get("latitude")
                reg_lng = reg_row.get("longitude")
            elif m_stat == "auto" and match_status == "review":
                # Guard: Do not downgrade an already confident auto match with a lower-confidence review candidate
                is_locked = True
                reg_lat = reg_row.get("latitude")
                reg_lng = reg_row.get("longitude")

    # 2. Backfill discovered GPS coordinates into official_registry IF NOT LOCKED
    if business_id and not is_locked:
        if lat and lng:
            stat_sql = "review" if match_status == "review" else "auto"
            cursor.execute(f"""
                UPDATE official_registry
                SET latitude = %s,
                    longitude = %s,
                    placeID = %s,
                    placeIDKind = 'poi',
                    coordSource = 'places',
                    coordFetchedAt = NOW(),
                    matchScore = %s,
                    matchStatus = '{stat_sql}'
                WHERE businessID = %s
            """, (
                lat,
                lng,
                place_id,
                round(float(match_score), 3) if match_score is not None else None,
                business_id
            ))

    # 3. Check all geospatial_logs matching businessID, placeID OR (businessID IS NULL AND detectedName + barangayID)
    cursor.execute("""
        SELECT logID, businessID, placeID, flagColor, latitude, longitude
        FROM geospatial_logs
        WHERE (businessID IS NOT NULL AND businessID = %s)
           OR (placeID IS NOT NULL AND placeID = %s)
           OR (businessID IS NULL AND detectedName = %s AND barangayID = %s)
        ORDER BY (businessID = %s) DESC, (placeID = %s) DESC
    """, (business_id, place_id, detected_name, barangay_id, business_id, place_id))
    matched_logs = cursor.fetchall()

    if matched_logs:
        # Keep primary log (prefer the one with matching businessID, then placeID)
        primary_log = None
        for log in matched_logs:
            if log.get("businessID") == business_id:
                primary_log = log
                break
        if not primary_log:
            for log in matched_logs:
                if log.get("placeID") == place_id:
                    primary_log = log
                    break
        if not primary_log:
            primary_log = matched_logs[0]

        # If locked, DO NOT overwrite existing verified coordinates with Google's lat/lng!
        final_lat = (reg_lat if reg_lat is not None else primary_log.get(
            "latitude")) if is_locked else lat
        final_lng = (reg_lng if reg_lng is not None else primary_log.get(
            "longitude")) if is_locked else lng

        cursor.execute("""
                UPDATE geospatial_logs
                SET businessID = %s,
                    placeID = %s, flagColor = %s,
                    detectedName = %s,
                    latitude = %s,
                    longitude = %s,
                    nearestLandmark = COALESCE(%s, nearestLandmark),
                    placeTypes = COALESCE(%s, placeTypes),
                    barangayID = COALESCE(%s, barangayID)
                WHERE logID = %s
            """, (
            business_id, place_id, target_color, detected_name, final_lat, final_lng,
            poi_address, serialized_types, barangay_id, primary_log["logID"]
        ))

        # Remove redundant duplicate unpositioned logs, repointing inspections first
        for log in matched_logs:
            if log["logID"] != primary_log["logID"]:
                cursor.execute(
                    "UPDATE inspection_reports SET targetID = %s WHERE targetID = %s",
                    (primary_log["logID"], log["logID"])
                )
                try:
                    cursor.execute(
                        "UPDATE inspection_lifecycle_events SET targetLogID = %s WHERE targetLogID = %s",
                        (primary_log["logID"], log["logID"])
                    )
                except Exception:
                    pass
                cursor.execute(
                    "DELETE FROM geospatial_logs WHERE logID = %s", (log["logID"],))

    elif lat and lng and barangay_id:
        final_lat = reg_lat if (is_locked and reg_lat is not None) else lat
        final_lng = reg_lng if (is_locked and reg_lng is not None) else lng
        cursor.execute("""
            INSERT INTO geospatial_logs
                (barangayID, businessID, reportID, detectedName, latitude, longitude,
                 flagColor, placeID, nearestLandmark, placeTypes)
            VALUES (%s, %s, NULL, %s, %s, %s, %s, %s, %s, %s)
        """, (
            barangay_id, business_id, detected_name, final_lat, final_lng,
            target_color, place_id, poi_address, serialized_types
        ))

    mysql.connection.commit()
    cursor.close()


_last_reconcile_time = 0.0  # module-level throttle
_RECONCILE_INTERVAL_S = 300   # run at most once every 5 minutes
_reconcile_lock = threading.Lock()


def reconcile_existing_flags(force: bool = False, silent: bool = False):
    """
    Reconciles existing Red flags in geospatial_logs against official_registry.
    If a Red flag was erroneously created for a registered business, converts it
    to Green (or appropriate permit status color), updates official_registry GPS,
    and removes any duplicate unpositioned baseline logs.

    Throttled to run at most once every 5 minutes unless force=True.
    silent=True suppresses all SSE progress events (use when called from run_detection
    to avoid the reconcile overlay flashing mid-scan on the frontend).
    """
    global _last_reconcile_time
    now = time.time()
    if not force and (now - _last_reconcile_time) < _RECONCILE_INTERVAL_S:
        return 0   # too soon; skip

    # Prevent concurrent reconcile runs
    if not _reconcile_lock.acquire(blocking=False):
        print("[Reconcile] Already running. Skipping duplicate concurrent call.")
        return 0

    try:
        _last_reconcile_time = now

        _ensure_place_types_column()
        cursor = mysql.connection.cursor()
        cursor.execute("""
            SELECT logID, businessID, placeID, detectedName, latitude, longitude, barangayID,
                   nearestLandmark, placeTypes
            FROM geospatial_logs
            WHERE flagColor = 'Red' AND latitude IS NOT NULL AND longitude IS NOT NULL
        """)
        red_flags = cursor.fetchall()
        cursor.close()

        if not red_flags:
            if not silent:
                hub.publish_to_admins({"type": "reconcile_progress", "percentage": 100,
                                      "status": "No Red flags to reconcile.", "converted": 0, "total": 0, "stage": "completed"})
            return 0

        cursor = mysql.connection.cursor()
        cursor.execute("SELECT COUNT(*) AS total FROM official_registry")
        r_row = cursor.fetchone()
        cursor.close()
        reg_count = (r_row.get("total") if isinstance(
            r_row, dict) else r_row[0]) if r_row else 0
        if reg_count == 0:
            if not silent:
                hub.publish_to_admins({"type": "reconcile_progress", "percentage": 100,
                                      "status": "Official registry is empty. No records to reconcile against.", "converted": 0, "total": len(red_flags), "stage": "completed"})
            return 0

        registry = _load_registry()
        converted_count = 0
        total = len(red_flags)

        if not silent:
            hub.publish_to_admins({"type": "reconcile_progress", "percentage": 0,
                                  "status": f"Checking {total} Red flag(s) against the registry...", "converted": 0, "total": total, "stage": "running"})

        for idx, flag in enumerate(red_flags):
            name = flag.get("detectedName") or ""
            lat = flag.get("latitude")
            lng = flag.get("longitude")
            b_id = flag.get("barangayID")
            place_id = flag.get("placeID")
            biz_id = flag.get("businessID")

            matched_by_id = None
            if biz_id:
                for entry in registry:
                    if entry.get("businessID") == biz_id:
                        matched_by_id = entry
                        break

            matched_by_place = None
            if not matched_by_id and place_id:
                for entry in registry:
                    if entry.get("placeID") == place_id:
                        matched_by_place = entry
                        break

            if matched_by_id:
                matched = matched_by_id
                dist = 0.0
                score = 1.0
                status = "auto"
            elif matched_by_place:
                matched = matched_by_place
                dist = 0.0
                score = 1.0
                status = "auto"
            else:
                matched, dist, score, status = _match_poi_to_registry(
                    name,
                    lat,
                    lng,
                    registry,
                    poi_barangay_id=b_id,
                    poi_types=_decode_place_types(flag.get("placeTypes")),
                    poi_address=flag.get("nearestLandmark") or "",
                )

            if matched and status != "no_match":
                app_status = (matched.get('applicationStatus')
                              or 'Active').strip()
                target_color = 'Green' if app_status == 'Active' else (
                    'Orange' if app_status == 'Expired' else (
                        'Black' if app_status == 'Revoked' else (
                            'Purple' if app_status == 'Closed' else 'Yellow'
                        )
                    )
                )
                if status == 'review':
                    target_color = 'Yellow'

                target_b_id = matched.get('barangayID') or b_id
                _match_registry_to_google(
                    place_id, matched['businessID'], matched['businessName'],
                    target_color=target_color, lat=lat, lng=lng, barangay_id=target_b_id,
                    match_score=score,
                    poi_types=_decode_place_types(flag.get("placeTypes")),
                    poi_address=flag.get("nearestLandmark"),
                )
                converted_count += 1

            if not silent and (idx % 5 == 0 or idx == total - 1):
                pct = min(99, int(((idx + 1) / max(total, 1)) * 100))
                hub.publish_to_admins({
                    "type": "reconcile_progress",
                    "percentage": pct,
                    "status": f"Checking '{name}'... ({idx + 1}/{total})",
                    "converted": converted_count,
                    "total": total,
                    "stage": "running"
                })

        if not silent:
            hub.publish_to_admins({
                "type": "reconcile_progress",
                "percentage": 100,
                "status": f"Done. Converted {converted_count} of {total} flag(s).",
                "converted": converted_count,
                "total": total,
                "stage": "completed"
            })
        return converted_count

    finally:
        _reconcile_lock.release()


# ── Google Places fetch & checkpointed grid scan ───────────────────────────────
DETECTION_RADIUS_M = 850
# Tunable via env so staging can probe spacing without a redeploy. Coverage is
# NOT monotonic in the step: the lattice is anchored to a fixed bounding-box
# origin while the municipality polygon is arbitrary, so a larger step can slide
# centers out of the inclusion buffer and OPEN a gap that a smaller step did not
# have. 0.0105 degrees leaves a hole; 0.0109 does not. Re-run
# test_reduced_grid_circles_cover_buffered_municipality for any new value
# instead of extrapolating.
DETECTION_GRID_STEP_DEGREES = _env_positive_float(
    "DETECTION_GRID_STEP_DEGREES", 0.009, 0.001
)
NEARBY_RESULT_LIMIT = 60
NEW_NEARBY_RESULT_LIMIT = 20
MAX_ADAPTIVE_DEPTH = 2
MAX_ADAPTIVE_QUERIES_PER_POINT = 12
ADAPTIVE_QUERY_RADIUS_RATIO = 0.72
ADAPTIVE_CENTER_OFFSET_RATIO = 0.5


def _grid_points():
    """Include nearby outside centers so search circles cover the municipal boundary."""
    min_lat, max_lat = 13.9450, 14.0125
    min_lng, max_lng = 121.0120, 121.1260
    step = DETECTION_GRID_STEP_DEGREES
    search_buffer_degrees = (DETECTION_RADIUS_M / 111_320.0) * 1.1
    search_area = _MUNICIPALITY_BOUNDARY.buffer(search_buffer_degrees)
    points = []
    lat = min_lat
    while lat <= max_lat:
        lng = min_lng
        while lng <= max_lng:
            if search_area.contains(Point(lng, lat)):
                points.append((lat, lng))
            lng += step
        lat += step
    return points


def _nearby_api_mode():
    mode = RUN_DETECTION_NEARBY_API
    if mode not in ("legacy", "new"):
        raise RuntimeError(
            "RUN_DETECTION_NEARBY_API must be either 'legacy' or 'new'."
        )
    return mode


def _record_nearby_api_error():
    current = getattr(_places_run_state, "api_errors", 0)
    _places_run_state.api_errors = current + 1


def _active_nearby_result_limit():
    return (
        NEW_NEARBY_RESULT_LIMIT
        if _nearby_api_mode() == "new"
        else NEARBY_RESULT_LIMIT
    )


def _detection_work_budget_reached():
    started_at = getattr(_places_run_state, "started_at", None)
    if started_at is None:
        return False
    calls = getattr(_places_run_state, "calls", {})
    request_count = calls.get("legacy_nearby", 0) + calls.get("new_nearby", 0)
    elapsed_seconds = time.monotonic() - started_at
    reached = (
        elapsed_seconds >= RUN_DETECTION_MAX_SECONDS
        or request_count >= RUN_DETECTION_MAX_REQUESTS
    )
    if reached:
        _places_run_state.work_budget_exhausted = True
        _places_run_state.work_budget_reason = (
            "time_limit"
            if elapsed_seconds >= RUN_DETECTION_MAX_SECONDS
            else "request_limit"
        )
    return reached


def _detection_elapsed_metrics(request_started_at):
    """
    Timing diagnostics for every terminal path.

    `elapsed_seconds` is end-to-end request time, so it includes the
    pre-scan reconciliation pass that is still synchronous. `scan_elapsed_seconds`
    covers only the grid traversal bounded by RUN_DETECTION_MAX_SECONDS.
    `scan_elapsed_seconds` is 0.0 when the run failed before grid traversal
    started, since the work-slice clock is not armed until then.
    """
    now = time.monotonic()
    scan_started_at = getattr(_places_run_state, "started_at", None)
    return {
        "elapsed_seconds": round(now - request_started_at, 1),
        "scan_elapsed_seconds": (
            0.0 if scan_started_at is None
            else round(now - scan_started_at, 1)
        ),
    }


def _normalize_new_nearby_results(data):
    normalized = []
    for place in data.get("places", []) or []:
        location = place.get("location") or {}
        display_name = place.get("displayName") or {}
        primary_type = place.get("primaryType")
        normalized.append({
            "place_id": place.get("id"),
            "name": display_name.get("text") or "Unknown",
            "geometry": {
                "location": {
                    "lat": location.get("latitude"),
                    "lng": location.get("longitude"),
                }
            },
            "vicinity": place.get("formattedAddress"),
            "primaryType": primary_type,
            "types": [primary_type] if primary_type else [],
            "business_status": place.get("businessStatus"),
        })
    return normalized


def _new_nearby_request(lat, lng, radius_m):
    """Send one quota-reserved New Nearby request with bounded RPM retries."""
    global _nearby_last_request_at
    api_key = os.getenv("GOOGLE_MAPS_API_KEY") or os.getenv(
        "GOOGLE_PLACES_API_KEY")
    if not api_key:
        raise RuntimeError(
            "GOOGLE_MAPS_API_KEY or GOOGLE_PLACES_API_KEY must be configured "
            "on the backend."
        )
    if NEW_NEARBY_DAILY_CAP <= 0 or NEW_NEARBY_MONTHLY_CAP <= 0:
        raise PlacesBudgetExceeded(
            "Nearby Search (New) is disabled until positive "
            "NEW_NEARBY_DAILY_CAP and NEW_NEARBY_MONTHLY_CAP limits are configured."
        )

    payload = {
        "excludedTypes": list(NEW_NEARBY_EXCLUDED_TYPES),
        "maxResultCount": NEW_NEARBY_RESULT_LIMIT,
        "locationRestriction": {
            "circle": {
                "center": {"latitude": lat, "longitude": lng},
                "radius": radius_m,
            }
        },
    }
    headers = {
        "Content-Type": "application/json",
        "X-Goog-Api-Key": api_key,
        "X-Goog-FieldMask": NEW_NEARBY_FIELD_MASK,
    }

    for attempt in range(4):
        if _detection_work_budget_reached():
            return [], False
        with _nearby_request_lock:
            elapsed = time.monotonic() - _nearby_last_request_at
            if _nearby_last_request_at and elapsed < 0.3:
                time.sleep(max(0.0, random.uniform(0.3, 0.5) - elapsed))
            try:
                allowed, reason = reserve_usage_slot(
                    mysql.connection,
                    "new_nearby_month",
                    "new_nearby_day",
                    NEW_NEARBY_MONTHLY_CAP,
                    NEW_NEARBY_DAILY_CAP,
                )
            except Exception as exc:
                print(
                    f"[Run Detection] new_nearby reservation failed closed: {exc}")
                raise PlacesBudgetExceeded(
                    "Nearby Search (New) usage ledger is unavailable; no request was sent."
                ) from exc
            if not allowed:
                raise PlacesBudgetExceeded(
                    f"Nearby Search (New) {reason.replace('_', ' ')} "
                    f"(daily {NEW_NEARBY_DAILY_CAP}, monthly {NEW_NEARBY_MONTHLY_CAP}).",
                    reason=reason,
                )
            calls = getattr(_places_run_state, "calls", None)
            if calls is not None:
                calls["new_nearby"] += 1
                query_kind = getattr(
                    _places_run_state, "query_kind", "initial")
                calls[f"new_nearby_{query_kind}"] += 1

            try:
                response = http.post(
                    NEW_NEARBY_URL, headers=headers, json=payload, timeout=10
                )
                _nearby_last_request_at = time.monotonic()
            except http.RequestException as exc:
                _record_nearby_api_error()
                print(
                    "[Run Detection] Nearby Search (New) network error "
                    f"({type(exc).__name__})"
                )
                return [], False

        if response.status_code == 429:
            body = getattr(response, "text", "") or ""
            print(
                f"[Run Detection] Nearby Search (New) HTTP 429 "
                f"attempt={attempt + 1} body={body[:2000]}"
            )
            lowered = body.lower()
            per_minute = any(marker in lowered for marker in (
                "requestsperminute", "requests_per_minute", "per minute",
                "per_minute", "rate limit", "rate_limit",
            ))
            daily_quota = any(marker in lowered for marker in (
                "resource_exhausted", "requestsperday", "per_day", "per day",
                "daily quota", "quota exceeded",
            ))
            if per_minute and attempt < 3:
                delay = (2 ** (attempt + 1)) * random.uniform(0.8, 1.2)
                print(
                    f"[Run Detection] New Nearby per-minute throttle; "
                    f"retry {attempt + 1}/3 after {delay:.2f}s"
                )
                time.sleep(delay)
                continue
            if daily_quota or not per_minute:
                raise PlacesBudgetExceeded(
                    "Nearby Search (New) quota exhausted by Google (HTTP 429); "
                    "stopping Places calls for this run.",
                    reason=(
                        "daily_quota_exceeded"
                        if daily_quota else "skipped_quota"
                    ),
                )
            _record_nearby_api_error()
            print("[Run Detection] New Nearby per-minute retries exhausted.")
            return [], False

        if response.status_code != 200:
            _record_nearby_api_error()
            body = getattr(response, "text", "") or ""
            print(
                f"[Run Detection] Nearby Search (New) HTTP "
                f"{response.status_code}: {body[:2000]}"
            )
            return [], False
        try:
            return _normalize_new_nearby_results(response.json()), True
        except (ValueError, TypeError) as exc:
            _record_nearby_api_error()
            print(
                f"[Run Detection] Nearby Search (New) invalid response: {exc}")
            return [], False
    return [], False


def _fetch_point_results_once(lat, lng, radius_m):
    if _nearby_api_mode() == "new":
        return _new_nearby_request(lat, lng, radius_m)
    return _fetch_legacy_point_results_once(lat, lng, radius_m)


def _fetch_legacy_point_results_once(lat, lng, radius_m):
    """
    Fetch all result pages for ONE grid point. Nothing is stored.
    Returns (results, complete). Raises PlacesBudgetExceeded when a limit is hit.
    """
    api_key = (
        os.getenv("GOOGLE_MAPS_API_KEY")
        or os.getenv("GOOGLE_PLACES_API_KEY")
    )
    if not api_key:
        raise RuntimeError(
            "GOOGLE_MAPS_API_KEY environment variable is not configured.")

    url = "https://maps.googleapis.com/maps/api/place/nearbysearch/json"
    params = {"location": f"{lat},{lng}", "radius": radius_m, "key": api_key}
    headers = {"User-Agent": "REVELA-Backend/1.0"}
    results, complete = [], True

    while True:
        if _detection_work_budget_reached():
            return results, False
        try:
            resp = _places_get("nearby", url, params=params,
                               headers=headers, timeout=10)
            data = resp.json()
        except PlacesBudgetExceeded:
            raise
        except Exception as he:
            _record_nearby_api_error()
            print(
                f"[Run Detection] HTTP error querying point ({lat}, {lng}): "
                f"{type(he).__name__}"
            )
            return results, False

        status = data.get("status")
        err_msg = data.get("error_message") or ""
        if status == "OVER_QUERY_LIMIT":
            raise PlacesBudgetExceeded(
                f"Places API daily budget reached (Google returned {status}). Try again tomorrow.")
        if status == "REQUEST_DENIED":
            details = f": {err_msg}" if err_msg else ""
            raise RuntimeError(
                f"Google Maps Places API request was denied (REQUEST_DENIED){details}. "
                "This is not a daily quota limit. Please verify in Google Cloud Console that 'Places API' "
                "is enabled, billing is active, and the API key has no incompatible HTTP referrer restrictions."
            )
        if status not in ("OK", "ZERO_RESULTS"):
            _record_nearby_api_error()
            print(
                f"[Run Detection] Places API status: {status}, message: {err_msg}")
            return results, False

        results.extend(data.get("results", []))
        next_token = data.get("next_page_token")
        if not next_token:
            return results, complete
        time.sleep(2)
        params = {"pagetoken": next_token, "key": api_key}


def _adaptive_nearby_centers(lat, lng, radius_m):
    """Split a saturated search circle into four overlapping, smaller search circles."""
    lat_offset = radius_m * ADAPTIVE_CENTER_OFFSET_RATIO / 111_320.0
    lng_scale = max(0.01, math.cos(math.radians(lat)))
    lng_offset = radius_m * ADAPTIVE_CENTER_OFFSET_RATIO / \
        (111_320.0 * lng_scale)
    child_radius = radius_m * ADAPTIVE_QUERY_RADIUS_RATIO
    return [
        (lat + lat_sign * lat_offset, lng + lng_sign * lng_offset, child_radius)
        for lat_sign, lng_sign in ((-1, -1), (-1, 1), (1, -1), (1, 1))
    ]


def _nearby_circle_intersects_municipality(lat, lng, radius_m):
    center = Point(
        lng * _METERS_PER_DEGREE_LNG,
        lat * _METERS_PER_DEGREE_LAT,
    )
    return (
        _MUNICIPALITY_WITH_TOLERANCE_METERS.distance(center)
        <= radius_m + 10
    )


def _fetch_point_results(lat, lng, radius_m):
    """
    Fetch one grid cell and deduplicate overlapping parent/child results by place ID.
    Refinement is bounded; a still-saturated area is left uncheckpointed for a later scan.
    """
    query_budget = {"remaining": MAX_ADAPTIVE_QUERIES_PER_POINT}
    results, complete = _fetch_point_results_adaptive(
        lat, lng, radius_m, depth=0, query_budget=query_budget
    )
    return _deduplicate_nearby_results(results), complete


def _fetch_point_results_adaptive(lat, lng, radius_m, depth, query_budget):
    if _detection_work_budget_reached():
        return [], False
    result_limit = _active_nearby_result_limit()
    previous_query_kind = getattr(_places_run_state, "query_kind", "initial")
    _places_run_state.query_kind = "adaptive" if depth else "initial"
    try:
        results, complete = _fetch_point_results_once(lat, lng, radius_m)
    finally:
        _places_run_state.query_kind = previous_query_kind
    _places_run_state.results_received = (
        getattr(_places_run_state, "results_received", 0) + len(results)
    )
    if not complete:
        return results, False
    if len(results) < result_limit:
        return results, True

    print(
        f"[Run Detection] Nearby Search saturated at {len(results)} results "
        f"(limit {result_limit}) "
        f"near ({lat:.5f}, {lng:.5f}); refining dense area"
    )
    if depth >= MAX_ADAPTIVE_DEPTH:
        return results, False

    refined = list(results)
    refined_complete = True
    for child_lat, child_lng, child_radius in _adaptive_nearby_centers(
        lat, lng, radius_m
    ):
        if not _nearby_circle_intersects_municipality(
            child_lat, child_lng, child_radius
        ):
            continue
        if query_budget["remaining"] <= 0 or _detection_work_budget_reached():
            refined_complete = False
            break
        query_budget["remaining"] -= 1
        child_results, child_complete = _fetch_point_results_adaptive(
            child_lat, child_lng, child_radius, depth + 1, query_budget
        )
        refined.extend(child_results)
        refined_complete = refined_complete and child_complete

    return refined, refined_complete


def _deduplicate_nearby_results(results):
    """Merge repeated Places records while retaining the first complete location."""
    unique = []
    places_by_id = {}
    duplicate_count = 0
    for place in results:
        place_id = place.get("place_id")
        if not place_id:
            unique.append(place)
            continue
        existing = places_by_id.get(place_id)
        if existing is None:
            places_by_id[place_id] = place
            unique.append(place)
            continue
        duplicate_count += 1
        _merge_nearby_place(existing, place)

    _places_run_state.duplicate_results = (
        getattr(_places_run_state, "duplicate_results", 0) + duplicate_count
    )
    return unique


def _merge_nearby_place(existing, duplicate):
    """Fill absent metadata from duplicate records without replacing a known location."""
    for key in ("name", "vicinity", "primaryType", "business_status"):
        current = existing.get(key)
        incoming = duplicate.get(key)
        if (current is None or current == "" or current == "Unknown") and incoming:
            existing[key] = incoming

    types = list(existing.get("types") or [])
    for place_type in duplicate.get("types") or []:
        if place_type not in types:
            types.append(place_type)
    if types:
        existing["types"] = types

    current_location = (
        (existing.get("geometry") or {}).get("location") or {}
    )
    duplicate_location = (
        (duplicate.get("geometry") or {}).get("location") or {}
    )
    if (
        (current_location.get("lat") is None or current_location.get("lng") is None)
        and duplicate_location.get("lat") is not None
        and duplicate_location.get("lng") is not None
    ):
        existing.setdefault("geometry", {})[
            "location"] = dict(duplicate_location)


def _scan_grid(process_places, progress_cb, state):
    """
    Walk the grid. For every point not finished in this scan cycle:
    fetch -> process_places(results inside the municipality) -> checkpoint.
    `state` is filled in as we go, so the caller still has it if PlacesBudgetExceeded is raised.
    """
    done_before = _completed_points_this_cycle()
    points = _grid_points()
    state["total_points"] = len(points)

    for idx, (lat, lng) in enumerate(points):
        if is_cancelled("run_detection"):
            break
        if _detection_work_budget_reached():
            state["work_budget_stop"] = True
            break
        key = f"{lat:.5f},{lng:.5f}"
        if key in done_before:
            state["skipped_points"] += 1
            continue

        if progress_cb:
            progress_cb(idx, len(points), lat, lng)

        errors_before_query = getattr(_places_run_state, "api_errors", 0)
        results, complete = _fetch_point_results(lat, lng, DETECTION_RADIUS_M)
        api_error_during_query = (
            getattr(_places_run_state, "api_errors", 0) > errors_before_query
        )
        if not complete:
            state["incomplete_points"] += 1

        inside = []
        for p in results:
            loc = (p.get("geometry") or {}).get("location") or {}
            p_lat, p_lng = loc.get("lat"), loc.get("lng")
            if p_lat is None or p_lng is None:
                continue
            if _within_municipality(p_lat, p_lng):
                inside.append(p)
            else:
                state["outside"] += 1

        process_places(inside)
        if getattr(_places_run_state, "work_budget_exhausted", False):
            if complete:
                state["incomplete_points"] += 1
            state["work_budget_stop"] = True
            break
        if api_error_during_query:
            state["api_error_stop"] = True
            break
        if complete:
            _mark_point_done(key)
            state["done_keys"].append(key)


def _grid_scan_has_terminal_gaps(state):
    attempted_points = (
        state["skipped_points"]
        + len(state["done_keys"])
        + state["incomplete_points"]
    )
    return (
        attempted_points >= state["total_points"]
        and state["incomplete_points"] > 0
        and not state.get("api_error_stop")
        and not state.get("work_budget_stop")
    )


# ── Registry loader ───────────────────────────────────────────────────────────

def _load_registry():
    """Load all official registry entries into memory for cross-referencing."""
    cursor = mysql.connection.cursor()
    cursor.execute("""
        SELECT r.businessID, r.barangayID, r.businessName, r.applicationStatus,
               r.businessType AS businessType,
               r.lineOfBusiness AS businessLine,
               r.businessAddress AS businessAddress,
               r.placeID, r.coordSource, r.matchStatus,
               COALESCE(r.latitude, g.latitude) AS latitude,
               COALESCE(r.longitude, g.longitude) AS longitude
        FROM official_registry r
        LEFT JOIN LATERAL (
            SELECT latitude, longitude
            FROM geospatial_logs
            WHERE flagColor = 'Green'
              AND latitude IS NOT NULL
              AND ((businessID IS NOT NULL AND businessID = r.businessID) OR (businessID IS NULL AND detectedName = r.businessName AND barangayID = r.barangayID))
            ORDER BY (businessID = r.businessID) DESC
            LIMIT 1
        ) g ON TRUE
    """)
    rows = cursor.fetchall()
    cursor.close()
    return rows


def _log_detection_summary(
    run_id, state, counters, stop_reason=None, elapsed=None
):
    calls = getattr(_places_run_state, "calls", {})
    state["api_errors"] = getattr(_places_run_state, "api_errors", 0)
    state["work_budget_reason"] = getattr(
        _places_run_state, "work_budget_reason", None
    )
    try:
        usage = get_places_usage_today()
    except Exception as exc:
        print(
            f"[Run Detection] run={run_id} Places usage summary unavailable "
            f"({type(exc).__name__})"
        )
        return None
    print(
        f"[Run Detection] run={run_id} mode={_nearby_api_mode()} "
        f"matched={counters['matched']} no_match={counters['no_match']} "
        f"new_flags={counters['new_flags']} api_error={state['api_errors']} "
        f"quota_stop={stop_reason or 'none'} "
        f"api_error_stop={state.get('api_error_stop', False)} "
        f"work_budget_stop={state.get('work_budget_stop', False)} "
        f"work_budget_reason={state['work_budget_reason'] or 'none'} "
        f"elapsed_seconds={(elapsed or {}).get('elapsed_seconds', 0)} "
        f"scan_elapsed_seconds={(elapsed or {}).get('scan_elapsed_seconds', 0)} "
        f"grid_completed={state['skipped_points'] + len(state['done_keys'])}/"
        f"{state['total_points']} grid_incomplete={state['incomplete_points']} "
        f"results={getattr(_places_run_state, 'results_received', 0)} "
        f"duplicates={getattr(_places_run_state, 'duplicate_results', 0) + counters.get('duplicates', 0)} "
        f"non_business={counters.get('non_business', 0)} "
        f"closed_results={counters.get('closed_results', 0)} "
        f"review={counters.get('review', 0)} "
        f"initial_requests="
        f"{calls.get('legacy_nearby_initial', 0) + calls.get('new_nearby_initial', 0)} "
        f"adaptive_requests="
        f"{calls.get('legacy_nearby_adaptive', 0) + calls.get('new_nearby_adaptive', 0)} "
        f"calls_this_run={calls} "
        f"legacy_nearby_day/month="
        f"{usage['nearby_search_legacy']['used_today']}/"
        f"{usage['nearby_search_legacy']['used_month']} "
        f"new_nearby_day/month="
        f"{usage['nearby_search_new']['used_today']}/"
        f"{usage['nearby_search_new']['used_month']} "
        f"text_search_day/month="
        f"{usage['text_search_day']['used']}/"
        f"{usage['text_search_month']['used']} "
        f"details_day/month="
        f"{usage['place_details_day']['used']}/"
        f"{usage['place_details_month']['used']} "
        f"geocode_day/month={usage['geocode']['used']}/"
        f"{usage['geocode']['used_month']}"
    )
    return usage


# ── 20-meter threshold check ──────────────────────────────────────────────────

def _find_nearest(poi_lat, poi_lng, registry):
    """
    For a given POI, find the nearest OFFICIAL_REGISTRY entry.
    Returns (nearest_row, distance_in_meters).
    """
    nearest = None
    nearest_dist = float("inf")

    for entry in registry:
        if not entry["latitude"] or not entry["longitude"]:
            continue
        dist = geodesic(
            (poi_lat, poi_lng),
            (float(entry["latitude"]), float(entry["longitude"]))
        ).meters

        if dist < nearest_dist:
            nearest_dist = dist
            nearest = entry

    return nearest, nearest_dist


# ── Barangay resolver ─────────────────────────────────────────────────────────

def _get_barangay_id_by_coords(
    lat, lng, barangay_rows=None, fallback_rows=None
):
    """
    Find which barangayID a POI belongs to by checking GeoJSON boundaries.
    Falls back to proximity to existing registry entries if not found in any polygon.
    """
    pt = Point(lng, lat)
    matched_geojson_name = None
    for name, poly in _BARANGAY_POLYGONS.items():
        if poly.contains(pt):
            matched_geojson_name = name
            break

    if not matched_geojson_name:
        for name, poly in _BARANGAY_POLYGONS.items():
            if poly.buffer(0.001).contains(pt):
                matched_geojson_name = name
                break

    if matched_geojson_name:
        if barangay_rows is None:
            cursor = mysql.connection.cursor()
            try:
                cursor.execute(
                    "SELECT barangayID, barangayName FROM barangays")
                barangay_rows = cursor.fetchall()
            finally:
                cursor.close()

        mapping = {
            "District I (Pob.)": "Barangay I",
            "District II (Pob.)": "Barangay II",
            "District III (Pob.)": "Barangay III",
            "District IV (Pob.)": "Barangay IV",
            "Barangay II-A (Pob.)": "Barangay II-A",
            "Lumang Lipa": "Barangay Lumanglipa"
        }

        for b in barangay_rows:
            b_name = b['barangayName']
            target_name = mapping.get(matched_geojson_name)

            if target_name and target_name == b_name:
                return b["barangayID"]

            if not target_name and matched_geojson_name.lower() in b_name.lower():
                return b["barangayID"]

    # Fallback to proximity
    if fallback_rows is None:
        cursor = mysql.connection.cursor()
        try:
            cursor.execute("""
                SELECT barangayID, latitude, longitude
                FROM official_registry
                WHERE latitude IS NOT NULL AND longitude IS NOT NULL
            """)
            fallback_rows = cursor.fetchall()
        finally:
            cursor.close()

    if not fallback_rows:
        return 1

    nearest_id = 1
    nearest_dist = float("inf")
    for row in fallback_rows:
        dist = geodesic(
            (lat, lng),
            (float(row["latitude"]), float(row["longitude"]))
        ).meters
        if dist < nearest_dist:
            nearest_dist = dist
            nearest_id = row["barangayID"]

    return nearest_id


# ── Already flagged check ─────────────────────────────────────────────────────

def _already_flagged(place_id):
    """Return True if this place_id already has any flag in GEOSPATIAL_LOGS."""
    cursor = mysql.connection.cursor()
    cursor.execute("""
        SELECT logID FROM geospatial_logs
        WHERE placeID = %s
        LIMIT 1
    """, (place_id,))
    row = cursor.fetchone()
    cursor.close()
    return row is not None


# ── Insert Red Flag ───────────────────────────────────────────────────────────

def _insert_red_flag(place_id, place_name, lat, lng, barangay_id, address=None, poi_types=()):
    serialized_types = json.dumps(
        sorted(set(poi_types))) if poi_types else None
    cursor = mysql.connection.cursor()
    cursor.execute("""
        INSERT INTO geospatial_logs
            (barangayID, reportID, detectedName, latitude, longitude,
             flagColor, placeID, nearestLandmark, placeTypes)
        VALUES (%s, NULL, %s, %s, %s, 'Red', %s, %s, %s)
    """, (barangay_id, place_name, lat, lng, place_id, address, serialized_types))
    flag_id = cursor.lastrowid
    mysql.connection.commit()
    cursor.close()
    return flag_id


def _is_non_business_place(place):
    """
    Return True if this POI is non-commercial (religious, public school, government,
    cemetery, park, infrastructure, residential).
    Such places must NEVER be flagged as unregistered commercial businesses.
    """
    # 1. Closed permanently
    types = set(place.get("types") or [])
    if place.get("primaryType"):
        types.add(place["primaryType"])

    # Non-business Google types
    disqualifying_types = {
        # Religious
        "place_of_worship", "church", "mosque", "hindu_temple", "synagogue",
        # Education / Schools
        "school", "primary_school", "secondary_school", "university",
        # Government & Municipal infrastructure
        "local_government_office", "city_hall", "courthouse", "embassy",
        "fire_station", "police", "post_office", "library",
        # Public parks, landmarks, cemetery
        "cemetery", "park", "natural_feature",
        # Transit
        "transit_station", "bus_station", "subway_station", "train_station", "light_rail_station",
        # Geographic / Boundaries / Residential
        "political", "neighborhood", "sublocality", "sublocality_level_1", "route", "locality"
    }

    if types.intersection(disqualifying_types):
        return True

    # Name heuristics for local public/community facilities
    name_lower = (place.get("name") or "").lower()
    non_business_keywords = [
        "barangay hall", "brgy hall", "covered court", "basketball court",
        "elementary school", "national high school", "integrated school",
        "parish church", "catholic church", "chapel", "kapilya", "iglesia ni cristo",
        "health center", "rural health", "police station", "municipal hall",
        "memorial park", "cemetery", "santo entiero", "waiting shed",
        "purok outpost", "tanod outpost"
    ]
    if any(kw in name_lower for kw in non_business_keywords):
        return True

    return False


# ── Main detection runner ─────────────────────────────────────────────────────


def run_detection(user_id=None):
    """
    Full detection cycle, resumable across days:
    1. Enforce monthly limit (max 2 completed scans per calendar month)
    2. For each grid point not yet done in this cycle: fetch Places POIs, cross-reference against
       OFFICIAL_REGISTRY, insert Red Flags for unmatched POIs, checkpoint the point
    3. If the Places budget runs out, keep the progress and stop (status 'partial', quota NOT used)
    """
    request_started_at = time.monotonic()
    set_cancel("run_detection", False)
    _places_run_state.calls = {
        "legacy_nearby": 0,
        "legacy_nearby_initial": 0,
        "legacy_nearby_adaptive": 0,
        "new_nearby": 0,
        "new_nearby_initial": 0,
        "new_nearby_adaptive": 0,
    }
    _places_run_state.api_errors = 0
    _places_run_state.results_received = 0
    _places_run_state.duplicate_results = 0
    _places_run_state.query_kind = "initial"
    _places_run_state.started_at = None
    _places_run_state.work_budget_exhausted = False
    _places_run_state.work_budget_reason = None

    quota_info = get_detection_quota_info()
    if quota_info.get("is_limit_reached"):
        limit = quota_info.get("monthly_limit", 2)
        return None, f"Monthly detection limit reached ({limit}/{limit} scans used for this month). Detection scans can only be run {limit} times a month."

    # Guard: check if official_registry has any records
    cursor = mysql.connection.cursor()
    try:
        cursor.execute("SELECT COUNT(*) AS total FROM official_registry")
        row = cursor.fetchone()
        reg_count = (row.get("total") if isinstance(
            row, dict) else row[0]) if row else 0
        if reg_count == 0:
            return None, "Cannot run detection: The official business registry is empty. Please import official business records first so REVELA has a baseline to cross-reference against."
    finally:
        cursor.close()

    run_id = create_detection_run(user_id)
    state = {
        "done_keys": [], "total_points": 0, "skipped_points": 0,
        "outside": 0, "incomplete_points": 0, "api_errors": 0,
        "api_error_stop": False,
    }
    inserted_flag_ids = []
    seen_place_ids = set()
    counters = {
        "new_flags": 0, "total_checked": 0, "matched": 0, "no_match": 0,
        "duplicates": 0, "non_business": 0, "closed_results": 0, "review": 0,
    }

    try:
        def progress_callback(idx, total_steps, lat, lng):
            percentage = int((idx / max(total_steps, 1)) * 95)
            hub.publish_to_admins({
                "type": "detection_progress",
                "stage": "scanning",
                "current_step": idx + 1,
                "total_steps": total_steps,
                "percentage": percentage,
                "status": f"Scanning coordinates ({lat:.4f}, {lng:.4f}) — step {idx + 1} of {total_steps}..."
            })

        hub.publish_to_admins({
            "type": "detection_progress", "stage": "matching", "percentage": 1,
            "status": "Loading official business registry database..."
        })
        _ensure_place_types_column()
        registry = _load_registry()
        lookup_cursor = mysql.connection.cursor()
        try:
            lookup_cursor.execute(
                "SELECT barangayID, barangayName FROM barangays")
            barangay_rows = lookup_cursor.fetchall()
        finally:
            lookup_cursor.close()
        try:
            reconcile_existing_flags(silent=True)
        except Exception as re_err:
            print(f"[Run Detection] Reconcile error: {re_err}")

        def process_places(places):
            for place in places:
                if _detection_work_budget_reached():
                    return
                place_id = place.get("place_id")
                if not place_id:
                    continue
                if place_id in seen_place_ids:
                    counters["duplicates"] += 1
                    continue          # adjacent grid cells can return the same place
                seen_place_ids.add(place_id)
                counters["total_checked"] += 1

                place_name = place.get("name", "Unknown")
                loc = (place.get("geometry") or {}).get("location") or {}
                lat, lng = loc.get("lat"), loc.get("lng")
                address = place.get("vicinity")
                if not lat or not lng:
                    continue
                if place.get("business_status") in (
                    "CLOSED_PERMANENTLY", "CLOSED_TEMPORARILY"
                ):
                    counters["closed_results"] += 1

                cursor = mysql.connection.cursor()
                cursor.execute("""
                    SELECT logID, flagColor FROM geospatial_logs
                    WHERE placeID = %s
                    LIMIT 1
                """, (place_id,))
                existing_flag = cursor.fetchone()
                cursor.close()

                if existing_flag and existing_flag["flagColor"] in ("Green", "Orange", "Black", "Purple"):
                    continue

                barangay_id = _get_barangay_id_by_coords(
                    lat, lng, barangay_rows
                )

                if _is_non_business_place(place):
                    counters["non_business"] += 1
                    if existing_flag and existing_flag["flagColor"] == "Red":
                        cursor = mysql.connection.cursor()
                        cursor.execute(
                            "DELETE FROM geospatial_logs WHERE logID = %s", (existing_flag["logID"],))
                        mysql.connection.commit()
                        cursor.close()
                    continue

                matching_by_place = None
                if place_id:
                    for entry in registry:
                        if entry.get("placeID") == place_id:
                            matching_by_place = entry
                            break

                p_types = place.get("types") or []
                if place.get("primaryType"):
                    p_types = list(p_types) + [place.get("primaryType")]
                poi_types = tuple(sorted(set(p_types)))

                if matching_by_place:
                    nearest = matching_by_place
                    dist = 0.0
                    sim_score = 1.0
                    match_status = "auto"
                else:
                    nearest, dist, sim_score, match_status = _match_poi_to_registry(
                        place_name, lat, lng, registry,
                        poi_barangay_id=barangay_id,
                        poi_types=poi_types,
                        poi_address=address or "",
                    )

                if nearest is None or match_status == "no_match":
                    # Guard: Detection skips creating a Red flag for any Google POI whose
                    # placeID is already held by an official registry business
                    is_held = False
                    if place_id:
                        if any(e.get("placeID") == place_id for e in registry):
                            is_held = True
                        else:
                            cursor = mysql.connection.cursor()
                            cursor.execute(
                                "SELECT businessID FROM official_registry WHERE placeID = %s LIMIT 1",
                                (place_id,)
                            )
                            held_row = cursor.fetchone()
                            cursor.close()
                            if held_row:
                                is_held = True

                    if is_held:
                        counters["matched"] += 1
                        continue

                    counters["no_match"] += 1
                    if not existing_flag:
                        flag_id = _insert_red_flag(
                            place_id, place_name, lat, lng, barangay_id, address,
                            poi_types=poi_types,
                        )
                        inserted_flag_ids.append(flag_id)
                        counters["new_flags"] += 1
                else:
                    counters["matched"] += 1
                    app_status = (nearest.get("applicationStatus")
                                  or "Active").strip()
                    target_color = (
                        "Green" if app_status == "Active" else
                        "Orange" if app_status == "Expired" else
                        "Black" if app_status == "Revoked" else
                        "Purple" if app_status == "Closed" else "Yellow"
                    )
                    if match_status == "review":
                        target_color = "Yellow"
                        counters["review"] += 1

                    target_barangay_id = nearest.get(
                        "barangayID") or barangay_id
                    _match_registry_to_google(
                        place_id, nearest["businessID"], nearest["businessName"],
                        target_color=target_color, lat=lat, lng=lng, barangay_id=target_barangay_id,
                        match_score=sim_score, match_status=match_status,
                        poi_types=poi_types,
                        poi_address=address,
                    )

        _places_run_state.started_at = time.monotonic()
        _scan_grid(process_places, progress_callback, state)

        if is_cancelled("run_detection"):
            # Roll back the flags created by THIS run and un-checkpoint its points, so a later
            # run re-scans them (otherwise their flags would be missing but the points "done").
            if inserted_flag_ids:
                cursor = mysql.connection.cursor()
                format_strings = ",".join(["%s"] * len(inserted_flag_ids))
                cursor.execute(f"DELETE FROM geospatial_logs WHERE logID IN ({format_strings})", tuple(
                    inserted_flag_ids))
                mysql.connection.commit()
                cursor.close()
            _unmark_points(state["done_keys"])
            update_detection_run_status(run_id, "cancelled")
            hub.publish_to_admins({
                "type": "detection_progress", "stage": "completed", "percentage": 100,
                "status": "Detection cancelled by user. Flags found in this run were rolled back."
            })
            return None, "Detection cancelled by user."

        new_flags = counters["new_flags"]
        total_checked = counters["total_checked"]
        done_total = state["skipped_points"] + len(state["done_keys"])
        terminal_gaps = _grid_scan_has_terminal_gaps(state)
        scan_terminal = done_total >= state["total_points"] or terminal_gaps
        elapsed = _detection_elapsed_metrics(request_started_at)
        places_usage = _log_detection_summary(
            run_id, state, counters, elapsed=elapsed
        )
        print(
            f"[Run Detection] grid summary completed={done_total}/{state['total_points']} "
            f"incomplete_dense_or_failed_points={state['incomplete_points']} "
            f"outside_boundary_results={state['outside']}"
        )

        if terminal_gaps:
            update_detection_run_status(
                run_id, "completed_with_gaps",
                new_flags=new_flags, total_checked=total_checked)
            msg = (
                f"Scan reached all {state['total_points']} grid points, but "
                f"{state['incomplete_points']} dense cells remained saturated. "
                f"{new_flags} new flags were recorded; this attempt counts toward "
                "the monthly scan limit."
            )
            hub.publish_to_admins({
                "type": "detection_progress", "stage": "completed",
                "percentage": 100, "status": msg
            })
        elif not scan_terminal:
            update_detection_run_status(
                run_id, "partial", new_flags=new_flags, total_checked=total_checked)
            msg = (
                f"Scan partial: {done_total} of {state['total_points']} grid points completed. "
                f"{new_flags} new flags recorded. "
                f"{state['incomplete_points']} dense or failed points need another scan."
                + (
                    " Places API returned an error; remaining cells were not requested."
                    if state["api_error_stop"] else
                    " Run again later to finish."
                )
            )
            if state.get("work_budget_stop"):
                msg = (
                    f"Scan paused at its work limit: {done_total} of "
                    f"{state['total_points']} grid points completed. "
                    f"{new_flags} new flags recorded; run again to continue."
                )
            hub.publish_to_admins({
                "type": "detection_progress", "stage": "completed", "percentage": 100,
                "status": msg
            })
        else:
            update_detection_run_status(
                run_id, "completed", new_flags=new_flags, total_checked=total_checked)
            hub.publish_to_admins({
                "type": "detection_progress", "stage": "completed", "percentage": 100,
                "status": f"Scan complete! Discovered {new_flags} new unregistered business{'' if new_flags == 1 else 'es'}."
            })

        return {
            "status": (
                "completed_with_gaps" if terminal_gaps else
                "partial" if not scan_terminal else "completed"
            ),
            "new_flags":        new_flags,
            "total_checked":    total_checked,
            "completed_points": done_total,
            "attempted_points": (
                done_total + state["incomplete_points"]
            ),
            "total_points":     state["total_points"],
            "outside_boundary": state["outside"],
            "incomplete_points": state["incomplete_points"],
            "api_errors": getattr(_places_run_state, "api_errors", 0),
            "run_summary": {
                "results_received": getattr(_places_run_state, "results_received", 0),
                "duplicates": (
                    getattr(_places_run_state, "duplicate_results", 0)
                    + counters["duplicates"]
                ),
                "non_business": counters["non_business"],
                "closed_results": counters["closed_results"],
                "matched": counters["matched"],
                "no_match": counters["no_match"],
                "review": counters["review"],
                "new_flags": counters["new_flags"],
                "initial_requests": (
                    _places_run_state.calls["legacy_nearby_initial"]
                    + _places_run_state.calls["new_nearby_initial"]
                ),
                "adaptive_requests": (
                    _places_run_state.calls["legacy_nearby_adaptive"]
                    + _places_run_state.calls["new_nearby_adaptive"]
                ),
                "api_errors": getattr(_places_run_state, "api_errors", 0),
                "api_error_stop": state["api_error_stop"],
                "work_budget_stop": state.get("work_budget_stop", False),
                "work_budget_reason": state["work_budget_reason"],
                "work_budget_max_seconds": RUN_DETECTION_MAX_SECONDS,
                "work_budget_max_requests": RUN_DETECTION_MAX_REQUESTS,
                **elapsed,
                "quota_stop": None,
            },
            "quota_stop": None,
            "quota":            get_detection_quota_info(),
            "places_usage":     places_usage,
        }, None

    except PlacesBudgetExceeded as be:
        done_total = state["skipped_points"] + len(state["done_keys"])
        places_usage = _log_detection_summary(
            run_id, state, counters, stop_reason=str(be),
            elapsed=_detection_elapsed_metrics(request_started_at),
        )
        update_detection_run_status(
            run_id, "partial",
            new_flags=counters["new_flags"], total_checked=counters["total_checked"])
        msg = (f"{be} Progress is saved: {done_total} of {state['total_points']} grid points are done, "
               f"{counters['new_flags']} new flag(s) recorded in this run. Run Detection again later to continue "
               "where it stopped. This did not use one of your monthly scans.")
        hub.publish_to_admins({
            "type": "detection_progress", "stage": "completed", "percentage": 100, "status": msg
        })
        return {
            "status": be.reason,
            "quota_reason": be.reason,
            "run_summary": {
                "results_received": getattr(_places_run_state, "results_received", 0),
                "duplicates": (
                    getattr(_places_run_state, "duplicate_results", 0)
                    + counters["duplicates"]
                ),
                "non_business": counters["non_business"],
                "closed_results": counters["closed_results"],
                "matched": counters["matched"],
                "no_match": counters["no_match"],
                "review": counters["review"],
                "new_flags": counters["new_flags"],
                "initial_requests": (
                    _places_run_state.calls["legacy_nearby_initial"]
                    + _places_run_state.calls["new_nearby_initial"]
                ),
                "adaptive_requests": (
                    _places_run_state.calls["legacy_nearby_adaptive"]
                    + _places_run_state.calls["new_nearby_adaptive"]
                ),
                "api_errors": getattr(_places_run_state, "api_errors", 0),
                "api_error_stop": state["api_error_stop"],
                "work_budget_stop": state.get("work_budget_stop", False),
                "work_budget_reason": getattr(
                    _places_run_state, "work_budget_reason", None
                ),
                "work_budget_max_seconds": RUN_DETECTION_MAX_SECONDS,
                "work_budget_max_requests": RUN_DETECTION_MAX_REQUESTS,
                **_detection_elapsed_metrics(request_started_at),
                "quota_stop": be.reason,
            },
            "places_usage": places_usage,
            "completed_points": done_total,
            "attempted_points": (
                done_total + state["incomplete_points"]
            ),
            "total_points": state["total_points"],
        }, msg

    except Exception as e:
        elapsed = _detection_elapsed_metrics(request_started_at)
        print(
            f"[Run Detection] run={run_id} failed ({type(e).__name__}) "
            f"elapsed_seconds={elapsed['elapsed_seconds']} "
            f"scan_elapsed_seconds={elapsed['scan_elapsed_seconds']}"
        )
        update_detection_run_status(run_id, "failed")
        return None, str(e)


# ── Get all flags ─────────────────────────────────────────────────────────────

def get_flags(color=None, barangay_id=None, page=1, per_page=50, reported_by_user_id=None):
    """
    Return paginated flag entries with optional filters.

    Results are a UNION of two sources:
      1. geospatial_logs  — POIs detected via Google Places scan or reported by inspectors.
      2. official_registry — Businesses with stored coordinates that have NO matching
         geospatial_log yet.  These appear as "virtual" flags so that all 515+ registry
         businesses with GPS coordinates are visible on the map regardless of whether a
         detection scan has run.  Their flagColor is derived from applicationStatus:
           Active  → Green
           Expired → Orange
           Revoked → Black
           Closed  → Purple
           Pending → Yellow  (anything else → Yellow)
    """
    try:
        cursor = mysql.connection.cursor()

        # ── Build per-source WHERE fragments ────────────────────────────────────
        # Filters that apply to the geospatial_logs branch
        geo_conditions = []
        geo_params = []

        # Filters that apply to the registry-only branch
        reg_conditions = [
            # Exclude registry rows that already have a geospatial_log (avoids duplicates)
            """
            NOT EXISTS (
                SELECT 1 FROM geospatial_logs g2
                WHERE (g2.businessID IS NOT NULL AND g2.businessID = r.businessID)
                   OR (g2.placeID IS NOT NULL AND g2.placeID = r.placeID
                       AND (g2.businessID IS NULL OR g2.businessID = r.businessID))
                   OR (g2.businessID IS NULL AND g2.detectedName = r.businessName AND g2.barangayID = r.barangayID)
            )
            """,
        ]
        reg_params = []

        # reporter filter only applies to geospatial_logs (registry has no reporter)
        if reported_by_user_id:
            geo_conditions.append("g.reportedByUserID = %s")
            geo_params.append(reported_by_user_id)
            # When filtering by reporter, registry-only rows should be excluded
            reg_conditions.append("FALSE")

        if color:
            # Map the color filter back to the applicationStatus for the registry branch
            _status_for_color = {
                "Green":  "Active",
                "Orange": "Expired",
                "Black":  "Revoked",
                "Purple": "Closed",
                "Yellow": "Pending",
            }
            mapped_status = _status_for_color.get(color)
            if mapped_status:
                geo_conditions.append(
                    "(g.flagColor = %s OR EXISTS ("
                    "    SELECT 1 FROM official_registry r_chk"
                    "    WHERE ((g.businessID IS NOT NULL AND r_chk.businessID = g.businessID)"
                    "           OR (g.placeID IS NOT NULL AND r_chk.placeID = g.placeID"
                    "               AND (g.businessID IS NULL OR r_chk.businessID = g.businessID))"
                    "           OR (g.businessID IS NULL AND r_chk.barangayID = g.barangayID AND r_chk.businessName = g.detectedName))"
                    "      AND r_chk.applicationStatus = %s"
                    "))"
                )
                geo_params.extend([color, mapped_status])
                reg_conditions.append("r.applicationStatus = %s")
                reg_params.append(mapped_status)
            else:
                # Color has no registry equivalent (e.g. Red for detected unregistered POIs)
                geo_conditions.append(
                    "(g.flagColor = %s AND NOT EXISTS ("
                    "    SELECT 1 FROM official_registry r_chk"
                    "    WHERE ((g.businessID IS NOT NULL AND r_chk.businessID = g.businessID)"
                    "           OR (g.placeID IS NOT NULL AND r_chk.placeID = g.placeID"
                    "               AND (g.businessID IS NULL OR r_chk.businessID = g.businessID))"
                    "           OR (g.businessID IS NULL AND r_chk.barangayID = g.barangayID AND r_chk.businessName = g.detectedName))"
                    "      AND r_chk.applicationStatus IN ('Active', 'Expired', 'Revoked', 'Closed', 'Pending')"
                    "))"
                )
                geo_params.append(color)
                reg_conditions.append("FALSE")

        if barangay_id:
            geo_conditions.append("g.barangayID = %s")
            geo_params.append(barangay_id)
            reg_conditions.append("r.barangayID = %s")
            reg_params.append(barangay_id)

        geo_where = ("WHERE " + " AND ".join(geo_conditions)
                     ) if geo_conditions else ""
        # always has at least 3 conditions
        reg_where = "WHERE " + " AND ".join(reg_conditions)

        offset = (page - 1) * per_page

        # ── Count across both branches ───────────────────────────────────────────
        count_sql = f"""
            SELECT COUNT(*) AS total FROM (
                SELECT g.logID
                FROM geospatial_logs g
                {geo_where}

                UNION ALL

                SELECT r.businessID * -1 AS logID
                FROM official_registry r
                {reg_where}
            ) AS combined
        """
        cursor.execute(count_sql, geo_params + reg_params)
        total = cursor.fetchone()["total"]

        # ── Fetch combined rows ──────────────────────────────────────────────────
        fetch_sql = f"""
            SELECT * FROM (

                -- Branch 1: existing geospatial_logs entries
                SELECT
                    g.logID,
                    COALESCE(g.businessID, r.businessID) AS businessID,
                    g.detectedName,
                    COALESCE(g.latitude, r.latitude) AS latitude,
                    COALESCE(g.longitude, r.longitude) AS longitude,
                    CASE
                        WHEN r.businessID IS NOT NULL AND r.applicationStatus = 'Active'  THEN 'Green'
                        WHEN r.businessID IS NOT NULL AND r.applicationStatus = 'Expired' THEN 'Orange'
                        WHEN r.businessID IS NOT NULL AND r.applicationStatus = 'Revoked' THEN 'Black'
                        WHEN r.businessID IS NOT NULL AND r.applicationStatus = 'Closed'  THEN 'Purple'
                        WHEN r.businessID IS NOT NULL AND r.applicationStatus = 'Pending' THEN 'Yellow'
                        ELSE g.flagColor
                    END AS flagColor,
                    g.detectedDate,
                    g.nearestLandmark,
                    g.notes,
                    g.placeID,
                    g.reportedByUserID,
                    g.noticeLevel,
                    b.barangayID,
                    b.barangayName,
                    r.businessSize,
                    COALESCE(g.nearestLandmark, r.businessAddress) AS resolvedAddress,
                    CASE
                        WHEN g.reportedByUserID IS NOT NULL AND g.flagColor != 'Green' THEN 'inspector_reported'
                        WHEN g.placeID IS NOT NULL AND r.businessID IS NOT NULL THEN 'registry_and_maps'
                        WHEN g.placeID IS NULL AND r.businessID IS NOT NULL THEN 'registry_only'
                        ELSE 'maps_only'
                    END AS flagSource,
                    (
                        SELECT verificationStatus
                        FROM inspection_reports
                        WHERE targetID = g.logID
                          AND targetType = 'geospatial_log'
                        ORDER BY irTimestamp DESC
                        LIMIT 1
                    ) AS verificationStatus,
                    r.matchStatus,
                    r.coordSource,
                    r.matchScore
                FROM geospatial_logs g
                LEFT JOIN barangays b ON g.barangayID = b.barangayID
                LEFT JOIN LATERAL (
                    SELECT businessID, businessSize, businessAddress, latitude, longitude, applicationStatus,
                           matchStatus, coordSource, matchScore
                    FROM official_registry
                    WHERE (g.businessID IS NOT NULL AND businessID = g.businessID)
                       OR (g.placeID IS NOT NULL AND placeID = g.placeID
                           AND (g.businessID IS NULL OR businessID = g.businessID))
                       OR (g.businessID IS NULL AND barangayID = g.barangayID AND businessName = g.detectedName)
                    ORDER BY (g.businessID IS NOT NULL AND businessID = g.businessID) DESC,
                             (g.placeID IS NOT NULL AND placeID = g.placeID) DESC
                    LIMIT 1
                ) r ON TRUE
                {geo_where}

                UNION ALL

                -- Branch 2: registry-only businesses (have coordinates, no geospatial_log yet)
                SELECT
                    r.businessID * -1          AS logID,
                    r.businessID               AS businessID,
                    r.businessName             AS detectedName,
                    r.latitude                 AS latitude,
                    r.longitude                AS longitude,
                    CASE r.applicationStatus
                        WHEN 'Active'  THEN 'Green'
                        WHEN 'Expired' THEN 'Orange'
                        WHEN 'Revoked' THEN 'Black'
                        WHEN 'Closed'  THEN 'Purple'
                        ELSE 'Yellow'
                    END                        AS flagColor,
                    COALESCE(r.lastRenewalDate, NOW()) AS detectedDate,
                    r.businessAddress          AS nearestLandmark,
                    NULL                       AS notes,
                    NULL                       AS placeID,
                    NULL                       AS reportedByUserID,
                    0                          AS noticeLevel,
                    b.barangayID               AS barangayID,
                    b.barangayName             AS barangayName,
                    r.businessSize             AS businessSize,
                    r.businessAddress          AS resolvedAddress,
                    'registry_only'            AS flagSource,
                    NULL                       AS verificationStatus,
                    r.matchStatus              AS matchStatus,
                    r.coordSource              AS coordSource,
                    r.matchScore               AS matchScore
                FROM official_registry r
                LEFT JOIN barangays b ON r.barangayID = b.barangayID
                {reg_where}

            ) AS combined
            ORDER BY detectedDate DESC
            LIMIT %s OFFSET %s
        """
        cursor.execute(fetch_sql, geo_params + reg_params + [per_page, offset])
        rows = cursor.fetchall()
        cursor.close()

        for row in rows:
            if row.get("detectedDate"):
                row["detectedDate"] = str(row["detectedDate"])
            if row.get("latitude") is not None:
                row["latitude"] = float(row["latitude"])
            if row.get("longitude") is not None:
                row["longitude"] = float(row["longitude"])
            if row.get("matchScore") is not None:
                row["matchScore"] = float(row["matchScore"])

        return {
            "data":     rows,
            "total":    total,
            "page":     page,
            "per_page": per_page,
            "pages":    max(1, -(-total // per_page)),
        }, None

    except Exception as e:
        return None, str(e)


# ── Insert Yellow Flag ────────────────────────────────────────────────────────

def insert_yellow_flag(business_name, lat, lng, barangay_id, notes=None, flag_color='Yellow', reported_by_user_id=None):
    """Manually insert a Yellow Flag."""
    if flag_color != 'Yellow':
        return None, "Only Yellow flags can be manually created."

    try:
        # Validate that the manual pin falls within the municipality
        if lat and lng and not _within_municipality(float(lat), float(lng)):
            return None, "Cannot place a flag outside the official municipality boundaries."

        cursor = mysql.connection.cursor()
        cursor.execute("""
            INSERT INTO geospatial_logs
                (barangayID, reportID, detectedName, latitude, longitude,
                 flagColor, notes, reportedByUserID)
            VALUES (%s, NULL, %s, %s, %s, %s, %s, %s)
        """, (barangay_id, business_name, lat, lng, flag_color, notes, reported_by_user_id))
        mysql.connection.commit()
        log_id = cursor.lastrowid
        cursor.close()

        # Fire admin notification (non-blocking)
        if reported_by_user_id:
            try:
                from api.notifications.service import notify_yellow_flag_reported
                notify_yellow_flag_reported(
                    log_id=log_id,
                    business_name=business_name,
                    barangay_id=barangay_id,
                    reporter_user_id=reported_by_user_id,
                    flag_color=flag_color,
                )
            except Exception as ne:
                print(f"insert_yellow_flag notification error: {ne}")

        return {"logID": log_id, "lat": lat, "lng": lng}, None
    except Exception as e:
        return None, str(e)


def update_flag_color(log_id, color):
    """Update a flag's color manually (e.g. to Purple, Orange, Yellow, Red, Black, Green).
    Supports both real geospatial_logs (log_id > 0) and virtual registry flags (log_id < 0).
    """
    try:
        cursor = mysql.connection.cursor()

        if log_id < 0:
            biz_id = -log_id
            status_map = {
                "Green": "Active",
                "Purple": "Closed",
                "Orange": "Expired",
                "Black": "Revoked",
                "Yellow": "Pending"
            }
            app_status = status_map.get(color, "Pending")
            cursor.execute(
                "UPDATE official_registry SET applicationStatus = %s WHERE businessID = %s", (app_status, biz_id))
            mysql.connection.commit()
            cursor.close()

            try:
                from api.notifications import hub
                hub.publish_to_admins({
                    "type": "flag_updated",
                    "logID": log_id,
                    "color": color
                })
            except Exception:
                pass
            return True, None

        cursor.execute(
            "SELECT flagColor, detectedName, barangayID FROM geospatial_logs WHERE logID = %s", (log_id,))
        row = cursor.fetchone()
        if not row:
            cursor.close()
            return False, "Flag not found"

        cursor.execute("""
            UPDATE geospatial_logs
            SET flagColor = %s
            WHERE logID = %s
        """, (color, log_id))

        # Propagate changes: if marked Purple, set registry status to Closed
        if color == 'Purple':
            cursor.execute("""
                UPDATE official_registry
                SET applicationStatus = 'Closed'
                WHERE LOWER(businessName) = LOWER(%s) AND barangayID = %s
            """, (row["detectedName"], row["barangayID"]))
        elif color == 'Green' and row["flagColor"] == 'Purple':
            cursor.execute("""
                UPDATE official_registry
                SET applicationStatus = 'Active'
                WHERE LOWER(businessName) = LOWER(%s) AND barangayID = %s AND applicationStatus = 'Closed'
            """, (row["detectedName"], row["barangayID"]))

        mysql.connection.commit()
        cursor.close()

        try:
            from api.notifications import hub
            hub.publish_to_admins({
                "type": "flag_updated",
                "logID": log_id,
                "color": color
            })
        except Exception:
            pass

        return True, None
    except Exception as e:
        return False, str(e)


def update_flag_location(log_id: int, lat: float, lng: float):
    """
    Update coordinates of a flag manually (e.g. via drag-and-drop on the map).
    Handles both:
      - log_id > 0: real geospatial_logs entry
      - log_id < 0: virtual registry entry (businessID = -log_id)
    Also updates barangayID based on new coordinates and backfills official_registry.
    """
    try:
        cursor = mysql.connection.cursor()
        new_barangay_id = _get_barangay_id_by_coords(lat, lng)

        if log_id < 0:
            # Virtual flag from official_registry (businessID = -log_id)
            biz_id = -log_id
            cursor.execute("""
                UPDATE official_registry
                SET latitude = %s,
                    longitude = %s,
                    barangayID = COALESCE(%s, barangayID),
                    coordSource = 'manual',
                    matchStatus = 'approved',
                    coordFetchedAt = NOW(),
                    placeID = NULL,
                    placeIDKind = NULL
                WHERE businessID = %s
            """, (lat, lng, new_barangay_id, biz_id))
            mysql.connection.commit()
            cursor.close()

            try:
                from api.notifications import hub
                hub.publish_to_admins({
                    "type": "flag_location_updated",
                    "logID": log_id,
                    "latitude": lat,
                    "longitude": lng
                })
            except Exception:
                pass

            return True, None

        # Real flag in geospatial_logs
        cursor.execute(
            "SELECT detectedName, barangayID, placeID, latitude, longitude FROM geospatial_logs WHERE logID = %s", (log_id,))
        row = cursor.fetchone()
        if not row:
            cursor.close()
            return False, "Flag not found"

        detected_name = row["detectedName"]
        old_place_id = row.get("placeID")

        # Admin physically moved the pin: clear placeID on geospatial_logs
        cursor.execute("""
            UPDATE geospatial_logs
            SET latitude = %s,
                longitude = %s,
                barangayID = COALESCE(%s, barangayID),
                placeID = NULL
            WHERE logID = %s
        """, (lat, lng, new_barangay_id, log_id))

        # Also backfill official_registry strictly by businessID
        target_biz_id = None
        if old_place_id:
            cursor.execute(
                "SELECT businessID FROM official_registry WHERE placeID = %s LIMIT 1", (old_place_id,))
            reg_match = cursor.fetchone()
            if reg_match:
                target_biz_id = reg_match["businessID"]

        if not target_biz_id and detected_name:
            orig_barangay_id = row.get("barangayID")
            cursor.execute("""
                SELECT businessID FROM official_registry
                WHERE LOWER(businessName) = LOWER(%s)
                  AND (barangayID = %s OR barangayID = %s)
                LIMIT 1
            """, (detected_name, orig_barangay_id, new_barangay_id))
            reg_match = cursor.fetchone()
            if reg_match:
                target_biz_id = reg_match["businessID"]

        if target_biz_id:
            cursor.execute("""
                UPDATE official_registry
                SET latitude = %s,
                    longitude = %s,
                    barangayID = COALESCE(%s, barangayID),
                    coordSource = 'manual',
                    matchStatus = 'approved',
                    coordFetchedAt = NOW(),
                    placeID = NULL,
                    placeIDKind = NULL
                WHERE businessID = %s
            """, (lat, lng, new_barangay_id, target_biz_id))

        mysql.connection.commit()
        cursor.close()

        try:
            from api.notifications import hub
            hub.publish_to_admins({
                "type": "flag_location_updated",
                "logID": log_id,
                "latitude": lat,
                "longitude": lng
            })
        except Exception:
            pass

        return True, None
    except Exception as e:
        return False, str(e)


# ── Escalate to Black Flag ────────────────────────────────────────────────────

def escalate_to_black(log_id):
    """Update flagColor to Black. Only valid if current status is Red, Yellow, or Orange."""
    try:
        if log_id < 0:
            return update_flag_color(log_id, "Black")

        cursor = mysql.connection.cursor()

        cursor.execute(
            "SELECT flagColor, detectedName, barangayID FROM geospatial_logs WHERE logID = %s",
            (log_id,)
        )
        row = cursor.fetchone()

        if not row:
            cursor.close()
            return False, "Flag not found"

        if row["flagColor"] not in ("Red", "Yellow", "Orange"):
            cursor.close()
            return False, f"Cannot escalate from '{row['flagColor']}' to Black"

        cursor.execute("""
            UPDATE geospatial_logs
            SET flagColor = 'Black'
            WHERE logID = %s
        """, (log_id,))

        # Propagate changes: if marked Black, set registry status to Revoked
        cursor.execute("""
            UPDATE official_registry
            SET applicationStatus = 'Revoked'
            WHERE LOWER(businessName) = LOWER(%s) AND barangayID = %s
        """, (row["detectedName"], row["barangayID"]))

        mysql.connection.commit()
        cursor.close()

        try:
            from api.notifications import hub
            hub.publish_to_admins({
                "type": "flag_updated",
                "logID": log_id,
                "color": "Black"
            })
        except Exception:
            pass

        return True, None

    except Exception as e:
        return False, str(e)


# ── Delete Flag ───────────────────────────────────────────────────────────────

def delete_flag(log_id):
    """
    Delete a single flag.
    - If log_id < 0: virtual registry entry (businessID = -log_id). Removes official_registry entry.
    - If log_id > 0: isolates deletion strictly to log_id.
      Does NOT perform broad delete across all same-named businesses or logs.
      Before deleting geospatial_logs, repoints any inspection_reports / lifecycle events
      to a primary surviving duplicate log if one exists, otherwise removes them.
    """
    try:
        cursor = mysql.connection.cursor()

        if log_id < 0:
            biz_id = -log_id
            cursor.execute(
                "DELETE FROM official_registry WHERE businessID = %s", (biz_id,))
            mysql.connection.commit()
            cursor.close()

            try:
                from api.notifications import hub
                hub.publish_to_admins({
                    "type": "flag_deleted",
                    "logID": log_id
                })
            except Exception:
                pass
            return True, None

        # Find the specific flag
        cursor.execute(
            """SELECT logID, businessID, reportID, detectedName, barangayID, placeID, latitude, longitude
               FROM geospatial_logs WHERE logID = %s""",
            (log_id,)
        )
        flag = cursor.fetchone()

        if not flag:
            cursor.close()
            return False, "Flag not found"

        # Check if there is an explicit surviving duplicate log for this establishment
        surviving_log = None
        if flag.get("businessID"):
            cursor.execute(
                """SELECT logID, reportID FROM geospatial_logs
                   WHERE businessID = %s AND logID <> %s
                   ORDER BY (reportID IS NOT NULL) DESC, logID ASC LIMIT 1""",
                (flag["businessID"], log_id)
            )
            surviving_log = cursor.fetchone()

        if not surviving_log and flag.get("placeID"):
            cursor.execute(
                """SELECT logID, reportID FROM geospatial_logs
                   WHERE placeID = %s AND logID <> %s
                   ORDER BY (reportID IS NOT NULL) DESC, logID ASC LIMIT 1""",
                (flag["placeID"], log_id)
            )
            surviving_log = cursor.fetchone()

        # Check if this flag has inspection reports
        cursor.execute(
            "SELECT reportID FROM inspection_reports WHERE targetID = %s", (log_id,))
        reports = cursor.fetchall()

        if reports:
            if surviving_log:
                surv_id = surviving_log["logID"]
                cursor.execute(
                    "UPDATE inspection_reports SET targetID = %s WHERE targetID = %s",
                    (surv_id, log_id)
                )
                try:
                    cursor.execute(
                        "UPDATE inspection_lifecycle_events SET targetLogID = %s WHERE targetLogID = %s",
                        (surv_id, log_id)
                    )
                except Exception:
                    pass
                if flag.get("reportID") and not surviving_log.get("reportID"):
                    cursor.execute(
                        "UPDATE geospatial_logs SET reportID = %s WHERE logID = %s AND reportID IS NULL",
                        (flag["reportID"], surv_id)
                    )
            else:
                cursor.execute(
                    "DELETE FROM inspection_reports WHERE targetID = %s", (log_id,))

        # Strictly delete ONLY this logID
        cursor.execute(
            "DELETE FROM geospatial_logs WHERE logID = %s", (log_id,))

        mysql.connection.commit()
        cursor.close()

        try:
            from api.notifications import hub
            hub.publish_to_admins({
                "type": "flag_deleted",
                "logID": log_id
            })
        except Exception:
            pass

        return True, None

    except Exception as e:
        return False, str(e)


# ── DBSCAN parameters (recalibrate during testing if over/under-clustering) ───
#
# DBSCAN_EPS_RAD   — neighbourhood search radius expressed in radians.
#                    20 m is chosen to match the ~8–15 m commercial lot
#                    frontage typical of a rural Filipino municipality;
#                    two adjacent flagged venues will therefore be pulled
#                    into the same cluster only if they are genuinely
#                    co-located, not merely on the same street block.
#
# DBSCAN_MIN_SAMPLES — minimum flags required to form a dense cluster.
#                    Set to 3 so that a pair of adjacent detections does
#                    NOT qualify as a systemic hotspot; at least three
#                    co-located Red Flags must exist. Isolated detections
#                    (label == -1) are treated as statistical anomalies
#                    and are discarded before the result is returned.
#
# To recalibrate: adjust DBSCAN_EPS_M (converted automatically) and/or
# DBSCAN_MIN_SAMPLES, then re-run and inspect cluster counts vs map.
EARTH_RADIUS_M = 6_371_000
DBSCAN_EPS_M = 20                            # metres  ← change this to retune
DBSCAN_EPS_RAD = DBSCAN_EPS_M / EARTH_RADIUS_M  # radians fed to sklearn
# MinPts  ← change this to retune
DBSCAN_MIN_SAMPLES = 3


def get_red_flag_clusters():
    """
    Barangay Risk Heatmap — geographic hotspot detection for Red Flags.

    Implements the second analytic level described in the system design:
    DBSCAN is used to collate neighbouring Red Flags into dense clusters
    while discarding single detections as statistical anomalies (noise).

    Algorithm
    ---------
    1. Pull every Red Flag coordinate from geospatial_logs.
    2. Run DBSCAN (haversine metric, eps = DBSCAN_EPS_M metres,
       min_samples = DBSCAN_MIN_SAMPLES) to identify spatially dense
       groups without requiring a pre-specified cluster count.
    3. Discard noise points (label == -1) — isolated flags are treated
       as anomalies, not hotspots.
    4. For each true cluster compute:
         • centroid  – mean lat/lng of member flags
         • size      – number of Red Flags in the cluster
         • logIDs    – contributing log IDs (for drill-down)
         • radius_m  – max geodesic distance from centroid to any member
           (used by the front end to size the circle overlay)
    5. Return clusters sorted largest-first.

    Returns
    -------
    (list[dict], None)   on success
    (None, str)          on error
    """
    try:
        cursor = mysql.connection.cursor()
        cursor.execute("""
            SELECT logID, latitude, longitude
            FROM   geospatial_logs
            WHERE  flagColor = 'Red'
              AND  latitude  IS NOT NULL
              AND  longitude IS NOT NULL
        """)
        rows = cursor.fetchall()
        cursor.close()

        if not rows:
            return [], None

        # ── Build coordinate matrix in radians ──────────────────────────────
        log_ids = [r["logID"] for r in rows]
        lats = [float(r["latitude"]) for r in rows]
        lngs = [float(r["longitude"]) for r in rows]

        coords_rad = np.radians(np.column_stack([lats, lngs]))   # (N, 2)

        # ── DBSCAN ──────────────────────────────────────────────────────────
        db = DBSCAN(
            eps=DBSCAN_EPS_RAD,
            min_samples=DBSCAN_MIN_SAMPLES,
            algorithm="ball_tree",
            metric="haversine",
        ).fit(coords_rad)

        labels = db.labels_   # -1 = noise (isolated flag)

        # ── Aggregate per cluster ────────────────────────────────────────────
        from collections import defaultdict
        groups = defaultdict(list)
        for idx, label in enumerate(labels):
            groups[label].append(idx)

        clusters = []
        for label, indices in groups.items():

            # label == -1 → DBSCAN noise: isolated flags that do not share a
            # 20-m neighbourhood with ≥ 2 others.  Per the system design these
            # are statistical anomalies and are intentionally discarded here.
            if label == -1:
                continue

            member_lats = [lats[i] for i in indices]
            member_lngs = [lngs[i] for i in indices]
            member_ids = [log_ids[i] for i in indices]

            centroid_lat = sum(member_lats) / len(member_lats)
            centroid_lng = sum(member_lngs) / len(member_lngs)

            # Radius = max geodesic distance from centroid to any member flag.
            # A minimum of DBSCAN_EPS_M is enforced so that very tight clusters
            # (e.g. two flags at nearly identical coordinates) are still visible
            # as a circle on the map at town-level zoom.
            radius_m = 0.0
            for mlat, mlng in zip(member_lats, member_lngs):
                from geopy.distance import geodesic
                d = geodesic((centroid_lat, centroid_lng), (mlat, mlng)).meters
                if d > radius_m:
                    radius_m = d

            radius_m = max(radius_m, DBSCAN_EPS_M)

            clusters.append({
                "clusterID":   int(label),
                "centroidLat": round(centroid_lat, 7),
                "centroidLng": round(centroid_lng, 7),
                "size":        len(indices),
                "radius_m":    round(radius_m, 1),
                "logIDs":      member_ids,
            })

        # Largest hotspots first
        clusters.sort(key=lambda c: c["size"], reverse=True)
        return clusters, None

    except Exception as e:
        return None, str(e)
