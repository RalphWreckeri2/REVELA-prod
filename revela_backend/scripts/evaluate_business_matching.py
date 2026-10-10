"""Run the business-matching evaluator against a human-reviewed JSONL dataset."""

import argparse
import json
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from api.utils.matching_evaluation import evaluate_labeled_cases


def load_cases(path):
    cases = []
    with Path(path).open("r", encoding="utf-8") as source:
        for line_number, line in enumerate(source, start=1):
            if not line.strip():
                continue
            try:
                cases.append(json.loads(line))
            except json.JSONDecodeError as error:
                raise ValueError(
                    f"Invalid JSON on line {line_number}: {error.msg}"
                ) from error
    return cases


def main():
    parser = argparse.ArgumentParser(
        description="Measure automatic business matches against human-labeled cases."
    )
    parser.add_argument("dataset", help="UTF-8 JSONL file of reviewed cases")
    args = parser.parse_args()
    try:
        cases = load_cases(args.dataset)
        if not cases:
            parser.error("The labeled dataset contains no cases.")
        print(json.dumps(evaluate_labeled_cases(cases), indent=2, ensure_ascii=False))
    except (OSError, ValueError) as error:
        parser.error(str(error))


if __name__ == "__main__":
    main()
