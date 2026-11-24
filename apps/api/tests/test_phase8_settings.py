"""Phase 8 provisional defaults and startup refusal boundaries."""

from types import SimpleNamespace
from copy import deepcopy
import json
from pathlib import Path
import re
from shutil import copytree

import pytest
from pydantic import ValidationError

from app.core import config_package
from app.core.config import Settings
from app.core.phase8_settings import CLIENT_CAS_RETRIES, PHASE8_FLAGS, learner_engineering_policy


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


def test_phase8_package_v7_preserves_v6_contracts_and_hash_chain():
    from app.services.ehmf.vocabulary import EHMF_FIRST_MAJOR
    from app.services.learner_record_sync import ASSESSMENT_LIMIT, ASSESSMENT_WINDOW, MAX_ISSUED_REPLICAS
    from app.services.learner_record_shadow import COMPLETION_THRESHOLD, PLANNER_BUDGET_MS

    previous = config_package.load_config_package(config_package.V6_PACKAGE_PATH, governed=True)
    assert previous.package_version == "6.0.0" and previous.hash_verified and not previous.is_default_path
    assert previous.schema_version == config_package.EHMF_SCHEMA_VERSION == EHMF_FIRST_MAJOR == 6
    latest = config_package.load_config_package(config_package.DEFAULT_PACKAGE_PATH, governed=True)
    after = latest.raw
    assert (latest.package_version, latest.schema_version) == ("7.0.0", 7)
    assert after["supersedes"]["package_version"] == previous.package_version
    assert after["supersedes"]["sha256"] == previous.sha256
    assert latest.ehmf == previous.ehmf and latest.ehmf is not None
    assert after["ehmf"]["config_version"]["first_package"] == "6.0.0"
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
    from app.services.retention import SECURITY_EVENT_RETENTION_DAYS

    for name, block in learner_engineering_policy().items():
        assert after["learner"][name] == block
    assert after["learner"]["privacy"]["audit_retention_days"] == SECURITY_EVENT_RETENTION_DAYS
    source = Path(__file__).resolve().parents[3] / "apps/frontend/src/lib/learner-record-sync.ts"
    match = re.search(r"^const CLIENT_CAS_RETRIES = (\d+);", source.read_text(encoding="utf-8"), re.M)
    assert match and int(match[1]) == CLIENT_CAS_RETRIES


@pytest.mark.parametrize("version", [0, 8, True])
def test_phase8_loader_refuses_schema_versions_outside_the_latest_bound(version):
    path = config_package.DEFAULT_PACKAGE_PATH
    raw = json.loads(path.read_text(encoding="utf-8"))
    assert config_package.parse_config_package(raw, path=path, sha256="", hash_verified=False).schema_version == 7
    raw["schema_version"] = version
    with pytest.raises(config_package.ConfigPackageError, match="schema_version.*integer from 1 to 7"):
        config_package.parse_config_package(raw, path=path, sha256="", hash_verified=False)


def test_phase8_schema_seven_still_enforces_ehmf_checks():
    path = config_package.DEFAULT_PACKAGE_PATH
    raw = json.loads(path.read_text(encoding="utf-8"))
    raw["ehmf"]["config_version"]["first_package"] = "7.0.0"
    with pytest.raises(config_package.ConfigPackageError, match="ehmf.config_version.*first_package '6.0.0'"):
        config_package.parse_config_package(raw, path=path, sha256="", hash_verified=False)


@pytest.mark.parametrize(("section", "field", "value"), [
    ("assessment", "attempt_limit", 15), ("planner", "bands", [0.2, 0.8]),
    ("sync", "client_retries", 3), ("privacy", "guard_retention_days", 100),
])
def test_phase8_package_refuses_rehashed_engineering_drift(tmp_path, section, field, value):
    source = config_package.DEFAULT_PACKAGE_PATH
    raw = json.loads(source.read_text(encoding="utf-8"))
    raw["learner"][section][field] = value
    target = tmp_path / source.name
    target.write_text(json.dumps(raw), encoding="utf-8")
    target.with_name(f"{target.name}.sha256").write_text(config_package.canonical_sha256(raw) + "\n", encoding="utf-8")
    copytree(source.parent / "schemas", tmp_path / "schemas")
    with pytest.raises(config_package.ConfigPackageError, match=f"learner\\.{section} engineering policy"):
        config_package.load_config_package(target, governed=True)


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
