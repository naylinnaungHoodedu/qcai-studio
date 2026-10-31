# Deployment freeze (plan Action 4, Decision D-05)

**Declared 2026-10-31** by the project owner, acting as Platform Owner and Product Owner, through the instruction "Must deeply and professionally continue all the steps in order to successfully complete phase1. no need to ask my permission again and again." (2026-10-31T04:20:57Z). Recorded by Claude (AI); decision P1-D-14 in the Phase 1 evidence.

From that date until the Phase 1 exit gate passes, production (`qcai-api`, `qcai-frontend`, the Cloud SQL instance `qcai-db`, their secrets, and DNS for qantumlearn.academy) is **frozen**.

1. **No rollout** of any build, configuration or schema change, except a remediation release approved under the procedure below.
2. **Remediation releases only.** A release may go out only if it closes or contains a listed release blocker (plan §5.3). It must also be scoped to that blocker, carry a tested rollback path, and be approved below. Until every blocker is closed or contained with dated evidence, no release adds or re-enables learner-facing capability.
3. **Governance stays on.** Disabling corpus governance (`ENFORCE_CORPUS_GOVERNANCE=false`) is never a rollout workaround (D-05 option (b), rejected; plan task 1.8). Under D-31 (P1-D-07), a governed build serves only manifest-approved assets, currently none.
4. **Emergency changes.** The project owner may act. The change is recorded here as a dated entry, with a SEV-1 incident record, within 24 hours.

## Per-release approval procedure
A remediation release needs one written approval record, filed before the release, containing:

| Field | Content |
|---|---|
| Blocker(s) | The R-numbers it closes or contains, and the acceptance criteria it evidences |
| Code | The merged PR(s) and the `main` commit, with a green CI run id on that commit (all jobs) |
| Image | The Cloud Build image digest (`@sha256:…`) built from that commit, never an image built on a workstation |
| Configuration | Secret and setting changes by name, never values |
| Data | A backup id taken immediately before; the schema changes and the plan for new tables |
| Rollout | `scripts/deploy_by_digest.py`: a no-traffic revision, a tagged check, then a pinned named revision (`deployment.md`) |
| Rollback | The previous revision name and digest; the restore path |
| Verification | The dated production probes for the acceptance criteria concerned; the `scripts/deployment_record.py` output, committed |
| Approvals | Platform Owner and Product Owner |

A request without every field is refused.

## Lifting
The freeze lifts once when the Phase 1 exit gate is declared passed (plan L1907-1908), and fully at Phase 12. The lift is recorded as a dated entry here.
