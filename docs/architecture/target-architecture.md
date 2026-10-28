# CS595 target architecture specification

## Boundaries

| Boundary | Responsibility | Trust rule |
| --- | --- | --- |
| Identity | OIDC PKCE/local session adaptation | Only durable identities can write cross-device records. |
| Learner Record | Idempotent operation log and convergent materialized state | Never use wall-clock LWW for mastery, completions, or attempts. |
| Tutor | Thread persistence, resolved-query management, pedagogical guidance | Learner state may alter style only. |
| Retrieval and corpus | Evidence selection, public access classification, lexical fallback | Only approved corpus spans support facts/citations. |
| Claim gate | Sentence-to-span verification and abstention | Failed binding produces `abstain`, never a grounded label. |
| Evaluation | Private LQS execution and reports | Restricted text never enters public release/runtime surfaces. |

The reviewed diagrams are maintained in `docs/uml/`. The detailed rationale and traceability IDs remain in the transformation blueprint.
