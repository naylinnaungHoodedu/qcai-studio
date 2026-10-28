from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db_models import ArenaMatchRecord, ArenaProfile, BuilderRun, BuilderShare, PeerReview, ProjectSubmission


REPO_ROOT = Path(__file__).resolve().parents[4]
DEFAULT_FIXTURES_ROOT = REPO_ROOT / "seeds" / "demo"


@dataclass
class SeedActionCounts:
    created: int = 0
    updated: int = 0
    unchanged: int = 0


@dataclass
class DemoSeedReport:
    project_submission: SeedActionCounts
    peer_review: SeedActionCounts
    builder_run: SeedActionCounts
    builder_share: SeedActionCounts
    arena_profile: SeedActionCounts
    arena_match_record: SeedActionCounts

    @property
    def total_created(self) -> int:
        return sum(
            item.created
            for item in (
                self.project_submission,
                self.peer_review,
                self.builder_run,
                self.builder_share,
                self.arena_profile,
                self.arena_match_record,
            )
        )

    @property
    def total_updated(self) -> int:
        return sum(
            item.updated
            for item in (
                self.project_submission,
                self.peer_review,
                self.builder_run,
                self.builder_share,
                self.arena_profile,
                self.arena_match_record,
            )
        )

    @property
    def total_unchanged(self) -> int:
        return sum(
            item.unchanged
            for item in (
                self.project_submission,
                self.peer_review,
                self.builder_run,
                self.builder_share,
                self.arena_profile,
                self.arena_match_record,
            )
        )


def _parse_timestamp(value: str | None) -> datetime | None:
    if not value:
        return None
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        return parsed
    return parsed.astimezone(UTC).replace(tzinfo=None)


def _load_fixture(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _set_fields_if_changed(model: object, values: dict[str, Any]) -> bool:
    changed = False
    for field_name, value in values.items():
        if getattr(model, field_name) != value:
            setattr(model, field_name, value)
            changed = True
    return changed


def _upsert_project_submission(db: Session, fixture: dict[str, Any]) -> SeedActionCounts:
    counts = SeedActionCounts()
    submission_payload = fixture["submission"]
    submission = db.scalars(
        select(ProjectSubmission).where(
            ProjectSubmission.user_id == submission_payload["user_id"],
            ProjectSubmission.project_slug == submission_payload["project_slug"],
        )
    ).first()
    payload = {
        "user_id": submission_payload["user_id"],
        "project_slug": submission_payload["project_slug"],
        "title": submission_payload["title"],
        "solution_summary": submission_payload["solution_summary"],
        "implementation_notes": submission_payload["implementation_notes"],
        "confidence_level": submission_payload["confidence_level"],
        "status": submission_payload.get("status", "submitted"),
        "is_deleted": False,
        "ai_feedback_summary": submission_payload["ai_feedback_summary"],
        "ai_recommendations": submission_payload["ai_recommendations"],
        "created_at": _parse_timestamp(submission_payload.get("created_at")),
    }
    if submission is None:
        db.add(ProjectSubmission(**payload))
        counts.created += 1
        return counts
    if _set_fields_if_changed(submission, payload):
        counts.updated += 1
    else:
        counts.unchanged += 1
    return counts


def _upsert_peer_review(db: Session, fixture: dict[str, Any]) -> SeedActionCounts:
    counts = SeedActionCounts()
    submission_payload = fixture["submission"]
    review_payload = fixture["review"]
    submission = db.scalars(
        select(ProjectSubmission).where(
            ProjectSubmission.user_id == submission_payload["user_id"],
            ProjectSubmission.project_slug == submission_payload["project_slug"],
        )
    ).first()
    if submission is None:
        raise ValueError("Seeded project submission must exist before seeding the peer review.")
    review = db.scalars(
        select(PeerReview).where(
            PeerReview.submission_id == submission.id,
            PeerReview.reviewer_user_id == review_payload["reviewer_user_id"],
        )
    ).first()
    rubric_scores = {key: int(value) for key, value in review_payload["rubric_scores"].items()}
    overall_score = round(sum(rubric_scores.values()) / len(rubric_scores), 1)
    payload = {
        "submission_id": submission.id,
        "reviewer_user_id": review_payload["reviewer_user_id"],
        "rubric_scores": rubric_scores,
        "overall_score": overall_score,
        "feedback": review_payload["feedback"],
        "created_at": _parse_timestamp(review_payload.get("created_at")),
    }
    if review is None:
        db.add(PeerReview(**payload))
        counts.created += 1
        return counts
    if _set_fields_if_changed(review, payload):
        counts.updated += 1
    else:
        counts.unchanged += 1
    return counts


def _upsert_builder_run(db: Session, fixture: dict[str, Any]) -> SeedActionCounts:
    counts = SeedActionCounts()
    run_payload = fixture["builder_run"]
    run = db.scalars(
        select(BuilderRun).where(
            BuilderRun.user_id == run_payload["user_id"],
            BuilderRun.scenario_slug == run_payload["scenario_slug"],
        )
    ).first()
    payload = {
        "user_id": run_payload["user_id"],
        "scenario_slug": run_payload["scenario_slug"],
        "placements": run_payload["placements"],
        "correct_slots": run_payload["correct_slots"],
        "total_slots": run_payload["total_slots"],
        "completion_percent": run_payload["completion_percent"],
        "points_earned": run_payload["points_earned"],
        "status": run_payload.get("status", "completed"),
        "created_at": _parse_timestamp(run_payload.get("created_at")),
    }
    if run is None:
        db.add(BuilderRun(**payload))
        counts.created += 1
        return counts
    if _set_fields_if_changed(run, payload):
        counts.updated += 1
    else:
        counts.unchanged += 1
    return counts


def _upsert_builder_share(db: Session, fixture: dict[str, Any]) -> SeedActionCounts:
    counts = SeedActionCounts()
    share_payload = fixture["share"]
    share = db.scalars(
        select(BuilderShare).where(
            BuilderShare.user_id == share_payload["user_id"],
            BuilderShare.scenario_slug == share_payload["scenario_slug"],
        )
    ).first()
    payload = {
        "user_id": share_payload["user_id"],
        "scenario_slug": share_payload["scenario_slug"],
        "caption": share_payload["caption"],
        "completion_percent": share_payload["completion_percent"],
        "map_snapshot": share_payload["map_snapshot"],
        "created_at": _parse_timestamp(share_payload.get("created_at")),
    }
    if share is None:
        db.add(BuilderShare(**payload))
        counts.created += 1
        return counts
    if _set_fields_if_changed(share, payload):
        counts.updated += 1
    else:
        counts.unchanged += 1
    return counts


def _upsert_arena_profile(db: Session, fixture: dict[str, Any]) -> SeedActionCounts:
    counts = SeedActionCounts()
    profile_payload = fixture["profile"]
    profile = db.scalars(select(ArenaProfile).where(ArenaProfile.player_id == profile_payload["player_id"])).first()
    payload = {
        "player_id": profile_payload["player_id"],
        "display_name": profile_payload["display_name"],
        "xp": profile_payload["xp"],
        "matches_played": profile_payload["matches_played"],
        "wins": profile_payload["wins"],
        "skill_rating": profile_payload["skill_rating"],
        "adaptive_level": profile_payload["adaptive_level"],
        "created_at": _parse_timestamp(profile_payload.get("created_at")),
        "updated_at": _parse_timestamp(profile_payload.get("updated_at")),
    }
    if profile is None:
        db.add(ArenaProfile(**payload))
        counts.created += 1
        return counts
    if _set_fields_if_changed(profile, payload):
        counts.updated += 1
    else:
        counts.unchanged += 1
    return counts


def _upsert_arena_match_record(db: Session, fixture: dict[str, Any]) -> SeedActionCounts:
    counts = SeedActionCounts()
    record_payload = fixture["match_record"]
    record = db.scalars(
        select(ArenaMatchRecord).where(
            ArenaMatchRecord.player_id == record_payload["player_id"],
            ArenaMatchRecord.opponent_id == record_payload["opponent_id"],
            ArenaMatchRecord.mode == record_payload["mode"],
        )
    ).first()
    payload = {
        "player_id": record_payload["player_id"],
        "opponent_id": record_payload["opponent_id"],
        "mode": record_payload["mode"],
        "result": record_payload["result"],
        "score": record_payload["score"],
        "correct_answers": record_payload["correct_answers"],
        "total_rounds": record_payload["total_rounds"],
        "xp_delta": record_payload["xp_delta"],
        "difficulty_band": record_payload["difficulty_band"],
        "created_at": _parse_timestamp(record_payload.get("created_at")),
    }
    if record is None:
        db.add(ArenaMatchRecord(**payload))
        counts.created += 1
        return counts
    if _set_fields_if_changed(record, payload):
        counts.updated += 1
    else:
        counts.unchanged += 1
    return counts


def seed_demo_data(db: Session, fixtures_root: Path = DEFAULT_FIXTURES_ROOT) -> DemoSeedReport:
    project_fixture = _load_fixture(fixtures_root / "routing-rescue-submission.json")
    builder_fixture = _load_fixture(fixtures_root / "builder-map-hybrid-loop.json")
    arena_fixture = _load_fixture(fixtures_root / "arena-match-log.json")

    project_submission = _upsert_project_submission(db, project_fixture)
    db.flush()
    peer_review = _upsert_peer_review(db, project_fixture)
    builder_run = _upsert_builder_run(db, builder_fixture)
    builder_share = _upsert_builder_share(db, builder_fixture)
    arena_profile = _upsert_arena_profile(db, arena_fixture)
    arena_match_record = _upsert_arena_match_record(db, arena_fixture)
    db.commit()

    return DemoSeedReport(
        project_submission=project_submission,
        peer_review=peer_review,
        builder_run=builder_run,
        builder_share=builder_share,
        arena_profile=arena_profile,
        arena_match_record=arena_match_record,
    )
