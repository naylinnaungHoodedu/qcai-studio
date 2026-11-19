"""--check-public-assets flags approvals that can never take effect ([R15]; tasks 2.8 and 2.9)."""

from __future__ import annotations

import copy
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from app.core.config import SOURCE_DOCUMENT_NAMES, SOURCE_VIDEO_NAMES, Settings
from app.core.corpus_governance import CorpusRegistry, review_problems
from app.core.manifest_v2 import compute_corpus_version

REPO_ROOT = Path(__file__).resolve().parents[3]
MANIFEST = json.loads((REPO_ROOT / "corpus" / "public" / "manifest.json").read_text(encoding="utf-8"))
DOCUMENT = "Module2_Routing, Graph Shrinking, and Logistics under Hardware Constraints.docx"
VIDEO_2026 = "Quantum Computing and Artificial Intelligence 2026.mp4"


def _manifest(tmp_path: Path, filename: str, **changes) -> Path:
    payload = copy.deepcopy(MANIFEST)
    for item in payload["items"]:
        if filename in item["asset_filenames"]:
            item.update(changes)
    payload["corpus_version"] = compute_corpus_version(payload["items"])
    path = tmp_path / "public" / "manifest.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


@pytest.mark.parametrize(
    ("filename", "changes", "problem"),
    [
        (DOCUMENT, {"plane": "private", "public_service": True}, "private-plane item must not be approved for public service"),
        (VIDEO_2026, {"public_service": True}, "unbound item must not be approved for public service (Q-10)"),
    ],
)
def test_an_approval_that_can_never_serve_is_a_review_problem(tmp_path, filename, changes, problem):
    manifest = _manifest(tmp_path, filename, **changes)
    registry = CorpusRegistry(Settings(environment="production", enforce_corpus_governance=True, corpus_manifest_path=str(manifest)))
    problems = review_problems(registry, [], [*SOURCE_DOCUMENT_NAMES, *SOURCE_VIDEO_NAMES])
    assert any(problem in entry for entry in problems)
    register = tmp_path / "license-register.csv"
    register.write_text("item_id,version,source,license,permitted_use,public_service,library_confirmation,asset_filenames,reviewed_by,reviewed_at,notes\n", encoding="utf-8")
    completed = subprocess.run(
        [sys.executable, str(REPO_ROOT / "scripts" / "validate_corpus.py"), "--check-public-assets", "--register", str(register)],
        cwd=REPO_ROOT, env={**os.environ, "CORPUS_MANIFEST_PATH": str(manifest), "DATABASE_URL": "sqlite:///:memory:"},
        capture_output=True, text=True, timeout=120,
    )
    assert completed.returncode != 0 and problem in completed.stderr
