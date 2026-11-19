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
