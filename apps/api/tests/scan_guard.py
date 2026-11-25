"""The whole-tree scan guard for tests (Phase 10 spec 8.3).

CI's own `scan_research_logs.py --repo` step scans the whole tracked tree once (it took about 37 s). No test repeats it:
`install()` wraps `contamination.repository_target` so that any in-process call that would list the real checkout through
the real `contamination.git_files` (a test that did not replace `git_files` with its own file list) fails the test. The
wrapper runs whatever the call path: `scan_research_logs.main([... "--repo" ...])` with the argv built anywhere, a direct
`contamination.repository_target(...)`, a sync or an async test. A subprocess that runs the script is outside the process
and is refused by the static check in `test_contamination_scan.py`.
"""

from __future__ import annotations

import os
from pathlib import Path
import sys

import pytest

GUARD_MARKER = "_whole_tree_scan_guard"


def _same(left: Path | str, right: Path | str) -> bool:
    try:
        return os.path.samefile(left, right)
    except (OSError, ValueError):
        return os.path.realpath(left) == os.path.realpath(right)


def install(repo_root: Path) -> None:
    if str(repo_root) not in sys.path:
        sys.path.append(str(repo_root))
    from evaluation.qcai_eval import contamination

    if getattr(contamination.repository_target, GUARD_MARKER, False):
        return
    real_target = contamination.repository_target
    real_git_files = contamination.git_files

    def guarded(root, sets, **options):
        if contamination.git_files is real_git_files and _same(root, repo_root):
            pytest.fail("a test ran the repository target over the whole tracked tree; CI's --repo step does that once. "
                        "Replace contamination.git_files with the test's own file list (spec 8.3).", pytrace=False)
        return real_target(root, sets, **options)

    setattr(guarded, GUARD_MARKER, True)
    guarded.__wrapped__ = real_target
    guarded.__doc__ = real_target.__doc__
    contamination.repository_target = guarded
