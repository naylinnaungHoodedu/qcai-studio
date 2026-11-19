import json
import os
from datetime import datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings
from app.core.db import Base, engine, get_db
from app.core.schema_upgrades import run_schema_upgrades
from app.db_models import ArenaMatchRecord, ArenaProfile, BuilderRun, BuilderShare, PeerReview, ProjectSubmission
from app.main import _initialize_database, app
from app.services import arena_engine
from app.services.demo_seed import seed_demo_data


_initialize_database()
client = TestClient(app)
FIXTURES_ROOT = Path(__file__).resolve().parents[3] / "seeds" / "demo"


def test_api_test_session_uses_a_disposable_database():
    # conftest ignores an ambient DATABASE_URL; only in-memory SQLite or the CI's TEST_DATABASE_URL is used.
    assert get_settings().database_url == os.environ.get("TEST_DATABASE_URL", "sqlite:///:memory:")


@pytest.fixture
def isolated_database(fresh_database_url, monkeypatch):
    """An empty database of the session's dialect with the full schema, which the routes this test reads are served
    from (get_db and the Arena service's sessions). Rows that earlier tests, or earlier runs on a reused PostgreSQL
    database, left behind can then neither turn the first seed into an update nor push the seeded submission off
    the review queue's first page (eight items)."""
    connect_args = {"check_same_thread": False} if fresh_database_url.startswith("sqlite") else {}
    isolated = create_engine(fresh_database_url, connect_args=connect_args)
    Base.metadata.create_all(bind=isolated)
    run_schema_upgrades(isolated)
    factory = sessionmaker(bind=isolated, autoflush=False, autocommit=False)

    def isolated_db():
        db = factory()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = isolated_db
    monkeypatch.setattr(arena_engine, "SessionLocal", factory)
    try:
        yield factory
    finally:
        app.dependency_overrides.pop(get_db, None)
        isolated.dispose()


def test_demo_seed_is_idempotent_and_populates_public_activity(isolated_database):
    with isolated_database() as session:
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
    assert any(item["author_handle"] == "fixture-ac-03" for item in queue_response.json())

    feed_response = client.get("/builder/feed", headers={"x-demo-user": "demo-builder", "x-demo-role": "learner"})
    assert feed_response.status_code == 200
    assert any(item["public_handle"] == "fixture-ac-05" for item in feed_response.json())

    leaderboard_response = client.get("/arena/leaderboard", params={"limit": 50})
    assert leaderboard_response.status_code == 200
    assert any(item["public_handle"] == "fixture-ac-07" for item in leaderboard_response.json())

    status_response = client.get("/arena/status")
    assert status_response.status_code == 200
    assert {"queue_size", "active_matches", "connected_players"} <= set(status_response.json())


@pytest.mark.skipif(engine.dialect.name != "postgresql", reason="timestamptz session time zones are PostgreSQL behaviour")
def test_demo_seed_keeps_fixture_instants_under_a_non_utc_session_time_zone():
    # A naive UTC value written to timestamptz is read as session-local time, which shifted these rows.
    fixture = json.loads((FIXTURES_ROOT / "routing-rescue-submission.json").read_text(encoding="utf-8"))
    expected = datetime.fromisoformat(fixture["submission"]["created_at"].replace("Z", "+00:00"))
    zone = "Asia/Kolkata"  # +05:30, and not the server default of any cluster these tests run on
    # psycopg passes libpq options; pg8000 (the production driver) sends the setting as a startup parameter.
    connect_args = {"startup_params": {"TimeZone": zone}} if engine.dialect.driver == "pg8000" else {"options": f"-c timezone={zone}"}
    non_utc = create_engine(engine.url, connect_args=connect_args)
    try:
        with Session(non_utc) as session:
            assert session.execute(text("SHOW TimeZone")).scalar() == zone
            seed_demo_data(session, FIXTURES_ROOT)
            seed_demo_data(session, FIXTURES_ROOT)
            stored = session.scalar(
                select(ProjectSubmission.created_at).where(ProjectSubmission.user_id == "fixture-ac-03")
            )
    finally:
        non_utc.dispose()

    assert stored == expected
