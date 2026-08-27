from __future__ import annotations

import argparse
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from evaluation.qcai_eval.lqs_loader import load_lqs, validate_lqs


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate the CS595 LQS manifest.")
    parser.add_argument("--manifest", type=Path, default=Path("lqs/manifest.jsonl"))
    parser.add_argument("--allow-draft", action="store_true", help="Allow an unfilled pre-freeze manifest.")
    args = parser.parse_args()
    items = load_lqs(args.manifest)
    validate_lqs(items, enforce_proposal_range=not args.allow_draft)
    print(f"Validated {len(items)} LQS items from {args.manifest}")


if __name__ == "__main__":
    main()
