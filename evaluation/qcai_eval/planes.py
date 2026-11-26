"""The research-plane path rule (Phase 10 spec R-a, PD-74).

Until owner decision D-14 is decided there is no research data plane. A research-plane path is then either a location
outside the repository checkout, or a repository path that matches the pinned package's `private_plane_globs` and that
git ignores. Research-plane scripts refuse any input or output path outside that rule. A checkout path is recognised
in any spelling: through a link or junction, with an extended-length prefix, or as another alias of the same directory
(`checkout_relative`). A path holding a NUL character is refused everywhere: as a script argument (`cli_path`, exit 2
usage) and as an input or output (`PathRefused`), on every platform: `os.path.realpath` raises ValueError for it on
POSIX and maps it on Windows, and `open()` and `os.stat` raise ValueError for it on both.
The rule governs preparation only; runs over non-synthetic data stay refused by hold H12 (runner).
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import subprocess
import sys
from typing import Any, Iterable, Mapping

from .access_log import Unwritable as LogUnwritable
from .canonical import OutputUnwritable

PROVISIONAL_DEFAULTS = ("PD-74",)
REPO_ROOT = Path(__file__).resolve().parents[2]
API_ROOT = REPO_ROOT / "apps" / "api"
# The one place the harness names the package it pins (spec conflict 17): the synthetic spec (`synthetic.PACKAGE_PATH`),
# the pinned configuration record (`check_research_harness.PACKAGE`) and the path rule's default boundary all read it.
# Re-pinning (when v7 is retired, DI-317 and DI-146) changes these two constants and rewrites the records with --write.
PINNED_PACKAGE = "apps/api/app/config_package/v7.json"
PINNED_PACKAGE_VERSION = "7.0.0"
PINNED_PACKAGE_PATH = REPO_ROOT / PINNED_PACKAGE
SYNTHETIC_LICENSE = "synthetic"


class PathRefused(ValueError):
    """A research-plane script was given a path outside the research plane."""


# The last-resort exit code of every research-plane script (spec 5): any exception its `main` does not otherwise handle.
# Never 1, which means drift (or a match, for the scanner); the stderr line names the exception's class, never its
# message, which could quote an input. run_evaluation.py logs the run's `refused` outcome before it.
INTERNAL_ERROR = 10


def internal_error(error: BaseException) -> None:
    """The last-resort refusal line on stderr: the reason `internal_error` and the exception's class only."""
    print(f"refused (exit {INTERNAL_ERROR}): internal_error ({type(error).__name__})", file=sys.stderr)


# What each research-plane script's `main` refuses with exit 2 (spec 5): an output (`canonical.write_lf`) or the access
# log (`access_log.append`) that cannot be written. Neither is an uncaught traceback with exit 1, a code with another meaning.
UNWRITABLE = (OutputUnwritable, LogUnwritable)


def has_nul(path: Path | str) -> bool:
    """True for a path holding a NUL character, which no file system path can hold (`open()` raises ValueError)."""
    return "\x00" in os.fspath(path)


def cli_path(value: str) -> Path:
    """The argparse type of every path argument of a research-plane script: a NUL is a usage error (exit 2)."""
    if has_nul(value):
        raise argparse.ArgumentTypeError("a path holding a NUL character")
    return Path(value)


def _app_on_path() -> None:
    for path in (REPO_ROOT, API_ROOT):
        if str(path) not in sys.path:
            sys.path.insert(0, str(path))


def boundary_policy(package_path: Path = PINNED_PACKAGE_PATH):
    """The boundary block of the package at an explicit path (never the application's default package path): the pinned
    package by default, or the package a run spec pins (the runner passes it for a non-synthetic run's output)."""
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
    except (OSError, ValueError):  # ValueError: an argument with an embedded NUL
        return False
    return result.returncode == 0


def _require_private(path: Path | str, *, root: Path, boundary: Any, what: str) -> Path:
    if has_nul(path):
        raise PathRefused(f"{what}: a path holding a NUL character")
    candidate = Path(os.path.abspath(Path(path)))
    rel = checkout_relative(candidate, root)
    if rel is None:
        return candidate
    _app_on_path()
    from app.core.data_planes import is_private_plane_path

    policy = boundary if boundary is not None else boundary_policy()
    root_abs = Path(os.path.abspath(root))
    try:
        private = rel != "." and is_private_plane_path(root_abs / rel, root_abs, policy)
    except (OSError, ValueError):  # a path the path calls refuse is never a private-plane path
        private = False
    if not private:
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
