"""The evaluation tests' set-up (Phase 10 spec 8.2): the repository, apps/api and its tests on the path, an in-memory
development database for any lazy application import, and the network guard installed before anything else runs."""

from __future__ import annotations

import os
from pathlib import Path
import sys

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
for path in (REPO_ROOT, REPO_ROOT / "apps" / "api", REPO_ROOT / "apps" / "api" / "tests"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("ENVIRONMENT", "development")

import network_guard  # noqa: E402

# No test touches the network (Phase 5 spec 13.2); install() is idempotent when apps/api/tests' conftest ran first.
network_guard.install()


@pytest.fixture(autouse=True)
def _no_network_attempt_in_evaluation_tests():
    network_guard.take_blocked()
    yield
    blocked = network_guard.take_blocked()
    if blocked:
        pytest.fail(f"a test tried to touch the network: {blocked[:3]}")
