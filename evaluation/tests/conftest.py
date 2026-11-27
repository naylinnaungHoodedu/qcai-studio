"""The evaluation tests' set-up (Phase 10 spec 8.2): the repository, apps/api and its tests on the path, an in-memory
development database for any lazy application import, the network guard and the whole-tree scan guard installed before
anything else runs, and the UTC day the run window reads (`governance.utc_today`) fixed at the synthetic specs' created_at."""

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
import scan_guard  # noqa: E402

# No test touches the network (Phase 5 spec 13.2); install() is idempotent when apps/api/tests' conftest ran first.
network_guard.install()
# No test repeats CI's whole-tree research-log scan (spec 8.3); idempotent too.
scan_guard.install(REPO_ROOT)


@pytest.fixture(autouse=True)
def _no_network_attempt_in_evaluation_tests():
    network_guard.take_blocked()
    yield
    blocked = network_guard.take_blocked()
    if blocked:
        pytest.fail(f"a test tried to touch the network: {blocked[:3]}")


@pytest.fixture(autouse=True)
def _the_run_day_is_the_synthetic_specs_day(monkeypatch):
    """A confirmatory or live run is judged on the UTC day it is planned (the run window, governance module docstring);
    the tests plan theirs on synthetic.CREATED's day, whatever the clock says (a test that checks the rule sets another)."""
    import datetime

    from evaluation.qcai_eval import governance, synthetic

    monkeypatch.setattr(governance, "utc_today", lambda: datetime.date.fromisoformat(synthetic.CREATED[:10]))
