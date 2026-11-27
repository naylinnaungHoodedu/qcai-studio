# QC+AI Studio: Phase 11 Implementation Spec
## Production hardening and product quality (plan L1744-1799)

- **Repository:** `D:\QC_AI_Studio\Codex_Webapp_QC_AI_Studio`.
- **Slice 11-0 branch:** `phase11/entry-records`, cut from `origin/main` `25a8f89` (Phase 10 merged, PR #42). Phases 2-10 are on `main`; the shipped configuration package is v8 (`8.0.0`, `apps/api/app/config_package/v8.json`) and the single Alembic head is `20261123_phase8_learner`.
- **Plan:** `D:\QC_AI_Studio\QC_AI_Studio_Ultimate_Software_Upgrade_Plan.txt` (sha256 `68354a7c…`). Plan locations used here:
  - The Phase 11 block: L1744-1799 (preconditions L1751-1752, tasks 1-9 L1756-1765, AC-11-1..AC-11-8 L1781-1788, exit P L1798-1799).
  - Holds H4 and H9: L1915 and L1920. Decisions D-06, D-10, D-15 and D-18: L2547, L2551, L2556 and L2559 (D-18 in 18.3: L2992). Open questions Q-03, Q-13 and Q-20: L2930, L2942 and L2950. Assumption A-15: L3192. The SLO approval rule ("PO and PI approve each change below [Decision D-06]"): L2718.
  - The decision owners of the Phase 1 and Phase 2 exits: L1148 ("Decision owner: Product Owner.") and L1219 ("Decision owner: Principal Investigator.").
- **Fixed decisions:** E1-E26 of the Phase 11 design (`BEP-2-12/00_meta/workflows/p11/p11_design.txt`, run `wf_3dbd3308-f36`, corrected under G1-G7). The design is the engineering source; this spec states what the code does, slice by slice, as each slice lands.
- **Builder:** Claude on the main track (owner decision P2-12-D-08). Entry decision: P2-12-D-10 (section 0.2).

**Status of this file.** Slice 11-0 is records only: it adds this skeleton, the entry decision and its deferred items, and the Phase 11 section of `docs/testing/test-strategy.md`. No code, configuration package, Alembic revision, setting, `/ready` field, workflow step or frontend file changes in slice 11-0. Each later slice (section 1) fills the sections it owns, in its own PR, and keeps the sections already written current in place (P2-12-D-03). A section marked "not yet written" states no behaviour. Section 14 is the review history, one table row per round. This file is LF in every checkout (`.gitattributes`).

---

## 0. Entry, binding constraints and readings

### 0.1 Binding constraints

- **Freeze (D-05).** No production change, cloud write, deploy, registry push, bucket, alert policy or tag push in Phase 11 (design E2). Cloud-touching tools are plan-only by default; a cloud write needs D-05 and the owner's explicit approval.
- **Secrets.** Never open `infra/cloudrun/*.env.yaml`, `apps/frontend/.env.local` or any `.env*` file.
- **Git.** Every change reaches `main` through a reviewed PR; no history rewrite, force-push or `git stash`.
- **Numbering.** Phase 11 takes main-track numbers after the highest rows on `main` at its start (P2-12-D-08): DI-149 onward and PD-76 onward. PD-200..PD-249 and DI-300..DI-399 are Phase 8's; PD-250..PD-299 and DI-400..DI-499 are Phase 12's (P2-12-D-09); Phase 11 uses neither range.
- **ADR numbers.** `main` `25a8f89` holds ADR-001 to ADR-012 (`docs/adr/`; ADR-012 is Phase 10's). ADR-013 is reserved for slice 11-D's media ADR and ADR-014 for Phase 12 (design QC-21, G5); no other Phase 11 slice takes an ADR number.
- **Status words.** No record may say a Phase 11 AC "passed". Records say "mechanism proven in CI" and name the deferred item that carries the rest (design E1).

### 0.2 Entry (design E1; decision P2-12-D-10)

Phase 11 enters under P1-D-18 with every named precondition and hold unmet, as Phase 8 entered with hold H13 held (P2-12-D-04). The entry is recorded as DI-149, and the exit is recorded NOT passed from the outset as DI-150, because every AC needs production, owner or calendar evidence (section 2).

| # | Precondition or hold (plan) | Owner | Release evidence | State at entry (2026-11-27) |
|---|---|---|---|---|
| 1 | Phase 1 and Phase 2 exits (L1752) | PO for Phase 1 (L1148); PI for Phase 2 (L1219) | Each phase's exit gate (plan P) | NOT passed: Phase 1 ended with recorded deviations (P1-D-18); the Phase 2 exit is not passed |
| 2 | D-10 REC "Media to object storage", "existing route" (L2551) | PfO | None named in the plan (a REC decision); the PfO's ratification | Not ratified; slice 11-D builds on the recommended "existing route" reading as a provisional default for the PfO's ratification |
| 3 | D-15 REC "Environments", "five" (L2556) | PfO | None named in the plan (a REC decision); the PfO's ratification and the environments | Not ratified; no staging environment exists, so the CT-09 and CT-10 staging runs are deferred |
| 4 | Q-03 "Backups/PITR; restore tested?" (L2930), evidence "Backup id, drill" | PfO | The current backup id and a drill | Partly evidenced only: a dated Phase 0 drill exists (2026-10-28), the current backup and PITR state are UNVERIFIED, and no backups were taken 2026-11-03..16. Not answered |
| 5 | Q-13 "Ingress; API instance count?" (L2942), evidence "Scaling export" | PfO | A scaling export | Unanswered; every per-instance assumption is provisional until it is answered |
| 6 | Q-20 "Budget and capacity?" (L2950), evidence "Approved budget" | PO, PI | An approved budget | Unanswered; it underlies the A-15 amounts and hold H9 |
| 7 | Hold H4, staffing D-18, "P11 start" (L1915) | PO (D-18, L2559; PO and PI in 18.3, L2992) | Capacity statement | Holds |
| 8 | Hold H9, budget A-15, "P11 storage" (L1920) | The owner (A-15 "Owner-approved ceilings", L3192); PO and PI for the budget (Q-20) | Approved budget | Holds. Under the deviation only repository code for storage proceeds (slice 11-D: settings, manifest fields, a scan category, a plan-only staging script, a checker over exported listings); no bucket, object, IAM binding or storage spend |

### 0.3 Measured facts at the base

Not yet written. Slice 11-A re-reads every fact it uses at its real base (the build plan's pre-build checks) and records it here with its measurement id.

### 0.4 Readings

- "Reversible configuration" (L1790, "Flags or reversible configuration") includes a commit revert for presentation-only changes (design E2); settings guard every behaviour change that is not presentation-only.
- "LCP < 2.5 s, INP < 200 ms" (L1756) are "RECOMMENDATION (operator-set value)": provisional (PD-76) until D-06 sets them; "CLS p75 < 0.1" (L1781) is the plan's value.

## 1. Scope and slices

In scope (L1754): performance, accessibility, content QA, media, supply chain, SLOs, DR and cost. Out: new features. Each slice is its own branch and PR from current `main`, reviewed to convergence under P2-12-D-02 and P2-12-D-03, in this merge order (design QC-01):

| Slice | Content (design) | State |
|---|---|---|
| 11-0 | Entry records: P2-12-D-10, DI-149 and DI-150, this skeleton, the test strategy's Phase 11 section | This PR |
| 11-A | Operations core, the shared contracts first (11-E, 11-C, 11-D and Phase 12 read them): the per-declaration test-baseline helper, full bump stability before a configuration package bump, the v9 bump, SLIs, the cost caps and shared limits (task 9), the vitals endpoint and checker, the restore drill tooling | Not started |
| 11-E | Supply chain (task 5): SHA-pinned actions and digest-pinned images, SBOMs, provenance verification | Not started |
| 11-B | Content QA (tasks 3 and the transcript contract): the source-fidelity register v2 and the transcript-or-nothing policy | Not started |
| 11-C | Product quality, frontend (tasks 1 and 2): CLS fixes, the lab gate, the accessibility audits | Not started |
| 11-D | Media delivery and code-only releases (task 4), repository code only under the H9 deviation | Not started |
| 11-F | Production evidence, no code: each item only under an owner-approved D-05 action | Not started |

From 11-E's merge on, every later slice (and Phase 12) SHA-pins each workflow step and digest-pins each image it adds (design E17h). Phase 12 (OpenAI Codex, P2-12-D-09) starts after 11-A and 11-E are on `main`.

## 2. Acceptance map

The exit will not pass at merge: every AC below needs production, owner or calendar evidence (DI-150). The repository half of each AC is the mechanism a slice builds and proves in CI; the other half is a deferred item.

| AC (L1781-1788) | Repository mechanism (slice) | Needs, outside the repository |
|---|---|---|
| AC-11-1 CLS p75 < 0.1, LCP and INP in budget for two weeks | Layout fixes, a navigation-mode lab gate, the vitals checker on synthetic rows (11-A, 11-C) | 14 days of field data for the exit build in production (D-05; the owner's freeze exception); LCP and INP values set under D-06 |
| AC-11-2 Zero critical accessibility issues | Dated axe records per commit (P2-12-D-07), Lighthouse records, contrast-token tests, a manual keyboard record (11-C) | Staging and production runs (CT-10; D-15); screen-reader passes on the device matrix (D-18) |
| AC-11-3 Zero DOCX mismatches; QUEN row reads Sensitivity 0.828, FP 1.143 | Register v2, the inventory gate and the prepared `--require-zero` (11-B) | The Content Owner's corrected DOCX (D-16, DI-105; Q-11) |
| AC-11-4 No duplicate lecture asset or unaligned timestamp | The transcript contract and strict policy, the catalogue invariant (11-B) | Transcripts or author notes (Q-10) |
| AC-11-5 Image holds no MP4 or DOCX; `/ready` source_assets equals the approved count | The media scan of both CI-built images and release zips, the governed `/ready` tests (11-D) | The media cutover (cloud write, D-05, D-10, H9); approved assets (D-02, Q-07) |
| AC-11-6 SBOM, signatures and provenance verify | SBOMs in CI, the pin checker, the provenance verifier on fixtures (11-E) | Signature verification and commit binding (OD-3); the hashed lock (OD-5); a trigger-built Cloud Build run |
| AC-11-7 Restore within RTO; row counts match | The restore drill on a local PostgreSQL 16, the runbook, RPO and RTO as provisional entries (11-A) | A Cloud SQL drill (Q-03, a cloud write, D-05, D-15) |
| AC-11-8 Spend at cap refuses calls and alerts | Caps and shared limits with two-instance tests on SQLite and PostgreSQL, linted alert definitions (11-A) | Non-zero caps on a real provider and a created alert firing to a channel (A-15, H9, Q-20, Q-13, a cloud write) |
| Exit P "SLOs, runbooks, RACI filed" | Filed as provisional documents | Binding only after D-06 and D-18 |

## 3. Architecture

Not yet written (slice 11-A first).

## 4. Data shapes

Not yet written.

## 5. Scripts

Not yet written.

## 6. Settings, configuration package, start-up, `/ready`, migrations, frontend

Not yet written. At the base: package v8 (`8.0.0`) is shipped and the Alembic head is `20261123_phase8_learner`; slice 11-0 changes neither.

## 7. File-by-file changes

Slice 11-0: `docs/architecture/phase11-implementation-spec.md` (new), `docs/testing/test-strategy.md` (the Performance row marks LCP and INP provisional; the Phase 11 section) and `.gitattributes` (this file LF).

## 8. Tests

Slice 11-0 adds no test module and changes no test. The earlier phases' documentation guards that read `docs/testing/test-strategy.md` and the specs (`test_phase3_docs.py`, `test_phase8_docs.py`, and the tests of `test_phase4_acceptance.py`, `test_phase5_acceptance.py`, `test_phase6_acceptance.py`, `test_phase7_acceptance.py`, `test_phase9_acceptance.py` and `test_phase10_acceptance.py` selected by `-k 'docs or strategy or spec or k3 or i8'`) pass unchanged. The slice's own guards are the BEP record checks `check_p11_entry_*` in `BEP-2-12/00_meta/check_records.py` (outside the repository): they hold the registers to section 12, the decision and section 0.2 to the plan's preconditions and holds with their owners and release evidence, the records to the NOT passed exit, the test strategy's Phase 11 map to the test modules Phase 11 adds, and section 14 and the phase record's history to each other.

## 9. CI changes

None in slice 11-0.

## 10. Docs and evidence

Not yet written. Plan F (L1769): SLO document, runbooks, drill log, SBOM, audit reports, RACI.

## 11. Records

The BEP package `BEP-2-12/phase11/` (the phase record), `00_meta/DECISIONS.md` (P2-12-D-10), `00_meta/DEFERRED_ITEMS_REGISTER.md` (the Phase 11 rows), `00_meta/PROVISIONAL_DEFAULTS_REGISTER.md` (PD-76) and `00_meta/STATUS.md` row 11.

## 12. Provisional defaults and deferred items

### 12.1 Provisional defaults

| # | Decision | Plan text | Default applied | Where |
|---|---|---|---|---|
| PD-76 | LCP and INP budgets (D-06, L2547: PI decision owner; PO and PI approve each change, L2718) | Task 1: "RECOMMENDATION (operator-set value): LCP < 2.5 s, INP < 200 ms." | LCP p75 < 2500 ms and INP p75 < 200 ms, provisional until D-06; CLS p75 < 0.1 is the plan's value (L1781), not provisional | `docs/testing/test-strategy.md` (Performance row and the Phase 11 section) |

### 12.2 Deferred items

| # | Item | Who | State |
|---|---|---|---|
| DI-149 | The Phase 11 entry (design E1; P2-12-D-10): Phase 11 entered with every named precondition and hold unmet. Blocked by: the Phase 1 and Phase 2 exits (P1-D-18); D-10 REC and D-15 REC (PfO ratification); Q-03 (PfO; partly evidenced only, not answered; the current backup id and a drill); Q-13 (PfO; a scaling export); Q-20 (PO, PI; an approved budget); hold H4 (D-18; a capacity statement); hold H9 (A-15; an approved budget; only repository storage code proceeds). | PO / PfO / PI | Open |
| DI-150 | The Phase 11 exit (plan P: "AC-11-1 to AC-11-8 passed; SLOs, runbooks, RACI filed."). Recorded NOT passed from the outset: every AC needs production, owner or calendar evidence (the Phase 11 spec's section 2), and the SLOs and RACI become binding only after D-06 and D-18. Blocked by: DI-149 and each AC's deferred items as the slices record them. | PO | Open |

## 13. Verification, work order and exit

**Latest verification (slice 11-0, the entry commit).** On the workstation, one suite at a time: the API suite on SQLite (`pytest -q -m "not release_artifacts" apps/api/tests`) 2557 passed, 2 skipped, 1 deselected, 3 xfailed; the earlier phases' documentation guards (`test_phase3_docs.py`, `test_phase8_docs.py` and the docs, strategy and spec tests of `test_phase4_acceptance.py` to `test_phase10_acceptance.py`) 145 passed; the BEP record checks 75 of 75. `evaluation/tests`, the validators, PostgreSQL and the frontend are unaffected by a documentation-only change and were not rerun; CI runs them.

**Exit.** NOT passed (DI-150).

## 14. Review history

The rows below record what each round fixed, in order. A row may describe behaviour or text a later round superseded; sections 0-13 are authoritative and describe the current state.

| Round | Commit | Findings fixed (one line each, with their checks) |
|---|---|---|
| Entry | `10021b4` | Slice 11-0 records: this skeleton, the test strategy's Phase 11 section, `.gitattributes`; P2-12-D-10, DI-149, DI-150 and PD-76 (checks `check_p11_entry_*`) |
