from collections.abc import Iterable

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db_models import BuilderRun, BuilderShare
from app.schemas import (
    BuilderConnection,
    BuilderFeedItem,
    BuilderNode,
    BuilderProfile,
    BuilderScenario,
    BuilderSlot,
    BuilderSubmissionResult,
)


SCENARIO_DEFINITIONS = [
    {
        "slug": "qcai-hybrid-loop",
        "title": "QC+AI Hybrid Loop",
        "domain": "Quantum Systems",
        "summary": "Assemble a hardware-aware hybrid workflow from data intake through quantum execution and classical interpretation.",
        "unlock_order": 1,
        "points_reward": 180,
        "nodes": [
            {
                "id": "data-ingest",
                "label": "Data Ingest",
                "description": "Collect and normalize the classical signals or optimization state.",
                "color": "#0f766e",
            },
            {
                "id": "feature-bottleneck",
                "label": "Feature Bottleneck",
                "description": "Compress the state into a representation the quantum subroutine can actually support.",
                "color": "#0b5cab",
            },
            {
                "id": "quantum-routine",
                "label": "Quantum Routine",
                "description": "Apply the targeted kernel, circuit, or optimization routine.",
                "color": "#9a3412",
            },
            {
                "id": "measurement",
                "label": "Measurement",
                "description": "Extract observables or bitstrings from the circuit execution.",
                "color": "#5b21b6",
            },
            {
                "id": "classical-postprocess",
                "label": "Classical Post-Process",
                "description": "Interpret outputs, score solutions, and update the control loop.",
                "color": "#be185d",
            },
        ],
        "slots": [
            {
                "id": "slot-ingest",
                "label": "Step 1",
                "description": "Capture the raw problem state before any model compression.",
                "x": 8,
                "y": 30,
            },
            {
                "id": "slot-bottleneck",
                "label": "Step 2",
                "description": "Reduce dimensionality before quantum execution.",
                "x": 28,
                "y": 18,
            },
            {
                "id": "slot-quantum",
                "label": "Step 3",
                "description": "Execute the specialized quantum subroutine.",
                "x": 50,
                "y": 30,
            },
            {
                "id": "slot-measurement",
                "label": "Step 4",
                "description": "Read out the quantum state into classical values.",
                "x": 72,
                "y": 18,
            },
            {
                "id": "slot-postprocess",
                "label": "Step 5",
                "description": "Translate outputs into actions, explanations, or rankings.",
                "x": 84,
                "y": 44,
            },
        ],
        "connections": [
            {"from_slot": "slot-ingest", "to_slot": "slot-bottleneck"},
            {"from_slot": "slot-bottleneck", "to_slot": "slot-quantum"},
            {"from_slot": "slot-quantum", "to_slot": "slot-measurement"},
            {"from_slot": "slot-measurement", "to_slot": "slot-postprocess"},
        ],
        "solution": {
            "slot-ingest": "data-ingest",
            "slot-bottleneck": "feature-bottleneck",
            "slot-quantum": "quantum-routine",
            "slot-measurement": "measurement",
            "slot-postprocess": "classical-postprocess",
        },
    },
    {
        "slug": "control-systems-loop",
        "title": "Control Systems Stability Loop",
        "domain": "Control Engineering",
        "summary": "Construct a resilient closed-loop control circuit with the right sensing, actuation, and feedback ordering.",
        "unlock_order": 2,
        "points_reward": 200,
        "nodes": [
            {
                "id": "reference-signal",
                "label": "Reference Signal",
                "description": "Define the target state or setpoint.",
                "color": "#1d4ed8",
            },
            {
                "id": "controller",
                "label": "Controller",
                "description": "Generate the correction command based on error.",
                "color": "#0f766e",
            },
            {
                "id": "actuator",
                "label": "Actuator",
                "description": "Apply the physical control action to the plant.",
                "color": "#9a3412",
            },
            {
                "id": "plant",
                "label": "Plant",
                "description": "The system whose state is being controlled.",
                "color": "#7c3aed",
            },
            {
                "id": "sensor-feedback",
                "label": "Sensor Feedback",
                "description": "Measure output and return it to the controller.",
                "color": "#be185d",
            },
        ],
        "slots": [
            {
                "id": "slot-reference",
                "label": "Setpoint",
                "description": "Desired target value enters the loop here.",
                "x": 10,
                "y": 48,
            },
            {
                "id": "slot-controller",
                "label": "Control Law",
                "description": "Decision stage that turns error into action.",
                "x": 30,
                "y": 22,
            },
            {
                "id": "slot-actuator",
                "label": "Drive",
                "description": "Converts the signal into physical motion or force.",
                "x": 52,
                "y": 22,
            },
            {
                "id": "slot-plant",
                "label": "Plant",
                "description": "Physical system under control.",
                "x": 74,
                "y": 48,
            },
            {
                "id": "slot-feedback",
                "label": "Feedback Path",
                "description": "Closes the loop with measured output.",
                "x": 42,
                "y": 72,
            },
        ],
        "connections": [
            {"from_slot": "slot-reference", "to_slot": "slot-controller"},
            {"from_slot": "slot-controller", "to_slot": "slot-actuator"},
            {"from_slot": "slot-actuator", "to_slot": "slot-plant"},
            {"from_slot": "slot-plant", "to_slot": "slot-feedback"},
            {"from_slot": "slot-feedback", "to_slot": "slot-controller"},
        ],
        "solution": {
            "slot-reference": "reference-signal",
            "slot-controller": "controller",
            "slot-actuator": "actuator",
            "slot-plant": "plant",
            "slot-feedback": "sensor-feedback",
        },
    },
    {
        "slug": "safety-permit-chain",
        "title": "Safety Permit Dependency Chain",
        "domain": "Operations Safety",
        "summary": "Place the permit, isolation, and execution concepts into a defensible safety workflow.",
        "unlock_order": 3,
        "points_reward": 220,
        "nodes": [
            {
                "id": "hazard-review",
                "label": "Hazard Review",
                "description": "Identify task risks and operating boundaries.",
                "color": "#b91c1c",
            },
            {
                "id": "isolation-plan",
                "label": "Isolation Plan",
                "description": "Define lockout, tagout, and energy isolation controls.",
                "color": "#9a3412",
            },
            {
                "id": "permit-approval",
                "label": "Permit Approval",
                "description": "Authorize execution only after controls are verified.",
                "color": "#0f766e",
            },
            {
                "id": "field-execution",
                "label": "Field Execution",
                "description": "Carry out the maintenance or operational task.",
                "color": "#2563eb",
            },
            {
                "id": "closeout-review",
                "label": "Closeout Review",
                "description": "Confirm restoration, learning capture, and handback.",
                "color": "#7c3aed",
            },
        ],
        "slots": [
            {
                "id": "slot-hazard",
                "label": "Review",
                "description": "Work begins with the pre-task risk view.",
                "x": 10,
                "y": 40,
            },
            {
                "id": "slot-isolation",
                "label": "Control",
                "description": "Controls are defined before the permit is released.",
                "x": 30,
                "y": 20,
            },
            {
                "id": "slot-permit",
                "label": "Authorize",
                "description": "The formal permission gate.",
                "x": 52,
                "y": 20,
            },
            {
                "id": "slot-execution",
                "label": "Execute",
                "description": "Task work under the approved permit.",
                "x": 74,
                "y": 40,
            },
            {
                "id": "slot-closeout",
                "label": "Closeout",
                "description": "Restore service and capture lessons.",
                "x": 88,
                "y": 66,
            },
        ],
        "connections": [
            {"from_slot": "slot-hazard", "to_slot": "slot-isolation"},
            {"from_slot": "slot-isolation", "to_slot": "slot-permit"},
            {"from_slot": "slot-permit", "to_slot": "slot-execution"},
            {"from_slot": "slot-execution", "to_slot": "slot-closeout"},
        ],
        "solution": {
            "slot-hazard": "hazard-review",
            "slot-isolation": "isolation-plan",
            "slot-permit": "permit-approval",
            "slot-execution": "field-execution",
            "slot-closeout": "closeout-review",
        },
    },
]


def _find_scenario(slug: str) -> dict | None:
    return next((scenario for scenario in SCENARIO_DEFINITIONS if scenario["slug"] == slug), None)


def _best_completion_by_slug(records: Iterable[BuilderRun]) -> dict[str, int]:
    best: dict[str, int] = {}
    for record in records:
        current = best.get(record.scenario_slug, 0)
        if record.completion_percent > current:
            best[record.scenario_slug] = record.completion_percent
    return best


def _completed_scenarios(best_completion: dict[str, int]) -> set[str]:
    return {slug for slug, percent in best_completion.items() if percent >= 100}


def _derive_badges(total_points: int, current_streak: int, completed_count: int, share_count: int) -> list[str]:
    badges: list[str] = []
    if completed_count >= 1:
        badges.append("Circuit Starter")
    if total_points >= 350:
        badges.append("Graph Builder")
    if current_streak >= 2:
        badges.append("Streak Operator")
    if completed_count == len(SCENARIO_DEFINITIONS):
        badges.append("Dependency Architect")
    if share_count >= 1:
        badges.append("Map Publisher")
    return badges


def _compute_current_streak(records: list[BuilderRun]) -> int:
    streak = 0
    for record in records:
        if record.status != "completed":
            break
        streak += 1
    return streak


def get_builder_profile(db: Session, user_id: str) -> BuilderProfile:
    records = db.scalars(
        select(BuilderRun).where(BuilderRun.user_id == user_id).order_by(BuilderRun.created_at.desc(), BuilderRun.id.desc())
    ).all()
    shares = db.scalars(select(BuilderShare).where(BuilderShare.user_id == user_id)).all()
    total_points = sum(record.points_earned for record in records)
    best_completion = _best_completion_by_slug(records)
    completed = _completed_scenarios(best_completion)
    completed_count = len(completed)
    unlocked = min(len(SCENARIO_DEFINITIONS), completed_count + 1)
    next_challenge = next(
        (scenario["slug"] for scenario in SCENARIO_DEFINITIONS if scenario["unlock_order"] == unlocked and scenario["slug"] not in completed),
        None,
    )
    completion_percent = round((completed_count / len(SCENARIO_DEFINITIONS)) * 100) if SCENARIO_DEFINITIONS else 0
    current_streak = _compute_current_streak(records)
    return BuilderProfile(
        user_id=user_id,
        total_points=total_points,
        current_streak=current_streak,
        completion_percent=completion_percent,
        completed_scenarios=completed_count,
        unlocked_scenarios=unlocked,
        badges=_derive_badges(total_points, current_streak, completed_count, len(shares)),
        next_challenge_slug=next_challenge,
    )


def list_builder_scenarios(db: Session, user_id: str) -> list[BuilderScenario]:
    records = db.scalars(select(BuilderRun).where(BuilderRun.user_id == user_id)).all()
    best_completion = _best_completion_by_slug(records)
    completed = _completed_scenarios(best_completion)
    unlocked_order = min(len(SCENARIO_DEFINITIONS), len(completed) + 1)
    scenarios: list[BuilderScenario] = []
    for scenario in SCENARIO_DEFINITIONS:
        scenarios.append(
            BuilderScenario(
                slug=scenario["slug"],
                title=scenario["title"],
                domain=scenario["domain"],
                summary=scenario["summary"],
                unlock_order=scenario["unlock_order"],
                points_reward=scenario["points_reward"],
                nodes=[BuilderNode(**node) for node in scenario["nodes"]],
                slots=[BuilderSlot(**slot) for slot in scenario["slots"]],
                connections=[BuilderConnection(**connection) for connection in scenario["connections"]],
                unlocked=scenario["unlock_order"] <= unlocked_order,
                completed=scenario["slug"] in completed,
                best_completion_percent=best_completion.get(scenario["slug"], 0),
            )
        )
    return scenarios


def submit_builder_run(db: Session, user_id: str, scenario_slug: str, placements: dict[str, str]) -> BuilderSubmissionResult:
    scenario = _find_scenario(scenario_slug)
    if not scenario:
        raise ValueError("Scenario not found.")

    solution = scenario["solution"]
    incorrect_slots = sorted([slot_id for slot_id, expected in solution.items() if placements.get(slot_id) != expected])
    correct_slots = len(solution) - len(incorrect_slots)
    total_slots = len(solution)
    completion_percent = round((correct_slots / total_slots) * 100) if total_slots else 0
    completed = correct_slots == total_slots
    points_earned = correct_slots * 20 + (scenario["points_reward"] if completed else 0)

    db.add(
        BuilderRun(
            user_id=user_id,
            scenario_slug=scenario_slug,
            placements=placements,
            correct_slots=correct_slots,
            total_slots=total_slots,
            completion_percent=completion_percent,
            points_earned=points_earned,
            status="completed" if completed else "in_progress",
        )
    )
    db.commit()

    profile = get_builder_profile(db, user_id)
    unlocked_next = next(
        (
            item["slug"]
            for item in SCENARIO_DEFINITIONS
            if item["unlock_order"] == profile.unlocked_scenarios and item["slug"] != scenario_slug
        ),
        None,
    )
    return BuilderSubmissionResult(
        scenario_slug=scenario_slug,
        completion_percent=completion_percent,
        correct_slots=correct_slots,
        total_slots=total_slots,
        points_earned=points_earned,
        unlocked_next_slug=unlocked_next,
        completed=completed,
        incorrect_slots=incorrect_slots,
        current_streak=profile.current_streak,
        badges=profile.badges,
    )


def share_builder_map(
    db: Session,
    user_id: str,
    scenario_slug: str,
    caption: str,
    placements: dict[str, str],
) -> BuilderFeedItem:
    scenario = _find_scenario(scenario_slug)
    if not scenario:
        raise ValueError("Scenario not found.")

    latest_completed = db.scalars(
        select(BuilderRun)
        .where(
            BuilderRun.user_id == user_id,
            BuilderRun.scenario_slug == scenario_slug,
            BuilderRun.status == "completed",
        )
        .order_by(BuilderRun.created_at.desc(), BuilderRun.id.desc())
    ).first()
    if not latest_completed:
        raise ValueError("Complete the scenario before sharing it.")

    share = BuilderShare(
        user_id=user_id,
        scenario_slug=scenario_slug,
        caption=caption,
        completion_percent=latest_completed.completion_percent,
        map_snapshot=placements or latest_completed.placements,
    )
    db.add(share)
    db.commit()
    db.refresh(share)
    return BuilderFeedItem(
        id=share.id,
        user_id=share.user_id,
        scenario_slug=share.scenario_slug,
        scenario_title=scenario["title"],
        caption=share.caption,
        completion_percent=share.completion_percent,
        created_at=share.created_at,
    )


def list_builder_feed(db: Session, limit: int = 12) -> list[BuilderFeedItem]:
    shares = db.scalars(select(BuilderShare).order_by(BuilderShare.created_at.desc(), BuilderShare.id.desc())).all()
    items: list[BuilderFeedItem] = []
    for share in shares[:limit]:
        scenario = _find_scenario(share.scenario_slug)
        items.append(
            BuilderFeedItem(
                id=share.id,
                user_id=share.user_id,
                scenario_slug=share.scenario_slug,
                scenario_title=scenario["title"] if scenario else share.scenario_slug,
                caption=share.caption,
                completion_percent=share.completion_percent,
                created_at=share.created_at,
            )
        )
    return items
