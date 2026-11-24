"""Phase 8 defaults and the pre-exit runtime freeze."""

from collections.abc import Mapping
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.core.config import Settings


PHASE8_FLAGS = {
    "learner_sync": (("off", "on"), "on"),
    "learner_planner": (("off", "shadow", "on"), "shadow"),
    "learner_identity": (("off", "on"), "off"),
    "learner_privacy": (("off", "on"), "on"),
}

MAX_ISSUED_REPLICAS = 16
ASSESSMENT_LIMIT = 12
ASSESSMENT_WINDOW_MINUTES = 15
COMPLETION_THRESHOLD = 0.7
FOUNDATION_THRESHOLD = 0.4
ADVANCED_THRESHOLD = 0.75
PLANNER_BUDGET_MS = 150
LEVELS = (0.1, 0.5, 0.9)
SERVER_CAS_RETRIES = 0
CLIENT_CAS_RETRIES = 1  # Mirrored by the dormant browser client and verified by the package test.
AUDIT_RETENTION_DAYS = 365
GUARD_RETENTION_DAYS = 365


def learner_engineering_policy() -> dict:
    return {
        "sync": {
            "active_replicas": MAX_ISSUED_REPLICAS, "retirement": "least-recently-used",
            "server_retries": SERVER_CAS_RETRIES, "client_retries": CLIENT_CAS_RETRIES,
        },
        "assessment": {
            "attempt_limit": ASSESSMENT_LIMIT, "window_minutes": ASSESSMENT_WINDOW_MINUTES,
            "completion_threshold": COMPLETION_THRESHOLD,
        },
        "planner": {
            "bands": [FOUNDATION_THRESHOLD, ADVANCED_THRESHOLD], "shadow_budget_ms": PLANNER_BUDGET_MS,
            "renderer_wiring": "DI-312", "harness_levels": list(LEVELS),
        },
        "privacy": {
            "export": "ndjson", "receipt_digest": "canonical-json-sha256",
            "audit_retention_days": AUDIT_RETENTION_DAYS, "guard_retention_days": GUARD_RETENTION_DAYS,
        },
    }


def check_phase8_package(raw: Mapping) -> None:
    """Validate the package's Phase 8 release policy against its runtime switches."""
    from app.core.config_package import ConfigPackageError

    def require(condition, field):
        if not condition:
            raise ConfigPackageError(f"Configuration package: invalid Phase 8 {field}.")

    policy = raw.get("flag_policy")
    require(isinstance(policy, Mapping), "flag_policy")
    require(policy.get("provisional") is True and "PD-203" in str(policy.get("authority")), "flag authority")
    exit_passed = policy.get("phase8_exit_passed")
    evidence = policy.get("phase8_exit_evidence")
    require(type(exit_passed) is bool, "exit flag")
    require(isinstance(evidence, str) and bool(evidence.strip()) if exit_passed else evidence is None, "exit evidence")
    for name, (values, development_default) in PHASE8_FLAGS.items():
        entry = policy.get(name)
        require(isinstance(entry, Mapping), name)
        require(
            entry.get("values") == list(values)
            and entry.get("default_development") == development_default
            and entry.get("default_elsewhere") == "off"
            and entry.get("on_requires") == "phase8_exit_passed",
            name,
        )
    learner = raw.get("learner")
    require(isinstance(learner, Mapping) and learner.get("provisional") is True, "learner policy")
    require(learner.get("authority") == "PD-200 through PD-205", "learner authority")
    for name, policy in learner_engineering_policy().items():
        require(learner.get(name) == policy, f"learner.{name} engineering policy")
    classes = learner.get("consent_classes")
    require(isinstance(classes, Mapping), "learner consent classes")
    decision = raw["owner_decisions"].get("D-27")
    require(isinstance(decision, Mapping), "D-27 owner decision")
    if decision.get("state") == "open":
        require(
            decision.get("ratified") is False and learner.get("consent_version") == "d27-unresolved-v1"
            and classes == {
                "adaptation": {"development": "synthetic-grant", "elsewhere": "refused"},
                "analytics": {"development": "synthetic-grant", "elsewhere": "refused"},
                "research": {"development": "refused", "elsewhere": "refused"},
            },
            "D-27 provisional consent",
        )


def resolve_phase8_settings(settings: "Settings") -> None:
    development = settings.environment.lower() == "development"
    active = {}
    for name, (_, development_default) in PHASE8_FLAGS.items():
        value = getattr(settings, name)
        if value is None:
            value = development_default if development else "off"
            setattr(settings, name, value)
        if value != "off":
            active[name] = value
    if active and not development:
        _require_shipped_phase8_exit(settings, active)
    if settings.learner_planner == "on":
        raise ValueError("LEARNER_PLANNER=on requires the versioned renderer wiring (DI-312). Use off or shadow.")
    if not development and settings.learner_planner != "off":
        raise ValueError("LEARNER_PLANNER requires approved adaptation consent outside development (D-27). Use off.")


def _require_shipped_phase8_exit(settings: "Settings", active: Mapping[str, str]) -> None:
    from app.core.config_package import ConfigPackageError, get_config_package

    names = ", ".join(f"{name.upper()}={value}" for name, value in active.items())
    try:
        package = get_config_package(settings)
    except ConfigPackageError as exc:
        raise ValueError(f"{names} needs a valid Phase 8 configuration package. Use off.") from exc
    policy = package.raw.get("flag_policy")
    if not isinstance(policy, Mapping) or policy.get("phase8_exit_passed") is not True:
        raise ValueError(
            f"{names} is refused outside development before the Phase 8 exit "
            "(configuration package flag_policy.phase8_exit_passed is false; plan Phase 8 L, P). Use off."
        )
    if not (package.is_default_path and package.hash_verified):
        raise ValueError(f"{names} outside development needs the shipped, hash-verified configuration package. Use off.")
