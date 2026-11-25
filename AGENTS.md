# Agent rules for this branch (Phase 8)

If this session was not given the Phase 8 hand-off brief, stop and ask the owner for it before changing anything.

These rules bind the agent building Phase 8 on this branch, not the main-track agent that reviews and merges it.
They do not replace the repository's own docs.

1. Secrets: never open, print, copy, `git show` or `cat` `.env*` files, `infra/cloudrun/*.env.yaml`, release env
   files, keys or credentials, nor the tracked templates `apps/api/.env.example`, `apps/frontend/.env.example`,
   `infra/cloudrun/*.env.example.yaml`, `infra/k8s/secret.example.yaml`. Exclude them from every search:
   `git grep <p> -- ':!*.env*' ':!infra/k8s/secret*'` or `rg <p> -g '!*.env*' -g '!infra/k8s/secret*'`, and from
   every command that prints a diff or file contents: every `git diff` in any form (`<a> <b>`, `--cached`, `HEAD`,
   `MERGE_HEAD`, the working tree; `git diff ... -- . ':!*.env*' ':!infra/k8s/secret*'`), every `git log -p`, every
   `git show` and every `git stash show -p`; run `--stat` or `--name-only` first. Never `rg -uu`/`--hidden` or a
   script that prints file contents across the tree. Run the tests that read a template (the hand-off brief's 7.2
   lists them) only by id with `--tb=no -rN -q`, and keep them out of every other run with `-k "not (...)"`; if one
   fails, never re-run it in any other form or print its operands: stop and ask (after the one check the brief's 7.2
   allows). Never put a secret in code, tests, logs, docs or commit messages.
2. No cloud or production actions: no deploys, no cloud CLI, no Cloud Build or Cloud Run changes, no image pushes,
   no DNS, registrar, billing or account changes, no reads of production data or production databases. Never create
   accounts, keys or service identities. Never deploy an image built on a workstation.
3. Freeze: nothing new reaches learners. Every new behaviour is behind a flag that is off outside development; any
   non-off value outside development is refused while `phase8_exit_passed` is false.
4. Git: work only on this branch. Never push to `main`, merge a PR, enable auto-merge, change repository settings,
   force-push, rebase a pushed branch or rewrite history. Bring `main` in with a merge commit. Never open, edit or
   close a PR, push a tag or delete a branch. Every commit ends with the attribution trailer the owner gave. Changes
   reach `main` only through a reviewed PR that the main-track agent owns and merges.
5. Network: tests and scripts make no network call and call no model provider or external API. Your only network
   use is `git fetch` of this repository and `git push` of this branch. Use only pinned dependencies and never
   install anything; adding or upgrading a dependency needs the owner's approval.
6. Privacy: no emails, account names, learner identifiers, real personal data or secrets anywhere. Test data is
   synthetic. No reviewer names in the repository.
7. Decisions: never close an open owner decision. Delegated decisions take the plan's own default, provisionally,
   recorded in configuration and as a PD row. Never decide a factual question (Q-nn): it takes its unresolved path.
   With no plan default, take the most protective path and record it. Never offer "accept in writing" for a
   blocker. Use only PD-200..PD-249 and DI-300..DI-399.
8. Fix everything: every upheld review finding is fixed, minor ones included. Only items blocked by an open owner
   decision, a cloud write, a production deploy, network access or learner-facing capability outside development stay
   open, each with a DI row naming its blocker. "Minor", "low risk" and "pre-existing" are not reasons.
9. Workstation: do not modify system or security settings; add no permission or sandbox rules.
10. Other copies: never read or write any other checkout of this repository or the owner's evidence folder, except
    reading the review findings files and writing the response files the owner names. Never edit or delete a
    findings file.
11. Scope: Phase 8 only. Shared files follow the collision rules in the Phase 8 spec.
12. Stop and ask: when blocked by an owner decision, a factual question or a conflict between these rules and the
    plan, stop that item, record it and ask the owner. Never route around a refusal.

Rule numbers here equal the hand-off brief's section 2, so "rule N" means the same rule in both.
