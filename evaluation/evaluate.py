"""Command-line entry point for the offline privacy evaluator."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from .privacy_metrics import EvaluationInputError, evaluate_privacy, load_json


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Evaluate box-level person-redaction coverage from annotated JSON."
    )
    parser.add_argument("--ground-truth", required=True, type=Path)
    parser.add_argument("--predictions", required=True, type=Path)
    parser.add_argument("--iou-threshold", type=float, default=0.5)
    parser.add_argument(
        "--output",
        type=Path,
        help="Write JSON here instead of stdout. Existing files are replaced.",
    )
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    try:
        report = evaluate_privacy(
            load_json(args.ground_truth),
            load_json(args.predictions),
            iou_threshold=args.iou_threshold,
        )
    except (EvaluationInputError, OSError, json.JSONDecodeError) as exc:
        parser.error(str(exc))
    rendered = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.write_text(rendered, encoding="utf-8")
    else:
        print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
