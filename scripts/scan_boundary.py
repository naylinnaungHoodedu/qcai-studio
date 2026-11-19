"""Boundary scans for the public/private corpus planes (plan Phase 2 task 2.8, AC-2-7; Phase 2 spec 2.9, 3.13).

Run: python scripts/scan_boundary.py --repo --docker-context apps/api/Dockerfile:. \\
         --docker-context apps/frontend/Dockerfile:apps/frontend [--image-tar PATH] [--release-zip PATH]
         [--fingerprints PATH] [--require-passage-scan] [--require-ac-2-7] [--report PATH]

Targets:
- --repo: the tracked tree (git ls-files; --working-tree adds untracked files that are not ignored);
- --docker-context DOCKERFILE:CONTEXT: a filesystem walk of CONTEXT filtered by CONTEXT's own .dockerignore,
  with Docker semantics (patterns relative to the context, matching a path or any parent; "!" lines refused).
  It is a proxy for the image: it shows what the build can copy, not what the image holds;
- --image-tar PATH: a built image's filesystem, from `docker save` (every layer, so a file a later layer deletes
  still counts, because the image still ships it) or a flat `docker export` tar;
- --release-zip PATH: a release bundle's namelist.
Each target is scanned for private-plane paths and licensed volumes (configuration package `boundary`); image
contexts, images and zips also fail on a secret-like name (never opened). Passage scanning needs the salted
fingerprint file from the private plane (--fingerprints); public CI has none, so the report says passage scanning
was not run and never claims it passed. Paths only: the scanner never prints or stores file contents.

The report's "ac_2_7" block says what the run evidences. AC-2-7 ("Scans find zero private-plane paths or licensed
passages") with task 2.8 ("licensed-passage scans of images and releases") is "met" only when the path and the
passage scans both ran and passed over at least one built image and one release bundle; otherwise it is
"partial" (nothing found, but a half is missing) or "fail". --require-passage-scan makes a passage scan that did
not run a failure, and --require-ac-2-7 makes anything short of "met" a failure (the Phase 2 exit-gate run).
Exit 1 when anything is found or a requirement is not met, 2 on a usage error, 0 otherwise.
"""

from __future__ import annotations

import argparse
import hashlib
import hmac
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import subprocess
import sys
import tarfile
import unicodedata
import zipfile

REPO_ROOT = Path(__file__).resolve().parents[1]
API_ROOT = REPO_ROOT / "apps" / "api"
for path in (REPO_ROOT, API_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from app.core.config import Settings  # noqa: E402
from app.core.config_package import BoundaryPolicy, get_config_package  # noqa: E402
from app.core.data_planes import glob_match, is_licensed_volume_path, is_private_plane_path, is_secret_like_name  # noqa: E402

REPORT_NAME = "qcai-boundary-scan"
FINGERPRINT_FORMAT = "qcai-licensed-fingerprints/1"
DEFAULT_CONTEXTS = ("apps/api/Dockerfile:.", "apps/frontend/Dockerfile:apps/frontend")
TEXT_EXTENSIONS = {
    ".py", ".md", ".txt", ".json", ".jsonl", ".csv", ".ts", ".tsx", ".js", ".mjs", ".html", ".css", ".yaml", ".yml",
    ".toml", ".ini", ".cfg", ".sql", ".xml", ".svg",
}
MAX_SCAN_BYTES = 20 * 1024 * 1024
WORDS = re.compile(r"[^\W_]+")
NOT_RUN_REASON = "no licensed-passage fingerprint file was supplied; passage scanning was not run"


class DockerIgnoreError(ValueError):
    """A .dockerignore this scanner cannot apply safely (a "!" re-include)."""


def policy() -> BoundaryPolicy:
    return get_config_package(Settings()).boundary


# --- .dockerignore and the build context ---


def dockerignore_patterns(path: Path) -> list[str]:
    if not path.exists():
        return []
    patterns = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("!"):
            raise DockerIgnoreError(f"{path}: '!' re-includes are refused (the boundary scan cannot prove them safe)")
        cleaned = PurePosixPath(line.lstrip("/")).as_posix().rstrip("/")
        if cleaned and cleaned != ".":
            patterns.append(cleaned)
    return patterns


def docker_ignored(rel: str, patterns: list[str]) -> bool:
    parts = rel.split("/")
    prefixes = ["/".join(parts[: index + 1]) for index in range(len(parts))]
    return any(glob_match(prefix, pattern) for pattern in patterns for prefix in prefixes)


def walk_context(context: Path, patterns: list[str]) -> list[str]:
    """Files Docker would send: every file under context not matched (or under a directory matched) by a pattern."""
    files: list[str] = []
    for current, directories, names in os.walk(context):
        rel_dir = Path(current).relative_to(context).as_posix()
        rel_dir = "" if rel_dir == "." else rel_dir
        directories[:] = sorted(d for d in directories if not docker_ignored(f"{rel_dir}/{d}".lstrip("/"), patterns))
        for name in sorted(names):
            rel = f"{rel_dir}/{name}".lstrip("/")
            if not docker_ignored(rel, patterns):
                files.append(rel)
    return files


def dockerfile_sources(dockerfile: Path) -> list[str]:
    """COPY/ADD sources taken from the build context (multi-stage --from= copies are skipped)."""
    sources: list[str] = []
    for line in dockerfile.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped.upper().startswith(("COPY ", "ADD ")):
            continue
        tokens = stripped.split()[1:]
        if any(token.startswith("--from=") for token in tokens):
            continue
        arguments = [token for token in tokens if not token.startswith("--")]
        sources.extend("." if source in {".", "./"} else (source[2:] if source.startswith("./") else source) for source in arguments[:-1])
    return sources


def image_source_files(files: list[str], sources: list[str]) -> list[str]:
    selected = []
    for rel in files:
        for source in sources:
            if source == "." or rel == source or rel.startswith(source.rstrip("/") + "/") or glob_match(rel, source):
                selected.append(rel)
                break
    return selected


# --- path checks ---


def check_paths(paths: list[str], root: Path, boundary: BoundaryPolicy) -> dict[str, list[str]]:
    private, licensed, secret = [], [], []
    for rel in paths:
        absolute = root / rel
        if is_private_plane_path(absolute, root, boundary):
            private.append(rel)
        if is_licensed_volume_path(absolute, root, boundary):
            licensed.append(rel)
        if is_secret_like_name(rel, boundary):
            secret.append(rel)
    return {"private_plane_paths": private, "licensed_volume_paths": licensed, "secret_like_paths": secret}


# --- fingerprints (salted shingles from the private plane) ---


def normalized_words(text: str) -> list[str]:
    return WORDS.findall(unicodedata.normalize("NFKC", text).casefold())


def fingerprint_shingles(text: str, salt: bytes, n: int) -> set[str]:
    words = normalized_words(text)
    return {
        hmac.new(salt, " ".join(words[index : index + n]).encode("utf-8"), hashlib.sha256).hexdigest()[:32]
        for index in range(max(0, len(words) - n + 1))
    }


def load_fingerprints(path: Path) -> dict:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("format") != FINGERPRINT_FORMAT or payload.get("hash") != "hmac-sha256-trunc32":
        raise ValueError(f"{path}: not a {FINGERPRINT_FORMAT} file")
    return {
        "id": str(payload.get("fingerprint_set_id", "unknown")),
        "salt": bytes.fromhex(payload["salt_hex"]),
        "n": int(payload.get("shingle_words", 12)),
        "set": frozenset(payload["fingerprints"]),
    }


def _text_of(name: str, data: bytes) -> str | None:
    suffix = PurePosixPath(name).suffix.lower()
    if suffix == ".docx":
        from docx import Document

        try:
            return "\n".join(paragraph.text for paragraph in Document(io.BytesIO(data)).paragraphs)
        except Exception:
            return None
    if suffix in TEXT_EXTENSIONS:
        return data.decode("utf-8", errors="replace")
    return None


def passage_hits(entries: list[tuple[str, callable]], fingerprints: dict, boundary: BoundaryPolicy) -> tuple[list[dict], int, int]:
    """(files with hits, files scanned, secret-like files skipped). Each entry is (name, read bytes)."""
    hits, scanned, skipped = [], 0, 0
    for name, read in entries:
        if is_secret_like_name(name, boundary):
            skipped += 1  # never opened
            continue
        suffix = PurePosixPath(name).suffix.lower()
        if suffix not in TEXT_EXTENSIONS and suffix != ".docx":
            continue
        data = read()
        if data is None or len(data) > MAX_SCAN_BYTES:
            continue
        text = _text_of(name, data)
        if text is None:
            continue
        scanned += 1
        count = len(fingerprint_shingles(text, fingerprints["salt"], fingerprints["n"]) & fingerprints["set"])
        if count >= boundary.passage_min_hits:
            hits.append({"path": name, "hits": count})
    return hits, scanned, skipped


def _file_reader(path: Path):
    def read() -> bytes | None:
        try:
            if path.stat().st_size > MAX_SCAN_BYTES:
                return None
            return path.read_bytes()
        except OSError:
            return None

    return read


# --- targets ---


def git_files(root: Path, working_tree: bool) -> list[str]:
    tracked = subprocess.run(["git", "ls-files", "-z"], cwd=root, capture_output=True, check=True).stdout.decode("utf-8")
    files = [name for name in tracked.split("\0") if name]
    if working_tree:
        others = subprocess.run(["git", "ls-files", "-z", "--others", "--exclude-standard"], cwd=root, capture_output=True, check=True)
        files += [name for name in others.stdout.decode("utf-8").split("\0") if name]
    return sorted(set(files))


def scan_repository(root: Path, boundary: BoundaryPolicy, working_tree: bool = False) -> tuple[dict, list]:
    files = git_files(root, working_tree)
    found = check_paths(files, root, boundary)
    scan = {
        "target": "repository",
        "listing": "git ls-files" + (" plus untracked, not ignored" if working_tree else ""),
        "files": len(files),
        "private_plane_paths": found["private_plane_paths"],
        "licensed_volume_paths": found["licensed_volume_paths"],
        # Informational for the repository (templates such as .env.example are tracked on purpose) [R16].
        "secret_like_paths": found["secret_like_paths"],
        "fails_on_secret_like": False,
    }
    return scan, [(name, _file_reader(root / name)) for name in files]


def scan_docker_context(root: Path, spec: str, boundary: BoundaryPolicy) -> tuple[dict, list]:
    dockerfile_text, _, context_text = spec.partition(":")
    dockerfile = (root / dockerfile_text).resolve()
    context = (root / (context_text or ".")).resolve()
    ignore_file = context / ".dockerignore"
    patterns = dockerignore_patterns(ignore_file)
    files = walk_context(context, patterns)
    found = check_paths(files, context, boundary)
    # Paths relative to the repository read better in the report; the checks above used the context root.
    prefix = context.relative_to(root).as_posix() if context != root else ""
    as_repo = (lambda rel: f"{prefix}/{rel}" if prefix else rel)
    sources = dockerfile_sources(dockerfile) if dockerfile.exists() else []
    scan = {
        "target": "docker-context",
        "dockerfile": dockerfile_text,
        "context": context_text or ".",
        "ignore_file": (Path(context_text or ".") / ".dockerignore").as_posix() if ignore_file.exists() else None,
        "listing": "filesystem walk filtered by the context's .dockerignore",
        "files": len(files),
        "image_source_files": len(image_source_files(files, sources)),
        "private_plane_paths": [as_repo(rel) for rel in found["private_plane_paths"]],
        "licensed_volume_paths": [as_repo(rel) for rel in found["licensed_volume_paths"]],
        "secret_like_paths": [as_repo(rel) for rel in found["secret_like_paths"]],
        "fails_on_secret_like": True,
    }
    return scan, [(as_repo(rel), _file_reader(context / rel)) for rel in files]


def scan_release_zip(path: Path, boundary: BoundaryPolicy) -> tuple[dict, list]:
    with zipfile.ZipFile(path) as bundle:
        names = [info.filename for info in bundle.infolist() if not info.is_dir()]
    found = check_paths(names, Path("/zip-root"), boundary)

    def reader(name: str):
        def read() -> bytes | None:
            with zipfile.ZipFile(path) as bundle:
                info = bundle.getinfo(name)
                if info.file_size > MAX_SCAN_BYTES:
                    return None
                return bundle.read(name)

        return read

    scan = {
        "target": "release-zip",
        "path": path.as_posix(),
        "entries": len(names),
        "private_plane_paths": found["private_plane_paths"],
        "licensed_volume_paths": found["licensed_volume_paths"],
        "secret_like_paths": found["secret_like_paths"],
        "fails_on_secret_like": True,
    }
    return scan, [(name, reader(name)) for name in names]


class _ImageArchive:
    """A built image tar kept open while it is scanned; each layer is opened once, in order."""

    def __init__(self, path: Path) -> None:
        self.outer = tarfile.open(path, "r:*")
        self._layer_name: str | None = None
        self._layer: tarfile.TarFile | None = None

    def layer(self, name: str | None) -> tarfile.TarFile:
        if name is None:
            return self.outer
        if self._layer_name != name:
            if self._layer is not None:
                self._layer.close()
            stream = self.outer.extractfile(name)
            if stream is None:
                raise ValueError(f"image layer {name} is not a file")
            self._layer = tarfile.open(fileobj=stream, mode="r:*")
            self._layer_name = name
        return self._layer

    def close(self) -> None:
        if self._layer is not None:
            self._layer.close()
        self.outer.close()


def _image_layers(archive: _ImageArchive) -> list[str | None]:
    """The layer tars of a `docker save` archive (manifest.json "Layers"), or [None] for a flat filesystem tar."""
    try:
        member = archive.outer.getmember("manifest.json")
    except KeyError:
        return [None]
    stream = archive.outer.extractfile(member)
    manifest = json.loads(stream.read()) if stream is not None else None
    if not (isinstance(manifest, list) and manifest and all(isinstance(entry, dict) and "Layers" in entry for entry in manifest)):
        return [None]
    return list(dict.fromkeys(layer for entry in manifest for layer in entry["Layers"]))


def _image_path(name: str) -> str:
    cleaned = PurePosixPath(name.replace("\\", "/")).as_posix()
    while cleaned.startswith(("./", "/")):
        cleaned = cleaned[2:] if cleaned.startswith("./") else cleaned[1:]
    return cleaned


def scan_image_tar(path: Path, boundary: BoundaryPolicy, opened: list) -> tuple[dict, list]:
    archive = _ImageArchive(path)
    opened.append(archive)
    layers = _image_layers(archive)
    files: list[str] = []
    entries: list = []
    for layer in layers:
        for member in archive.layer(layer).getmembers():
            name = _image_path(member.name)
            if not member.isfile() or not name or PurePosixPath(name).name.startswith(".wh."):
                continue  # directories, links and whiteout markers carry no content of their own
            files.append(name)

            def read(layer=layer, member_name=member.name, size=member.size) -> bytes | None:
                if size > MAX_SCAN_BYTES:
                    return None
                stream = archive.layer(layer).extractfile(member_name)
                return stream.read() if stream is not None else None

            entries.append((f"{path.name}:{name}", read))
    unique = sorted(set(files))
    found = check_paths(unique, Path("/image-root"), boundary)
    scan = {
        "target": "image",
        "path": path.as_posix(),
        "format": "docker-save" if layers != [None] else "filesystem-tar",
        "layers": len([layer for layer in layers if layer is not None]),
        "files": len(unique),
        "private_plane_paths": found["private_plane_paths"],
        "licensed_volume_paths": found["licensed_volume_paths"],
        "secret_like_paths": found["secret_like_paths"],
        "fails_on_secret_like": True,
    }
    return scan, entries


def ac_2_7_summary(scans: list[dict], path_result: str, passage_result: str) -> dict:
    """What this run evidences for AC-2-7 and task 2.8; "met" needs both halves over an image and a release."""
    targets: dict[str, int] = {}
    for scan in scans:
        targets[scan["target"]] = targets.get(scan["target"], 0) + 1
    missing = []
    if passage_result == "not_run":
        missing.append("licensed-passage scan not run: it needs the private-plane fingerprint file (D-14)")
    if not targets.get("image"):
        missing.append("no built image scanned (--image-tar); a build context is only a proxy for the image")
    if not targets.get("release-zip"):
        missing.append("no release bundle scanned (--release-zip)")
    if path_result == "fail" or passage_result == "fail":
        status = "fail"
    else:
        status = "partial" if missing else "met"
    return {"status": status, "path_scan": path_result, "passage_scan": passage_result, "targets": targets, "missing": missing}


def run(args: argparse.Namespace) -> dict:
    opened: list[_ImageArchive] = []
    try:
        return _run(args, opened)
    finally:
        for archive in opened:
            archive.close()


def _run(args: argparse.Namespace, opened: list) -> dict:
    boundary = policy()
    root = Path(args.root).resolve()
    scans: list[tuple[dict, list]] = []
    if args.repo:
        scans.append(scan_repository(root, boundary, args.working_tree))
    for spec in args.docker_context or []:
        scans.append(scan_docker_context(root, spec, boundary))
    for image_path in getattr(args, "image_tar", None) or []:
        scans.append(scan_image_tar(Path(image_path), boundary, opened))
    for zip_path in args.release_zip or []:
        scans.append(scan_release_zip(Path(zip_path), boundary))
    path_fail = any(
        scan["private_plane_paths"] or scan["licensed_volume_paths"] or (scan["fails_on_secret_like"] and scan["secret_like_paths"])
        for scan, _ in scans
    )
    if args.fingerprints:
        fingerprints = load_fingerprints(Path(args.fingerprints))
        files_with_hits, scanned, skipped = [], 0, 0
        for scan, entries in scans:
            hits, count, skip = passage_hits(entries, fingerprints, boundary)
            files_with_hits += [{**hit, "target": scan["target"]} for hit in hits]
            scanned += count
            skipped += skip
        passage = {
            "status": "run",
            "fingerprint_set_id": fingerprints["id"],
            "files_scanned": scanned,
            "files_with_hits": files_with_hits,
            "skipped_secret_like_files": skipped,
        }
        passage_result = "fail" if files_with_hits else "pass"
    else:
        passage = {"status": "not_run", "reason": NOT_RUN_REASON}
        passage_result = "not_run"
    path_result = "fail" if path_fail else "pass"
    return {
        "report": REPORT_NAME,
        "format_version": 1,
        "policy": get_config_package(Settings()).raw["boundary"]["version"],
        "scans": [scan for scan, _ in scans],
        "passage_scan": passage,
        "path_scan_result": path_result,
        "passage_scan_result": passage_result,
        "ac_2_7": ac_2_7_summary([scan for scan, _ in scans], path_result, passage_result),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--repo", action="store_true")
    parser.add_argument("--working-tree", action="store_true", help="with --repo: add untracked files that are not ignored")
    parser.add_argument("--docker-context", action="append", metavar="DOCKERFILE:CONTEXT")
    parser.add_argument("--image-tar", action="append", metavar="PATH", help="a built image: `docker save` or `docker export` tar")
    parser.add_argument("--release-zip", action="append", metavar="PATH")
    parser.add_argument("--fingerprints", metavar="PATH", help="salted licensed-passage fingerprints from the private plane")
    parser.add_argument("--require-passage-scan", action="store_true", help="a passage scan that did not run fails")
    parser.add_argument("--require-ac-2-7", action="store_true", help="fail unless the run evidences AC-2-7 in full (exit gate)")
    parser.add_argument("--report", type=Path)
    parser.add_argument("--root", default=str(REPO_ROOT))
    args = parser.parse_args(argv)
    if not (args.repo or args.docker_context or args.image_tar or args.release_zip):
        args.repo = True
        args.docker_context = list(DEFAULT_CONTEXTS)
    try:
        report = run(args)
    except DockerIgnoreError as exc:
        print(f"boundary scan refused: {exc}", file=sys.stderr)
        return 1
    except (OSError, ValueError, subprocess.CalledProcessError, zipfile.BadZipFile, tarfile.TarError) as exc:
        print(f"boundary scan error: {exc}", file=sys.stderr)
        return 2
    text = json.dumps(report, indent=2)
    if args.report:
        args.report.write_text(text + "\n", encoding="utf-8", newline="\n")
    summary = {scan["target"] + (":" + scan.get("dockerfile", scan.get("path", "")) if scan["target"] != "repository" else ""):
               {"files": scan.get("files", scan.get("entries")), "private": len(scan["private_plane_paths"]),
                "licensed": len(scan["licensed_volume_paths"]), "secret_like": len(scan["secret_like_paths"])}
               for scan in report["scans"]}
    print(json.dumps({"path_scan_result": report["path_scan_result"], "passage_scan_result": report["passage_scan_result"],
                      "passage_scan": report["passage_scan"].get("reason", report["passage_scan"]["status"]),
                      "ac_2_7": report["ac_2_7"]["status"], "targets": summary}, indent=2))
    failed = report["path_scan_result"] == "fail" or report["passage_scan_result"] == "fail"
    if args.require_passage_scan and report["passage_scan_result"] == "not_run":
        print("boundary scan requirement not met: the licensed-passage scan did not run (--require-passage-scan)", file=sys.stderr)
        failed = True
    if args.require_ac_2_7 and report["ac_2_7"]["status"] != "met":
        print("boundary scan requirement not met: AC-2-7 is " + report["ac_2_7"]["status"] + " ("
              + "; ".join(report["ac_2_7"]["missing"]) + ")", file=sys.stderr)
        failed = True
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
