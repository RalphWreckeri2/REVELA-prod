"""Evaluate business auto-matches against reviewed, human-labeled cases."""

from datetime import date

from api.flags.service import _match_poi_to_registry


def evaluate_labeled_cases(cases):
    seen_case_ids = set()
    true_positives = 0
    false_positives = 0
    false_negatives = 0
    true_negatives = 0
    review_count = 0
    false_matches = []
    missed_matches = []

    for case in cases:
        if not isinstance(case, dict):
            raise ValueError("Each labeled case must be a JSON object.")
        case_id = str(case.get("case_id") or "").strip()
        expected_id = case.get("expected_business_id")
        reviewer = str(case.get("reviewed_by") or "").strip()
        reviewed_at = str(case.get("reviewed_at") or "").strip()
        label_source = str(case.get("label_source") or "").strip()
        poi = case.get("poi")
        candidates = case.get("registry_candidates")

        if not case_id or case_id in seen_case_ids:
            raise ValueError("Each case must have a unique, non-empty case_id.")
        seen_case_ids.add(case_id)
        if not reviewer or not reviewed_at or not label_source:
            raise ValueError(
                f"Case {case_id} must include reviewed_by, reviewed_at, and label_source."
            )
        if "expected_business_id" not in case:
            raise ValueError(
                f"Case {case_id} must explicitly label expected_business_id; use null for a known non-match."
            )
        if expected_id is not None and not str(expected_id).strip():
            raise ValueError(f"Case {case_id} has an empty expected_business_id.")
        try:
            reviewed_date = date.fromisoformat(reviewed_at)
        except ValueError as error:
            raise ValueError(
                f"Case {case_id} reviewed_at must use YYYY-MM-DD format."
            ) from error
        if reviewed_date.isoformat() != reviewed_at:
            raise ValueError(
                f"Case {case_id} reviewed_at must use YYYY-MM-DD format."
            )
        if not isinstance(poi, dict) or not str(poi.get("name") or "").strip():
            raise ValueError(f"Case {case_id} must include a named poi object.")
        if not isinstance(candidates, list):
            raise ValueError(f"Case {case_id} must include registry_candidates as a list.")
        for candidate in candidates:
            if not isinstance(candidate, dict) or not candidate.get("businessID") or not candidate.get("businessName"):
                raise ValueError(
                    f"Case {case_id} has a candidate without businessID or businessName."
                )

        matched, distance, score, status = _match_poi_to_registry(
            poi["name"],
            poi.get("latitude"),
            poi.get("longitude"),
            candidates,
            poi_barangay_id=poi.get("barangay_id"),
            poi_types=tuple(poi.get("types") or ()),
            poi_address=poi.get("address") or "",
        )
        predicted_id = (
            str(matched["businessID"])
            if matched is not None and status == "auto"
            else None
        )
        expected_id = str(expected_id) if expected_id is not None else None
        if matched is not None and status == "review":
            review_count += 1

        if predicted_id is not None and predicted_id == expected_id:
            true_positives += 1
        elif predicted_id is not None:
            false_positives += 1
            false_matches.append({
                "case_id": case_id,
                "expected_business_id": expected_id,
                "predicted_business_id": predicted_id,
            })
            if expected_id is not None:
                false_negatives += 1
                missed_matches.append({
                    "case_id": case_id,
                    "expected_business_id": expected_id,
                    "match_status": status,
                })
        elif expected_id is not None:
            false_negatives += 1
            missed_matches.append({
                "case_id": case_id,
                "expected_business_id": expected_id,
                "match_status": status,
            })
        else:
            true_negatives += 1

    precision_denominator = true_positives + false_positives
    recall_denominator = true_positives + false_negatives
    precision = (
        true_positives / precision_denominator
        if precision_denominator else None
    )
    recall = (
        true_positives / recall_denominator
        if recall_denominator else None
    )
    f1_score = (
        2 * precision * recall / (precision + recall)
        if precision is not None and recall is not None and precision + recall
        else 0.0 if precision is not None and recall is not None
        else None
    )

    return {
        "cases": len(seen_case_ids),
        "auto_match_true_positives": true_positives,
        "auto_match_false_positives": false_positives,
        "auto_match_false_negatives": false_negatives,
        "known_nonmatch_true_negatives": true_negatives,
        "review_cases": review_count,
        "precision": precision,
        "recall": recall,
        "f1_score": f1_score,
        "false_matches": false_matches,
        "missed_matches": missed_matches,
    }
