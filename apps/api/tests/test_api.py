from pathlib import Path
from uuid import uuid4

from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import app


client = TestClient(app)
DEMO_HEADERS = {"x-demo-user": "demo-test-user", "x-demo-role": "learner"}
RAW_DOCUMENT_TITLES = {
    "Quantum Computing AI Research Synthesis 2026.docx",
    "Analyzing Quantum Computing and AI Paper 2025.docx",
    "Quantum Computing and Artificial Intelligence Industry Use Cases.docx",
}
DISPLAY_DOCUMENT_TITLES = {
    "Ali, Chicano, and Moraglio (Eds.), QC+AI 2025 Proceedings",
    "Ali, Chicano, and Moraglio (Eds.), QC+AI 2026 Proceedings",
    "Raj et al. (Eds.), Quantum Computing and Artificial Intelligence: The Industry Use Cases",
}
RAW_VIDEO_TITLES = {
    "Quantum Computing and Artificial Intelligence 2025.mp4",
    "Quantum Computing and Artificial Intelligence 2026.mp4",
}
DISPLAY_VIDEO_TITLES = {
    "Quantum Computing and Artificial Intelligence 2025",
    "Quantum Computing and Artificial Intelligence 2026",
}


def test_healthcheck():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-frame-options"] == "DENY"


def test_readiness_check():
    response = client.get("/ready")
    assert response.status_code == 200
    assert response.json()["status"] == "ready"
    assert response.json()["lessons"] >= 1


def test_course_overview():
    response = client.get("/content/course")
    assert response.status_code == 200
    data = response.json()
    assert data["id"] == "qcai-hardware-aware-course"
    assert len(data["modules"]) == 6
    source_filenames = [asset["filename"] for asset in data["source_assets"]]
    assert "Quantum Computing and Artificial Intelligence Industry Use Cases.docx" in source_filenames
    assert "Vital_Concepts.docx" not in source_filenames
    document_titles = {asset["title"] for asset in data["source_assets"] if asset["kind"] == "document"}
    assert DISPLAY_DOCUMENT_TITLES <= document_titles
    assert not (document_titles & RAW_DOCUMENT_TITLES)
    document_urls = [asset["download_url"] for asset in data["source_assets"] if asset["kind"] == "document"]
    assert all(url.startswith("/source-assets/by-id/") for url in document_urls)
    assert not any(any(raw_title in url for raw_title in RAW_DOCUMENT_TITLES) for url in document_urls)


def test_lesson_lookup():
    response = client.get("/content/lessons/ai4qc-routing-and-optimization")
    assert response.status_code == 200
    data = response.json()
    assert data["module_slug"] == "ai-for-quantum-hardware"
    assert data["sections"]
    assert data["video_asset"]["filename"] == "Quantum Computing and Artificial Intelligence 2025.mp4"
    assert data["video_asset"]["title"] == "Quantum Computing and Artificial Intelligence 2025"
    assert data["video_asset"]["download_url"] == "/source-assets/by-id/quantum-computing-and-artificial-intelligence-2025"


def test_industry_use_cases_lesson_lookup():
    response = client.get("/content/lessons/industry-use-cases")
    assert response.status_code == 200
    data = response.json()
    assert data["module_slug"] == "industry-use-cases"
    assert data["sections"]
    assert data["video_asset"] is None
    source_filenames = [asset["filename"] for asset in data["source_assets"]]
    assert "Quantum Computing and Artificial Intelligence Industry Use Cases.docx" in source_filenames
    source_titles = {section["source_title"] for section in data["sections"]}
    assert "Raj et al. (Eds.), Quantum Computing and Artificial Intelligence: The Industry Use Cases" in source_titles
    assert not (source_titles & RAW_DOCUMENT_TITLES)
    asset_titles = {asset["title"] for asset in data["source_assets"] if asset["kind"] == "document"}
    assert "Raj et al. (Eds.), Quantum Computing and Artificial Intelligence: The Industry Use Cases" in asset_titles
    assert not (asset_titles & RAW_DOCUMENT_TITLES)


def test_search_returns_results():
    response = client.get("/search", params={"query": "QUBO logistics"})
    assert response.status_code == 200
    data = response.json()
    assert data
    assert not ({result["source_title"] for result in data} & RAW_DOCUMENT_TITLES)


def test_search_returns_industry_use_case_results():
    response = client.get("/search", params={"query": "post-quantum cryptography"})
    assert response.status_code == 200
    data = response.json()
    assert any(result["lesson_slug"] == "industry-use-cases" for result in data)


def test_search_uses_clean_video_source_titles():
    response = client.get("/search", params={"query": "NISQ Bottlenecks"})
    assert response.status_code == 200
    data = response.json()
    video_results = [result for result in data if result["source_kind"] == "video"]
    assert video_results
    source_titles = {result["source_title"] for result in video_results}
    assert "Quantum Computing and Artificial Intelligence 2025" in source_titles
    assert not (source_titles & RAW_VIDEO_TITLES)


def test_qa_returns_citations():
    response = client.post(
        "/qa/ask",
        json={"question": "Why does routing overhead matter in the NISQ era?", "lesson_slug": "ai4qc-routing-and-optimization"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["citations"]
    assert data["answer"]
    assert not ({citation["source_title"] for citation in data["citations"]} & RAW_DOCUMENT_TITLES)

def test_source_asset_requires_authentication_headers():
    response = client.head("/source-assets/Quantum%20Computing%20and%20Artificial%20Intelligence%202025.mp4")
    assert response.status_code == 401


def test_source_asset_supports_head_requests():
    response = client.head(
        "/source-assets/Quantum%20Computing%20and%20Artificial%20Intelligence%202025.mp4",
        headers=DEMO_HEADERS,
    )
    assert response.status_code == 200


def test_document_source_asset_supports_id_based_head_requests():
    response = client.head(
        "/source-assets/by-id/quantum-computing-ai-research-synthesis-2026",
        headers=DEMO_HEADERS,
    )
    assert response.status_code == 200


def test_video_source_asset_supports_id_based_head_requests():
    response = client.head(
        "/source-assets/by-id/quantum-computing-and-artificial-intelligence-2025",
        headers=DEMO_HEADERS,
    )
    assert response.status_code == 200


def test_renamed_2026_source_asset_supports_head_requests():
    response = client.head(
        "/source-assets/Quantum%20Computing%20and%20Artificial%20Intelligence%202026.mp4",
        headers=DEMO_HEADERS,
    )
    assert response.status_code == 200


def test_video_source_asset_supports_byte_ranges():
    response = client.get(
        "/source-assets/by-id/quantum-computing-and-artificial-intelligence-2025",
        headers={**DEMO_HEADERS, "Range": "bytes=0-255"},
    )
    assert response.status_code == 206
    assert response.headers["accept-ranges"] == "bytes"
    assert response.headers["content-range"].startswith("bytes 0-255/")
    assert len(response.content) == 256


def test_course_overview_excludes_removed_prerequisite_module():
    response = client.get("/content/course")
    assert response.status_code == 200
    modules = response.json()["modules"]
    module_slugs = [module["slug"] for module in modules]
    assert "hardware-prerequisite" not in module_slugs
    assert modules[0]["slug"] == "nisq-hybrid-workflows"


def test_video_assets_use_updated_titles():
    response = client.get("/content/course")
    assert response.status_code == 200
    assets = response.json()["source_assets"]
    video_titles = [asset["title"] for asset in assets if asset["kind"] == "video"]
    assert DISPLAY_VIDEO_TITLES <= set(video_titles)
    assert not (set(video_titles) & RAW_VIDEO_TITLES)


def test_video_assets_use_updated_filenames():
    response = client.get("/content/course")
    assert response.status_code == 200
    assets = response.json()["source_assets"]
    video_filenames = [asset["filename"] for asset in assets if asset["kind"] == "video"]
    assert "Quantum Computing and Artificial Intelligence 2025.mp4" in video_filenames
    assert "Quantum Computing and Artificial Intelligence 2026.mp4" in video_filenames
    video_urls = [asset["download_url"] for asset in assets if asset["kind"] == "video"]
    assert all(url.startswith("/source-assets/by-id/") for url in video_urls)
    assert not any(any(raw_title in url for raw_title in RAW_VIDEO_TITLES) for url in video_urls)


def test_allowed_origins_env_accepts_scalar_and_csv(monkeypatch):
    monkeypatch.setenv("ALLOWED_ORIGINS", "http://localhost:3000, https://app.qcai.local")
    settings = Settings()
    assert settings.allowed_origins == ["http://localhost:3000", "https://app.qcai.local"]


def test_allowed_origins_rejects_wildcard_in_production(monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("ALLOWED_ORIGINS", "[\"*\"]")
    try:
        Settings()
    except ValueError as exc:
        assert "Wildcard ALLOWED_ORIGINS" in str(exc)
    else:
        raise AssertionError("Expected wildcard CORS configuration to be rejected outside development.")


def test_source_document_selection_uses_curated_allowlist(tmp_path: Path):
    for name in (
        "Quantum Computing AI Research Synthesis 2026.docx",
        "Analyzing Quantum Computing and AI Paper 2025.docx",
        "Quantum Computing and Artificial Intelligence Industry Use Cases.docx",
        "Vital_Concepts.docx",
        "06_Future_Deliverable.docx",
    ):
        (tmp_path / name).write_bytes(b"test")
    (tmp_path / "01_Repository_Artifact_Study_and_Assessment.docx").write_bytes(b"test")

    settings = Settings(source_assets_root=str(tmp_path))
    discovered = [path.name for path in settings.source_documents]
    assert discovered == [
        "Quantum Computing AI Research Synthesis 2026.docx",
        "Analyzing Quantum Computing and AI Paper 2025.docx",
        "Quantum Computing and Artificial Intelligence Industry Use Cases.docx",
    ]


def test_progress_endpoint_aggregates_activity():
    user_headers = {"x-demo-user": f"progress-{uuid4()}", "x-demo-role": "learner"}

    note_response = client.post(
        "/content/lessons/ai4qc-routing-and-optimization/notes",
        headers=user_headers,
        json={"body": "Routing depth and SWAP cost dominate NISQ execution."},
    )
    assert note_response.status_code == 200

    analytics_response = client.post(
        "/analytics/events",
        headers=user_headers,
        json={"event_type": "lesson_viewed", "lesson_slug": "ai4qc-routing-and-optimization", "payload": {}},
    )
    assert analytics_response.status_code == 200

    quiz_response = client.post(
        "/content/quiz-attempts",
        headers=user_headers,
        json={
            "lesson_slug": "ai4qc-routing-and-optimization",
            "score": 1,
            "responses": {"ai4qc-routing-and-optimization-quiz-1": "sample"},
        },
    )
    assert quiz_response.status_code == 200

    progress_response = client.get("/content/progress", headers=user_headers)
    assert progress_response.status_code == 200
    data = progress_response.json()
    assert data["total_lessons"] == 6
    assert data["visited_lessons"] >= 1
    assert data["completed_lessons"] >= 1
    lesson = next(item for item in data["lessons"] if item["lesson_slug"] == "ai4qc-routing-and-optimization")
    assert lesson["status"] == "completed"
    assert lesson["note_count"] == 1
    assert lesson["quiz_attempts"] == 1
    assert lesson["analytics_events"] == 1
    assert lesson["best_score_percent"] == 100.0
    module = next(item for item in data["modules"] if item["module_slug"] == "ai-for-quantum-hardware")
    assert module["status"] in {"in_progress", "completed"}
    assert data["recent_notes"]
    assert data["recent_quiz_attempts"]
