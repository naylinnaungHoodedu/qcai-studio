from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys

from app.services.text_utils import truncate_display_excerpt


REPO_ROOT = Path(__file__).resolve().parents[3]
API_ROOT = REPO_ROOT / "apps" / "api"


def _read_text(relative_path: str) -> str:
    return (REPO_ROOT / relative_path).read_text(encoding="utf-8")


def _run_worker_entrypoint(module_name: str) -> tuple[bool, str]:
    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"
    try:
        completed = subprocess.run(
            [sys.executable, "-m", module_name],
            cwd=API_ROOT,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            env=env,
            timeout=6,
        )
        return False, completed.stdout
    except subprocess.TimeoutExpired as exc:
        return True, exc.stdout or ""


def test_worker_entrypoints_start_cleanly():
    expected_output = {
        "app.workers.ingestion": "ingestion worker starting",
        "app.workers.rag": "rag worker starting",
        "app.workers.analytics": "analytics worker starting",
    }

    for module_name, expected_message in expected_output.items():
        timed_out, output = _run_worker_entrypoint(module_name)
        assert "Traceback" not in output
        assert timed_out or expected_message in output


def test_k8s_manifests_use_artifact_registry_images():
    expected_api_image = "us-central1-docker.pkg.dev/naylinnaung/qcai-repo/qcai-api:latest"
    expected_frontend_image = "us-central1-docker.pkg.dev/naylinnaung/qcai-repo/qcai-frontend:latest"

    api_manifest = _read_text("infra/k8s/api-deployment.yaml")
    frontend_manifest = _read_text("infra/k8s/frontend-deployment.yaml")
    workers_manifest = _read_text("infra/k8s/workers.yaml")

    assert "PROJECT_ID" not in api_manifest
    assert "PROJECT_ID" not in frontend_manifest
    assert "PROJECT_ID" not in workers_manifest
    assert expected_api_image in api_manifest
    assert expected_frontend_image in frontend_manifest
    assert expected_api_image in workers_manifest


def test_k8s_database_url_moves_to_secret_example():
    configmap = _read_text("infra/k8s/configmap.yaml")
    secret_example = _read_text("infra/k8s/secret.example.yaml")

    assert "DATABASE_URL" not in configmap
    assert "change-me" not in configmap
    assert 'DATABASE_URL: "postgresql+psycopg://qcai:replace-me@cloudsql/qcai_prod"' in secret_example


def test_api_cloud_run_example_disables_demo_auth_and_documents_secret_injection():
    api_env_example = _read_text("infra/cloudrun/api-production.env.example.yaml")

    assert 'ENVIRONMENT: "production"' in api_env_example
    assert 'ENABLE_DEMO_AUTH: "false"' in api_env_example
    assert "OPENAI_API_KEY" in api_env_example
    assert "PINECONE_API_KEY" in api_env_example


def test_display_excerpt_cleanup_removes_inline_reference_artifacts():
    raw_text = (
        "routing bottlenecks persist.1 Hybrid quantum-classical workflows can narrow the executable search space "
        "while keeping classical control in the loop. Edited by Shaukat Ali, Francisco Chicano, and Alberto Moraglio."
    )

    excerpt = truncate_display_excerpt(raw_text, 120)

    assert ".1" not in excerpt
    assert excerpt.startswith("Hybrid quantum-classical workflows")
    assert "Edited by Shaukat Ali" not in excerpt


def test_display_excerpt_cleanup_repairs_common_mojibake():
    raw_text = (
        "Quantum phenomena\u00e2\u0080\u0094such as superposition and "
        "entanglement\u00e2\u0080\u0094can support richer representations."
    )

    excerpt = truncate_display_excerpt(raw_text, 160)

    assert "\u00e2\u0080" not in excerpt
    assert "Quantum phenomena—such as superposition and entanglement—can support richer representations." == excerpt


def test_curated_transcript_copy_is_public_safe():
    transcripts_source = _read_text("apps/api/app/services/transcripts.py")

    assert "local development" not in transcripts_source
    assert "Full transcript alignment can replace this field later." not in transcripts_source
    assert "curated_chapter_summary" in transcripts_source
