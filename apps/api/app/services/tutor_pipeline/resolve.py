"""Resolver thread-resolver-v1 (plan task 3.1; Phase 3 spec 4.2; AC-3-5).

The resolved question is built only from the learner's own user turns of the same thread: never an assistant
reply, never the client-supplied history, never another table. It is the sole retrieval input and the abstention
subject. It replaces the word-count heuristic of TutorOrchestrator._resolve_query on the two-pass path (E-44);
the legacy path keeps its heuristic until two-pass output is delivered (DI-41).

A message is a follow-up when it has fewer than min_content_terms package content terms, or starts with a
continuation cue; its anchor is the most recent of the last max_lookback prior user turns with at least
min_content_terms content terms. Deterministic: the same turns always give the same text and source_turn_ids.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from app.core.config_package import ConfigPackage, RetrievalParams, TutorPipelineParams, canonical_sha256
from app.db_models import TutorMessage
from app.services.tutor_pipeline.contracts import ResolvedQuestion, ResolverRef
from app.services.tutor_pipeline.text import content_terms, whitespace

RESOLVER_ID = "thread-resolver-v1"
RESOLVER_TEMPLATE = "{anchor}\n{current}"
RESOLVER_INPUTS = "the learner's own user messages of one thread"


class ResolverInputError(ValueError):
    """The current message is not a user message of the named thread."""


@dataclass(frozen=True)
class LearnerTurn:
    """A role == "user" TutorMessage: its id and its text."""

    message_id: str
    text: str


def resolver_prompt_hash(params: TutorPipelineParams, retrieval: RetrievalParams) -> str:
    return canonical_sha256(
        {
            "id": RESOLVER_ID,
            "template": RESOLVER_TEMPLATE,
            "min_content_terms": params.min_content_terms,
            "continuation_cues": list(params.continuation_cues),
            "max_lookback": params.max_lookback,
            "tokenizer": retrieval.tokenizer_version,
            "stopwords": retrieval.stopwords_version,
            "inputs": RESOLVER_INPUTS,
        }
    )


def _params(package: ConfigPackage) -> TutorPipelineParams:
    if package.tutor_pipeline is None:
        raise ResolverInputError("the configuration package has no tutor_pipeline block (package v2 is required)")
    return package.tutor_pipeline


def resolve_turns(prior: Sequence[LearnerTurn], current: LearnerTurn, *, package: ConfigPackage) -> ResolvedQuestion:
    params = _params(package)
    retrieval = package.retrieval
    ref = ResolverRef(model_id=RESOLVER_ID, prompt_hash=params.resolver_prompt_hash)
    current_text = whitespace(current.text)
    follow_up = len(content_terms(current_text, retrieval)) < params.min_content_terms or current_text.lower().startswith(
        params.continuation_cues
    )
    anchor: LearnerTurn | None = None
    if follow_up:
        for turn in reversed(list(prior)[-params.max_lookback :]):
            if len(content_terms(turn.text, retrieval)) >= params.min_content_terms:
                anchor = turn
                break
    if anchor is not None:
        text = RESOLVER_TEMPLATE.format(anchor=whitespace(anchor.text), current=current_text)
        return ResolvedQuestion(text=text, resolver=ref, source_turn_ids=(anchor.message_id, current.message_id))
    return ResolvedQuestion(text=current_text, resolver=ref, source_turn_ids=(current.message_id,))


def resolve_thread(db: Session, thread_id: str, current_message_id: str, *, package: ConfigPackage) -> ResolvedQuestion:
    params = _params(package)
    current = db.get(TutorMessage, current_message_id)
    if current is None or current.thread_id != thread_id or current.role != "user":
        raise ResolverInputError("the current message is not a user message of this thread")
    rows = db.scalars(
        select(TutorMessage)
        .where(
            TutorMessage.thread_id == thread_id,
            TutorMessage.role == "user",
            TutorMessage.id != current.id,
            or_(
                TutorMessage.created_at < current.created_at,
                and_(TutorMessage.created_at == current.created_at, TutorMessage.id < current.id),
            ),
        )
        .order_by(TutorMessage.created_at.desc(), TutorMessage.id.desc())
        .limit(params.max_lookback)
    ).all()
    prior = [LearnerTurn(row.id, row.content) for row in reversed(rows)]
    return resolve_turns(prior, LearnerTurn(current.id, current.content), package=package)
