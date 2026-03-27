from pathlib import Path
from uuid import uuid4

from fastapi.testclient import TestClient

from app.core.db import SessionLocal
from app.db_models import ArenaProfile
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
    "Industry Use Cases.mp4",
    "Quantum Computing and Artificial Intelligence 2025.mp4",
    "Quantum Computing and Artificial Intelligence 2026.mp4",
}
DISPLAY_VIDEO_TITLES = {
    "Industry Use Cases",
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
    assert data["related_lessons"]
    assert data["video_asset"]["filename"] == "Quantum Computing and Artificial Intelligence 2025.mp4"
    assert data["video_asset"]["title"] == "Quantum Computing and Artificial Intelligence 2025"
    assert data["video_asset"]["download_url"] == "/source-assets/by-id/quantum-computing-and-artificial-intelligence-2025"


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


def test_search_returns_results():
    response = client.get("/search", params={"query": "QUBO logistics"})
    assert response.status_code == 200
    data = response.json()
    assert data
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
    assert "Industry Use Cases.mp4" in video_filenames
    assert "Quantum Computing and Artificial Intelligence 2025.mp4" in video_filenames
    assert "Quantum Computing and Artificial Intelligence 2026.mp4" in video_filenames
    video_urls = [asset["download_url"] for asset in assets if asset["kind"] == "video"]
    assert all(url.startswith("/source-assets/by-id/") for url in video_urls)
    assert not any(any(raw_title in url for raw_title in RAW_VIDEO_TITLES) for url in video_urls)


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


def test_guest_cookie_auth_is_supported():
    guest_id = "guest-123e4567-e89b-12d3-a456-426614174000"
    with TestClient(app) as cookie_client:
        cookie_client.cookies.set("qcai_guest_id", guest_id)
        response = cookie_client.get("/auth/me")
        assert response.status_code == 200
        assert response.json()["user_id"] == guest_id
        assert response.json()["role"] == "learner"


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
        session.add_all(
            [
                ArenaProfile(
                    player_id=top_player,
                    display_name="Top Player",
                    xp=9000,
                    matches_played=12,
                    wins=9,
                    skill_rating=1290,
                    adaptive_level=4,
                ),
                ArenaProfile(
                    player_id=runner_up,
                    display_name="Runner Up",
                    xp=8500,
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
