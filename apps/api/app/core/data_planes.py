"""The public/private corpus boundary in code (plan Phase 2 task 2.8; section 11.5; Phase 2 spec 3.13).

Plan 11.5: "the API has no path, mount or secret for the private plane". No route, index or resolver may reach a
private-plane item or any path the boundary policy (configuration package v1, `boundary`) names private. Every
check fails closed: a path outside the given root is still tested through every component suffix of its resolved
absolute form, so `/app/corpus/private/x` is private whatever the root resolves to.

Glob semantics: paths are POSIX; `**` matches any number of segments, `*` and `?` stay within one segment, and a
pattern ending in `/` matches a directory prefix.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path, PurePosixPath
import re

from app.core.config_package import BoundaryPolicy, get_config_package


class PrivatePlaneAccessError(PermissionError):
    """A code path tried to reach the private plane or a licensed volume."""


@lru_cache(maxsize=512)
def _glob_regex(pattern: str) -> re.Pattern[str]:
    directory = pattern.endswith("/")
    body = pattern.rstrip("/")
    out: list[str] = []
    index = 0
    while index < len(body):
        char = body[index]
        if body.startswith("**/", index):
            out.append("(?:[^/]+/)*")
            index += 3
            continue
        if body.startswith("**", index):
            out.append(".*")
            index += 2
            continue
        if char == "*":
            out.append("[^/]*")
        elif char == "?":
            out.append("[^/]")
        elif char == "[":
            close = body.find("]", index + 1)
            if close == -1:
                out.append(re.escape(char))
            else:
                content = body[index + 1 : close]
                if content.startswith("!"):
                    content = "^" + content[1:]
                out.append(f"[{content}]")
                index = close
        else:
            out.append(re.escape(char))
        index += 1
    suffix = "(?:/.*)?" if directory else ""
    return re.compile("^" + "".join(out) + suffix + "$")


def glob_match(rel_posix: str, pattern: str) -> bool:
    return bool(_glob_regex(pattern).match(rel_posix.lstrip("/")))


def relative_posix(path: Path | str, root: Path) -> str | None:
    try:
        return Path(path).resolve().relative_to(Path(root).resolve()).as_posix()
    except (ValueError, OSError):
        return None


def path_suffixes(path: Path | str) -> list[str]:
    """Every component suffix of the resolved path: a/b/c -> ["a/b/c", "b/c", "c"]."""
    try:
        resolved = Path(path).resolve()
    except OSError:
        resolved = Path(path)
    parts = [part for part in PurePosixPath(resolved.as_posix()).parts if part not in {"/", ""}]
    # Drop a Windows drive ("D:") so suffixes are repository-shaped.
    if parts and re.fullmatch(r"[A-Za-z]:", parts[0]):
        parts = parts[1:]
    return ["/".join(parts[index:]) for index in range(len(parts))]


def _policy(policy: BoundaryPolicy | None) -> BoundaryPolicy:
    return policy if policy is not None else get_config_package().boundary


def _candidates(path: Path | str, root: Path) -> list[str]:
    candidates: list[str] = []
    relative = relative_posix(path, root)
    if relative is not None:
        candidates.append(relative)
    if isinstance(path, str) and not Path(path).is_absolute():
        candidates.append(PurePosixPath(path.replace("\\", "/")).as_posix())
    candidates.extend(path_suffixes(path))
    return list(dict.fromkeys(candidate for candidate in candidates if candidate))


def is_private_plane_path(path: Path | str, root: Path, policy: BoundaryPolicy | None = None) -> bool:
    boundary = _policy(policy)
    candidates = _candidates(path, root)
    for candidate in candidates:
        if candidate in boundary.public_exceptions:
            # An exception names one repository path exactly; it never widens to a suffix elsewhere.
            if candidate == relative_posix(path, root) or candidate == str(path).replace("\\", "/"):
                return False
    return any(glob_match(candidate, pattern) for candidate in candidates for pattern in boundary.private_plane_globs)


def is_licensed_volume_path(path: Path | str, root: Path, policy: BoundaryPolicy | None = None) -> bool:
    boundary = _policy(policy)
    candidates = _candidates(path, root) + [Path(str(path)).name]
    return any(glob_match(candidate, pattern) for candidate in candidates for pattern in boundary.licensed_volume_globs)


def is_secret_like_name(path: Path | str, policy: BoundaryPolicy | None = None) -> bool:
    boundary = _policy(policy)
    text = str(path).replace("\\", "/")
    candidates = [text.lstrip("/"), PurePosixPath(text).name]
    return any(glob_match(candidate, pattern) for candidate in candidates for pattern in boundary.secret_like_name_globs)


def assert_public_plane_path(path: Path | str, root: Path, policy: BoundaryPolicy | None = None) -> None:
    """Raise PrivatePlaneAccessError for a private-plane path or a licensed volume (fail closed)."""
    if is_private_plane_path(path, root, policy) or is_licensed_volume_path(path, root, policy):
        raise PrivatePlaneAccessError("This path is outside the public corpus plane.")
