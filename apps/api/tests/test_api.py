from pathlib import Path
from uuid import uuid4

from fastapi.responses import FileResponse, StreamingResponse
from fastapi.testclient import TestClient
from starlette.requests import Request
from sqlalchemy import func, select

from app.api.routes import assets, assistant
from app.core.db import SessionLocal
from app.db_models import ArenaProfile, Note, UserAccount
from app.core.config import Settings
from app.main import _build_security_headers, _initialize_database, app
from app.schemas import AssistantChatResponse, Citation
from app.services.retrieval_engine import RetrievalEngine
from app.services.store import get_course_store
from app.services.teaching_assistant import TeachingAssistantService


_initialize_database()
get_course_store()
client = TestClient(app)
DEMO_HEADERS = {"x-demo-user": "demo-test-user", "x-demo-role": "learner"}
RAW_DOCUMENT_TITLES = {
    "Quantum Computing AI Research Synthesis 2026.docx",
    "Analyzing Quantum Computing and AI Paper 2025.docx",
    "Quantum Computing and Artificial Intelligence Industry Use Cases.docx",
    "Module2_Routing, Graph Shrinking, and Logistics under Hardware Constraints.docx",
    "Module3_Quantum Vision, GNN, and Few-Shot Hybrid Architectures.docx",
    "Introduction_to_Hardware-Constrained_Learning_for_Quantum_Computing_and_Artificial_Intelligence.docx",
    "Hardware-Constrained_Learning_for_Quantum_Computing_and_Artificial_Intelligence_Models.docx",
    "Intermediate_Quantum_Programming_for_Hardware-Constrained_Learning_for_Quantum_Computing_and_Artificial_Intelligence.docx",
    "Advanced_Programming_and_Software_Development_for_Hardware-Constrained_Learning_for_Quantum_Computing_and_Artificial_Intelligence.docx",
    "Quantum_Finance_Programming_and_Optimization_for_Hardware-Constrained_Learning_for_Quantum_Computing_and_Artificial_Intelligence.docx",
}
DISPLAY_DOCUMENT_TITLES = {
    "Ali, Chicano, and Moraglio (Eds.), QC+AI 2025 Proceedings",
    "Ali, Chicano, and Moraglio (Eds.), QC+AI 2026 Proceedings",
    "Raj et al. (Eds.), Quantum Computing and Artificial Intelligence: The Industry Use Cases",
    "Routing, Graph Shrinking, and Logistics under Hardware Constraints",
    "Quantum Vision, GNN, and Few-Shot Hybrid Architectures",
    "Introduction to Hardware-Constrained QC+AI",
    "Hardware-Constrained QC+AI Models",
    "Intermediate Quantum Programming for Hardware-Constrained QC+AI",
    "Advanced Quantum Software Development for Hardware-Constrained QC+AI",
    "Quantum Finance Programming and Optimization for Hardware-Constrained QC+AI",
}
RAW_VIDEO_TITLES = {
    "Industry Use Cases.mp4",
    "Quantum Computing and Artificial Intelligence 2025.mp4",
    "Quantum Computing and Artificial Intelligence 2026.mp4",
    "Module2_Routing, Graph Shrinking, and Logistics under Hardware Constraints.mp4",
    "Module3_Quantum Vision, GNN, and Few-Shot Hybrid Architectures.mp4",
    "Introduction_to_Hardware-Constrained_Learning_for_Quantum_Computing_and_Artificial_Intelligence.mp4",
    "The Hardware-First Imperative in Quantum Machine LearningHardware-Constrained_Learning_for_Quantum_Computing_and_Artificial_Intelligence_Models.mp4",
    "Intermediate_Quantum_Programming_for_Hardware-Constrained_Learning_for_Quantum_Computing_and_Artificial_Intelligence.mp4",
    "Advanced_Programming_and_Software_Development_for_Hardware-Constrained_Learning_for_Quantum_Computing_and_Artificial_Intelligence.mp4",
    "Quantum_Finance_Programming_and_Optimization_for_Hardware-Constrained_Learning_for_Quantum_Computing_and_Artificial_Intelligence.mp4",
}
DISPLAY_VIDEO_TITLES = {
    "Industry Use Cases",
    "Quantum Computing and Artificial Intelligence 2025",
    "Quantum Computing and Artificial Intelligence 2026",
    "Routing, Graph Shrinking, and Logistics under Hardware Constraints",
    "Quantum Vision, GNN, and Few-Shot Hybrid Architectures",
    "Introduction to Hardware-Constrained QC+AI",
    "Hardware-Constrained QC+AI Models",
    "Intermediate Quantum Programming for Hardware-Constrained QC+AI",
    "Advanced Quantum Software Development for Hardware-Constrained QC+AI",
    "Quantum Finance Programming and Optimization for Hardware-Constrained QC+AI",
}


def _build_asset_request(
    method: str = "GET",
    headers: dict[str, str] | None = None,
) -> Request:
    request_headers = [
        (key.lower().encode("latin-1"), value.encode("latin-1"))
        for key, value in (headers or {}).items()
    ]
    return Request(
        {
            "type": "http",
            "http_version": "1.1",
            "method": method,
            "scheme": "http",
            "path": "/source-assets/by-id/quantum-computing-and-artificial-intelligence-2025",
            "raw_path": b"/source-assets/by-id/quantum-computing-and-artificial-intelligence-2025",
            "query_string": b"",
            "headers": request_headers,
            "client": ("testclient", 50000),
            "server": ("testserver", 80),
        }
    )


def test_healthcheck():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert response.json()["environment"] in {"development", "production"}
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-frame-options"] == "DENY"
    assert response.headers["x-xss-protection"] == "1; mode=block"
    assert response.headers["x-request-id"]
    assert "permissions-policy" in response.headers


def test_readiness_check():
    response = client.get("/ready")
    assert response.status_code == 200
    assert response.json()["status"] == "ready"
    assert response.json()["database"] == "ok"
    assert response.json()["lessons"] >= 1
    assert response.headers["x-request-id"]


def test_course_overview():
    response = client.get("/content/course")
    assert response.status_code == 200
    data = response.json()
    assert data["id"] == "qcai-hardware-aware-course"
    assert len(data["modules"]) == 11
    assert sum(len(module["lesson_slugs"]) for module in data["modules"]) == 12
    assert len(data["source_assets"]) == 20
    source_filenames = [asset["filename"] for asset in data["source_assets"]]
    assert "Quantum Computing and Artificial Intelligence Industry Use Cases.docx" in source_filenames
    assert "Module2_Routing, Graph Shrinking, and Logistics under Hardware Constraints.docx" in source_filenames
    assert "Module3_Quantum Vision, GNN, and Few-Shot Hybrid Architectures.docx" in source_filenames
    assert (
        "Introduction_to_Hardware-Constrained_Learning_for_Quantum_Computing_and_Artificial_Intelligence.docx"
        in source_filenames
    )
    assert (
        "Quantum_Finance_Programming_and_Optimization_for_Hardware-Constrained_Learning_for_Quantum_Computing_and_Artificial_Intelligence.docx"
        in source_filenames
    )
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
    assert data["related_lessons"]
    assert data["chapters"]
    assert data["video_asset"]["filename"] == "Module2_Routing, Graph Shrinking, and Logistics under Hardware Constraints.mp4"
    assert data["video_asset"]["title"] == "Routing, Graph Shrinking, and Logistics under Hardware Constraints"
    assert (
        data["video_asset"]["download_url"]
        == "/source-assets/by-id/module2_routing-graph-shrinking-and-logistics-under-hardware-constraints-video"
    )
    source_filenames = {asset["filename"] for asset in data["source_assets"]}
    assert "Module2_Routing, Graph Shrinking, and Logistics under Hardware Constraints.docx" in source_filenames
    assert "Module2_Routing, Graph Shrinking, and Logistics under Hardware Constraints.mp4" in source_filenames


def test_hybrid_applications_lesson_lookup_uses_module3_source_pair():
    response = client.get("/content/lessons/hybrid-applications-healthcare-vision")
    assert response.status_code == 200
    data = response.json()
    assert data["module_slug"] == "quantum-enhanced-applications"
    assert data["sections"]
    assert data["chapters"]
    assert data["video_asset"]["filename"] == "Module3_Quantum Vision, GNN, and Few-Shot Hybrid Architectures.mp4"
    assert data["video_asset"]["title"] == "Quantum Vision, GNN, and Few-Shot Hybrid Architectures"
    assert (
        data["video_asset"]["download_url"]
        == "/source-assets/by-id/module3_quantum-vision-gnn-and-few-shot-hybrid-architectures-video"
    )
    source_filenames = {asset["filename"] for asset in data["source_assets"]}
    assert "Module3_Quantum Vision, GNN, and Few-Shot Hybrid Architectures.docx" in source_filenames
    assert "Module3_Quantum Vision, GNN, and Few-Shot Hybrid Architectures.mp4" in source_filenames
    source_titles = {section["source_title"] for section in data["sections"]}
    assert "Quantum Vision, GNN, and Few-Shot Hybrid Architectures" in source_titles
    headings = {section["heading"] for section in data["sections"]}
    assert "Quantum Vision Transformers: Overcoming Quadratic Attention Bottlenecks" in headings
    assert "The Generative Shift: Quantum Diffusion Models for Few-Shot Learning" in headings


def test_lesson_lookup_repairs_mojibake_in_source_excerpts():
    response = client.get("/content/lessons/nisq-reality-overview")
    assert response.status_code == 200
    data = response.json()

    excerpt = next(
        section["excerpt"]
        for section in data["sections"]
        if section["heading"] == "The Convergence of Quantum Mechanics and Computational Intelligence"
    )

    assert "\u00e2\u0080" not in excerpt
    assert (
        "accessible, albeit noisy, physical systems—commonly referred to as "
        "Noisy Intermediate-Scale Quantum (NISQ) devices"
    ) in excerpt


def test_industry_use_cases_lesson_lookup():
    response = client.get("/content/lessons/industry-use-cases")
    assert response.status_code == 200
    data = response.json()
    assert data["module_slug"] == "industry-use-cases"
    assert data["sections"]
    assert data["video_asset"]["filename"] == "Industry Use Cases.mp4"
    assert data["video_asset"]["title"] == "Industry Use Cases"
    assert data["video_asset"]["download_url"] == "/source-assets/by-id/industry-use-cases"
    assert data["chapters"]
    source_filenames = [asset["filename"] for asset in data["source_assets"]]
    assert "Quantum Computing and Artificial Intelligence Industry Use Cases.docx" in source_filenames
    assert "Industry Use Cases.mp4" in source_filenames
    source_titles = {section["source_title"] for section in data["sections"]}
    assert "Raj et al. (Eds.), Quantum Computing and Artificial Intelligence: The Industry Use Cases" in source_titles
    assert not (source_titles & RAW_DOCUMENT_TITLES)
    asset_titles = {asset["title"] for asset in data["source_assets"] if asset["kind"] == "document"}
    assert "Raj et al. (Eds.), Quantum Computing and Artificial Intelligence: The Industry Use Cases" in asset_titles
    assert not (asset_titles & RAW_DOCUMENT_TITLES)


def test_intro_hardware_constrained_lesson_lookup():
    response = client.get("/content/lessons/introduction-to-hardware-constrained-learning")
    assert response.status_code == 200
    data = response.json()
    assert data["module_slug"] == "hardware-constrained-introduction"
    assert data["video_asset"]["filename"] == (
        "Introduction_to_Hardware-Constrained_Learning_for_Quantum_Computing_and_Artificial_Intelligence.mp4"
    )
    assert data["video_asset"]["title"] == "Introduction to Hardware-Constrained QC+AI"
    assert data["video_asset"]["download_url"].endswith("-video")
    assert data["chapters"]


def test_intermediate_programming_lesson_lookup_uses_expanded_video_asset():
    response = client.get("/content/lessons/intermediate-quantum-programming-patterns")
    assert response.status_code == 200
    data = response.json()
    assert data["module_slug"] == "intermediate-quantum-programming"
    assert data["video_asset"]["filename"] == (
        "Intermediate_Quantum_Programming_for_Hardware-Constrained_Learning_for_Quantum_Computing_and_Artificial_Intelligence.mp4"
    )
    assert data["video_asset"]["title"] == "Intermediate Quantum Programming for Hardware-Constrained QC+AI"
    assert data["video_asset"]["download_url"].endswith("-video")
    assert data["chapters"]


def test_advanced_quantum_software_lesson_lookup_uses_expanded_video_asset():
    response = client.get("/content/lessons/advanced-quantum-software-development")
    assert response.status_code == 200
    data = response.json()
    assert data["module_slug"] == "advanced-quantum-software"
    assert data["video_asset"]["filename"] == (
        "Advanced_Programming_and_Software_Development_for_Hardware-Constrained_Learning_for_Quantum_Computing_and_Artificial_Intelligence.mp4"
    )
    assert data["video_asset"]["title"] == "Advanced Quantum Software Development for Hardware-Constrained QC+AI"
    assert data["video_asset"]["download_url"].endswith("-video")
    assert data["chapters"]


def test_search_returns_results():
    response = client.get("/search", params={"query": "QUBO logistics"})
    assert response.status_code == 200
    data = response.json()
    assert data
    assert response.headers["x-retrieval-mode"] == "lexical"
    assert not ({result["source_title"] for result in data} & RAW_DOCUMENT_TITLES)


def test_public_content_endpoints_set_cache_headers():
    for path in (
        "/content/course",
        "/content/modules/ai-for-quantum-hardware",
        "/content/lessons/ai4qc-routing-and-optimization",
    ):
        response = client.get(path)
        assert response.status_code == 200
        assert "public, max-age=300" in response.headers["cache-control"]


def test_public_content_endpoints_accept_head_requests():
    for path in (
        "/content/course",
        "/content/modules/ai-for-quantum-hardware",
        "/content/lessons/ai4qc-routing-and-optimization",
    ):
        response = client.head(path)
        assert response.status_code == 200
        assert "public, max-age=300" in response.headers["cache-control"]


def test_search_returns_industry_use_case_results():
    response = client.get("/search", params={"query": "post-quantum cryptography"})
    assert response.status_code == 200
    data = response.json()
    assert any(result["lesson_slug"] == "industry-use-cases" for result in data)


def test_search_uses_clean_video_source_titles():
    response = client.get("/search", params={"query": "nested routing"})
    assert response.status_code == 200
    data = response.json()
    video_results = [result for result in data if result["source_kind"] == "video"]
    assert video_results
    source_titles = {result["source_title"] for result in video_results}
    assert "Routing, Graph Shrinking, and Logistics under Hardware Constraints" in source_titles
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


def test_assistant_chat_returns_vertex_backed_contract(monkeypatch):
    class StubAssistant:
        def chat(self, message: str, **_: object):
            assert message == "How should I study routing depth?"
            return AssistantChatResponse(
                answer="Start with routing as a hardware constraint, then compare graph shrinking and baseline checks [1].",
                citations=[
                    Citation(
                        chunk_id="routing-1",
                        source_title="Routing, Graph Shrinking, and Logistics under Hardware Constraints",
                        source_kind="video",
                        section_title="Routing bottlenecks",
                        excerpt="Routing overhead grows because constrained hardware connectivity forces additional SWAP operations.",
                        timestamp_label="01:11",
                    )
                ],
                retrieval_mode="vertex-rag-lexical",
                provider="vertex-ai-service-account",
                model="gemini-3.1-flash-lite-preview",
                grounded=True,
            )

    monkeypatch.setattr(assistant, "get_teaching_assistant", lambda: StubAssistant())

    user_headers = {"x-demo-user": f"assistant-{uuid4().hex[:8]}", "x-demo-role": "learner"}
    response = client.post(
        "/assistant/chat",
        headers=user_headers,
        json={
            "message": "How should I study routing depth?",
            "lesson_slug": "ai4qc-routing-and-optimization",
            "page_path": "/lessons/ai4qc-routing-and-optimization",
            "history": [{"role": "assistant", "content": "What topic do you want to focus on?"}],
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert data["provider"] == "vertex-ai-service-account"
    assert data["model"] == "gemini-3.1-flash-lite-preview"
    assert data["grounded"] is True
    assert data["citations"]
    assert response.headers["x-assistant-provider"] == "vertex-ai-service-account"
    assert response.headers["x-assistant-model"] == "gemini-3.1-flash-lite-preview"


def test_assistant_chat_truncates_oversized_history_instead_of_rejecting_it(monkeypatch):
    oversized_history = "A" * 4501

    class StubAssistant:
        def chat(self, message: str, **kwargs: object):
            history = kwargs["history"]
            assert history is not None
            assert len(history) == 2
            assert history[0].content == "Tell me about routing depth."
            assert history[1].content == oversized_history[:4000]
            return AssistantChatResponse(
                answer="Noise and routing overhead both matter [1].",
                citations=[
                    Citation(
                        chunk_id="routing-2",
                        source_title="Routing, Graph Shrinking, and Logistics under Hardware Constraints",
                        source_kind="video",
                        section_title="Routing depth",
                        excerpt="Additional SWAPs increase depth and noise pressure.",
                        timestamp_label="02:04",
                    )
                ],
                retrieval_mode="vertex-rag-lexical",
                provider="vertex-ai-api-key",
                model="gemini-3.1-flash-lite-preview",
                grounded=True,
            )

    monkeypatch.setattr(assistant, "get_teaching_assistant", lambda: StubAssistant())

    user_headers = {"x-demo-user": f"assistant-{uuid4().hex[:8]}", "x-demo-role": "learner"}
    response = client.post(
        "/assistant/chat",
        headers=user_headers,
        json={
            "message": "Why does noise matter after routing?",
            "page_path": "/",
            "history": [
                {"role": "user", "content": "Tell me about routing depth."},
                {"role": "assistant", "content": oversized_history},
            ],
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert data["provider"] == "vertex-ai-api-key"
    assert data["model"] == "gemini-3.1-flash-lite-preview"
    assert data["citations"]


def test_teaching_assistant_falls_back_to_grounded_local_answer_without_vertex():
    store = get_course_store()
    engine = RetrievalEngine(store, Settings())

    class NoVertexAssistant(TeachingAssistantService):
        @property
        def vertex_project_id(self) -> str | None:
            return None

    service = NoVertexAssistant(
        engine,
        Settings(vertex_ai_project_id="", vertex_ai_chat_model="gemini-3.1-flash-lite-preview"),
    )

    response = service.chat(
        "Why does routing depth matter?",
        lesson_slug="ai4qc-routing-and-optimization",
        page_path="/lessons/ai4qc-routing-and-optimization",
    )

    assert response.provider == "local-grounded-fallback"
    assert response.model == "qcai-course-corpus"
    assert response.grounded is True
    assert response.citations
    assert "routing" in response.answer.lower()


def test_teaching_assistant_uses_api_key_endpoint_without_bearer_header():
    store = get_course_store()
    engine = RetrievalEngine(store, Settings())

    class RecordingClient:
        def __init__(self):
            self.captured_url = ""
            self.captured_headers = {}

        def post(self, url: str, *, headers: dict[str, str], json: dict):
            self.captured_url = url
            self.captured_headers = headers

            class Response:
                def raise_for_status(self):
                    return None

                def json(self):
                    return {
                        "candidates": [
                            {
                                "content": {
                                    "parts": [{"text": "Use the hardware-constrained lessons as your study anchor [1]."}]
                                }
                            }
                        ]
                    }

            return Response()

    client_stub = RecordingClient()

    class ApiKeyAssistant(TeachingAssistantService):
        @property
        def vertex_api_key(self) -> str | None:
            return "test-api-key"

        @property
        def _vertex_client(self):
            return client_stub

    service = ApiKeyAssistant(
        engine,
        Settings(
            vertex_ai_api_key="test-api-key",
            vertex_ai_chat_model="gemini-3.1-flash-lite-preview",
        ),
    )

    response = service.chat("How should I start?", page_path="/")

    assert response.provider == "vertex-ai-api-key"
    assert response.model == "gemini-3.1-flash-lite-preview"
    assert "key=test-api-key" in client_stub.captured_url
    assert "/publishers/google/models/gemini-3.1-flash-lite-preview:generateContent" in client_stub.captured_url
    assert "Authorization" not in client_stub.captured_headers

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


def test_document_source_asset_uses_docx_media_type():
    response = client.head(
        "/source-assets/by-id/quantum-computing-ai-research-synthesis-2026",
        headers=DEMO_HEADERS,
    )
    assert response.status_code == 200
    assert response.headers["content-type"].startswith(
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    )


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


def test_full_video_get_uses_capped_open_ended_ranges(monkeypatch, tmp_path: Path):
    payload = b"\x00\x00\x00\x18ftypmp42" + (b"chunk-range" * (assets.VIDEO_OPEN_ENDED_RANGE_CHUNK_SIZE // 11 + 1))
    payload = payload[: assets.VIDEO_OPEN_ENDED_RANGE_CHUNK_SIZE + 1_024]
    (tmp_path / "Quantum Computing and Artificial Intelligence 2025.mp4").write_bytes(payload)
    settings = Settings(source_assets_root=str(tmp_path))
    monkeypatch.setattr(assets, "get_settings", lambda: settings)

    response = client.get(
        "/source-assets/by-id/quantum-computing-and-artificial-intelligence-2025",
        headers={**DEMO_HEADERS, "Range": "bytes=0-"},
    )

    capped_end = assets.VIDEO_OPEN_ENDED_RANGE_CHUNK_SIZE - 1
    assert response.status_code == 206
    assert response.headers["accept-ranges"] == "bytes"
    assert response.headers["content-range"] == f"bytes 0-{capped_end}/{len(payload)}"
    assert len(response.content) == assets.VIDEO_OPEN_ENDED_RANGE_CHUNK_SIZE


def test_full_video_get_uses_streaming_response(tmp_path: Path):
    payload = b"\x00\x00\x00\x18ftypmp42" + (b"video-payload" * 32)
    video_path = tmp_path / "Quantum Computing and Artificial Intelligence 2025.mp4"
    video_path.write_bytes(payload)

    response = assets._serve_source_asset(video_path, _build_asset_request())

    assert isinstance(response, StreamingResponse)
    assert not isinstance(response, FileResponse)
    assert response.status_code == 200
    assert response.media_type == "video/mp4"
    assert response.headers["accept-ranges"] == "bytes"
    assert "content-length" not in response.headers


def test_video_source_asset_supports_full_gets(monkeypatch, tmp_path: Path):
    payload = b"\x00\x00\x00\x18ftypmp42" + (b"stream-me" * 64)
    (tmp_path / "Quantum Computing and Artificial Intelligence 2025.mp4").write_bytes(payload)
    settings = Settings(source_assets_root=str(tmp_path))
    monkeypatch.setattr(assets, "get_settings", lambda: settings)

    response = client.get(
        "/source-assets/by-id/quantum-computing-and-artificial-intelligence-2025",
        headers=DEMO_HEADERS,
    )

    assert response.status_code == 200
    assert response.headers["accept-ranges"] == "bytes"
    assert response.headers["content-type"].startswith("video/mp4")
    assert "content-length" not in response.headers
    assert response.content == payload


def test_course_overview_excludes_removed_prerequisite_module():
    response = client.get("/content/course")
    assert response.status_code == 200
    modules = response.json()["modules"]
    module_slugs = [module["slug"] for module in modules]
    assert "hardware-prerequisite" not in module_slugs
    assert modules[0]["slug"] == "nisq-hybrid-workflows"


def test_quantum_applications_module_supports_multiple_lessons():
    response = client.get("/content/modules/quantum-enhanced-applications")
    assert response.status_code == 200
    data = response.json()
    lesson_slugs = data["module"]["lesson_slugs"]
    assert lesson_slugs == [
        "hybrid-applications-healthcare-vision",
        "clinical-and-kernel-qcai-systems",
    ]
    assert len(data["lessons"]) == 2


def test_new_hardware_constrained_module_supports_lookup():
    response = client.get("/content/modules/hardware-constrained-models")
    assert response.status_code == 200
    data = response.json()
    assert data["module"]["title"] == "Hardware-Constrained QC+AI Models"
    assert data["module"]["lesson_slugs"] == ["hardware-constrained-qcai-models"]
    assert len(data["lessons"]) == 1
    assert data["lessons"][0]["sections"]
    source_titles = {section["source_title"] for section in data["lessons"][0]["sections"]}
    assert "Hardware-Constrained QC+AI Models" in source_titles


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
    assert "Industry Use Cases.mp4" in video_filenames
    assert "Quantum Computing and Artificial Intelligence 2025.mp4" in video_filenames
    assert "Quantum Computing and Artificial Intelligence 2026.mp4" in video_filenames
    assert "Module2_Routing, Graph Shrinking, and Logistics under Hardware Constraints.mp4" in video_filenames
    assert "Module3_Quantum Vision, GNN, and Few-Shot Hybrid Architectures.mp4" in video_filenames
    assert (
        "Introduction_to_Hardware-Constrained_Learning_for_Quantum_Computing_and_Artificial_Intelligence.mp4"
        in video_filenames
    )
    assert (
        "The Hardware-First Imperative in Quantum Machine LearningHardware-Constrained_Learning_for_Quantum_Computing_and_Artificial_Intelligence_Models.mp4"
        in video_filenames
    )
    assert (
        "Intermediate_Quantum_Programming_for_Hardware-Constrained_Learning_for_Quantum_Computing_and_Artificial_Intelligence.mp4"
        in video_filenames
    )
    assert (
        "Advanced_Programming_and_Software_Development_for_Hardware-Constrained_Learning_for_Quantum_Computing_and_Artificial_Intelligence.mp4"
        in video_filenames
    )
    assert (
        "Quantum_Finance_Programming_and_Optimization_for_Hardware-Constrained_Learning_for_Quantum_Computing_and_Artificial_Intelligence.mp4"
        in video_filenames
    )
    assert len(video_filenames) == 10
    video_urls = [asset["download_url"] for asset in assets if asset["kind"] == "video"]
    assert all(url.startswith("/source-assets/by-id/") for url in video_urls)
    assert not any(any(raw_title in url for raw_title in RAW_VIDEO_TITLES) for url in video_urls)


def test_duplicate_stem_assets_use_kind_specific_ids():
    response = client.get("/content/course")
    assert response.status_code == 200
    assets = response.json()["source_assets"]

    intro_document = next(
        asset
        for asset in assets
        if asset["filename"]
        == "Introduction_to_Hardware-Constrained_Learning_for_Quantum_Computing_and_Artificial_Intelligence.docx"
    )
    intro_video = next(
        asset
        for asset in assets
        if asset["filename"]
        == "Introduction_to_Hardware-Constrained_Learning_for_Quantum_Computing_and_Artificial_Intelligence.mp4"
    )
    finance_document = next(
        asset
        for asset in assets
        if asset["filename"]
        == "Quantum_Finance_Programming_and_Optimization_for_Hardware-Constrained_Learning_for_Quantum_Computing_and_Artificial_Intelligence.docx"
    )
    finance_video = next(
        asset
        for asset in assets
        if asset["filename"]
        == "Quantum_Finance_Programming_and_Optimization_for_Hardware-Constrained_Learning_for_Quantum_Computing_and_Artificial_Intelligence.mp4"
    )
    advanced_document = next(
        asset
        for asset in assets
        if asset["filename"]
        == "Advanced_Programming_and_Software_Development_for_Hardware-Constrained_Learning_for_Quantum_Computing_and_Artificial_Intelligence.docx"
    )
    advanced_video = next(
        asset
        for asset in assets
        if asset["filename"]
        == "Advanced_Programming_and_Software_Development_for_Hardware-Constrained_Learning_for_Quantum_Computing_and_Artificial_Intelligence.mp4"
    )
    module2_document = next(
        asset
        for asset in assets
        if asset["filename"] == "Module2_Routing, Graph Shrinking, and Logistics under Hardware Constraints.docx"
    )
    module2_video = next(
        asset
        for asset in assets
        if asset["filename"] == "Module2_Routing, Graph Shrinking, and Logistics under Hardware Constraints.mp4"
    )
    module3_document = next(
        asset
        for asset in assets
        if asset["filename"] == "Module3_Quantum Vision, GNN, and Few-Shot Hybrid Architectures.docx"
    )
    module3_video = next(
        asset
        for asset in assets
        if asset["filename"] == "Module3_Quantum Vision, GNN, and Few-Shot Hybrid Architectures.mp4"
    )

    assert intro_document["id"].endswith("-document")
    assert intro_video["id"].endswith("-video")
    assert intro_document["id"] != intro_video["id"]
    assert advanced_document["id"].endswith("-document")
    assert advanced_video["id"].endswith("-video")
    assert advanced_document["id"] != advanced_video["id"]
    assert finance_document["id"].endswith("-document")
    assert finance_video["id"].endswith("-video")
    assert finance_document["id"] != finance_video["id"]
    assert module2_document["id"].endswith("-document")
    assert module2_video["id"].endswith("-video")
    assert module2_document["id"] != module2_video["id"]
    assert module3_document["id"].endswith("-document")
    assert module3_video["id"].endswith("-video")
    assert module3_document["id"] != module3_video["id"]
    assert "," not in module2_document["id"]
    assert "," not in module2_video["id"]
    assert "," not in module3_document["id"]
    assert "," not in module3_video["id"]


def test_industry_video_asset_supports_head_requests():
    response = client.head(
        "/source-assets/by-id/industry-use-cases",
        headers=DEMO_HEADERS,
    )
    assert response.status_code == 200


def test_industry_video_asset_supports_byte_ranges():
    response = client.get(
        "/source-assets/by-id/industry-use-cases",
        headers={**DEMO_HEADERS, "Range": "bytes=0-255"},
    )
    assert response.status_code == 206
    assert response.headers["accept-ranges"] == "bytes"
    assert response.headers["content-range"].startswith("bytes 0-255/")
    assert len(response.content) == 256


def test_industry_video_asset_caps_open_ended_ranges(monkeypatch, tmp_path: Path):
    payload = b"\x00\x00\x00\x18ftypmp42" + (
        b"industry-range" * (assets.VIDEO_OPEN_ENDED_RANGE_CHUNK_SIZE // 14 + 1)
    )
    payload = payload[: assets.VIDEO_OPEN_ENDED_RANGE_CHUNK_SIZE + 2_048]
    (tmp_path / "Industry Use Cases.mp4").write_bytes(payload)
    settings = Settings(source_assets_root=str(tmp_path))
    monkeypatch.setattr(assets, "get_settings", lambda: settings)

    response = client.get(
        "/source-assets/by-id/industry-use-cases",
        headers={**DEMO_HEADERS, "Range": "bytes=0-"},
    )

    capped_end = assets.VIDEO_OPEN_ENDED_RANGE_CHUNK_SIZE - 1
    assert response.status_code == 206
    assert response.headers["accept-ranges"] == "bytes"
    assert response.headers["content-range"] == f"bytes 0-{capped_end}/{len(payload)}"
    assert len(response.content) == assets.VIDEO_OPEN_ENDED_RANGE_CHUNK_SIZE


def test_kind_specific_video_asset_id_resolves_to_video_with_duplicate_stem():
    response = client.head(
        "/source-assets/by-id/introduction_to_hardware-constrained_learning_for_quantum_computing_and_artificial_intelligence-video",
        headers=DEMO_HEADERS,
    )
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("video/mp4")


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


def test_demo_auth_defaults_off_outside_development(monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.delenv("ENABLE_DEMO_AUTH", raising=False)
    settings = Settings()
    assert settings.enable_demo_auth is False


def test_production_security_headers_drop_localhost_and_add_hsts():
    settings = Settings(
        environment="production",
        allowed_origins=["https://qantumlearn.academy"],
        api_base_url="https://api.qantumlearn.academy",
        site_url="https://qantumlearn.academy",
    )
    headers = _build_security_headers(settings, nonce="unit-test-nonce")
    assert "http://127.0.0.1:*" not in headers["Content-Security-Policy"]
    assert "http://localhost:*" not in headers["Content-Security-Policy"]
    assert "wss://api.qantumlearn.academy" in headers["Content-Security-Policy"]
    assert "'unsafe-inline'" not in headers["Content-Security-Policy"].split("script-src", 1)[1]
    assert "style-src 'self'" in headers["Content-Security-Policy"]
    assert "style-src-elem 'self'" in headers["Content-Security-Policy"]
    assert "style-src-attr 'unsafe-inline'" in headers["Content-Security-Policy"]
    assert "'nonce-unit-test-nonce'" in headers["Content-Security-Policy"]
    assert headers["X-XSS-Protection"] == "1; mode=block"
    assert headers["Cross-Origin-Opener-Policy"] == "same-origin"
    assert headers["Cross-Origin-Resource-Policy"] == "same-site"
    assert headers["Strict-Transport-Security"].startswith("max-age=")


def test_production_security_headers_drop_loopback_urls_even_if_configured():
    settings = Settings(
        environment="production",
        allowed_origins=["https://qantumlearn.academy"],
        api_base_url="https://0.0.0.0:3000",
        site_url="https://localhost:3000",
    )
    headers = _build_security_headers(settings, nonce="unit-test-nonce")
    assert "0.0.0.0:3000" not in headers["Content-Security-Policy"]
    assert "localhost:3000" not in headers["Content-Security-Policy"]


def test_source_document_selection_uses_curated_allowlist(tmp_path: Path):
    for name in (
        "Quantum Computing AI Research Synthesis 2026.docx",
        "Analyzing Quantum Computing and AI Paper 2025.docx",
        "Quantum Computing and Artificial Intelligence Industry Use Cases.docx",
        "Module2_Routing, Graph Shrinking, and Logistics under Hardware Constraints.docx",
        "Introduction_to_Hardware-Constrained_Learning_for_Quantum_Computing_and_Artificial_Intelligence.docx",
        "Hardware-Constrained_Learning_for_Quantum_Computing_and_Artificial_Intelligence_Models.docx",
        "Intermediate_Quantum_Programming_for_Hardware-Constrained_Learning_for_Quantum_Computing_and_Artificial_Intelligence.docx",
        "Advanced_Programming_and_Software_Development_for_Hardware-Constrained_Learning_for_Quantum_Computing_and_Artificial_Intelligence.docx",
        "Quantum_Finance_Programming_and_Optimization_for_Hardware-Constrained_Learning_for_Quantum_Computing_and_Artificial_Intelligence.docx",
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
        "Module2_Routing, Graph Shrinking, and Logistics under Hardware Constraints.docx",
        "Introduction_to_Hardware-Constrained_Learning_for_Quantum_Computing_and_Artificial_Intelligence.docx",
        "Hardware-Constrained_Learning_for_Quantum_Computing_and_Artificial_Intelligence_Models.docx",
        "Intermediate_Quantum_Programming_for_Hardware-Constrained_Learning_for_Quantum_Computing_and_Artificial_Intelligence.docx",
        "Advanced_Programming_and_Software_Development_for_Hardware-Constrained_Learning_for_Quantum_Computing_and_Artificial_Intelligence.docx",
        "Quantum_Finance_Programming_and_Optimization_for_Hardware-Constrained_Learning_for_Quantum_Computing_and_Artificial_Intelligence.docx",
    ]


def test_source_video_selection_uses_curated_allowlist(tmp_path: Path):
    for name in (
        "Quantum Computing and Artificial Intelligence 2025.mp4",
        "Quantum Computing and Artificial Intelligence 2026.mp4",
        "Industry Use Cases.mp4",
        "Module2_Routing, Graph Shrinking, and Logistics under Hardware Constraints.mp4",
        "Introduction_to_Hardware-Constrained_Learning_for_Quantum_Computing_and_Artificial_Intelligence.mp4",
        "The Hardware-First Imperative in Quantum Machine LearningHardware-Constrained_Learning_for_Quantum_Computing_and_Artificial_Intelligence_Models.mp4",
        "Intermediate_Quantum_Programming_for_Hardware-Constrained_Learning_for_Quantum_Computing_and_Artificial_Intelligence.mp4",
        "Advanced_Programming_and_Software_Development_for_Hardware-Constrained_Learning_for_Quantum_Computing_and_Artificial_Intelligence.mp4",
        "Quantum_Finance_Programming_and_Optimization_for_Hardware-Constrained_Learning_for_Quantum_Computing_and_Artificial_Intelligence.mp4",
        "draft-lecture.mp4",
    ):
        (tmp_path / name).write_bytes(b"test")

    settings = Settings(source_assets_root=str(tmp_path))
    discovered = [path.name for path in settings.source_videos]
    assert discovered == [
        "Quantum Computing and Artificial Intelligence 2025.mp4",
        "Quantum Computing and Artificial Intelligence 2026.mp4",
        "Industry Use Cases.mp4",
        "Module2_Routing, Graph Shrinking, and Logistics under Hardware Constraints.mp4",
        "Introduction_to_Hardware-Constrained_Learning_for_Quantum_Computing_and_Artificial_Intelligence.mp4",
        "The Hardware-First Imperative in Quantum Machine LearningHardware-Constrained_Learning_for_Quantum_Computing_and_Artificial_Intelligence_Models.mp4",
        "Intermediate_Quantum_Programming_for_Hardware-Constrained_Learning_for_Quantum_Computing_and_Artificial_Intelligence.mp4",
        "Advanced_Programming_and_Software_Development_for_Hardware-Constrained_Learning_for_Quantum_Computing_and_Artificial_Intelligence.mp4",
        "Quantum_Finance_Programming_and_Optimization_for_Hardware-Constrained_Learning_for_Quantum_Computing_and_Artificial_Intelligence.mp4",
    ]


def test_source_asset_selection_discovers_nested_update_data_assets(tmp_path: Path):
    update_data = tmp_path / "update_data"
    update_data.mkdir()
    (update_data / "Module2_Routing, Graph Shrinking, and Logistics under Hardware Constraints.docx").write_bytes(b"test")
    (update_data / "Module2_Routing, Graph Shrinking, and Logistics under Hardware Constraints.mp4").write_bytes(b"test")
    (update_data / "Module3_Quantum Vision, GNN, and Few-Shot Hybrid Architectures.docx").write_bytes(b"test")
    (update_data / "Module3_Quantum Vision, GNN, and Few-Shot Hybrid Architectures.mp4").write_bytes(b"test")

    settings = Settings(source_assets_root=str(tmp_path))

    assert [path.name for path in settings.source_documents] == [
        "Module2_Routing, Graph Shrinking, and Logistics under Hardware Constraints.docx",
        "Module3_Quantum Vision, GNN, and Few-Shot Hybrid Architectures.docx",
    ]
    assert [path.name for path in settings.source_videos] == [
        "Module2_Routing, Graph Shrinking, and Logistics under Hardware Constraints.mp4",
        "Module3_Quantum Vision, GNN, and Few-Shot Hybrid Architectures.mp4",
    ]


def test_guest_cookie_auth_is_supported():
    guest_id = "guest-123e4567-e89b-12d3-a456-426614174000"
    with TestClient(app) as cookie_client:
        cookie_client.cookies.set("qcai_guest_id", guest_id)
        response = cookie_client.get("/auth/me")
        assert response.status_code == 200
        assert response.json()["user_id"] == guest_id
        assert response.json()["role"] == "learner"


def test_guest_mutation_requires_csrf_protection():
    with TestClient(app) as guest_client:
        guest_client.cookies.set("qcai_guest_id", "guest-123e4567-e89b-12d3-a456-426614174000")
        response = guest_client.post(
            "/insights/check-ins",
            json={
                "motivation_level": 3,
                "focus_level": 3,
                "energy_level": 3,
                "session_minutes": 10,
                "today_goal": "Audit the protections.",
                "blocker": "None",
            },
        )
        assert response.status_code == 403
        assert response.json()["detail"] == "Missing CSRF protection."


def test_guest_mutation_accepts_trusted_origin_with_matching_csrf():
    with TestClient(app) as guest_client:
        guest_client.cookies.set("qcai_guest_id", "guest-123e4567-e89b-12d3-a456-426614174000")
        guest_client.cookies.set("qcai_guest_csrf", "3b1f2f40-7132-4778-8df5-44c1c5cf6bb0")
        response = guest_client.post(
            "/insights/check-ins",
            headers={
                "origin": "http://localhost:3000",
                "x-qcai-csrf": "3b1f2f40-7132-4778-8df5-44c1c5cf6bb0",
            },
            json={
                "motivation_level": 3,
                "focus_level": 3,
                "energy_level": 3,
                "session_minutes": 10,
                "today_goal": "Audit the protections.",
                "blocker": "None",
            },
        )
        assert response.status_code == 200
        assert response.json()["session_minutes"] == 10
        assert response.json()["today_goal"] == "Audit the protections."


def test_local_account_register_login_logout_and_delete():
    email = f"learner-{uuid4().hex[:8]}@qcai.local"
    password = "S3cureQuantumPath"
    note_body = f"Local account note {uuid4().hex[:8]} for deletion coverage."

    with TestClient(app) as account_client:
        register_response = account_client.post(
            "/auth/register",
            json={"email": email, "password": password},
        )
        assert register_response.status_code == 201
        registered_user = register_response.json()["user"]
        assert registered_user["email"] == email
        assert registered_user["auth_provider"] == "local"
        assert registered_user["can_delete_account"] is True
        assert account_client.cookies.get("qcai_session_token")
        assert account_client.cookies.get("qcai_auth_csrf")

        me_response = account_client.get("/auth/me")
        assert me_response.status_code == 200
        assert me_response.json()["email"] == email

        csrf_token = account_client.cookies.get("qcai_auth_csrf")
        note_response = account_client.post(
            "/content/lessons/ai4qc-routing-and-optimization/notes",
            headers={"origin": "http://localhost:3000", "x-qcai-csrf": csrf_token},
            json={"body": note_body},
        )
        assert note_response.status_code == 200

        logout_response = account_client.post(
            "/auth/logout",
            headers={"origin": "http://localhost:3000", "x-qcai-csrf": csrf_token},
        )
        assert logout_response.status_code == 200
        assert logout_response.json()["status"] == "signed_out"
        assert account_client.cookies.get("qcai_session_token") is None

        post_logout_me = account_client.get("/auth/me")
        assert post_logout_me.status_code == 200
        assert post_logout_me.json()["user_id"] != registered_user["user_id"]

        login_response = account_client.post(
            "/auth/login",
            json={"email": email, "password": password},
        )
        assert login_response.status_code == 200
        assert login_response.json()["user"]["email"] == email

        delete_csrf = account_client.cookies.get("qcai_auth_csrf")
        delete_response = account_client.request(
            "DELETE",
            "/auth/account",
            headers={"origin": "http://localhost:3000", "x-qcai-csrf": delete_csrf},
            json={"password": password},
        )
        assert delete_response.status_code == 200
        assert delete_response.json()["status"] == "deleted"

    with SessionLocal() as db:
        assert db.scalars(select(UserAccount).where(UserAccount.email == email)).first() is None
        assert not db.scalars(select(Note).where(Note.body == note_body)).all()


def test_local_account_rejects_bad_password_on_login():
    email = f"learner-{uuid4().hex[:8]}@qcai.local"
    password = "S3cureQuantumPath"
    with TestClient(app) as account_client:
        response = account_client.post("/auth/register", json={"email": email, "password": password})
        assert response.status_code == 201
        account_client.post(
            "/auth/logout",
            headers={
                "origin": "http://localhost:3000",
                "x-qcai-csrf": account_client.cookies.get("qcai_auth_csrf"),
            },
        )

    with TestClient(app) as fresh_client:
        failed_login = fresh_client.post("/auth/login", json={"email": email, "password": "wrong-password"})
        assert failed_login.status_code == 401
        assert failed_login.json()["detail"] == "Invalid email or password."


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
    assert data["total_lessons"] == 12
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

    notes_response = client.get(
        "/content/lessons/ai4qc-routing-and-optimization/notes",
        headers=user_headers,
        params={"limit": 1, "offset": 0},
    )
    assert notes_response.status_code == 200
    assert len(notes_response.json()) == 1

    qa_response = client.post(
        "/qa/ask",
        headers=user_headers,
        json={"question": "Why does routing depth matter?", "lesson_slug": "ai4qc-routing-and-optimization"},
    )
    assert qa_response.status_code == 200
    history_response = client.get(
        "/qa/history",
        headers=user_headers,
        params={"lesson_slug": "ai4qc-routing-and-optimization", "limit": 5},
    )
    assert history_response.status_code == 200
    assert history_response.json()[0]["question"] == "Why does routing depth matter?"


def test_arena_leaderboard_orders_profiles():
    top_player = f"arena-top-{uuid4().hex[:8]}"
    runner_up = f"arena-runner-{uuid4().hex[:8]}"
    with SessionLocal() as session:
        current_max_xp = session.scalar(select(func.max(ArenaProfile.xp))) or 0
        session.add_all(
            [
                ArenaProfile(
                    player_id=top_player,
                    display_name="Top Player",
                    xp=current_max_xp + 200,
                    matches_played=12,
                    wins=9,
                    skill_rating=1290,
                    adaptive_level=4,
                ),
                ArenaProfile(
                    player_id=runner_up,
                    display_name="Runner Up",
                    xp=current_max_xp + 100,
                    matches_played=11,
                    wins=7,
                    skill_rating=1210,
                    adaptive_level=4,
                ),
            ]
        )
        session.commit()

    response = client.get("/arena/leaderboard", params={"limit": 50})
    assert response.status_code == 200
    data = response.json()
    top_index = next(index for index, item in enumerate(data) if item["player_id"] == top_player)
    runner_index = next(index for index, item in enumerate(data) if item["player_id"] == runner_up)
    assert top_index < runner_index
    assert data[top_index]["rank_label"] == "Quantum Master"


def test_arena_bot_match_streams_round_updates():
    player_id = f"arena-bot-{uuid4().hex[:8]}"
    with client.websocket_connect(f"/arena/ws?player_id={player_id}&display_name=TestPilot&mode=bot") as websocket:
        connected = websocket.receive_json()
        assert connected["type"] == "connected"
        match_found = websocket.receive_json()
        assert match_found["type"] == "match_found"
        challenge = websocket.receive_json()
        assert challenge["type"] == "challenge"
        prompt = challenge["challenge"]["prompt"]
        if challenge["challenge"]["options"]:
            answer = challenge["challenge"]["options"][0]
        elif "softmax" in prompt.lower():
            answer = "np.exp(shifted).sum()"
        elif "optimizer" in prompt.lower():
            answer = "step()"
        elif "reward" in prompt.lower():
            answer = "reward"
        else:
            answer = "target_network"
        websocket.send_json({"type": "answer", "answer": answer})
        round_result = websocket.receive_json()
        assert round_result["type"] == "round_result"
        assert round_result["correct_answer"]
        assert round_result["players"]


def test_arena_status_endpoint_reports_live_counts():
    response = client.get("/arena/status")
    assert response.status_code == 200
    data = response.json()
    assert {"queue_size", "active_matches", "connected_players"} <= set(data)


def test_builder_submit_unlocks_next_scenario_and_share_feed():
    user_headers = {"x-demo-user": f"builder-{uuid4()}", "x-demo-role": "learner"}
    scenarios_response = client.get("/builder/scenarios", headers=user_headers)
    assert scenarios_response.status_code == 200
    scenarios = scenarios_response.json()
    assert scenarios[0]["slug"] == "qcai-hybrid-loop"
    assert scenarios[0]["unlocked"] is True
    assert scenarios[1]["unlocked"] is False

    placements = {
        "slot-ingest": "data-ingest",
        "slot-bottleneck": "feature-bottleneck",
        "slot-quantum": "quantum-routine",
        "slot-measurement": "measurement",
        "slot-postprocess": "classical-postprocess",
    }
    submit_response = client.post(
        "/builder/submit",
        headers=user_headers,
        json={"scenario_slug": "qcai-hybrid-loop", "placements": placements},
    )
    assert submit_response.status_code == 200
    result = submit_response.json()
    assert result["completed"] is True
    assert result["completion_percent"] == 100
    assert result["unlocked_next_slug"] == "control-systems-loop"

    updated_scenarios = client.get("/builder/scenarios", headers=user_headers).json()
    assert updated_scenarios[1]["unlocked"] is True

    share_response = client.post(
        "/builder/share",
        headers=user_headers,
        json={
            "scenario_slug": "qcai-hybrid-loop",
            "caption": "Completed the hybrid loop under hardware constraints.",
            "placements": placements,
        },
    )
    assert share_response.status_code == 200
    feed = client.get("/builder/feed", headers=user_headers).json()
    assert any(item["caption"] == "Completed the hybrid loop under hardware constraints." for item in feed)


def test_learning_dashboard_path_and_skill_gap_flow():
    user_headers = {"x-demo-user": f"insights-{uuid4().hex[:8]}", "x-demo-role": "learner"}

    profile_response = client.put(
        "/insights/profile",
        headers=user_headers,
        json={
            "target_role": "Quantum Optimization Analyst",
            "weekly_goal_hours": 6,
            "preferred_pace": "balanced",
            "focus_area": "optimization",
            "self_ratings": {
                "quantum_hardware": 2,
                "hybrid_architecture": 3,
                "optimization": 2,
                "applied_qcai": 2,
                "representation_xai": 2,
                "industry_strategy": 2,
                "roadmapping": 2,
            },
        },
    )
    assert profile_response.status_code == 200
    assert profile_response.json()["target_role"] == "Quantum Optimization Analyst"

    note_response = client.post(
        "/content/lessons/ai4qc-routing-and-optimization/notes",
        headers=user_headers,
        json={"body": "Need to compare graph shrinking and routing depth before the next optimization run."},
    )
    assert note_response.status_code == 200

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

    pulse_response = client.post(
        "/insights/check-ins",
        headers=user_headers,
        json={
            "motivation_level": 4,
            "focus_level": 3,
            "energy_level": 4,
            "session_minutes": 45,
            "today_goal": "Close the optimization gap for my target role.",
            "blocker": "Still weak on routing tradeoffs.",
        },
    )
    assert pulse_response.status_code == 200
    assert pulse_response.json()["blocker"] == "Still weak on routing tradeoffs."

    dashboard_response = client.get("/insights/dashboard", headers=user_headers)
    assert dashboard_response.status_code == 200
    dashboard = dashboard_response.json()
    assert dashboard["profile"]["target_role"] == "Quantum Optimization Analyst"
    assert dashboard["metrics"]["focus_score"] > 0
    assert dashboard["activity"]
    assert len(dashboard["heatmap"]) == 90
    assert dashboard["recommendations"]
    assert dashboard["coach_feedback"]["recommended_actions"]

    path_response = client.get("/insights/path", headers=user_headers)
    assert path_response.status_code == 200
    path = path_response.json()
    assert path["steps"]
    assert path["steps"][0]["href"].startswith("/")

    gap_response = client.get("/insights/skill-gap", headers=user_headers)
    assert gap_response.status_code == 200
    gap_report = gap_response.json()
    assert gap_report["target_role"] == "Quantum Optimization Analyst"
    assert gap_report["gaps"]
    assert gap_report["recommendations"]

    feedback_response = client.post(
        "/insights/realtime-feedback",
        headers=user_headers,
        json={
            "context_type": "project_submission",
            "project_slug": "routing-rescue-playbook",
            "content": "Routing depth is still inflating SWAP count. I need a better graph shrinking and baseline comparison plan for the QUBO workflow.",
        },
    )
    assert feedback_response.status_code == 200
    feedback = feedback_response.json()
    assert feedback["signal"] in {"advance", "stabilize"}
    assert feedback["suggested_resources"]


def test_project_submission_and_peer_review_flow():
    author_headers = {"x-demo-user": f"project-author-{uuid4().hex[:8]}", "x-demo-role": "learner"}
    reviewer_headers = {"x-demo-user": f"project-reviewer-{uuid4().hex[:8]}", "x-demo-role": "learner"}

    catalog_response = client.get("/projects/catalog", headers=author_headers)
    assert catalog_response.status_code == 200
    catalog = catalog_response.json()
    assert len(catalog) >= 3

    submission_response = client.post(
        "/projects/submissions",
        headers=author_headers,
        json={
            "project_slug": "routing-rescue-playbook",
            "title": "Routing rescue for constrained logistics",
            "solution_summary": "I propose a hardware-aware rescue workflow that shrinks the QUBO graph before routing, then validates the reduced instance against a classical baseline so the claimed gain stays honest and measurable.",
            "implementation_notes": "The plan explicitly tracks SWAP depth, post-routing circuit depth, and a fallback classical solver. It introduces graph shrinking before quantum execution and compares solution quality and runtime against a classical control path.",
            "confidence_level": 4,
        },
    )
    assert submission_response.status_code == 200
    submission = submission_response.json()
    assert submission["project_slug"] == "routing-rescue-playbook"
    assert submission["ai_feedback_summary"]

    author_submissions = client.get("/projects/my-submissions", headers=author_headers)
    assert author_submissions.status_code == 200
    assert any(item["title"] == "Routing rescue for constrained logistics" for item in author_submissions.json())

    queue_response = client.get("/projects/review-queue", headers=reviewer_headers)
    assert queue_response.status_code == 200
    queue = queue_response.json()
    queued_item = next(item for item in queue if item["submission_id"] == submission["id"])

    review_response = client.post(
        "/projects/reviews",
        headers=reviewer_headers,
        json={
            "submission_id": queued_item["submission_id"],
            "rubric_scores": {criterion["id"]: 4 for criterion in queued_item["rubric"]},
            "feedback": "Strong systems grounding and baseline awareness. Tighten the validation thresholds so the routing rescue can be audited more easily.",
        },
    )
    assert review_response.status_code == 200
    assert review_response.json()["overall_score"] == 4.0

    updated_submissions = client.get("/projects/my-submissions", headers=author_headers)
    assert updated_submissions.status_code == 200
    updated = next(item for item in updated_submissions.json() if item["id"] == submission["id"])
    assert updated["review_count"] == 1
    assert updated["average_peer_score"] == 4.0


def test_project_submission_can_be_retracted_without_hard_delete():
    author_headers = {"x-demo-user": f"retract-author-{uuid4().hex[:8]}", "x-demo-role": "learner"}
    reviewer_headers = {"x-demo-user": f"retract-reviewer-{uuid4().hex[:8]}", "x-demo-role": "learner"}

    submission_response = client.post(
        "/projects/submissions",
        headers=author_headers,
        json={
            "project_slug": "post-quantum-migration-roadmap",
            "title": "Migration plan draft",
            "solution_summary": "This draft prioritizes store-now-decrypt-later risk, creates a staged cryptographic inventory, and aligns baseline controls with a phased migration plan across the organization.",
            "implementation_notes": "The roadmap names governance checkpoints, risk-ranked assets, baseline comparisons, validation metrics, and communication milestones so the transition can be audited rather than treated as a one-off rollout.",
            "confidence_level": 3,
        },
    )
    assert submission_response.status_code == 200
    submission = submission_response.json()

    queue_before = client.get("/projects/review-queue", headers=reviewer_headers)
    assert queue_before.status_code == 200
    assert any(item["submission_id"] == submission["id"] for item in queue_before.json())

    retract_response = client.delete(f"/projects/submissions/{submission['id']}", headers=author_headers)
    assert retract_response.status_code == 200
    assert retract_response.json()["status"] == "retracted"

    queue_after = client.get("/projects/review-queue", headers=reviewer_headers)
    assert queue_after.status_code == 200
    assert not any(item["submission_id"] == submission["id"] for item in queue_after.json())


def test_qa_endpoint_rate_limits_repeated_requests():
    user_headers = {"x-demo-user": f"qa-limit-{uuid4().hex[:8]}", "x-demo-role": "learner"}
    for _ in range(5):
        response = client.post(
            "/qa/ask",
            headers=user_headers,
            json={"question": "Why does routing depth matter?", "lesson_slug": "ai4qc-routing-and-optimization"},
        )
        assert response.status_code == 200

    blocked = client.post(
        "/qa/ask",
        headers=user_headers,
        json={"question": "Why does routing depth matter?", "lesson_slug": "ai4qc-routing-and-optimization"},
    )
    assert blocked.status_code == 429


def test_search_endpoint_rate_limits_repeated_requests():
    user_headers = {"x-demo-user": f"search-limit-{uuid4().hex[:8]}", "x-demo-role": "learner"}
    for _ in range(10):
        response = client.get("/search", headers=user_headers, params={"query": "QUBO logistics"})
        assert response.status_code == 200

    blocked = client.get("/search", headers=user_headers, params={"query": "QUBO logistics"})
    assert blocked.status_code == 429


def test_retrieval_engine_merges_semantic_and_lexical_results():
    store = get_course_store()
    engine = RetrievalEngine(store, Settings())

    class StubSemanticBackend:
        enabled = True

        def search(self, query: str, lesson_slug: str | None = None, top_k: int = 8):
            return [
                store.search(query, lesson_slug=lesson_slug, top_k=1)[0].model_copy(update={"score": 0.99}),
                store.search("post-quantum cryptography", top_k=1)[0].model_copy(update={"score": 0.91}),
            ]

    engine._semantic_backend = StubSemanticBackend()
    response = engine.search("QUBO logistics", top_k=3)

    assert response.mode == "hybrid-pinecone"
    assert len(response.results) == 3
    assert response.results[0].chunk_id == store.search("QUBO logistics", top_k=1)[0].chunk_id
