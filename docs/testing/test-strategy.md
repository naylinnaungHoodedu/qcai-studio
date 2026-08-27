# CS595 test strategy

| Dimension | Primary automated gate | Acceptance evidence |
| --- | --- | --- |
| Functional | Pytest RTM-ID tests, merge property tests, claim-gate tests | All critical requirements pass. |
| Integration | API/provider/corpus contracts and semantic-off fallback | No contract failure; fallback yields controlled evidence/abstention. |
| System | Target-browser sign-in, Tutor, device-A/device-B resume | All critical journeys pass. |
| Accessibility | axe, Lighthouse, keyboard and screen-reader scripts | Zero critical issues; Lighthouse >=95. |
| Performance | CWV plus backend load profile | LCP <2.5s, INP <200ms, CLS <0.1; approved backend SLO. |
| Security | Threat model, SCA, SBOM/image scan, abuse tests | No open critical finding. |
| Grounding | Frozen LQS four-arm run, claim/citation labels | Wilson intervals, paired McNemar, effect sizes, full denominators. |
| Usability | IRB-authorized persona task sessions | Core-task success >85%. |

CI executes the safe pre-freeze gates. The frozen research run and human-subject evidence are separately archived at G3.
