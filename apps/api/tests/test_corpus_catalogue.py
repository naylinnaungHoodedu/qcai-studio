"""The served catalogue is the manifest (plan task 1.8, AC-1-5; Decision P1-D-07, D-31).

A governed build serves exactly the approved assets, possibly none: no file, excerpt, search chunk, chapter or
listing from an unapproved asset. A missing or invalid manifest still stops start-up (test_database_schema.py),
and every approved item needs a reviewed license-register row.
"""

from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
from uuid import uuid4

import httpx
import pytest

from app.core.config import SOURCE_DOCUMENT_NAMES, SOURCE_VIDEO_NAMES, Settings
from app.core.guest_tokens import GUEST_TOKEN_COOKIE, issue_guest_token
from app.core.source_assets import source_asset_id
from app.services.content_assembler import CourseStore

API_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = API_ROOT.parents[1]
APPROVED_DOCUMENT = "Module2_Routing, Graph Shrinking, and Logistics under Hardware Constraints.docx"
REGISTER_HEADER = "item_id,version,source,license,permitted_use,public_service,library_confirmation,asset_filenames,reviewed_by,reviewed_at,notes\n"
SECRET = "corpus-catalogue-test-secret-0123456789abcdef"


def _manifest(tmp_path: Path, filenames: list[str], *, public_service: bool = True) -> Path:
    items = [
        {
            "id": "routing-brief",
            "version": "v1",
            "source": "Course author",
            "license": "CC-BY-4.0",
            "permitted_use": "public course material",
            "public_service": public_service,
            "asset_filenames": filenames,
        }
    ] if filenames else []
    path = tmp_path / "public" / "manifest.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"schema_version": "1.0", "items": items}), encoding="utf-8")
    return path


def _governed(manifest: Path) -> Settings:
    return Settings(environment="production", enforce_corpus_governance=True, corpus_manifest_path=str(manifest))


@pytest.fixture(scope="module")
def ungoverned() -> CourseStore:
    return CourseStore(Settings())


def test_an_empty_manifest_serves_nothing_from_any_source_asset(tmp_path, ungoverned):
    store = CourseStore(_governed(_manifest(tmp_path, [])))

    assert ungoverned.overview.source_assets and any(lesson.sections for lesson in ungoverned.lessons.values())
    assert store.overview.source_assets == []
    assert store.lessons.keys() == ungoverned.lessons.keys()
    for slug, lesson in store.lessons.items():
        assert (lesson.sections, lesson.chapters, lesson.source_assets, lesson.video_asset) == ([], [], [], None), slug
        # The platform's own lesson content stays: summaries, key ideas, flashcards and quizzes.
        assert lesson.summary == ungoverned.lessons[slug].summary
        assert lesson.quiz_questions == ungoverned.lessons[slug].quiz_questions
    assert store.chunks, "authored lesson text stays searchable"
    assert {(chunk.source_kind, chunk.source_filename) for chunk in store.chunks} == {("lesson", None)}


def test_only_the_approved_document_feeds_the_course(tmp_path):
    store = CourseStore(_governed(_manifest(tmp_path, [APPROVED_DOCUMENT])))

    assert [asset.filename for asset in store.overview.source_assets] == [APPROVED_DOCUMENT]
    sections = [section for lesson in store.lessons.values() for section in lesson.sections]
    assert sections, "the approved document still provides lesson sections"
    documents = {chunk.source_filename for chunk in store.chunks if chunk.source_kind == "document"}
    assert documents == {APPROVED_DOCUMENT}
    assert not any(chunk.source_kind == "video" for chunk in store.chunks)
    assert not any(lesson.chapters or lesson.video_asset for lesson in store.lessons.values())
    assert {asset.filename for lesson in store.lessons.values() for asset in lesson.source_assets} <= {APPROVED_DOCUMENT}


def test_a_listed_item_not_approved_for_public_service_feeds_nothing(tmp_path):
    store = CourseStore(_governed(_manifest(tmp_path, [APPROVED_DOCUMENT], public_service=False)))

    assert store.overview.source_assets == []
    assert {chunk.source_kind for chunk in store.chunks} == {"lesson"}


# --- scripts/validate_corpus.py --check-public-assets (AC-1-5; CI and release packaging) ---


def _validate(manifest: Path, register_rows: list[str]) -> subprocess.CompletedProcess:
    register = manifest.parent.parent / "license-register.csv"
    register.write_text(REGISTER_HEADER + "".join(f"{row}\n" for row in register_rows), encoding="utf-8")
    env = {**os.environ, "CORPUS_MANIFEST_PATH": str(manifest)}
    return subprocess.run(
        [sys.executable, str(REPO_ROOT / "scripts" / "validate_corpus.py"), "--check-public-assets", "--register", str(register)],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )


REVIEWED = f'routing-brief,v1,Course author,CC-BY-4.0,public course material,true,library-2026-11,"{APPROVED_DOCUMENT}",Content Owner,2026-11-01,'


def test_an_empty_manifest_passes_the_public_asset_check(tmp_path):
    completed = _validate(_manifest(tmp_path, []), [])

    assert completed.returncode == 0, completed.stderr
    assert f"0 asset(s); withheld: {len(SOURCE_DOCUMENT_NAMES) + len(SOURCE_VIDEO_NAMES)}" in completed.stdout


def test_an_approved_asset_with_a_reviewed_register_row_passes(tmp_path):
    completed = _validate(_manifest(tmp_path, [APPROVED_DOCUMENT]), [REVIEWED])

    assert completed.returncode == 0, completed.stderr
    assert "Approved for public service: 1 asset(s)" in completed.stdout


@pytest.mark.parametrize(
    ("filenames", "rows", "problem"),
    [
        ([APPROVED_DOCUMENT], [], "needs exactly one license-register row, found 0"),
        ([APPROVED_DOCUMENT], [REVIEWED.replace("Content Owner,2026-11-01", ",")], "is not reviewed (reviewed_by, reviewed_at empty)"),
        ([APPROVED_DOCUMENT], [REVIEWED.replace("library-2026-11", "")], "is not reviewed (library_confirmation empty)"),
        ([APPROVED_DOCUMENT], [REVIEWED.replace(",true,", ",false,")], "does not approve public service"),
        ([APPROVED_DOCUMENT], [REVIEWED.replace("CC-BY-4.0", "CC-BY-NC-4.0")], "register license differs from the manifest"),
        ([APPROVED_DOCUMENT, "other.docx"], [REVIEWED], "other.docx is approved in the manifest but not in its register row"),
        (["other.docx"], [REVIEWED.replace(APPROVED_DOCUMENT, "other.docx")], "other.docx is not a source asset this application serves"),
    ],
)
def test_an_approved_asset_without_a_complete_review_fails_the_check(tmp_path, filenames, rows, problem):
    completed = _validate(_manifest(tmp_path, filenames), rows)

    assert completed.returncode != 0
    assert problem in completed.stderr


def test_release_packaging_still_refuses_unapproved_curated_assets():
    # The served catalogue may be empty; a release bundle that ships the curated media may not hold one unapproved.
    spec = importlib.util.spec_from_file_location("package_release", REPO_ROOT / "tools" / "package_release.py")
    package_release = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(package_release)

    assert len(package_release._unapproved_curated_assets()) == len(SOURCE_DOCUMENT_NAMES) + len(SOURCE_VIDEO_NAMES)
    with pytest.raises(RuntimeError, match="not approved for public release"):
        package_release._assert_public_release_assets_are_approved()


# --- A real production-mode API process with the empty manifest (D-31): it starts and serves no asset ---


def _free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def _stop(process: subprocess.Popen) -> None:
    if sys.platform == "win32":
        subprocess.run(["taskkill", "/T", "/F", "/PID", str(process.pid)], capture_output=True)
    else:
        process.terminate()
    try:
        process.wait(timeout=20)
    except subprocess.TimeoutExpired:
        process.kill()


def test_a_governed_production_process_starts_and_serves_no_asset(fresh_database_url, tmp_path):
    manifest = _manifest(tmp_path, [])
    port = _free_port()
    env = {
        **os.environ,
        "ENVIRONMENT": "production",
        "DATABASE_URL": fresh_database_url,
        "CORPUS_MANIFEST_PATH": str(manifest),
        "GUEST_TOKEN_SECRET": SECRET,
        "ALLOWED_ORIGINS": "https://qantumlearn.academy",
        "PYTHONUNBUFFERED": "1",
    }
    for name in ("TEST_DATABASE_URL", "ENFORCE_CORPUS_GOVERNANCE", "ENABLE_DEMO_AUTH"):
        env.pop(name, None)
    output = tmp_path / "api.log"
    guest = issue_guest_token(SECRET, f"guest-{uuid4()}", int(time.time()))
    document_id = source_asset_id(SOURCE_DOCUMENT_NAMES[0], "document")
    video_id = source_asset_id(SOURCE_VIDEO_NAMES[0], "video")
    with output.open("w", encoding="utf-8") as stream:
        process = subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", str(port), "--log-level", "warning"],
            cwd=API_ROOT,
            env=env,
            stdout=stream,
            stderr=subprocess.STDOUT,
        )
        base = f"http://127.0.0.1:{port}"
        try:
            deadline = time.monotonic() + 120
            while True:
                try:
                    if httpx.get(f"{base}/health", timeout=2).status_code == 200:
                        break
                except httpx.HTTPError:
                    pass
                if process.poll() is not None or time.monotonic() > deadline:
                    raise RuntimeError("The governed API process did not start:\n" + output.read_text(encoding="utf-8"))
                time.sleep(0.3)
            ready = httpx.get(f"{base}/ready", timeout=30)
            course = httpx.get(f"{base}/content/course", timeout=30)
            lesson_slug = course.json()["modules"][0]["lesson_slugs"][0]
            lesson = httpx.get(f"{base}/content/lessons/{lesson_slug}", timeout=30)
            assets = [
                httpx.get(f"{base}/source-assets/by-id/{asset_id}", cookies={GUEST_TOKEN_COOKIE: guest}, timeout=30)
                for asset_id in (document_id, video_id)
            ]
        finally:
            _stop(process)

    assert ready.status_code == 200, ready.text
    assert (ready.json()["governance_enforced"], ready.json()["source_assets"]) == (True, 0)
    assert course.status_code == 200 and course.json()["source_assets"] == []
    detail = lesson.json()
    assert lesson.status_code == 200
    assert (detail["sections"], detail["chapters"], detail["source_assets"], detail["video_asset"]) == ([], [], [], None)
    assert [response.status_code for response in assets] == [404, 404]
    assert all(response.json()["detail"] == "Source asset is not approved for public service." for response in assets)
    startup = [json.loads(line) for line in output.read_text(encoding="utf-8").splitlines() if '"event": "startup"' in line]
    assert len(startup) == 1 and startup[0]["environment"] == "production" and startup[0]["governance_enforced"] is True
