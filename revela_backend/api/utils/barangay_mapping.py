"""Canonical ADM4 GeoJSON names mapped to live barangay IDs."""

import json
from pathlib import Path


_ADM4_MAPPING_PATH = Path(__file__).with_name("adm4_en_barangay_ids.json")


def load_adm4_barangay_mapping():
    """Load and validate the shared ADM4_EN-to-barangayID mapping."""
    with _ADM4_MAPPING_PATH.open("r", encoding="utf-8") as mapping_file:
        mapping = json.load(mapping_file)
    if not isinstance(mapping, dict) or not mapping:
        raise ValueError(f"{_ADM4_MAPPING_PATH} must contain a non-empty object.")
    if any(not isinstance(name, str) or not name.strip() for name in mapping):
        raise ValueError(f"{_ADM4_MAPPING_PATH} contains an invalid ADM4_EN name.")
    if any(type(barangay_id) is not int or barangay_id <= 0 for barangay_id in mapping.values()):
        raise ValueError(f"{_ADM4_MAPPING_PATH} contains an invalid barangay ID.")
    if len(set(mapping.values())) != len(mapping):
        raise ValueError(f"{_ADM4_MAPPING_PATH} maps multiple features to one barangay ID.")
    return mapping


def map_adm4_barangay_ids(feature_names, barangay_rows):
    """Resolve GeoJSON feature names to IDs and validate them against live rows."""
    mapping = load_adm4_barangay_mapping()
    names = list(feature_names)
    duplicates = sorted({name for name in names if names.count(name) > 1})
    if duplicates:
        raise ValueError("Duplicate ADM4_EN features: " + ", ".join(duplicates))

    missing_mappings = sorted(set(names) - mapping.keys())
    if missing_mappings:
        raise ValueError(
            "No barangay ID mapping for ADM4_EN feature(s): "
            + ", ".join(missing_mappings)
        )

    names_by_id = {}
    for row in barangay_rows:
        barangay_id = int(row["barangayID"])
        if barangay_id in names_by_id:
            raise ValueError(f"Duplicate live barangayID {barangay_id}.")
        names_by_id[barangay_id] = str(row["barangayName"])

    ids_by_geojson_name = {name: mapping[name] for name in names}
    missing_ids = sorted(set(ids_by_geojson_name.values()) - names_by_id.keys())
    if missing_ids:
        raise ValueError(
            "ADM4_EN mapping references barangayID(s) missing from the live table: "
            + ", ".join(str(barangay_id) for barangay_id in missing_ids)
        )
    return ids_by_geojson_name, names_by_id
