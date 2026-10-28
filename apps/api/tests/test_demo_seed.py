from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.core.config import get_settings
from app.core.db import SessionLocal
from app.db_models import ArenaMatchRecord, ArenaProfile, BuilderRun, BuilderShare, PeerReview, ProjectSubmission
from app.main import _initialize_database, app
from app.services.demo_seed import seed_demo_data


_initialize_database()
client = TestClient(app)
FIXTURES_ROOT = Path(__file__).resolve().parents[3] / "seeds" / "demo"


def test_api_test_session_uses_in_memory_database():
    assert get_settings().database_url == "sqlite:///:memory:"


def test_demo_seed_is_idempotent_and_populates_public_activity():
    with SessionLocal() as session:
        first = seed_demo_data(session, FIXTURES_ROOT)
        second = seed_demo_data(session, FIXTURES_ROOT)

        seeded_submission_count = session.scalar(
            select(func.count()).select_from(ProjectSubmission).where(ProjectSubmission.user_id == "fixture-ac-03")
        )
        seeded_review_count = session.scalar(
            select(func.count()).select_from(PeerReview).where(PeerReview.reviewer_user_id == "fixture-ac-06")
        )
        seeded_builder_run_count = session.scalar(
            select(func.count()).select_from(BuilderRun).where(BuilderRun.user_id == "fixture-ac-05")
        )
        seeded_builder_share_count = session.scalar(
            select(func.count()).select_from(BuilderShare).where(BuilderShare.user_id == "fixture-ac-05")
        )
        seeded_arena_profile_count = session.scalar(
            select(func.count()).select_from(ArenaProfile).where(ArenaProfile.player_id == "fixture-ac-07")
        )
        seeded_arena_record_count = session.scalar(
            select(func.count()).select_from(ArenaMatchRecord).where(ArenaMatchRecord.player_id == "fixture-ac-07")
        )

    assert first.project_submission.created == 1
    assert first.peer_review.created == 1
    assert first.builder_share.created == 1
    assert first.arena_profile.created == 1
    assert first.arena_match_record.created == 1
    assert second.total_created == 0
    assert second.total_updated == 0
    assert second.total_unchanged == 6
    assert seeded_submission_count == 1
    assert seeded_review_count == 1
    assert seeded_builder_run_count == 1
    assert seeded_builder_share_count == 1
    assert seeded_arena_profile_count == 1
    assert seeded_arena_record_count == 1

    catalog_response = client.get("/projects/catalog", headers={"x-demo-user": "demo-reviewer", "x-demo-role": "learner"})
    assert catalog_response.status_code == 200
    routing_brief = next(item for item in catalog_response.json() if item["slug"] == "routing-rescue-playbook")
    assert routing_brief["submitted_count"] >= 1
    assert routing_brief["peer_reviews_received"] >= 1

    queue_response = client.get("/projects/review-queue", headers={"x-demo-user": "demo-reviewer", "x-demo-role": "learner"})
    assert queue_response.status_code == 200
    assert any(item["author_id"] == "fixture-ac-03" for item in queue_response.json())

    feed_response = client.get("/builder/feed", headers={"x-demo-user": "demo-builder", "x-demo-role": "learner"})
    assert feed_response.status_code == 200
    assert any(item["user_id"] == "fixture-ac-05" for item in feed_response.json())

    leaderboard_response = client.get("/arena/leaderboard", params={"limit": 50})
    assert leaderboard_response.status_code == 200
    assert any(item["player_id"] == "fixture-ac-07" for item in leaderboard_response.json())

    status_response = client.get("/arena/status")
    assert status_response.status_code == 200
    assert {"queue_size", "active_matches", "connected_players"} <= set(status_response.json())
