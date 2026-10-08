import difflib
import re

LEGAL = {
    'inc', 'corp', 'corporation', 'co', 'company', 'ltd', 'opc', 'enterprise',
    'enterprises', 'trading', 'the', 'and', 'of', 'commercial', 'philippines',
    'ph', 'branch', 'outlet', 'services', 'service', 'center', 'centre', 'hub'
}

# Order matters: specific business sectors first, generic retail (store/sari-sari) last.
CATEGORY_PATTERNS = [
    (r'\b(pharmacy|pharmaceuticals?|drug ?stores?|drugs?|medicines?|botika|farmacia)\b', 'pharmacy'),
    (r'\b(apartments?|apartelle|boarding ?house|dormitory|dorm|lodging|pension|inn|resort|hotel|motel)\b', 'lodging'),
    (r'\b(bakery|bake ?shop|panaderi[ay]|pastry|tinapayan)\b', 'bakery'),
    (r'\b(eatery|carinderi[ay]|karinderya|restaurant|grill|canteen|food ?house|lomi(han)?|gotohan|cafe|coffee ?shop|fast ?food|bulalohan|resto|diner|kitchen|lechon)\b', 'food'),
    (r'\b(meat ?shop|butchery|butcher|meat ?market|meat)\b', 'meat'),
    (r'\b(salon|barber ?shop|barbershop|beauty|spa|parlor|hair ?care)\b', 'personal_care'),
    (r'\b(hardware|construction supply|paint center)\b', 'hardware'),
    (r'\b(auto ?supply|motor ?parts|vulcanizing|tire ?repair|talyer|car ?wash|motorcycle (parts|supplies)|machine shop|motors?|auto ?care|car ?care|car ?repair|auto ?repair)\b', 'auto'),
    (r'\b(water refilling( station)?|water station|drinking water|purified water)\b', 'water'),
    (r'\b(clinic|dental|hospital|medical|laborator(y|ies)|optical|diagnostic|veterinar(y|ian)|vet ?clinic)\b', 'health'),
    (r'\b(laundry|laundromat|dry ?clean(ers|ing)?|lavanderia)\b', 'laundry'),
    (r'\b(funeral|mortuary|memorial( chapel| park)?|chapel|cremator(y|ium)|cemetery)\b', 'funeral'),
    (r'\b(tailor(ing)?|dress ?shop|sewing|apparel)\b', 'apparel'),
    (r'\b(internet ?cafe|cyber ?cafe|computer ?shop|pisonet)\b', 'internet_cafe'),
    (r'\b(rice ?dealer|rice ?mill|rice ?trading|poultry ?supply|farm ?supply|agri ?supply|agricultural|feeds?)\b', 'agriculture'),
    (r'\b(courier|logistics|delivery|cargo|forwarding)\b', 'logistics'),
    (r'\b(pawnshop)\b', 'pawnshop'),
    (r'\b(welding|furniture|iron ?works)\b', 'craft'),
    (r'\b(sari[- ]?sari|tindahan|grocery|mini ?mart|mart|supermarket|general merchandise|store)\b', 'retail'),
]

TYPE_GROUPS = {
    'pharmacy': 'pharmacy',
    'drugstore': 'pharmacy',
    'lodging': 'lodging',
    'hotel': 'lodging',
    'motel': 'lodging',
    'resort_hotel': 'lodging',
    'bakery': 'bakery',
    'restaurant': 'food',
    'cafe': 'food',
    'coffee_shop': 'food',
    'fast_food_restaurant': 'food',
    'bar': 'food',
    'meal_takeaway': 'food',
    'hair_care': 'personal_care',
    'beauty_salon': 'personal_care',
    'hair_salon': 'personal_care',
    'spa': 'personal_care',
    'hardware_store': 'hardware',
    'building_materials_store': 'hardware',
    'car_repair': 'auto',
    'auto_repair': 'auto',
    'car_dealer': 'auto',
    'car_wash': 'auto',
    'gas_station': 'auto',
    'auto_parts_store': 'auto',
    'convenience_store': 'retail',
    'grocery_store': 'retail',
    'supermarket': 'retail',
    'store': 'retail',
    'discount_store': 'retail',
    'hospital': 'health',
    'doctor': 'health',
    'dentist': 'health',
    'medical_lab': 'health',
    'physiotherapist': 'health',
    'veterinary_care': 'health',
    'optician': 'health',
    'laundry': 'laundry',
    'funeral_home': 'funeral',
    'cemetery': 'funeral',
    'tailor': 'apparel',
    'clothing_store': 'apparel',
    'internet_cafe': 'internet_cafe',
    'feed_store': 'agriculture',
    'farm_supply': 'agriculture',
    'courier': 'logistics',
    'butcher_shop': 'meat',
    'meat_market': 'meat',
    'water_station': 'water',
    'water_refilling': 'water',
    'furniture_store': 'craft',
}


def parse_name(raw: str) -> tuple[list[str], set[str]]:
    """
    Normalizes a business trade name or POI name:
    1. Lowercase and replace '&' with 'and'.
    2. Strip possessive apostrophes (e.g. Silva's -> silva).
    3. Extract category classifications into a set.
    4. Remove category keywords and legal noise tokens.
    Returns: (cleaned_tokens, category_groups_set)
    """
    s = (raw or '').lower().replace('&', ' and ')
    # Normalize curly and straight possessive apostrophes (silva's -> silva)
    s = re.sub(r'[\u2019\x27`]s\b', '', s)
    s = re.sub(r'[^a-z0-9 ]+', ' ', s)

    groups = set()
    for rx, g in CATEGORY_PATTERNS:
        if re.search(rx, s):
            groups.add(g)
            s = re.sub(rx, ' ', s)

    tokens = [t for t in s.split() if t not in LEGAL and len(t) > 0]
    return tokens, groups


def _overlap(ta: list[str], tb: list[str]) -> float:
    """
    Calculates fuzzy token overlap ratio:
    For each token in the smaller token list, checks if there is a match in
    the larger list with difflib SequenceMatcher ratio >= 0.85.
    Returns: matched_token_count / len(smaller_token_list)
    """
    if not ta or not tb:
        return 0.0
    small, big = (ta, tb) if len(ta) <= len(tb) else (tb, ta)
    hit = sum(
        1 for t in small
        if any(difflib.SequenceMatcher(None, t, u).ratio() >= 0.85 for u in big)
    )
    return hit / len(small)


def name_match(
    reg_name: str,
    poi_name: str,
    reg_line: str = '',
    poi_types: tuple = ()
) -> tuple[float, str]:
    """
    Evaluates similarity between a registered business and a candidate Google POI:
    - reg_name: Registered trade name (from official_registry.businessName).
    - poi_name: POI name from Google Places or field detection.
    - reg_line: Optional line of business (from official_registry.lineOfBusiness).
    - poi_types: Optional Google Places primaryType / types collection.

    Returns (score, match_decision):
      score: Float in [0.0, 1.0].
      match_decision: 'ok', 'category_conflict', or 'no_shared_name'.
    """
    ta, ga = parse_name(reg_name)
    tb, gb = parse_name(poi_name)

    if reg_line:
        ga |= parse_name(reg_line)[1]

    if poi_types:
        if isinstance(poi_types, str):
            poi_types = [poi_types]
        gb |= {TYPE_GROUPS[t] for t in poi_types if t in TYPE_GROUPS}

    base = _overlap(ta, tb)
    if base == 0:
        return 0.0, 'no_shared_name'

    # Lone surname / single-word penalty:
    # A single token without rich supporting name context is weak evidence
    if min(len(ta), len(tb)) == 1:
        base = min(base, 0.70)

    # Category conflict or alignment logic
    if ga and gb:
        # Category alignment: boost score
        if ga & gb:
            return min(1.0, round(base + 0.10, 4)), 'ok'

        # Category conflict:
        # If Google POI is generic retail while registry is a specific trade (e.g. Silva's Pharmacy vs Silva Store),
        # allow soft conflict cap at 0.60 so it routes to Human Review.
        # If Google POI has a specific specialty (bakery, lodging, auto, health, etc.) that conflicts with registry,
        # it is a hard conflict capped at 0.45 (No Match / Rejected).
        has_specific_poi_conflict = bool(gb - {'retail'})
        is_soft = ('retail' in gb and not has_specific_poi_conflict)
        cap = 0.60 if is_soft else 0.45
        return min(base, cap), 'category_conflict'

    # When one side has a category and the other is untagged:
    if ga or gb:
        return round(base * 0.90, 4), 'ok'

    return round(base, 4), 'ok'
