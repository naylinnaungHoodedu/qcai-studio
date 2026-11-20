"""The locked claim set (plan task 3.5; Phase 3 spec 4.7; spec conflict 1).

Each claim's source_order is its sentence's own place in the source, from binding (spec 18.10 H2). The lock is
taken before rendering and stamped with the corpus and index versions, the generator, both prompt
hashes (the pedagogical one is the hash of the whole renderer registry, so it is plan-independent), the resolver
and the configuration package. No stamp is plan-, learner-, request- or commit-specific, so three presentation
plans give one claim_set_hash (AC-3-2).
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING

from app.core.config_package import ConfigPackage
from app.services.tutor_pipeline.contracts import (
    ConfigStamp,
    EvidenceBundle,
    GeneratorRef,
    LockedClaim,
    LockedClaimSet,
    ResolverRef,
    lock_hash,
    verify_locked,
)

if TYPE_CHECKING:  # pragma: no cover
    from app.services.tutor_pipeline.bind import LockedClaimDraft

__all__ = ["lock", "verify_locked"]


def lock(
    drafts: Sequence["LockedClaimDraft"],
    *,
    bundle: EvidenceBundle,
    generator: GeneratorRef | None,
    evidential_prompt_hash: str | None,
    pedagogical_prompt_hash: str,
    resolver: ResolverRef,
    package: ConfigPackage,
) -> LockedClaimSet:
    claims = []
    for draft in drafts:
        # The sentence's own place, (item_id, item offset of its first character), earliest over its cited spans
        # (bind.py), so two sentences of one span keep their text order under the stepwise "in source order" lead.
        claims.append(LockedClaim(claim_id=draft.claim_id, text=draft.text, span_ids=tuple(sorted(draft.span_ids)),
                                  source_order=tuple(draft.source_order)))
    span_ids = tuple(sorted({span_id for claim in claims for span_id in claim.span_ids}))
    draft_set = LockedClaimSet.model_construct(
        claims=tuple(claims),
        span_ids=span_ids,
        corpus_version=bundle.corpus_version,
        index_version=bundle.index_version,
        generator=generator,
        evidential_prompt_hash=evidential_prompt_hash,
        pedagogical_prompt_hash=pedagogical_prompt_hash,
        resolver=resolver,
        config_package=ConfigStamp(version=package.package_version, sha256=package.sha256),
        claim_set_hash="0" * 64,
    )
    digest = lock_hash(draft_set)
    return LockedClaimSet.model_validate({**draft_set.model_dump(mode="json"), "claim_set_hash": digest})
