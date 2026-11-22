"""Phase 8 provisional defaults and startup refusal boundaries."""

from types import SimpleNamespace

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
