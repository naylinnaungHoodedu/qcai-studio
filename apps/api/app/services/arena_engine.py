import asyncio
from collections import deque
import random
import time
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any
from uuid import uuid4

from fastapi import WebSocket
from sqlalchemy import select

from app.core.db import SessionLocal
from app.db_models import ArenaMatchRecord, ArenaProfile
from app.schemas import ArenaLeaderboardEntry, ArenaProfileRead
from app.services.text_utils import sanitize_user_text


ROUND_COUNT = 5
ROUND_DURATION_SECONDS = 24
ROUND_ADVANCE_DELAY_SECONDS = 2.2


@dataclass(frozen=True)
class ArenaChallenge:
    id: str
    title: str
    topic: str
    difficulty: int
    kind: str
    scenario: str
    prompt: str
    options: list[str] = field(default_factory=list)
    accepted_answers: list[str] = field(default_factory=list)
    explanation: str = ""
    starter_code: str | None = None

    def to_client_payload(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "topic": self.topic,
            "difficulty": self.difficulty,
            "kind": self.kind,
            "scenario": self.scenario,
            "prompt": self.prompt,
            "options": self.options,
            "starter_code": self.starter_code,
        }


CHALLENGE_BANK: list[ArenaChallenge] = [
    ArenaChallenge(
        id="qai-1",
        title="Hybrid Workflow Gatekeeper",
        topic="Quantum Systems",
        difficulty=1,
        kind="mcq",
        scenario="A portfolio-optimization team needs a compact quantum stage without replacing the classical pipeline.",
        prompt="Which architectural pattern best fits the source corpus?",
        options=[
            "Use a narrow quantum bottleneck inside a larger classical workflow",
            "Replace all preprocessing and post-processing with one variational circuit",
            "Avoid measurement and keep the model fully latent",
            "Skip routing and compilation analysis to preserve speedup claims",
        ],
        accepted_answers=["Use a narrow quantum bottleneck inside a larger classical workflow"],
        explanation="The course repeatedly argues for targeted quantum subroutines embedded inside larger classical systems.",
    ),
    ArenaChallenge(
        id="qai-2",
        title="Optimization Pressure",
        topic="Quantum Optimization",
        difficulty=2,
        kind="mcq",
        scenario="A logistics model must fit a constrained QUBO onto limited hardware.",
        prompt="Which step most directly reduces instance size before quantum execution?",
        options=[
            "Graph shrinking",
            "Increasing token overlap",
            "Removing the measurement stage",
            "Switching to a larger learning rate",
        ],
        accepted_answers=["Graph shrinking"],
        explanation="Graph shrinking is presented as a practical compression strategy for limited qubit budgets.",
    ),
    ArenaChallenge(
        id="qai-3",
        title="Stable Softmax Patch",
        topic="AI/ML",
        difficulty=2,
        kind="code",
        scenario="You need the missing line in a numerically stable softmax snippet.",
        prompt="Complete the missing expression after `shifted = logits - logits.max()`.",
        starter_code="probs = np.exp(shifted) / __________",
        accepted_answers=["np.exp(shifted).sum()", "exp(shifted).sum()"],
        explanation="The denominator in stable softmax is the sum of exponentiated shifted logits.",
    ),
    ArenaChallenge(
        id="qai-4",
        title="Routing Reality Check",
        topic="Quantum Hardware",
        difficulty=2,
        kind="mcq",
        scenario="A team claims algorithmic advantage but ignores sparse connectivity costs.",
        prompt="What practical effect can poor routing have?",
        options=[
            "It can add SWAP depth and destroy executable fidelity",
            "It removes the need for classical orchestration",
            "It guarantees thermodynamic advantage",
            "It automatically improves qubit coherence",
        ],
        accepted_answers=["It can add SWAP depth and destroy executable fidelity"],
        explanation="Routing overhead is treated as a physical systems bottleneck, not a cosmetic compiler concern.",
    ),
    ArenaChallenge(
        id="qai-5",
        title="Gradient Step",
        topic="AI/ML",
        difficulty=1,
        kind="code",
        scenario="A PyTorch training loop has already called `loss.backward()`.",
        prompt="Which call advances the optimizer?",
        starter_code="loss.backward()\noptimizer.__________",
        accepted_answers=["step()", "step"],
        explanation="`optimizer.step()` applies the update after gradients have been populated.",
    ),
    ArenaChallenge(
        id="qai-6",
        title="Kernel Placement",
        topic="Biomedical AI",
        difficulty=3,
        kind="mcq",
        scenario="A biomedical-imaging workflow wants a quantum contribution without replacing the entire model.",
        prompt="Where is the quantum component most plausibly placed?",
        options=[
            "As a kernel or compact feature transformation inside a classical pipeline",
            "As the only deployment-stage component",
            "Only after removing all regularization",
            "As a substitute for the data acquisition process",
        ],
        accepted_answers=["As a kernel or compact feature transformation inside a classical pipeline"],
        explanation="The practical application papers place the quantum role at a bounded, interpretable bottleneck.",
    ),
    ArenaChallenge(
        id="qai-7",
        title="Bellman Completion",
        topic="AI/ML",
        difficulty=3,
        kind="code",
        scenario="You are updating a Q-learning target.",
        prompt="Fill the missing token in `target = reward + gamma * max_next_q * (1 - done)`.",
        starter_code="target = ________ + gamma * max_next_q * (1 - done)",
        accepted_answers=["reward"],
        explanation="The immediate reward anchors the Bellman-style backup before discounted continuation.",
    ),
    ArenaChallenge(
        id="qai-8",
        title="Post-Quantum Urgency",
        topic="Cybersecurity",
        difficulty=3,
        kind="mcq",
        scenario="A security lead asks why post-quantum migration is urgent now rather than later.",
        prompt="Which argument best matches the industry-use-case lesson?",
        options=[
            "Store-now-decrypt-later risks make delayed migration dangerous",
            "Quantum networks eliminate all compliance obligations",
            "Classical cryptography has already failed everywhere",
            "Blockchains automatically become quantum-safe at runtime",
        ],
        accepted_answers=["Store-now-decrypt-later risks make delayed migration dangerous"],
        explanation="The lesson frames cybersecurity as a transition problem with present-day consequences.",
    ),
    ArenaChallenge(
        id="qai-9",
        title="QAOA Cost Layer",
        topic="Quantum Optimization",
        difficulty=4,
        kind="mcq",
        scenario="A candidate proposes the wrong gate family for the QAOA cost operator.",
        prompt="Which gates most naturally encode the cost Hamiltonian phase in a diagonal Ising/QUBO setting?",
        options=[
            "Z-rotation style phase operators",
            "Only Hadamard gates",
            "Measurement gates during state preparation",
            "Reset gates after every layer",
        ],
        accepted_answers=["Z-rotation style phase operators"],
        explanation="Diagonal cost Hamiltonians are typically represented through phase rotations in the computational basis.",
    ),
    ArenaChallenge(
        id="qai-10",
        title="Tensor Shape Guardrail",
        topic="AI/ML",
        difficulty=4,
        kind="code",
        scenario="A batch of 32 samples each has 128 features entering a dense layer.",
        prompt="What is the input tensor shape?",
        starter_code="shape = (____, ____)",
        accepted_answers=["32,128", "(32,128)", "32, 128", "(32, 128)"],
        explanation="The conventional batch-first shape is `(batch_size, feature_count)`.",
    ),
    ArenaChallenge(
        id="qai-11",
        title="Thermodynamic Framing",
        topic="Future Systems",
        difficulty=5,
        kind="mcq",
        scenario="An investor presentation talks only about runtime speedup.",
        prompt="What broader framing does the 2026 synthesis add?",
        options=[
            "Quantum advantage may also concern memory and energetic efficiency",
            "Hardware constraints no longer matter in advanced markets",
            "Thermodynamics replaces optimization completely",
            "All hybrid systems become end-to-end quantum models",
        ],
        accepted_answers=["Quantum advantage may also concern memory and energetic efficiency"],
        explanation="The future-facing material broadens advantage beyond speed into resource-efficiency arguments.",
    ),
    ArenaChallenge(
        id="qai-12",
        title="Target Update",
        topic="AI/ML",
        difficulty=5,
        kind="code",
        scenario="A reinforcement-learning system separates stable target evaluation from online updates.",
        prompt="Name the network copied periodically to stabilize TD targets.",
        starter_code="stable_values = __________(next_state)",
        accepted_answers=["target_network", "target_net", "target model", "target_model"],
        explanation="Target networks provide a slower-moving reference for temporal-difference updates.",
    ),
]


@dataclass
class MatchPlayer:
    player_id: str
    display_name: str
    adaptive_level: int
    websocket: WebSocket | None = None
    is_bot: bool = False
    score: int = 0
    correct_answers: int = 0
    submitted_answers: int = 0


@dataclass
class ArenaMatch:
    match_id: str
    mode: str
    players: dict[str, MatchPlayer]
    current_round: int = 0
    difficulty_band: int = 2
    used_challenge_ids: set[str] = field(default_factory=set)
    current_challenge: ArenaChallenge | None = None
    current_answers: dict[str, str] = field(default_factory=dict)
    current_answer_times: dict[str, float] = field(default_factory=dict)
    round_started_at: float = 0.0
    round_task: asyncio.Task | None = None


def _normalize_answer(value: str) -> str:
    return "".join(ch.lower() for ch in value.strip() if ch.isalnum())


def _rank_label_from_xp(xp: int) -> str:
    if xp >= 2200:
        return "Quantum Master"
    if xp >= 1500:
        return "Hybrid Strategist"
    if xp >= 900:
        return "Applied Challenger"
    if xp >= 400:
        return "Systems Apprentice"
    return "Launch Pad"


class ArenaService:
    def __init__(self):
        self._lock = asyncio.Lock()
        self._connections: dict[str, WebSocket] = {}
        self._matches: dict[str, ArenaMatch] = {}
        self._player_match: dict[str, str] = {}
        self._waiting_player_ids: deque[str] = deque()

    def leaderboard(self, limit: int = 12) -> list[ArenaLeaderboardEntry]:
        with SessionLocal() as session:
            profiles = session.scalars(
                select(ArenaProfile).order_by(ArenaProfile.xp.desc(), ArenaProfile.skill_rating.desc(), ArenaProfile.id.asc())
            ).all()
        entries: list[ArenaLeaderboardEntry] = []
        for profile in profiles[:limit]:
            win_rate = round((profile.wins / profile.matches_played) * 100, 1) if profile.matches_played else 0.0
            entries.append(
                ArenaLeaderboardEntry(
                    player_id=profile.player_id,
                    display_name=profile.display_name,
                    xp=profile.xp,
                    matches_played=profile.matches_played,
                    wins=profile.wins,
                    skill_rating=profile.skill_rating,
                    adaptive_level=profile.adaptive_level,
                    win_rate_percent=win_rate,
                    rank_label=_rank_label_from_xp(profile.xp),
                )
            )
        return entries

    def profile(self, player_id: str) -> ArenaProfileRead:
        with SessionLocal() as session:
            profile = session.scalars(select(ArenaProfile).where(ArenaProfile.player_id == player_id)).first()
            if not profile:
                profile = ArenaProfile(
                    player_id=player_id,
                    display_name=player_id,
                    xp=0,
                    matches_played=0,
                    wins=0,
                    skill_rating=1000,
                    adaptive_level=2,
                )
                session.add(profile)
                session.commit()
                session.refresh(profile)
            records = session.scalars(
                select(ArenaMatchRecord)
                .where(ArenaMatchRecord.player_id == player_id)
                .order_by(ArenaMatchRecord.created_at.desc(), ArenaMatchRecord.id.desc())
            ).all()
        recent_form = "".join(
            "W" if record.result == "win" else "T" if record.result == "draw" else "L"
            for record in records[:5]
        ) or "No matches yet"
        return ArenaProfileRead(
            player_id=profile.player_id,
            display_name=profile.display_name,
            xp=profile.xp,
            matches_played=profile.matches_played,
            wins=profile.wins,
            skill_rating=profile.skill_rating,
            adaptive_level=profile.adaptive_level,
            win_rate_percent=round((profile.wins / profile.matches_played) * 100, 1) if profile.matches_played else 0.0,
            rank_label=_rank_label_from_xp(profile.xp),
            recent_form=recent_form,
        )

    def status(self) -> dict[str, int]:
        return {
            "queue_size": len(self._queued_player_ids()),
            "active_matches": len(self._matches),
            "connected_players": len(self._connections),
        }

    async def connect(self, websocket: WebSocket, player_id: str, display_name: str, mode: str) -> None:
        await websocket.accept()
        display_name = sanitize_user_text(display_name, preserve_newlines=False) or player_id
        await self._ensure_profile(player_id, display_name)
        match_start_id: str | None = None
        payload: dict[str, Any] | None = None
        queue_updates: list[tuple[str, dict[str, Any]]] = []
        direct_messages: list[tuple[str, dict[str, Any]]] = []
        async with self._lock:
            self._connections[player_id] = websocket
            self._remove_from_wait_queue(player_id)
            if player_id in self._player_match:
                match = self._matches.get(self._player_match[player_id])
                payload = self._match_found_payload(match, player_id) if match else None
            elif mode == "bot":
                match = self._build_bot_match(player_id, display_name, websocket)
                self._matches[match.match_id] = match
                self._player_match[player_id] = match.match_id
                payload = self._match_found_payload(match, player_id)
                match_start_id = match.match_id
            else:
                self._waiting_player_ids.append(player_id)
                self._prune_wait_queue()
                if len(self._waiting_player_ids) >= 2:
                    opponent_id = self._waiting_player_ids.popleft()
                    current_id = self._waiting_player_ids.popleft()
                    match = self._build_ranked_match(opponent_id, current_id)
                    self._matches[match.match_id] = match
                    self._player_match[opponent_id] = match.match_id
                    self._player_match[current_id] = match.match_id
                    direct_messages.append((opponent_id, self._match_found_payload(match, opponent_id)))
                    if current_id == player_id:
                        payload = self._match_found_payload(match, current_id)
                    else:
                        direct_messages.append((current_id, self._match_found_payload(match, current_id)))
                        payload = self._queue_status_payload(player_id)
                    match_start_id = match.match_id
                else:
                    payload = self._queue_status_payload(player_id)
                queue_updates = self._waiting_queue_updates()
        await self._send(player_id, {"type": "connected", "player_id": player_id, "display_name": display_name})
        for target_player_id, queued_payload in queue_updates:
            await self._send(target_player_id, queued_payload)
        for target_player_id, direct_payload in direct_messages:
            await self._send(target_player_id, direct_payload)
        if payload:
            await self._send(player_id, payload)
        if match_start_id:
            await self._schedule_next_round(match_start_id, immediate=True)

    async def disconnect(self, player_id: str) -> None:
        should_finish = False
        match_id: str | None = None
        queue_updates: list[tuple[str, dict[str, Any]]] = []
        async with self._lock:
            self._connections.pop(player_id, None)
            self._remove_from_wait_queue(player_id)
            queue_updates = self._waiting_queue_updates()
            match_id = self._player_match.get(player_id)
            if not match_id:
                pass
            else:
                match = self._matches.get(match_id)
                if not match:
                    self._player_match.pop(player_id, None)
                    match_id = None
                else:
                    remaining_humans = [candidate for candidate, player in match.players.items() if candidate != player_id and not player.is_bot]
                    should_finish = bool(remaining_humans)
        for target_player_id, payload in queue_updates:
            await self._send(target_player_id, payload)
        if should_finish and match_id:
            await self._finish_match(match_id, forfeit_player_id=player_id)

    async def handle_message(self, player_id: str, payload: dict[str, Any]) -> None:
        if payload.get("type") != "answer":
            return
        match_id = self._player_match.get(player_id)
        if not match_id:
            return
        should_finalize = False
        round_number = 0
        async with self._lock:
            match = self._matches.get(match_id)
            if not match or not match.current_challenge or player_id in match.current_answers:
                return
            answer = str(payload.get("answer", "")).strip()
            match.current_answers[player_id] = answer
            match.current_answer_times[player_id] = max(time.time() - match.round_started_at, 0.0)
            if all(candidate in match.current_answers for candidate in match.players):
                should_finalize = True
                round_number = match.current_round
        if should_finalize:
            await self._finalize_round(match_id, round_number)

    def _build_ranked_match(self, opponent_id: str, player_id: str) -> ArenaMatch:
        opponent_profile = self.profile(opponent_id)
        current_profile = self.profile(player_id)
        return ArenaMatch(
            match_id=f"match-{uuid4().hex[:10]}",
            mode="ranked",
            players={
                opponent_id: MatchPlayer(
                    player_id=opponent_id,
                    display_name=opponent_profile.display_name,
                    adaptive_level=opponent_profile.adaptive_level,
                    websocket=self._connections[opponent_id],
                ),
                player_id: MatchPlayer(
                    player_id=player_id,
                    display_name=current_profile.display_name,
                    adaptive_level=current_profile.adaptive_level,
                    websocket=self._connections[player_id],
                ),
            },
            difficulty_band=max(1, min(5, round((opponent_profile.adaptive_level + current_profile.adaptive_level) / 2))),
        )

    def _build_bot_match(self, player_id: str, display_name: str, websocket: WebSocket) -> ArenaMatch:
        profile = self.profile(player_id)
        bot_level = max(1, min(5, profile.adaptive_level + random.choice([-1, 0, 1])))
        bot_player = MatchPlayer(
            player_id=f"bot-{uuid4().hex[:6]}",
            display_name="Adaptive Arena Bot",
            adaptive_level=bot_level,
            websocket=None,
            is_bot=True,
        )
        human_player = MatchPlayer(
            player_id=player_id,
            display_name=display_name or profile.display_name,
            adaptive_level=profile.adaptive_level,
            websocket=websocket,
        )
        return ArenaMatch(
            match_id=f"match-{uuid4().hex[:10]}",
            mode="bot",
            players={player_id: human_player, bot_player.player_id: bot_player},
            difficulty_band=max(1, min(5, round((human_player.adaptive_level + bot_level) / 2))),
        )

    def _match_found_payload(self, match: ArenaMatch | None, self_player_id: str) -> dict[str, Any] | None:
        if not match:
            return None
        return {
            "type": "match_found",
            "match_id": match.match_id,
            "mode": match.mode,
            "rounds_total": ROUND_COUNT,
            "difficulty_band": match.difficulty_band,
            "players": self._scoreboard(match, self_player_id),
        }

    def _scoreboard(self, match: ArenaMatch, self_player_id: str | None = None) -> list[dict[str, Any]]:
        return [
            {
                "player_id": player.player_id,
                "display_name": player.display_name,
                "score": player.score,
                "correct_answers": player.correct_answers,
                "submitted_answers": player.submitted_answers,
                "adaptive_level": player.adaptive_level,
                "is_self": player.player_id == self_player_id,
                "is_bot": player.is_bot,
            }
            for player in match.players.values()
        ]

    def _queued_player_ids(self) -> list[str]:
        return [
            player_id
            for player_id in self._waiting_player_ids
            if player_id in self._connections and player_id not in self._player_match
        ]

    def _prune_wait_queue(self) -> None:
        self._waiting_player_ids = deque(dict.fromkeys(self._queued_player_ids()))

    def _remove_from_wait_queue(self, player_id: str) -> None:
        self._waiting_player_ids = deque(candidate for candidate in self._waiting_player_ids if candidate != player_id)

    def _queue_status_payload(self, player_id: str) -> dict[str, Any]:
        queued_ids = self._queued_player_ids()
        position = queued_ids.index(player_id) + 1 if player_id in queued_ids else 0
        return {
            "type": "queue_status",
            "state": "waiting",
            "position": position,
            "queue_size": len(queued_ids),
            "message": "Waiting for another challenger to enter the ranked arena...",
        }

    def _waiting_queue_updates(self) -> list[tuple[str, dict[str, Any]]]:
        self._prune_wait_queue()
        return [(player_id, self._queue_status_payload(player_id)) for player_id in self._waiting_player_ids]

    def _pick_challenge(self, match: ArenaMatch) -> ArenaChallenge:
        eligible = [
            challenge
            for challenge in CHALLENGE_BANK
            if challenge.id not in match.used_challenge_ids and abs(challenge.difficulty - match.difficulty_band) <= 1
        ]
        if not eligible:
            eligible = [challenge for challenge in CHALLENGE_BANK if challenge.id not in match.used_challenge_ids]
        if not eligible:
            match.used_challenge_ids.clear()
            eligible = CHALLENGE_BANK[:]
        challenge = random.choice(eligible)
        match.used_challenge_ids.add(challenge.id)
        return challenge

    def _grade_answer(self, challenge: ArenaChallenge, answer: str) -> bool:
        if not answer:
            return False
        normalized = _normalize_answer(answer)
        accepted = {_normalize_answer(item) for item in challenge.accepted_answers}
        if normalized in accepted:
            return True
        return any(token in normalized for token in accepted if token and len(token) >= 4)

    async def _schedule_next_round(self, match_id: str, immediate: bool = False) -> None:
        async def delayed_start() -> None:
            if not immediate:
                await asyncio.sleep(ROUND_ADVANCE_DELAY_SECONDS)
            await self._start_round(match_id)

        asyncio.create_task(delayed_start())

    async def _start_round(self, match_id: str) -> None:
        finalize_match = False
        payload: dict[str, Any] | None = None
        bot_targets: list[str] = []
        async with self._lock:
            match = self._matches.get(match_id)
            if not match:
                return
            match.current_round += 1
            if match.current_round > ROUND_COUNT:
                finalize_match = True
            else:
                match.current_challenge = self._pick_challenge(match)
                match.current_answers = {}
                match.current_answer_times = {}
                match.round_started_at = time.time()
                if match.round_task and not match.round_task.done():
                    match.round_task.cancel()
                match.round_task = asyncio.create_task(self._round_timeout(match_id, match.current_round))
                payload = {
                    "type": "challenge",
                    "round_number": match.current_round,
                    "rounds_total": ROUND_COUNT,
                    "difficulty_band": match.difficulty_band,
                    "round_duration_seconds": ROUND_DURATION_SECONDS,
                    "round_started_at": match.round_started_at,
                    "challenge": match.current_challenge.to_client_payload(),
                    "players": self._scoreboard(match),
                }
                bot_targets = [player.player_id for player in match.players.values() if player.is_bot]
        if finalize_match:
            await self._finish_match(match_id)
            return
        if payload:
            await self._broadcast(match_id, payload)
        for bot_player_id in bot_targets:
            asyncio.create_task(self._bot_submit(match_id, match.current_round, bot_player_id))

    async def _round_timeout(self, match_id: str, round_number: int) -> None:
        await asyncio.sleep(ROUND_DURATION_SECONDS)
        await self._finalize_round(match_id, round_number)

    async def _bot_submit(self, match_id: str, round_number: int, bot_player_id: str) -> None:
        async with self._lock:
            match = self._matches.get(match_id)
            if not match or not match.current_challenge or match.current_round != round_number:
                return
            challenge = match.current_challenge
            bot = match.players.get(bot_player_id)
            if not bot:
                return
            accuracy_threshold = min(0.88, 0.42 + (bot.adaptive_level * 0.1) + (challenge.difficulty * 0.04))
            delay = random.uniform(4.0, 9.0)
        await asyncio.sleep(delay)
        should_finalize = False
        async with self._lock:
            match = self._matches.get(match_id)
            if not match or not match.current_challenge or match.current_round != round_number or bot_player_id in match.current_answers:
                return
            if random.random() <= accuracy_threshold:
                answer = challenge.accepted_answers[0]
            elif challenge.options:
                wrong_choices = [choice for choice in challenge.options if choice not in challenge.accepted_answers]
                answer = random.choice(wrong_choices or challenge.options)
            else:
                answer = "pass"
            match.current_answers[bot_player_id] = answer
            match.current_answer_times[bot_player_id] = max(time.time() - match.round_started_at, 0.0)
            if all(candidate in match.current_answers for candidate in match.players):
                should_finalize = True
        if should_finalize:
            await self._finalize_round(match_id, round_number)

    async def _finalize_round(self, match_id: str, round_number: int) -> None:
        payload: dict[str, Any] | None = None
        async with self._lock:
            match = self._matches.get(match_id)
            if not match or not match.current_challenge or match.current_round != round_number:
                return
            challenge = match.current_challenge
            if match.round_task and not match.round_task.done():
                match.round_task.cancel()
            answer_state: list[dict[str, Any]] = []
            correct_count = 0
            for player in match.players.values():
                answer = match.current_answers.get(player.player_id, "")
                time_taken = match.current_answer_times.get(player.player_id, ROUND_DURATION_SECONDS)
                correct = self._grade_answer(challenge, answer)
                score_delta = 0
                if answer:
                    player.submitted_answers += 1
                if correct:
                    player.correct_answers += 1
                    correct_count += 1
                    speed_bonus = max(0, 44 - int(time_taken))
                    score_delta = 120 + (challenge.difficulty * 24) + speed_bonus
                    player.score += score_delta
                answer_state.append(
                    {
                        "player_id": player.player_id,
                        "display_name": player.display_name,
                        "answer": answer,
                        "correct": correct,
                        "score_delta": score_delta,
                        "time_taken_ms": int(time_taken * 1000),
                        "is_bot": player.is_bot,
                    }
                )
            if correct_count >= max(1, len(match.players) - 1):
                match.difficulty_band = min(5, match.difficulty_band + 1)
            elif correct_count == 0:
                match.difficulty_band = max(1, match.difficulty_band - 1)
            payload = {
                "type": "round_result",
                "round_number": match.current_round,
                "correct_answer": challenge.accepted_answers[0],
                "explanation": challenge.explanation,
                "players": self._scoreboard(match),
                "answer_state": answer_state,
                "next_difficulty_band": match.difficulty_band,
            }
            match.current_challenge = None
        if payload:
            await self._broadcast(match_id, payload)
        await self._schedule_next_round(match_id)

    async def _finish_match(self, match_id: str, forfeit_player_id: str | None = None) -> None:
        async with self._lock:
            match = self._matches.pop(match_id, None)
            if not match:
                return
            if match.round_task and not match.round_task.done():
                match.round_task.cancel()
            for player_id in list(match.players):
                self._player_match.pop(player_id, None)
                self._remove_from_wait_queue(player_id)
            if forfeit_player_id and forfeit_player_id in match.players:
                match.players[forfeit_player_id].score = max(0, match.players[forfeit_player_id].score - 120)
            players = list(match.players.values())
            highest_score = max(player.score for player in players)
            winner_ids = {player.player_id for player in players if player.score == highest_score}
        payload = {
            "type": "match_complete",
            "winner_ids": sorted(winner_ids),
            "players": self._scoreboard(match),
            "xp_updates": self._persist_results(match, winner_ids),
        }
        await self._broadcast(match, payload)

    def _persist_results(self, match: ArenaMatch, winner_ids: set[str]) -> list[dict[str, Any]]:
        xp_updates: list[dict[str, Any]] = []
        human_players = [player for player in match.players.values() if not player.is_bot]
        with SessionLocal() as session:
            for player in human_players:
                profile = session.scalars(select(ArenaProfile).where(ArenaProfile.player_id == player.player_id)).first()
                if not profile:
                    profile = ArenaProfile(
                        player_id=player.player_id,
                        display_name=player.display_name,
                        xp=0,
                        matches_played=0,
                        wins=0,
                        skill_rating=1000,
                        adaptive_level=2,
                    )
                    session.add(profile)
                    session.flush()
                profile.display_name = player.display_name
                profile.matches_played += 1
                accuracy = player.correct_answers / ROUND_COUNT if ROUND_COUNT else 0.0
                if len(winner_ids) > 1 and player.player_id in winner_ids:
                    result = "draw"
                    xp_delta = 150 + int(accuracy * 80)
                    skill_delta = 8
                elif player.player_id in winner_ids:
                    result = "win"
                    xp_delta = 220 + int(accuracy * 110)
                    skill_delta = 24
                    profile.wins += 1
                else:
                    result = "loss"
                    xp_delta = 95 + int(accuracy * 50)
                    skill_delta = -12
                profile.xp += xp_delta
                profile.skill_rating = max(800, profile.skill_rating + skill_delta)
                profile.adaptive_level = max(
                    1,
                    min(5, round((profile.adaptive_level + match.difficulty_band + (2 * accuracy)) / 2)),
                )
                opponent = next((candidate for candidate in match.players.values() if candidate.player_id != player.player_id), None)
                session.add(
                    ArenaMatchRecord(
                        player_id=player.player_id,
                        opponent_id=opponent.player_id if opponent else "unknown",
                        mode=match.mode,
                        result=result,
                        score=player.score,
                        correct_answers=player.correct_answers,
                        total_rounds=ROUND_COUNT,
                        xp_delta=xp_delta,
                        difficulty_band=match.difficulty_band,
                    )
                )
                xp_updates.append(
                    {
                        "player_id": player.player_id,
                        "display_name": player.display_name,
                        "xp_delta": xp_delta,
                        "new_xp": profile.xp,
                        "skill_rating": profile.skill_rating,
                        "adaptive_level": profile.adaptive_level,
                        "rank_label": _rank_label_from_xp(profile.xp),
                    }
                )
            session.commit()
        return xp_updates

    async def _ensure_profile(self, player_id: str, display_name: str) -> None:
        with SessionLocal() as session:
            profile = session.scalars(select(ArenaProfile).where(ArenaProfile.player_id == player_id)).first()
            if profile:
                if display_name and profile.display_name != display_name:
                    profile.display_name = display_name
                    session.commit()
                return
            session.add(
                ArenaProfile(
                    player_id=player_id,
                    display_name=display_name or player_id,
                    xp=0,
                    matches_played=0,
                    wins=0,
                    skill_rating=1000,
                    adaptive_level=2,
                )
            )
            session.commit()

    async def _send(self, player_id: str, payload: dict[str, Any]) -> None:
        websocket = self._connections.get(player_id)
        if not websocket:
            return
        try:
            await websocket.send_json(payload)
        except Exception:
            self._connections.pop(player_id, None)

    async def _broadcast(self, match_or_id: ArenaMatch | str, payload: dict[str, Any]) -> None:
        if isinstance(match_or_id, ArenaMatch):
            match = match_or_id
        else:
            match = self._matches.get(match_or_id)
        if not match:
            return
        for player in match.players.values():
            if player.websocket:
                await self._send(player.player_id, payload)


@lru_cache
def get_arena_service() -> ArenaService:
    return ArenaService()
