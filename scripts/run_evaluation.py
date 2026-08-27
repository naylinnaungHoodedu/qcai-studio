from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from evaluation.qcai_eval.lqs_loader import load_lqs, validate_lqs
from evaluation.qcai_eval.reporting import build_report


def main() -> None:
    parser = argparse.ArgumentParser(description="Create a reproducible CS595 evaluation run manifest.")
    parser.add_argument("--lqs", type=Path, default=Path("lqs/manifest.jsonl"))
    parser.add_argument("--output", type=Path, default=Path("evaluation/reports/draft-run.json"))
    parser.add_argument("--allow-draft", action="store_true")
    parser.add_argument("--corpus-version", required=True)
    parser.add_argument("--model-version", required=True)
    args = parser.parse_args()
    items = load_lqs(args.lqs)
    validate_lqs(items, enforce_proposal_range=not args.allow_draft)
    report = build_report(
        run_manifest={
            "lqs_path": str(args.lqs),
            "lqs_item_count": len(items),
            "corpus_version": args.corpus_version,
            "model_version": args.model_version,
            "draft": args.allow_draft,
        },
        metrics={},
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote reproducibility manifest to {args.output}")


if __name__ == "__main__":
    main()
