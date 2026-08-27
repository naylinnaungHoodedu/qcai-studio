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
from app.core.corpus_governance import CorpusRegistry


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate the reviewed public corpus manifest.")
    parser.add_argument("--check-public-assets", action="store_true", help="Require every configured source asset to be public-approved.")
    args = parser.parse_args()
    settings = Settings(environment="production", enforce_corpus_governance=True)
    registry = CorpusRegistry(settings)
    if args.check_public_assets:
        registry.assert_public_assets_ready([*SOURCE_DOCUMENT_NAMES, *SOURCE_VIDEO_NAMES])
    print(f"Validated corpus manifest at {registry.manifest_path}")


if __name__ == "__main__":
    main()
