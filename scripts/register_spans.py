"""Register span identity in corpus_spans (plan Phase 2 task 2.2): python scripts/register_spans.py --dry-run | --apply

A wrapper for app.workers.register_spans; see that module for the options, exit codes and approvals.
"""

from __future__ import annotations

from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
API_ROOT = REPO_ROOT / "apps" / "api"
for path in (REPO_ROOT, API_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from app.workers.register_spans import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
