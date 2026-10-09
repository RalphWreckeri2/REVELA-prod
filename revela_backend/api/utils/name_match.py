import difflib
import unicodedata
import re
from functools import lru_cache

LEGAL = {
    'inc', 'corp', 'corporation', 'co', 'company', 'ltd', 'opc', 'enterprise',
    'enterprises', 'trading', 'the', 'and', 'of', 'commercial', 'philippines',
    'ph', 'branch', 'outlet', 'services', 'service', 'center', 'centre', 'hub',
    'de', 'del', 'la', 'las', 'los', 'shop',
}

# Order matters: specific business sectors first, generic retail (store/sari-sari) last.
CATEGORY_PATTERNS = [
    (r'\b(pharmacy|pharmaceuticals?|drug ?stores?|drugs?|medicines?|botika|farmacia)\b', 'pharmacy'),
    (r'\b(apartments?|apartelle|boarding ?house|dormitory|dorm|lodging|pension|inn|resort|hotel|motel)\b', 'lodging'),
    (r'\b(bakery|bake ?shop|panaderi[ay]|pastry|tinapayan)\b', 'bakery'),
    (r'\b(eatery|carinderi[ay]|karinderya|restaurant|grill|canteen|food ?house|lomi(han)?|gotohan|cafe|coffee(?: ?shop| ?roast(?:er|ers|ing))?|roaster(y|ies)?|fast ?food|bulalohan|resto|diner|kitchen|lechon)\b', 'food'),
    (r'\b(meat ?shop|butchery|butcher|meat ?market|meat)\b', 'meat'),
    (r'\b(personal care|hair ?salon|salon|barber ?shop|barbershop|beauty|spa|parlor|hair ?care)\b', 'personal_care'),
    (r'\b(hardware|construction supply|paint center)\b', 'hardware'),
    (r'\b(auto ?supply|motor ?parts|vulcanizing|tire ?repair|talyer|car ?wash|motorcycle (parts|supplies)|machine shop|motors?|auto ?care|car ?care|car ?repair|auto ?repair)\b', 'auto'),
    (r'\b(water refilling(?: station)?|water station|drinking water(?: station)?|purified water)\b', 'water'),
    (r'\b(clinic|dental|hospital|medical|laborator(y|ies)|optical|diagnostic|veterinar(y|ian)|vet ?clinic)\b', 'health'),
    (r'\b(laundry|laundromat|dry ?clean(ers|ing)?|lavanderia)\b', 'laundry'),
    (r'\b(funeral|mortuary|memorial( chapel| park)?|chapel|cremator(y|ium)|cemetery)\b', 'funeral'),
    (r'\b(tailor(ing)?|dress ?shop|sewing|apparel)\b', 'apparel'),
    (r'\b(internet ?cafe|cyber ?cafe|computer ?shop|pisonet)\b', 'internet_cafe'),
    (r'\b(rice ?dealer|rice ?mill|rice ?trading|poultry ?suppl(y|ies)|farm ?suppl(y|ies)|agri ?suppl(y|ies)|agricultural( ?suppl(y|ies))?|feeds?)\b', 'agriculture'),
    (r'\b(courier|logistics|delivery|cargo|forwarding)\b', 'logistics'),
    (r'\b(pawnshop)\b', 'pawnshop'),
    (r'\b(welding|furniture|iron ?works)\b', 'craft'),
    (r'\b(event ?venue|events? ?place|banquet ?hall|wedding ?venue|convention ?center|function ?hall)\b', 'events'),
    (r'\b(sari[- ]?sari|tindahan|grocery|mini ?mart|mart|supermarket|general merchandise|retail|convenience(?: ?store)?|store)\b', 'retail'),
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
    'event_venue': 'events',
    'banquet_hall': 'events',
    'wedding_venue': 'events',
    'convention_center': 'events',
    'event_planner': 'events',
}


def _ascii_fold(raw: str) -> str:
    decomposed = unicodedata.normalize('NFKD', raw or '')
    return ''.join(char for char in decomposed if not unicodedata.combining(char))


@lru_cache(maxsize=32768)
def _parse_name_cached(raw: str) -> tuple[tuple[str, ...], frozenset[str]]:
    s = _ascii_fold(raw).lower().replace('&', ' and ')
    s = re.sub(r'[\u2019\x27`]s\b', '', s)
    s = re.sub(r'[^a-z0-9 ]+', ' ', s)

    groups = set()
    for rx, group in CATEGORY_PATTERNS:
        if re.search(rx, s):
            groups.add(group)
            s = re.sub(rx, ' ', s)

    tokens = tuple(token for token in s.split() if token not in LEGAL)
    return tokens, frozenset(groups)


def parse_name(raw: str) -> tuple[list[str], set[str]]:
    """
    Normalizes a business trade name or POI name:
    1. Lowercase and replace '&' with 'and'.
    2. Strip possessive apostrophes (e.g. Silva's -> silva).
    3. Extract category classifications into a set.
    4. Remove category keywords and legal noise tokens.
    Returns: (cleaned_tokens, category_groups_set)
    """
    tokens, groups = _parse_name_cached(str(raw or ''))
    return list(tokens), set(groups)


def _overlap(ta: list[str], tb: list[str]) -> float:
    """
    Return weighted Dice overlap, requiring tokens to match one-to-one.
    Unlike containment, a single shared token cannot score as a full match
    when the other business name contains additional distinctive tokens.
    """
    if not ta or not tb:
        return 0.0
    unmatched = list(tb)
    matched_weight = 0.0

    def weight(token):
        return 1.0 + min(max(len(token) - 4, 0) * 0.05, 0.25)

    for token in ta:
        best_index = None
        best_ratio = 0.0
        for index, candidate in enumerate(unmatched):
            ratio = difflib.SequenceMatcher(None, token, candidate).ratio()
            threshold = 0.85 if min(len(token), len(candidate)) >= 5 else 1.0
            if ratio >= threshold and ratio > best_ratio:
                best_index, best_ratio = index, ratio
        if best_index is not None:
            matched_weight += min(weight(token),
                                  weight(unmatched.pop(best_index)))

    total_weight = sum(weight(token) for token in ta + tb)
    return (2.0 * matched_weight / total_weight) if total_weight else 0.0


def _shared_token_count(ta: list[str], tb: list[str]) -> int:
    unmatched = list(tb)
    count = 0
    for token in ta:
        for index, candidate in enumerate(unmatched):
            ratio = difflib.SequenceMatcher(None, token, candidate).ratio()
            threshold = 0.85 if min(len(token), len(candidate)) >= 5 else 1.0
            if ratio >= threshold:
                unmatched.pop(index)
                count += 1
                break
    return count


def address_similarity(reg_address: str, poi_address: str) -> float:
    """Compare address tokens conservatively; missing addresses provide no evidence."""
    if not reg_address or not poi_address:
        return 0.0

    def tokens(value):
        folded = _ascii_fold(str(value)).lower()
        return {
            token for token in re.findall(r'[a-z0-9]+', folded)
            if token not in {'street', 'st', 'road', 'rd', 'barangay', 'brgy', 'philippines', 'ph'}
        }

    left, right = tokens(reg_address), tokens(poi_address)
    if not left or not right:
        return 0.0
    return 2 * len(left & right) / (len(left) + len(right))


def name_match(
    reg_name: str,
    poi_name: str,
    reg_line: str = '',
    poi_types: tuple = (),
    reg_type: str = '',
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
    if reg_type:
        ga |= parse_name(reg_type)[1]

    if poi_types:
        if isinstance(poi_types, str):
            poi_types = [poi_types]
        gb |= {TYPE_GROUPS[t] for t in poi_types if t in TYPE_GROUPS}

    base = _overlap(ta, tb)
    if base == 0:
        return 0.0, 'no_shared_name'
    shared_tokens = _shared_token_count(ta, tb)

    # Category conflict or alignment logic
    if ga and gb:
        # Category alignment: boost score
        if ga & gb:
            score = min(1.0, base + 0.10)
            return round(score, 4), 'ok'

        # Category conflict:
        # If Google POI is generic retail while registry is a specific trade (e.g. Silva's Pharmacy vs Silva Store),
        # allow soft conflict cap at 0.60 so it routes to Human Review.
        # If Google POI has a specific specialty (bakery, lodging, auto, health, etc.) that conflicts with registry,
        # it is a hard conflict capped at 0.45 (No Match / Rejected).
        has_specific_poi_conflict = bool(gb - {'retail'})
        is_soft = ('retail' in gb and not has_specific_poi_conflict)
        cap = 0.60 if is_soft else 0.45
        return round(min(base, cap), 4), (
            'soft_category_conflict' if is_soft else 'category_conflict'
        )

    # When one side has a category and the other is untagged:
    if ga or gb:
        if shared_tokens < 2:
            return round(min(base * 0.90, 0.45), 4), 'weak_name'
        return round(base * 0.90, 4), 'ok'

    if shared_tokens < 2:
        return round(min(base, 0.45), 4), 'weak_name'
    return round(base, 4), 'ok'
