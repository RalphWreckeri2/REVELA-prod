import numpy as np
from sklearn.cluster import DBSCAN
import os
import time
import requests as http
import json
from geopy.distance import geodesic
from app import mysql
from shapely.geometry import shape, Point
from api.utils.cancellation import is_cancelled, set_cancel

GOOGLE_MAPS_API_KEY = os.getenv("GOOGLE_MAPS_API_KEY")

# ── GeoJSON Loading ───────────────────────────────────────────────────────────
MATAASNAKAHOY_GEOJSON_PATH = os.path.join(os.path.dirname(__file__), '..', 'utils', 'mataasnakahoy.json')
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


def _within_municipality(lat: float, lng: float) -> bool:
    """Polygon test + hard coordinate caps to exclude Lipa border overlap."""
    if lng > 121.120:    # east cap — cuts off Lipa airbase corridor
        return False
    if lat < 13.951:     # south cap — Mataasnakahoy's southern boundary
        return False
    return _MUNICIPALITY_BOUNDARY.contains(Point(lng, lat))


def _match_registry_to_google(place_id, business_id, detected_name):
    """
    Updates the geospatial log for an existing registry business 
    with its official Google Maps Place ID.
    """
    cursor = mysql.connection.cursor()
    # Find the 'Green' flag record for this business and update it
    cursor.execute("""
        UPDATE geospatial_logs 
        SET placeID = %s 
        WHERE detectedName = %s 
        AND flagColor = 'Green'
    """, (place_id, detected_name))
    mysql.connection.commit()
    cursor.close()


# ── Google Places fetch ───────────────────────────────────────────────────────

def _fetch_places_for_point(lat, lng, radius_m, places_dict):
    api_key = (
        os.getenv("GOOGLE_MAPS_API_KEY")
        or os.getenv("GOOGLE_PLACES_API_KEY")
        or os.getenv("VITE_GOOGLE_MAPS_API_KEY")
    )
    if not api_key:
        print("[Run Detection] Error: GOOGLE_MAPS_API_KEY environment variable is not configured.")
        return 0

    url = "https://maps.googleapis.com/maps/api/place/nearbysearch/json"
    params = {
        "location": f"{lat},{lng}",
        "radius":   radius_m,
        "type":     "establishment",
        "key":      api_key,
    }

    outside_count = 0

    headers = {
        "User-Agent": "REVELA-Backend/1.0",
        "Referer": os.getenv("FRONTEND_URL", "https://revela-web.up.railway.app/"),
        "Origin": os.getenv("FRONTEND_URL", "https://revela-web.up.railway.app/").rstrip("/"),
    }

    while True:
        try:
            resp = http.get(url, params=params, headers=headers, timeout=10)
            data = resp.json()
        except Exception as he:
            print(f"[Run Detection] HTTP error querying point ({lat}, {lng}): {he}")
            break

        status = data.get("status")
        if status not in ("OK", "ZERO_RESULTS"):
            print(f"[Run Detection] Places API status: {status}, message: {data.get('error_message')}")
            break

        for p in data.get("results", []):
            place_id = p.get("place_id")
            # Deduplicate overlapping circles
            if not place_id or place_id in places_dict:
                continue

            loc = p.get("geometry", {}).get("location", {})
            p_lat = loc.get("lat")
            p_lng = loc.get("lng")

            if p_lat is None or p_lng is None:
                continue

            if _within_municipality(p_lat, p_lng):
                places_dict[place_id] = p
            else:
                outside_count += 1

        next_token = data.get("next_page_token")
        if not next_token:
            break

        time.sleep(2)
        params = {"pagetoken": next_token, "key": api_key}

    return outside_count


def _fetch_all_places(progress_cb=None):
    """
    Uses a grid-based search to bypass Google Places API's hard limit of 60 results
    per query. Returns a flat list of place dicts — filtered to municipality bounds.
    """
    places_dict = {}
    total_outside = 0

    # Bounding Box roughly covering Mataasnakahoy derived from GeoJSON
    min_lat, max_lat = 13.9490, 14.0115
    min_lng, max_lng = 121.0129, 121.1251

    # 2km step (approx 0.018 degrees). Search radius of 2000m ensures overlapping circles.
    step = 0.018
    radius_m = 2000

    # 1. Precalculate grid points to allow progress tracking
    grid_points = []
    lat = min_lat
    while lat <= max_lat:
        lng = min_lng
        while lng <= max_lng:
            # Buffer the municipality polygon by ~2km to save API calls on far corners
            if _MUNICIPALITY_BOUNDARY.buffer(0.02).contains(Point(lng, lat)):
                grid_points.append((lat, lng))
            lng += step
        lat += step

    total_steps = len(grid_points)

    # 2. Iterate and query each point
    for idx, (lat, lng) in enumerate(grid_points):
        if is_cancelled("run_detection"):
            break

        if progress_cb:
            progress_cb(idx, total_steps, lat, lng)
        outside = _fetch_places_for_point(lat, lng, radius_m, places_dict)
        total_outside += outside

    return list(places_dict.values()), total_outside


# ── Registry loader ───────────────────────────────────────────────────────────

def _load_registry():
    """Load all official registry entries that have coordinates or linked geospatial logs."""
    cursor = mysql.connection.cursor()
    cursor.execute("""
        SELECT r.businessID, r.barangayID, r.businessName,
               COALESCE(r.latitude, g.latitude) AS latitude,
               COALESCE(r.longitude, g.longitude) AS longitude
        FROM official_registry r
        LEFT JOIN (
            SELECT detectedName, barangayID, latitude, longitude
            FROM geospatial_logs
            WHERE flagColor = 'Green'
        ) g ON LOWER(r.businessName) = LOWER(g.detectedName) AND r.barangayID = g.barangayID
        WHERE r.latitude IS NOT NULL OR g.latitude IS NOT NULL
    """)
    rows = cursor.fetchall()
    cursor.close()
    return rows


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

def _get_barangay_id_by_coords(lat, lng):
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
            
    cursor = mysql.connection.cursor()
    
    if matched_geojson_name:
        cursor.execute("SELECT barangayID, barangayName FROM barangays")
        barangs = cursor.fetchall()
        
        mapping = {
            "District I (Pob.)": "Barangay I",
            "District II (Pob.)": "Barangay II",
            "District III (Pob.)": "Barangay III",
            "District IV (Pob.)": "Barangay IV",
            "Barangay II-A (Pob.)": "Barangay II-A",
            "Lumang Lipa": "Barangay Lumanglipa"
        }
        
        for b in barangs:
            b_name = b['barangayName']
            target_name = mapping.get(matched_geojson_name)
            
            if target_name and target_name == b_name:
                cursor.close()
                return b["barangayID"]
                
            if not target_name and matched_geojson_name.lower() in b_name.lower():
                cursor.close()
                return b["barangayID"]

    # Fallback to proximity
    cursor.execute("""
        SELECT barangayID, latitude, longitude
        FROM official_registry
        WHERE latitude IS NOT NULL AND longitude IS NOT NULL
    """)
    rows = cursor.fetchall()
    cursor.close()

    if not rows:
        return 1

    nearest_id = 1
    nearest_dist = float("inf")
    for row in rows:
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

def _insert_red_flag(place_id, place_name, lat, lng, barangay_id, address=None):
    cursor = mysql.connection.cursor()
    cursor.execute("""
        INSERT INTO geospatial_logs
            (barangayID, reportID, detectedName, latitude, longitude,
             flagColor, placeID, nearestLandmark)
        VALUES (%s, NULL, %s, %s, %s, 'Red', %s, %s)
    """, (barangay_id, place_name, lat, lng, place_id, address))
    flag_id = cursor.lastrowid
    mysql.connection.commit()
    cursor.close()
    return flag_id


# ── Main detection runner ─────────────────────────────────────────────────────

def run_detection():
    """
    Full detection cycle:
    1. Fetch Places API POIs — filter to municipality boundary
    2. Cross-reference against OFFICIAL_REGISTRY (20m threshold)
    3. Insert Red Flags for unmatched POIs
    Returns { new_flags, total_checked, outside_boundary }
    """
    set_cancel("run_detection", False)
    try:
        from api.registry.service import check_and_expire_old_permits
        check_and_expire_old_permits()
        from api.notifications import hub

        def progress_callback(idx, total_steps, lat, lng):
            percentage = int((idx / total_steps) * 80)
            hub.publish_to_admins({
                "type": "detection_progress",
                "stage": "scanning",
                "current_step": idx + 1,
                "total_steps": total_steps,
                "percentage": percentage,
                "status": f"Scanning coordinates ({lat:.4f}, {lng:.4f}) — step {idx + 1} of {total_steps}..."
            })

        places, outside_count = _fetch_all_places(progress_callback)

        if is_cancelled("run_detection"):
            hub.publish_to_admins({
                "type": "detection_progress",
                "stage": "completed",
                "percentage": 100,
                "status": "Detection cancelled by user. No flags were recorded."
            })
            return None, "Detection cancelled by user."

        hub.publish_to_admins({
            "type": "detection_progress",
            "stage": "matching",
            "percentage": 82,
            "status": "Loading official business registry database..."
        })
        registry = _load_registry()

        total_checked = len(places)
        new_flags = 0

        hub.publish_to_admins({
            "type": "detection_progress",
            "stage": "matching",
            "percentage": 85,
            "status": f"Cross-referencing {total_checked} detected POIs against official registry..."
        })

        inserted_flag_ids = []

        for idx, place in enumerate(places):
            if is_cancelled("run_detection"):
                # Rollback all inserted flags during this session
                if inserted_flag_ids:
                    cursor = mysql.connection.cursor()
                    format_strings = ','.join(['%s'] * len(inserted_flag_ids))
                    cursor.execute(f"DELETE FROM geospatial_logs WHERE logID IN ({format_strings})", tuple(inserted_flag_ids))
                    mysql.connection.commit()
                    cursor.close()
                hub.publish_to_admins({
                    "type": "detection_progress",
                    "stage": "completed",
                    "percentage": 100,
                    "status": "Detection cancelled by user. Discovered flags rolled back."
                })
                return None, "Detection cancelled by user."

            place_id = place.get("place_id")
            place_name = place.get("name", "Unknown")
            geometry = place.get("geometry") or {}
            loc = geometry.get("location") or {}
            lat = loc.get("lat")
            lng = loc.get("lng")
            address = place.get("vicinity")   # street address from Places API
            plus_code = place.get("plus_code") or {}
            compound_code = plus_code.get("compound_code", "")

            if not lat or not lng or not place_id:
                continue

            # Ensure coordinates are within municipality polygon
            if not _within_municipality(lat, lng):
                continue

            # Only reject if the specific street address explicitly belongs to an adjacent town
            addr_lower = (address or "").lower()
            if any(t in addr_lower for t in ["lipa city", "cuenca,", "balete,", "san jose,"]):
                continue

            if _already_flagged(place_id):
                continue

            # Publish matching progress updates periodically
            if idx % 5 == 0 or idx == total_checked - 1:
                percentage = 85 + int(((idx + 1) / (total_checked or 1)) * 12)
                hub.publish_to_admins({
                    "type": "detection_progress",
                    "stage": "matching",
                    "percentage": percentage,
                    "status": f"Analyzing geospatial location for “{place_name}” ({idx + 1}/{total_checked})..."
                })

            nearest, dist = _find_nearest(lat, lng, registry)

            if nearest is None or dist > THRESHOLD_M:
                barangay_id = _get_barangay_id_by_coords(lat, lng)
                flag_id = _insert_red_flag(place_id, place_name, lat,
                                 lng, barangay_id, address)
                inserted_flag_ids.append(flag_id)
                new_flags += 1
            else:
                _match_registry_to_google(
                    place_id, nearest['businessID'], nearest['businessName'])

        hub.publish_to_admins({
            "type": "detection_progress",
            "stage": "completed",
            "percentage": 100,
            "status": f"Scan complete! Discovered {new_flags} new unregistered business{'' if new_flags == 1 else 'es'}."
        })

        return {
            "new_flags":        new_flags,
            "total_checked":    total_checked,
            "outside_boundary": outside_count,
        }, None

    except Exception as e:
        return None, str(e)


# ── Get all flags ─────────────────────────────────────────────────────────────

def get_flags(color=None, barangay_id=None, page=1, per_page=50, reported_by_user_id=None):
    """Return paginated geospatial_logs entries with optional filters."""
    try:
        from api.registry.service import check_and_expire_old_permits
        check_and_expire_old_permits()
        cursor = mysql.connection.cursor()

        conditions = []
        params = []

        if color:
            conditions.append("g.flagColor = %s")
            params.append(color)

        if barangay_id:
            conditions.append("g.barangayID = %s")
            params.append(barangay_id)

        if reported_by_user_id:
            conditions.append("g.reportedByUserID = %s")
            params.append(reported_by_user_id)

        where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
        offset = (page - 1) * per_page

        cursor.execute(
            f"SELECT COUNT(*) AS total FROM geospatial_logs g {where}",
            params
        )
        total = cursor.fetchone()["total"]

        cursor.execute(
            f"""
            SELECT
                g.logID,
                g.detectedName,
                COALESCE(g.latitude, r.latitude) AS latitude,
                COALESCE(g.longitude, r.longitude) AS longitude,
                g.flagColor,
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
                ) AS verificationStatus
            FROM geospatial_logs g
            LEFT JOIN barangays b ON g.barangayID = b.barangayID
            LEFT JOIN official_registry r
                ON LOWER(r.businessName) = LOWER(g.detectedName)
                AND r.barangayID = g.barangayID
            {where}
            ORDER BY g.detectedDate DESC
            LIMIT %s OFFSET %s
            """,
            params + [per_page, offset]
        )
        rows = cursor.fetchall()
        cursor.close()

        for row in rows:
            if row.get("detectedDate"):
                row["detectedDate"] = str(row["detectedDate"])

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
    """Manually insert a Yellow or Orange Flag."""
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
    """Update a flag's color manually (e.g. to Purple, Orange, Yellow, Red, Black, Green)."""
    try:
        cursor = mysql.connection.cursor()
        cursor.execute("SELECT flagColor, detectedName, barangayID FROM geospatial_logs WHERE logID = %s", (log_id,))
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


# ── Escalate to Black Flag ────────────────────────────────────────────────────

def escalate_to_black(log_id):
    """Update flagColor to Black. Only valid if current status is Red or Yellow."""
    try:
        cursor = mysql.connection.cursor()

        cursor.execute(
            "SELECT flagColor, detectedName, barangayID FROM geospatial_logs WHERE logID = %s",
            (log_id,)
        )
        row = cursor.fetchone()

        if not row:
            cursor.close()
            return False, "Flag not found"

        if row["flagColor"] not in ("Red", "Yellow"):
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
    """Delete a flag. If it has a corresponding registry entry, delete that too."""
    try:
        cursor = mysql.connection.cursor()

        # Find the flag
        cursor.execute(
            "SELECT detectedName, barangayID FROM geospatial_logs WHERE logID = %s",
            (log_id,)
        )
        flag = cursor.fetchone()

        if not flag:
            cursor.close()
            return False, "Flag not found"

        # Check if there is an associated registry entry
        cursor.execute("""
            SELECT businessID FROM official_registry
            WHERE LOWER(businessName) = LOWER(%s) AND barangayID = %s
        """, (flag["detectedName"], flag["barangayID"]))
        business = cursor.fetchone()

        if business:
            # Delete all logs and inspection reports for this business
            cursor.execute("SELECT logID FROM geospatial_logs WHERE LOWER(detectedName) = LOWER(%s) AND barangayID = %s",
                           (flag["detectedName"], flag["barangayID"]))
            logs = cursor.fetchall()
            for log in logs:
                cursor.execute(
                    "DELETE FROM inspection_reports WHERE targetID = %s", (log["logID"],))
                cursor.execute(
                    "DELETE FROM geospatial_logs WHERE logID = %s", (log["logID"],))
            cursor.execute(
                "DELETE FROM official_registry WHERE businessID = %s", (business["businessID"],))
        else:
            # Just delete this specific flag and its inspections
            cursor.execute(
                "DELETE FROM inspection_reports WHERE targetID = %s", (log_id,))
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
