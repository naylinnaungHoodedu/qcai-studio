"""Phase 8 provisional defaults and startup refusal boundaries."""

from types import SimpleNamespace
from copy import deepcopy
import json

import pytest
from pydantic import ValidationError

from app.core import config_package
from app.core.config import Settings
from app.core.phase8_settings import PHASE8_FLAGS


def test_settings_phase8_defaults_and_refusals():
    dev = Settings(_env_file=None, environment="development")
    prod = Settings(_env_file=None, environment="production")
    assert tuple(getattr(dev, key) for key in PHASE8_FLAGS) == ("on", "shadow", "off", "on")
    assert tuple(getattr(prod, key) for key in PHASE8_FLAGS) == ("off",) * 4
    assert Settings(_env_file=None, learner_sync="off").learner_sync == "off"
    with pytest.raises(ValidationError, match="DI-312"):
        Settings(_env_file=None, environment="development", learner_planner="on")


@pytest.mark.parametrize(
    ("flag", "value"),
    [("learner_sync", "on"), ("learner_planner", "shadow"), ("learner_planner", "on"),
     ("learner_identity", "on"), ("learner_privacy", "on")],
)
def test_freeze_phase8_refuses_non_off_settings_with_the_current_package(flag, value):
    with pytest.raises(ValidationError, match="phase8_exit_passed is false"):
        Settings(_env_file=None, environment="production", **{flag: value})


@pytest.mark.parametrize(
    ("default_path", "hash_verified", "phase_exit", "message"),
    [
        (False, True, True, "shipped, hash-verified"),
        (True, False, True, "shipped, hash-verified"),
        (True, True, "true", "phase8_exit_passed is false"),
    ],
)
def test_freeze_phase8_rejects_invalid_exit_authority(monkeypatch, default_path, hash_verified, phase_exit, message):
    package = SimpleNamespace(
        raw={"flag_policy": {"phase8_exit_passed": phase_exit}},
        is_default_path=default_path,
        hash_verified=hash_verified,
    )
    monkeypatch.setattr(config_package, "get_config_package", lambda settings: package)
    with pytest.raises(ValidationError, match=message):
        Settings(_env_file=None, environment="production", learner_identity="on")


def test_freeze_phase8_requires_d27_even_after_exit(monkeypatch):
    package = SimpleNamespace(
        raw={"flag_policy": {"phase8_exit_passed": True}}, is_default_path=True, hash_verified=True
    )
    monkeypatch.setattr(config_package, "get_config_package", lambda settings: package)
    assert Settings(_env_file=None, environment="production", learner_sync="on").learner_sync == "on"
    with pytest.raises(ValidationError, match="D-27"):
        Settings(_env_file=None, environment="production", learner_planner="shadow")


def test_phase8_package_v6_preserves_v5_contracts_and_hash_chain():
    from app.services.learner_record_sync import ASSESSMENT_LIMIT, ASSESSMENT_WINDOW, MAX_ISSUED_REPLICAS
    from app.services.learner_record_shadow import COMPLETION_THRESHOLD, PLANNER_BUDGET_MS

    previous_path = config_package.DEFAULT_PACKAGE_PATH.with_name("v5.json")
    previous = config_package.load_config_package(previous_path, governed=True)
    assert previous.package_version == "5.0.0" and previous.hash_verified and not previous.is_default_path
    latest = config_package.load_config_package(config_package.DEFAULT_PACKAGE_PATH, governed=True)
    after = latest.raw
    assert latest.schema_version == 6 and after["supersedes"]["sha256"] == previous.sha256
    assert set(after) == set(previous.raw) | {"learner"}
    for key, value in previous.raw.items():
        if key not in {"package_version", "schema_version", "phase", "created", "supersedes", "flag_policy", "owner_decisions"}:
            assert after[key] == value, key
    for name, decision in previous.owner_decisions.items():
        assert latest.owner_decisions[name] == decision
    previous_flags, update_flags = previous.raw["flag_policy"], after["flag_policy"]
    assert update_flags["authority"].startswith(previous_flags["authority"])
    assert {key: update_flags[key] for key in previous_flags if key != "authority"} == {
        key: value for key, value in previous_flags.items() if key != "authority"
    }
    assert after["flag_policy"]["phase8_exit_passed"] is False
    assert after["learner"]["sync"]["active_replicas"] == MAX_ISSUED_REPLICAS
    assert after["learner"]["assessment"] == {
        "attempt_limit": ASSESSMENT_LIMIT, "window_minutes": ASSESSMENT_WINDOW.total_seconds() / 60,
        "completion_threshold": COMPLETION_THRESHOLD,
    }
    assert after["learner"]["planner"]["shadow_budget_ms"] == PLANNER_BUDGET_MS


@pytest.mark.parametrize("case", ["invalid-exit", "missing-evidence", "default-drift", "open-consent-grant"])
def test_phase8_package_refuses_inconsistent_release_policy(case):
    from app.core.phase8_settings import check_phase8_package

    raw = deepcopy(json.loads(config_package.DEFAULT_PACKAGE_PATH.read_text(encoding="utf-8")))
    if case == "invalid-exit":
        raw["flag_policy"]["phase8_exit_passed"] = "true"
    elif case == "missing-evidence":
        raw["flag_policy"]["phase8_exit_passed"] = True
    elif case == "default-drift":
        raw["flag_policy"]["learner_privacy"]["default_elsewhere"] = "on"
    else:
        raw["learner"]["consent_classes"]["adaptation"]["elsewhere"] = "granted"
    with pytest.raises(config_package.ConfigPackageError, match="Phase 8"):
        check_phase8_package(raw)
