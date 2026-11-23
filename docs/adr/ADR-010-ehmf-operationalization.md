# ADR-010: EHMF operationalization

## Context

Plan Phase 7 (L1500-1555) turns the Educational Hallucination Mitigation Framework (EHMF; types A-E, E-87) from a per-check label
into routed, versioned behaviour. The evidence it rests on: E-27 (the plan's "lexical gate with hard-coded constants" is
stale: the overlap ClaimGate, `evidence_digest` and `_STOPWORDS` were removed in Phase 3, and the lexical constants that
remain are already versioned), E-30 (the DOCX transposition in F-7), E-62 (config_version on `/ready`), E-79
(precedence), E-82 (two correction cycles, then X2), E-84, E-87 (the five types), E-88 (the weights are the PI's open
decision) and E-95 (the library holds public-corpus paraphrases, never licensed text). Risks: R-16, R-18, R-19, R-46.

## Decision 2026-11-23 (Phase 7: EHMF operationalization)

- One module, `app.services.ehmf`, holds the vocabulary (types A-E, subtypes B1/B2) and the routing table
  `ehmf-routing-v1` (detectors, mitigations, owners, telemetry; `docs/architecture/ehmf-routing.md`).
- Every failing V1 result and every objecting V2 family verdict is one finding with one type, recorded in an additive
  `ledger-entry-v4` (development shadow records only). B1 (an unresolvable citation) is final.
- Conflicts: `precedence-v1` is recorded only and needs complete Content-Owner metadata; every detected conflict is
  disclosed (`conflict-disclosure-v2`) and weighs 0.
- The misconception library v1 is a hashed file the package pins, edited only by the Content Owner or from V3, with no
  production entries.
- The correction guard is the loop's only bound (two cycles); every exhausted claim abstains with X2, and V3 moves to
  `x-triggers-v2`; a Type E re-render keeps the claim and span sets.
- Change control: the golden-set gate (`scripts/run_golden_set.py --check` in CI) pins the package, the library, the
  routing table and the golden set (`docs/architecture/ehmf-change-control.md`).
- Configuration package v6 holds the ehmf block, provisional (PD-40 to PD-49); `config_version` is the package version
  from v6 on and `pre-phase-7` before it, mapped at read time.
- The span penalty hook ranks only, under EHMF=on, with factor 1 outside development and empty lists.
- The rising-A/B stop is computed state: it reports "revert required" and raises the audit draw to 1/5; the revert is the
  operator's (plan L's "reverts it" would be an automatic production configuration write, which D-05 forbids; DI-114).
- The source-fidelity check reads the 12 DOCX read-only and reports the plan's measured mismatches; engineering edits no
  DOCX.
- EHMF is off outside development (D-05).

## Consequences

- Development records carry per-finding types, so per-type rates, the Type D disclosure share and the correction-cycle
  distribution are measurable (`GET /v3/metrics`, `python -m app.workers.ehmf status`); `/ready` reports
  `config_version` and static EHMF values only.
- Any package, library, routing or golden-set change needs a golden-set run committed with it, or CI fails.
- Production behaviour is unchanged until EHMF is enabled there after the Phase 7 exit (DI-111).

## Residuals

Plan M: "[Risk R-16][Risk R-19][Risk R-46][Risk R-18]; residual: conflicts outside the corpus." Only cited spans are
compared, so a conflict with a source outside the public corpus is not detected. Further residuals:

- the EHMF weights are the plan's provisional values until the PI's expert elicitation (DI-108);
- R-18 is open: the DOCX carry 3 mismatches until the Content Owner corrects them at source (DI-105), and Q-11 (other
  discrepancies) is unresolved;
- no item carries source metadata, so precedence never names a winner, and it is recorded only (DI-107, DI-111);
- the misconception library is empty (Q-14, A-18; DI-106);
- the stop is inert outside development, where no typed record is written (DI-111), and nothing reverts automatically (DI-114);
- per-type rates are telemetry, not E2 results (plan H).
