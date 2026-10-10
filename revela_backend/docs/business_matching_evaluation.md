# Business Matching Evaluation

REVELA does not treat test cases or synthetic examples as measured accuracy. Use a dataset reviewed by a human familiar with the official registry before reporting precision, recall, or F1.

## Labeled JSONL format

Provide one UTF-8 JSON object per line. Each case represents a Places result and the registry candidates considered for it:

```json
{
  "case_id": "unique-review-id",
  "reviewed_by": "reviewer identifier",
  "reviewed_at": "YYYY-MM-DD",
  "label_source": "how the reviewer confirmed the identity or non-match",
  "expected_business_id": "BPLO-ID-123",
  "poi": {
    "name": "Business name returned by Places",
    "latitude": 13.9667,
    "longitude": 121.1167,
    "barangay_id": 1,
    "types": ["bakery"],
    "address": "Returned address, if available"
  },
  "registry_candidates": [
    {
      "businessID": "BPLO-ID-123",
      "businessName": "Official registry name",
      "businessLine": "Bakery",
      "businessType": "Sole Proprietorship",
      "businessAddress": "Official registry address",
      "barangayID": 1,
      "latitude": 13.9667,
      "longitude": 121.1167
    }
  ]
}
```

`expected_business_id` is required. Use the confirmed ID for a real match and JSON `null` only when the reviewer has confirmed that none of the candidates is the same business. Include plausible decoy candidates so the evaluator exercises the same candidate-selection behavior as detection. Coordinates, candidate sets, labels, reviewer, review date, and evidence source should be preserved with the dataset for reproducibility.

## Run

From `revela_backend`:

```powershell
python scripts/evaluate_business_matching.py path\to\reviewed-cases.jsonl
```

The evaluator calls REVELA's current `_match_poi_to_registry` and measures **automatic (`auto`) decisions only** as predicted matches. Review-status results are reported separately and are not counted as automatic matches.

- **Precision** = correct automatic matches / all automatic matches.
- **Recall** = correct automatic matches / all confirmed matches in the labels.
- **F1** = harmonic mean of precision and recall.
- **False matches** list automatic IDs that differ from the reviewed ID, including automatic matches on confirmed non-matches.
- **Missed matches** list confirmed IDs that were not automatically selected. Review-only decisions are included as misses for auto-match recall and separately counted as review cases.

An incorrect automatically selected ID counts as both a false match and a missed match when the case has a confirmed expected ID. Undefined precision or recall is emitted as `null` when its denominator is zero. This evaluation does not tune thresholds or change matching behavior.
