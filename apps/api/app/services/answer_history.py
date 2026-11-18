"""Answers stored before containment are withheld from learners (R-16; plan section 5.3, task 1.11, Action 26).

Release R1 (2026-11-17) was the first build to serve contained answers: an abstention, or verbatim quotation
of manifest-approved spans, never marked grounded (Decision D-19). Q&A answers and tutor replies stored before
it were written by the 2026-04-05 build, which generated free text and marked it grounded. Those rows stay in
the database, as the learner's own data, erased with the account, but they are never shown again as answers.
"""

from datetime import UTC, datetime

# The first contained build took 100% of API traffic at this moment (Cloud audit log, ReplaceService on
# qcai-api, revision qcai-api-00038-sog). Every answer stored earlier came from the uncontained build.
CONTAINMENT_STARTED_AT = datetime(2026, 11, 17, 12, 39, 18, tzinfo=UTC)
WITHDRAWN_ANSWER = (
    "This answer came from an earlier version of the assistant that generated text, so it has been withdrawn. "
    "Answers now only quote approved course sources word for word, or say they cannot answer."
)


def stored_before_containment(created_at: datetime | None) -> bool:
    """True for an answer the uncontained build wrote. An answer with no time is treated as one."""
    if created_at is None:
        return True
    if created_at.tzinfo is None:  # SQLite returns naive values; the column holds UTC
        created_at = created_at.replace(tzinfo=UTC)
    return created_at < CONTAINMENT_STARTED_AT
