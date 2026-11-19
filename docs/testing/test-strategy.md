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

## Phase 2 acceptance map (plan Phase 2 K)

The acceptance tests are in `apps/api/tests/test_phase2_acceptance.py`. They run on SQLite in `api-and-evaluation` and on PostgreSQL 16 in `api-postgres`. The unit tests are in `test_spans.py`, `test_lexical_index.py`, `test_manifest_v2.py`, `test_config_package.py`, `test_citation_migration.py`, `test_near_duplicates.py`, `test_boundary_scan.py`, `test_corpus_spans_table.py` and `test_review_problems.py`.

| AC | Tests |
|---|---|
| AC-2-1 Unique chunk ids equal total chunks, identical across two rebuilds | `test_ac_2_1_unique_span_ids_equal_total_chunks_and_are_identical_across_two_rebuilds` (3 configurations x 2 gates), `..._a_section_used_by_two_lessons_is_one_index_entry`, `..._the_rebuild_route_reports_no_duplicate_span_ids`, `..._manifest_span_digests_match_a_fresh_build` |
| AC-2-2 A manifest licence-field edit changes no span id | `test_ac_2_2_a_manifest_licence_field_edit_changes_no_span_id` (governed and all-approved), `..._an_approval_edit_changes_membership_not_identity`, `..._corpus_version_hashes_the_built_items_and_ignores_licence_fields` (plan 11.1), `..._span_ids_do_not_depend_on_the_manifest_id_or_schema` |
| AC-2-3 Every stored or returned citation resolves (read as in ADR-004, revision 2026-11-19) | `test_ac_2_3_every_returned_citation_resolves`, `..._every_stored_citation_resolves` (qa_interactions and tutor_turns), `..._every_migrated_citation_resolves_and_the_rest_are_labelled_legacy_unresolved`, `..._a_legacy_unresolved_citation_is_never_returned_as_resolved`, `..._a_citation_that_does_not_resolve_is_never_quoted`, `..._governed_history_withholds_citations_of_unapproved_items` |
| AC-2-4 The out-of-scope fixture abstains with zero results above the floor | `test_ac_2_4_the_out_of_scope_fixture_abstains_with_zero_results_above_the_floor` (2 configurations x 2 gates), `..._an_out_of_scope_route_sample_abstains`; `test_score_floor.py` governed p1-floor siblings |
| AC-2-5 In-domain recall@5 is not below the baseline | `test_ac_2_5_in_domain_recall_at_5_is_not_below_the_pre_migration_baseline` (2 configurations x 2 gates; `p1-floor` with every public item approved is a strict xfail citing spec conflict 29, whose stop `test_plan_l_the_p1_floor_recall_stop_*` and `test_plan_l_validate_corpus_refuses_*` prove is enforced), `..._the_frozen_legacy_search_reproduces_the_pre_migration_snapshot`, `..._the_p1_floor_gate_on_the_governed_index_equals_todays_search`; `test_score_floor.py::test_floor_does_not_lower_in_domain_recall` (live code, both gates); `scripts/calibrate_abstention.py --check` in CI |
| AC-2-6 Every manifest hash matches disk | `test_ac_2_6_every_manifest_hash_matches_disk`, `..._a_changed_byte_or_wrong_pointer_oid_fails_the_hash_check`, `..._an_lfs_pointer_oid_is_accepted_as_the_content_hash`; `validate_corpus.py --check-hashes` in CI |
| AC-2-7 Scans find zero private-plane paths or licensed passages | **Partially met: the path half only.** `test_ac_2_7_the_source_asset_route_refuses_a_file_on_the_private_plane`, `..._no_index_resolver_or_span_route_reaches_a_private_plane_item`, `..._private_plane_paths_fail_closed`, `..._the_boundary_scans_find_zero_private_plane_paths`, `..._the_scanners_detect_a_planted_private_path_a_secret_like_name_and_a_planted_licensed_passage`; `test_boundary_scan.py` (built images, release packaging, `--require-ac-2-7`); `scan_boundary.py` in CI. The passage scan needs private-plane fingerprints (D-14), so public CI reports `not_run` and `ac_2_7.status` `partial`; the exit-gate run adds `--image-tar`, `--release-zip`, `--fingerprints` and `--require-ac-2-7`. |
| AC-2-8 A near-duplicate fixture pair fails the gate; the configured set passes | `test_ac_2_8_a_near_duplicate_fixture_pair_fails_the_gate_and_the_configured_set_passes`, `..._the_ci_gate_exits_1_on_a_bound_near_duplicate_pair_and_passes_the_configured_set`, `..._the_2026_video_stays_unbound_even_when_approved`; `validate_corpus.py --check-near-duplicates` in CI |
| AC-2-9 One query under different learner contexts returns identical spans, scores and abstention | `test_ac_2_9_one_query_under_different_learner_contexts_returns_identical_spans_scores_and_abstention` (both gates), `..._retrieval_abstention_and_resolver_take_no_learner_state_input`, `..._invariance_over_seeded_random_queries` |
| Plan G, H, L; tasks 2.1, 2.7; D9 | `test_plan_g_*`, `test_plan_h_*`, `test_plan_l_*`, `test_task_2_7_*`, `test_task_2_1_*`, `test_d9_*`, `test_spans_route_*`, `test_the_shipped_gate_outside_development_is_p1_floor_and_bm25_is_an_override` |

**Exit gate.** The Phase 2 exit gate needs AC-2-1 to AC-2-9 green "in a cited green CI run" (plan Phase 2 P). That needs a push and a CI run, which are recorded separately.
