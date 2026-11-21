"""Quiz answer keys, kept server-side (plan Phase 4 B precondition "keyed answers outside public payloads"; R-42;
Phase 4 spec 4.14).

The public QuizQuestion (app.schemas) carries no answer and no explanation, so no lesson, module or cached page
payload holds a key. The keys live here, in an internal frozen dataclass that is never a response model: the quiz
route scores an attempt with them (score_attempt, the server-side rule of task 1.2, E-110), and V1.6 reads them to
keep a keyed answer out of an assessment answer (QuizKeySource). After a saved attempt, the route returns per-question
feedback: the key and its explanation only for the questions that attempt answered. Nothing here is logged.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass

from app.schemas import QuizFeedbackItem
from app.services.v1_checks.v1_6_keyed_answers import KeyedItem

QUIZ_RESPONSE_MAX_LENGTH = 2000


@dataclass(frozen=True)
class QuizKey:
    id: str
    lesson_slug: str
    question_type: str
    prompt: str
    choices: tuple[str, ...]
    answer: str
    explanation: str


class QuizKeyStore:
    def __init__(self, keys: Iterable[QuizKey]) -> None:
        self._keys = tuple(keys)
        self._by_lesson: dict[str, tuple[QuizKey, ...]] = {}
        for key in self._keys:
            self._by_lesson[key.lesson_slug] = (*self._by_lesson.get(key.lesson_slug, ()), key)

    def for_lesson(self, slug: str) -> tuple[QuizKey, ...]:
        return self._by_lesson.get(slug, ())

    def all(self) -> tuple[QuizKey, ...]:
        return self._keys

    def __len__(self) -> int:
        return len(self._keys)


class QuizKeySource:
    """V1.6's KeyedItemSource over a QuizKeyStore: every lesson's keyed items."""

    def __init__(self, keys: QuizKeyStore) -> None:
        self._items = tuple(
            KeyedItem(item_id=key.id, lesson_slug=key.lesson_slug, prompt=key.prompt, choices=tuple(key.choices), answer=key.answer)
            for key in keys.all()
        )

    def items(self) -> tuple[KeyedItem, ...]:
        return self._items


def score_attempt(keys: Sequence[QuizKey], responses: Mapping) -> tuple[int, dict[str, str], list[QuizFeedbackItem]]:
    """Score on the server by the exact-match rule; keep only this lesson's string answers, each bounded, so a stored
    attempt carries no arbitrary data (a client-sent score is never read). Feedback has one item per question in lesson
    order: an answered question (non-empty after strip) gets its correctness, key and explanation; any other none."""
    kept = {
        key.id: responses[key.id][:QUIZ_RESPONSE_MAX_LENGTH]
        for key in keys
        if isinstance(responses.get(key.id), str)
    }
    score = sum(1 for key in keys if kept.get(key.id) == key.answer)
    feedback = []
    for key in keys:
        response = kept.get(key.id)
        if response is not None and response.strip():
            feedback.append(QuizFeedbackItem(question_id=key.id, answered=True, correct=response == key.answer, answer=key.answer,
                                             explanation=key.explanation))
        else:
            feedback.append(QuizFeedbackItem(question_id=key.id, answered=False))
    return score, kept, feedback
