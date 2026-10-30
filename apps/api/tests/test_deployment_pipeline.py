"""Commit stamp, digest-pinned deploys and the deployment record (plan task 1.9, AC-1-7). Offline."""

import importlib.util
import json
from pathlib import Path
import sys

import pytest
from fastapi.testclient import TestClient

import app.main as main_module
from app.core.config import Settings
from app.main import app

REPO_ROOT = Path(__file__).resolve().parents[3]
COMMIT = "95336ed886c620d9a639ef0250daa99c1fcf1549"
OTHER_COMMIT = "27ff1da105ed3d6fa7836b5994e23c4fe3338cbf"
DIGEST = "sha256:e94cadd00b9d7c86f7852f71651422860631101c43b599d24bcd2e279b4775a5"
IMAGE = "us-central1-docker.pkg.dev/naylinnaung/qcai-repo/qcai-api"


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, REPO_ROOT / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


record = _load("deployment_record")
deploy = _load("deploy_by_digest")


# --- The commit stamp ---


def test_health_and_ready_report_the_build_commit(monkeypatch):
    monkeypatch.setattr(main_module.settings, "git_sha", COMMIT)
    client = TestClient(app)

    health = client.get("/health").json()
    ready = client.get("/ready").json()

    assert health["commit"] == COMMIT
    assert ready["commit"] == COMMIT
    assert ready["governance_enforced"] is bool(main_module.settings.enforce_corpus_governance)
    assert ready["corpus_version"] == main_module.get_corpus_registry(main_module.settings).corpus_version


def test_the_commit_comes_from_the_image_environment(monkeypatch):
    monkeypatch.setenv("GIT_SHA", COMMIT)
    assert Settings(environment="development").git_sha == COMMIT
    monkeypatch.delenv("GIT_SHA")
    assert Settings(environment="development").git_sha == "unknown"


@pytest.mark.parametrize("dockerfile", ["apps/api/Dockerfile", "apps/frontend/Dockerfile"])
def test_each_image_is_stamped_with_its_commit(dockerfile):
    text = (REPO_ROOT / dockerfile).read_text(encoding="utf-8")

    assert "ARG GIT_SHA=unknown" in text and "ENV GIT_SHA=$GIT_SHA" in text
    if dockerfile == "apps/api/Dockerfile":
        # Last, so a new commit rebuilds only that layer, not the dependency install.
        assert text.index("ARG GIT_SHA") > text.index("RUN pip install")


@pytest.mark.parametrize("config", ["infra/cloudbuild/api-image.yaml", "infra/cloudbuild/frontend-image.yaml"])
def test_cloud_build_tags_and_stamps_the_commit_and_never_latest(config):
    lines = [line for line in (REPO_ROOT / config).read_text(encoding="utf-8").splitlines() if not line.lstrip().startswith("#")]
    text = "\n".join(lines)

    assert ":latest" not in text and "_IMAGE_TAG" not in text
    assert ":${_GIT_SHA}" in text and "GIT_SHA=${_GIT_SHA}" in text
    assert "substitutionOption: MUST_MATCH" in text
    assert "^[0-9a-f]{40}$" in text, "the build must refuse a missing or short commit"
    assert not any(line.strip().startswith("_GIT_SHA:") for line in lines), "_GIT_SHA must have no default"


# --- The deployment record (fixtures shaped like real `gcloud --format=json` output) ---


def _service(latest: bool, routes=None) -> dict:
    return {
        "metadata": {"name": "qcai-api"},
        "status": {
            "url": "https://qcai-api-55f6mkphiq-uc.a.run.app",
            "traffic": routes or [{"latestRevision": latest, "percent": 100, "revisionName": "qcai-api-00037-abc"}],
        },
    }


def _revision(digest: str | None = f"{IMAGE}@{DIGEST}") -> dict:
    status = {"imageDigest": digest} if digest else {}
    return {"metadata": {"name": "qcai-api-00037-abc", "creationTimestamp": "2026-11-02T10:00:00Z"}, "status": status}


def _entry(service, revision, health):
    return record.service_entry("qcai-api", "https://api.qantumlearn.academy", service, {"qcai-api-00037-abc": revision}, health, COMMIT)


def test_a_pinned_digest_with_the_matching_commit_passes():
    entry = _entry(_service(latest=False), _revision(), {"status": "ok", "commit": COMMIT})

    assert entry["problems"] == []
    assert entry["traffic"] == [
        {"revision": "qcai-api-00037-abc", "percent": 100, "latest_revision": False, "tag": None, "image_digest": f"{IMAGE}@{DIGEST}", "created_utc": "2026-11-02T10:00:00Z"}
    ]


def test_todays_production_shape_fails_on_latest_routing_and_a_missing_commit():
    # As read on 2026-10-30: 100% on the latest revision, and /health without a commit.
    entry = _entry(_service(latest=True), _revision(), {"status": "ok", "app": "QC+AI Learning API", "environment": "production"})

    assert entry["problems"] == [
        "traffic follows the latest revision instead of a named one",
        f"/health reports commit None, expected {COMMIT}",
    ]


@pytest.mark.parametrize(
    ("revision", "health", "problem"),
    [
        (_revision(None), {"commit": COMMIT}, "no image digest recorded for qcai-api-00037-abc"),
        (_revision(f"{IMAGE}:latest"), {"commit": COMMIT}, "no image digest recorded for qcai-api-00037-abc"),
        (_revision(), {"commit": OTHER_COMMIT}, f"/health reports commit '{OTHER_COMMIT}', expected {COMMIT}"),
        (_revision(), {"error": "URLError: timed out"}, "/health could not be read (URLError: timed out)"),
    ],
    ids=["no-digest", "tag-not-digest", "other-commit", "health-unreachable"],
)
def test_each_failed_check_is_named(revision, health, problem):
    assert _entry(_service(latest=False), revision, health)["problems"] == [problem]


def test_a_tagged_revision_without_traffic_does_not_count_as_serving():
    routes = [
        {"latestRevision": False, "percent": 100, "revisionName": "qcai-api-00037-abc"},
        {"latestRevision": False, "percent": 0, "revisionName": "qcai-api-00038-def", "tag": "c-27ff1da105ed"},
    ]

    assert _entry(_service(latest=False, routes=routes), _revision(), {"commit": COMMIT})["problems"] == []


def test_the_record_is_written_and_the_exit_code_follows_the_checks(monkeypatch, tmp_path):
    monkeypatch.setattr(record, "describe_service", lambda name, project, region: _service(latest=False))
    monkeypatch.setattr(record, "describe_revision", lambda name, project, region: _revision())
    monkeypatch.setattr(record, "fetch_health", lambda url: {"status": "ok", "commit": COMMIT})

    assert record.main(["--commit", COMMIT, "--service", "qcai-api=https://api.qantumlearn.academy", "--write", str(tmp_path)]) == 0
    (written,) = tmp_path.glob("*.json")
    saved = json.loads(written.read_text(encoding="utf-8"))
    assert saved["ok"] is True and saved["commit"] == COMMIT
    assert saved["services"][0]["traffic"][0]["image_digest"] == f"{IMAGE}@{DIGEST}"

    monkeypatch.setattr(record, "fetch_health", lambda url: {"status": "ok"})
    assert record.main(["--commit", COMMIT, "--service", "qcai-api=https://api.qantumlearn.academy"]) == 1


def test_the_record_needs_a_full_commit():
    with pytest.raises(SystemExit):
        record.main(["--commit", COMMIT[:12]])


# --- Deploying by digest ---


def test_the_deploy_uses_the_digest_without_traffic_and_pins_a_named_revision():
    command = deploy.deploy_command("qcai-api", IMAGE, DIGEST, COMMIT, "naylinnaung", "us-central1")
    pin = deploy.pin_command("qcai-api", "qcai-api-00037-abc", "naylinnaung", "us-central1")

    assert command[:3] == ["run", "deploy", "qcai-api"]
    assert f"{IMAGE}@{DIGEST}" in command and "--no-traffic" in command
    assert command[command.index("--tag") + 1] == "c-95336ed886c6"
    assert pin[pin.index("--to-revisions") + 1] == "qcai-api-00037-abc=100"
    assert "LATEST" not in " ".join(pin)


def test_without_execute_nothing_is_changed(monkeypatch, capsys):
    def no_cloud(arguments):
        raise AssertionError(f"gcloud must not run: {arguments}")

    monkeypatch.setattr(deploy, "_gcloud", no_cloud)

    assert deploy.main(["--service", "qcai-api", "--commit", COMMIT, "--digest", DIGEST]) == 0
    assert "Plan only. Nothing was changed" in capsys.readouterr().out


@pytest.mark.parametrize(
    "arguments",
    [
        ["--service", "qcai-api", "--commit", COMMIT, "--digest", "latest"],
        ["--service", "qcai-api", "--commit", COMMIT, "--digest", "sha256:short"],
        ["--service", "qcai-api", "--commit", COMMIT[:12], "--digest", DIGEST],
        ["--service", "other-service", "--commit", COMMIT, "--digest", DIGEST],
    ],
    ids=["tag", "short-digest", "short-commit", "unknown-service"],
)
def test_a_tag_short_value_or_unknown_service_is_refused(arguments):
    with pytest.raises(SystemExit):
        deploy.main(arguments)


def _execute(monkeypatch, reported_commit: str) -> tuple[int, list[list[str]]]:
    calls: list[list[str]] = []

    def fake_gcloud(arguments):
        calls.append(arguments)
        if arguments[:3] == ["run", "services", "describe"]:
            return json.dumps(
                {"status": {"traffic": [
                    {"revisionName": "qcai-api-00036-lzg", "percent": 100, "latestRevision": True},
                    {"revisionName": "qcai-api-00037-abc", "percent": 0, "tag": "c-95336ed886c6", "url": "https://c-95336ed886c6---qcai-api-55f6mkphiq-uc.a.run.app"},
                ]}}
            )
        return ""

    monkeypatch.setattr(deploy, "_gcloud", fake_gcloud)
    monkeypatch.setattr(deploy, "fetch_health", lambda url: {"status": "ok", "commit": reported_commit})
    code = deploy.main(["--service", "qcai-api", "--commit", COMMIT, "--digest", DIGEST, "--execute"])
    return code, calls


def test_execute_moves_traffic_only_after_the_new_revision_reports_the_commit(monkeypatch):
    code, calls = _execute(monkeypatch, COMMIT)

    assert code == 0
    assert [call[:3] for call in calls] == [["run", "deploy", "qcai-api"], ["run", "services", "describe"], ["run", "services", "update-traffic"]]
    assert "qcai-api-00037-abc=100" in calls[-1]


def test_execute_stops_with_no_traffic_moved_when_the_commit_differs(monkeypatch, capsys):
    code, calls = _execute(monkeypatch, OTHER_COMMIT)

    assert code == 1
    assert all(call[:3] != ["run", "services", "update-traffic"] for call in calls)
    assert "Stopped before any traffic moved" in capsys.readouterr().err
