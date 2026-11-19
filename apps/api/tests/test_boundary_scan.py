"""Boundary-scan units (plan Phase 2 task 2.8; spec 3.13; scripts/scan_boundary.py)."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import SimpleNamespace
import zipfile

import pytest

from app.core.data_planes import glob_match, is_private_plane_path, is_secret_like_name, path_suffixes

REPO_ROOT = Path(__file__).resolve().parents[3]
spec = importlib.util.spec_from_file_location("phase2_scan_boundary_units", REPO_ROOT / "scripts" / "scan_boundary.py")
scanner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(scanner)


def test_glob_semantics():
    assert glob_match("corpus/private/a/b.txt", "corpus/private/**")
    assert glob_match("x/y/z.private.json", "**/*.private.json") and glob_match("z.private.json", "**/*.private.json")
    assert glob_match("lqs/ratings/r.private.jsonl", "lqs/ratings/*.private.jsonl")
    assert not glob_match("lqs/ratings/deep/r.private.jsonl", "lqs/ratings/*.private.jsonl")
    assert glob_match("dist/release/a.zip", "dist/") and not glob_match("distx/a", "dist/")
    assert not glob_match("update_data/a.docx", "*.docx")  # Docker: "*" stays within one segment


def test_private_plane_paths_are_found_through_every_suffix(tmp_path):
    assert path_suffixes(Path("/app/corpus/private/x"))[-3:] == ["corpus/private/x", "private/x", "x"]
    assert is_private_plane_path("/app/corpus/private/x", Path("/"))
    assert is_private_plane_path(tmp_path / "elsewhere" / "lqs" / "private" / "items.jsonl", tmp_path)
    assert is_private_plane_path(REPO_ROOT / "evaluation" / "reports" / "run.private.json", REPO_ROOT)
    assert not is_private_plane_path(REPO_ROOT / "corpus" / "private" / "README.md", REPO_ROOT)
    assert is_private_plane_path(Path("/srv/copy/corpus/private/README.md"), Path("/srv/other"))  # the exception names one path


def test_dockerignore_is_read_per_context_with_docker_semantics(tmp_path):
    (tmp_path / "update_data").mkdir()
    (tmp_path / "update_data" / "a.docx").write_text("x")
    (tmp_path / "root.docx").write_text("x")
    (tmp_path / "node_modules" / "pkg").mkdir(parents=True)
    (tmp_path / "node_modules" / "pkg" / "index.js").write_text("x")
    (tmp_path / "keep.py").write_text("x")
    (tmp_path / ".dockerignore").write_text("# comment\n/*.docx\n**/node_modules\n", encoding="utf-8")
    files = scanner.walk_context(tmp_path, scanner.dockerignore_patterns(tmp_path / ".dockerignore"))
    assert files == [".dockerignore", "keep.py", "update_data/a.docx"]
    (tmp_path / ".dockerignore").write_text("*.docx\n!root.docx\n", encoding="utf-8")
    with pytest.raises(scanner.DockerIgnoreError):
        scanner.dockerignore_patterns(tmp_path / ".dockerignore")
    # The repository's own ignore files never re-include anything.
    for ignore in (REPO_ROOT / ".dockerignore", REPO_ROOT / "apps" / "frontend" / ".dockerignore"):
        assert scanner.dockerignore_patterns(ignore)


def test_copy_sources_skip_other_stages_and_expand_globs(tmp_path):
    dockerfile = tmp_path / "Dockerfile"
    dockerfile.write_text(
        "FROM node AS deps\nCOPY package*.json ./\nCOPY --from=deps /app/node_modules ./node_modules\nCOPY --chown=a:b ./src ./src\nADD app app\n",
        encoding="utf-8",
    )
    sources = scanner.dockerfile_sources(dockerfile)
    assert sources == ["package*.json", "src", "app"]
    files = ["package.json", "package-lock.json", "src/a.ts", "app/b.py", "README.md"]
    assert scanner.image_source_files(files, sources) == ["package.json", "package-lock.json", "src/a.ts", "app/b.py"]
    assert scanner.dockerfile_sources(REPO_ROOT / "apps" / "api" / "Dockerfile") == ["apps/api/requirements.txt", "apps/api/app", "corpus/public", "transcripts"]


def test_secret_like_names_are_matched_by_name_and_never_opened(tmp_path):
    for name in (".env", "apps/x/.env.local", "infra/cloudrun/api-production.env.yaml", "deep/dir/.env.production", "service.env"):
        assert is_secret_like_name(name), name
    for name in ("apps/api/app/core/config.py", "next-env.d.ts", "infra/cloudrun/api-production.env.example.yaml"):
        assert not is_secret_like_name(name), name

    def explode():
        raise AssertionError("a secret-like file was opened")

    fingerprints = {"salt": b"s" * 32, "n": 12, "set": frozenset(), "id": "t"}
    hits, scanned, skipped = scanner.passage_hits([(".env", explode), ("ok.md", lambda: b"hello")], fingerprints, scanner.policy())
    assert (hits, scanned, skipped) == ([], 1, 1)


def test_release_zip_namelists_and_the_not_run_wording(tmp_path):
    bundle = tmp_path / "bundle.zip"
    with zipfile.ZipFile(bundle, "w") as archive:
        archive.writestr("apps/api/app/main.py", "x")
        archive.writestr("volumes/book.pdf", "x")
    report = scanner.run(SimpleNamespace(root=str(REPO_ROOT), repo=False, working_tree=False, docker_context=[], release_zip=[str(bundle)], fingerprints=None))
    (scan,) = report["scans"]
    assert scan["entries"] == 2 and scan["licensed_volume_paths"] == ["volumes/book.pdf"]
    assert report["passage_scan"] == {"status": "not_run", "reason": scanner.NOT_RUN_REASON}
    assert "passed" not in scanner.NOT_RUN_REASON and report["passage_scan_result"] == "not_run"
    assert report["path_scan_result"] == "fail"


def _tar_bytes(files: dict[str, bytes]) -> bytes:
    import io
    import tarfile

    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w") as archive:
        for name, data in files.items():
            info = tarfile.TarInfo(name)
            info.size = len(data)
            archive.addfile(info, io.BytesIO(data))
    return buffer.getvalue()


def _docker_save(path: Path, layers: list[dict[str, bytes]]) -> Path:
    """A minimal `docker save` archive: manifest.json naming each layer tar, each layer a filesystem tar."""
    import json
    import tarfile
    import io

    files = {f"blobs/sha256/{index:064x}": _tar_bytes(layer) for index, layer in enumerate(layers)}
    manifest = json.dumps([{"Config": "config.json", "RepoTags": ["qcai-api:test"], "Layers": list(files)}]).encode()
    with tarfile.open(path, "w") as archive:
        for name, data in {"manifest.json": manifest, "config.json": b"{}", **files}.items():
            info = tarfile.TarInfo(name)
            info.size = len(data)
            archive.addfile(info, io.BytesIO(data))
    return path


def _args(**extra) -> SimpleNamespace:
    base = dict(root=str(REPO_ROOT), repo=False, working_tree=False, docker_context=[], image_tar=[], release_zip=[], fingerprints=None)
    return SimpleNamespace(**{**base, **extra})


def test_a_built_image_is_scanned_layer_by_layer_including_files_a_later_layer_deletes(tmp_path):
    # Task 2.8 "licensed-passage scans of images and releases": the image itself, not only its build context.
    image = _docker_save(tmp_path / "image.tar", [
        {"app/app/main.py": b"x", "app/corpus/private/volume.txt": b"private", "app/.env": b"NAME=value"},
        {"app/docs/book.pdf": b"%PDF-1.4", "app/corpus/private/.wh.volume.txt": b""},  # deleted later, still shipped
    ])
    report = scanner.run(_args(image_tar=[str(image)]))
    (scan,) = report["scans"]
    assert (scan["target"], scan["format"], scan["layers"]) == ("image", "docker-save", 2)
    assert scan["private_plane_paths"] == ["app/corpus/private/volume.txt"]
    assert scan["licensed_volume_paths"] == ["app/docs/book.pdf"] and scan["secret_like_paths"] == ["app/.env"]
    assert report["path_scan_result"] == "fail" and report["ac_2_7"]["status"] == "fail"

    flat = tmp_path / "export.tar"
    flat.write_bytes(_tar_bytes({"app/app/main.py": b"x", "usr/lib/python3/site.py": b"y"}))
    clean = scanner.run(_args(image_tar=[str(flat)]))
    assert clean["scans"][0]["format"] == "filesystem-tar" and clean["path_scan_result"] == "pass"


def test_the_ac_2_7_block_is_met_only_with_both_halves_over_an_image_and_a_release(tmp_path):
    passage = " ".join(f"licensedword{index}" for index in range(30))
    salt = bytes(range(32))
    fingerprints = tmp_path / "fingerprints.json"
    import json

    fingerprints.write_text(json.dumps({
        "format": scanner.FINGERPRINT_FORMAT, "fingerprint_set_id": "synthetic", "hash": "hmac-sha256-trunc32",
        "salt_hex": salt.hex(), "shingle_words": 12, "fingerprints": sorted(scanner.fingerprint_shingles(passage, salt, 12))}), encoding="utf-8")
    image = tmp_path / "image.tar"
    image.write_bytes(_tar_bytes({"app/app/main.py": b"print('clean')"}))
    bundle = tmp_path / "bundle.zip"
    with zipfile.ZipFile(bundle, "w") as archive:
        archive.writestr("README.md", "A clean readme.")

    partial = scanner.run(_args(release_zip=[str(bundle)]))
    assert partial["ac_2_7"]["status"] == "partial" and partial["passage_scan_result"] == "not_run"
    assert any("D-14" in reason for reason in partial["ac_2_7"]["missing"])
    assert any("--image-tar" in reason for reason in partial["ac_2_7"]["missing"])
    met = scanner.run(_args(image_tar=[str(image)], release_zip=[str(bundle)], fingerprints=str(fingerprints)))
    assert (met["ac_2_7"]["status"], met["ac_2_7"]["missing"]) == ("met", [])
    assert met["ac_2_7"]["targets"] == {"image": 1, "release-zip": 1}

    planted = tmp_path / "planted.tar"
    planted.write_bytes(_tar_bytes({"app/docs/notes.md": f"Intro. {passage} Outro.".encode()}))
    caught = scanner.run(_args(image_tar=[str(planted)], release_zip=[str(bundle)], fingerprints=str(fingerprints)))
    assert caught["passage_scan_result"] == "fail" and caught["ac_2_7"]["status"] == "fail"
    assert [hit["path"] for hit in caught["passage_scan"]["files_with_hits"]] == ["planted.tar:app/docs/notes.md"]
    assert "licensedword" not in json.dumps(caught)


def test_require_flags_turn_a_missing_half_into_a_failure(tmp_path, capsys):
    bundle = tmp_path / "bundle.zip"
    with zipfile.ZipFile(bundle, "w") as archive:
        archive.writestr("README.md", "A clean readme.")
    assert scanner.main(["--release-zip", str(bundle)]) == 0  # nothing found; the report says not_run and partial
    assert scanner.main(["--release-zip", str(bundle), "--require-passage-scan"]) == 1
    assert scanner.main(["--release-zip", str(bundle), "--require-ac-2-7"]) == 1
    assert "AC-2-7 is partial" in capsys.readouterr().err


def _packager():
    spec_ = importlib.util.spec_from_file_location("phase2_package_release", REPO_ROOT / "tools" / "package_release.py")
    module = importlib.util.module_from_spec(spec_)
    spec_.loader.exec_module(module)
    return module


def test_the_release_packager_never_packages_secret_like_private_or_licensed_paths(tmp_path, monkeypatch):
    packager = _packager()
    boundary = packager._boundary()
    for rel in ("apps/frontend/.env.local", "infra/cloudrun/api-production.env.yaml", "apps/frontend/.env.example", ".env",
                "corpus/private/volume.txt", "evaluation/reports/run.private.json", "docs/book.pdf"):
        assert packager._excluded(Path(rel), boundary), rel
    for rel in ("apps/api/app/main.py", "infra/cloudrun/api-production.env.example.yaml", "corpus/private/README.md", "docs/README.md"):
        assert not packager._excluded(Path(rel), boundary), rel

    tree = tmp_path / "repo"
    for rel in ("apps/api/app/main.py", "apps/frontend/.env.local", "infra/cloudrun/web.env.yaml", "infra/cloudrun/deployment.md"):
        (tree / rel).parent.mkdir(parents=True, exist_ok=True)
        (tree / rel).write_text("x", encoding="utf-8")
    monkeypatch.setattr(packager, "REPO_ROOT", tree)
    packaged = sorted(path.relative_to(tree).as_posix() for root in ("apps", "infra") for path in packager._iter_files(tree / root))
    assert packaged == ["apps/api/app/main.py", "infra/cloudrun/deployment.md"]


def test_the_release_packager_removes_bundles_that_fail_the_boundary_scan(tmp_path):
    packager = _packager()
    bad = tmp_path / "bad.zip"
    with zipfile.ZipFile(bad, "w") as archive:
        archive.writestr("apps/frontend/.env.local", "NAME=value")
    with pytest.raises(RuntimeError, match="failed the boundary scan"):
        packager._scan_bundles([bad], tmp_path / "scan.json")
    assert not bad.exists()
    good = tmp_path / "good.zip"
    with zipfile.ZipFile(good, "w") as archive:
        archive.writestr("README.md", "clean")
    packager._scan_bundles([good], tmp_path / "scan.json")
    assert good.exists()
