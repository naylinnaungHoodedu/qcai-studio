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
