from __future__ import annotations

import argparse
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
API_ROOT = REPO_ROOT / "apps" / "api"
for path in (REPO_ROOT, API_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from app.core.config import SOURCE_DOCUMENT_NAMES, SOURCE_VIDEO_NAMES, Settings
from app.core.corpus_governance import CorpusRegistry, load_license_register, review_problems

DEFAULT_REGISTER = REPO_ROOT / "corpus" / "license-register.csv"


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate the reviewed public corpus manifest.")
    parser.add_argument(
        "--check-public-assets",
        action="store_true",
        help="Require every approved asset to have a reviewed license-register row (AC-1-5; task 1.8).",
    )
    parser.add_argument("--register", type=Path, default=DEFAULT_REGISTER, help="the license register CSV")
    args = parser.parse_args()
    settings = Settings(environment="production", enforce_corpus_governance=True)
    registry = CorpusRegistry(settings)
    if args.check_public_assets:
        # The served catalogue is the manifest (Decision P1-D-07, D-31): an empty one is valid and serves nothing.
        problems = review_problems(registry, load_license_register(args.register), [*SOURCE_DOCUMENT_NAMES, *SOURCE_VIDEO_NAMES])
        if problems:
            sys.exit("Public corpus is not ready to serve:\n" + "\n".join(f"- {problem}" for problem in problems))
        approved = sorted({name for item in registry.approved_items for name in item.asset_filenames})
        withheld = len({*SOURCE_DOCUMENT_NAMES, *SOURCE_VIDEO_NAMES} - set(approved))
        print(f"Approved for public service: {len(approved)} asset(s); withheld: {withheld} of the application's source assets")
    print(f"Validated corpus manifest at {registry.manifest_path}")


if __name__ == "__main__":
    main()
