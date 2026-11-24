"""The research-plane path rule (Phase 10 spec R-a, PD-74).

Until owner decision D-14 is decided there is no research data plane. A research-plane path is then either a location
outside the repository checkout, or a repository path that matches the pinned package's `private_plane_globs` and that
git ignores. Research-plane scripts refuse any input or output path outside that rule. A checkout path is recognised
in any spelling: through a link or junction, with an extended-length prefix, or as another alias of the same directory
(`checkout_relative`). The rule governs preparation only; runs over non-synthetic data stay refused by hold H12
(runner).
"""

from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
from typing import Any, Iterable, Mapping

PROVISIONAL_DEFAULTS = ("PD-74",)
REPO_ROOT = Path(__file__).resolve().parents[2]
API_ROOT = REPO_ROOT / "apps" / "api"
V7_PATH = API_ROOT / "app" / "config_package" / "v7.json"
SYNTHETIC_LICENSE = "synthetic"


class PathRefused(ValueError):
    """A research-plane script was given a path outside the research plane."""


def _app_on_path() -> None:
    for path in (REPO_ROOT, API_ROOT):
        if str(path) not in sys.path:
            sys.path.insert(0, str(path))


def boundary_policy(package_path: Path = V7_PATH):
    """The boundary block of the package at an explicit path (never the application's default package path)."""
    _app_on_path()
    from app.core.config_package import load_config_package

    return load_config_package(Path(package_path), governed=False).boundary


def _realpath(path: Path) -> Path:
    try:
        return Path(os.path.realpath(path))
    except (OSError, ValueError):
        return path


def checkout_relative(path: Path | str, root: Path = REPO_ROOT) -> str | None:
    """The POSIX path of `path` relative to the checkout `root` ("." for the root itself), or None when it lies outside.

    Three readings, so that no spelling of a checkout path counts as outside: the lexical absolute paths; both sides with
    links and junctions resolved (`os.path.realpath`); and file identity, where the nearest existing ancestor of `path`,
    or any of its ancestors, is the same directory as the root (`os.path.samefile`), which maps an extended-length,
    administrative-share or other alias of the checkout."""
    candidate = Path(os.path.abspath(Path(path)))
    root_abs = Path(os.path.abspath(Path(root)))
    for left, right in ((candidate, root_abs), (_realpath(candidate), _realpath(root_abs))):
        try:
            return left.relative_to(right).as_posix()
        except ValueError:
            pass
    tail: list[str] = []
    probe = candidate
    while True:
        try:
            if probe.exists() and os.path.samefile(probe, root_abs):
                return "/".join(reversed(tail)) if tail else "."
        except (OSError, ValueError):
            pass
        if probe.parent == probe:
            return None
        tail.append(probe.name)
        probe = probe.parent


def inside_checkout(path: Path | str, root: Path = REPO_ROOT) -> bool:
    return checkout_relative(path, root) is not None


def _git_ignored(rel_posix: str, root: Path) -> bool:
    try:
        result = subprocess.run(["git", "check-ignore", "-q", "--no-index", rel_posix], cwd=root, capture_output=True)
    except OSError:
        return False
    return result.returncode == 0


def _require_private(path: Path | str, *, root: Path, boundary: Any, what: str) -> Path:
    candidate = Path(os.path.abspath(Path(path)))
    rel = checkout_relative(candidate, root)
    if rel is None:
        return candidate
    _app_on_path()
    from app.core.data_planes import is_private_plane_path

    policy = boundary if boundary is not None else boundary_policy()
    root_abs = Path(os.path.abspath(root))
    if rel == "." or not is_private_plane_path(root_abs / rel, root_abs, policy):
        raise PathRefused(f"{what} {rel}: inside the checkout and not a private-plane path (PD-74)")
    if not _git_ignored(rel, root_abs):
        raise PathRefused(f"{what} {rel}: a private-plane path that git does not ignore (PD-74)")
    return candidate


def require_private_output(path: Path | str, *, root: Path = REPO_ROOT, boundary: Any = None) -> Path:
    return _require_private(path, root=root, boundary=boundary, what="output")


def require_private_input(path: Path | str, *, root: Path = REPO_ROOT, boundary: Any = None) -> Path:
    return _require_private(path, root=root, boundary=boundary, what="input")


def all_synthetic(items: Iterable[Mapping[str, Any]]) -> bool:
    items = list(items)
    return bool(items) and all(item.get("license_class") == SYNTHETIC_LICENSE for item in items)
