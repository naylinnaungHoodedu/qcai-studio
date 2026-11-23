# EHMF change control (golden-set gate)

Plan Phase 7 F "change procedure", D task 6 ("each change passes the Stage 11 golden-set gate"), K AC-7-6, L
("Reload the prior package"), and 12.5 ("it reruns on every model, prompt, corpus, threshold or weight change, and any
drift blocks promotion"). PD-47.

## What the gate pins

`docs/evaluation/phase7/golden_run_v1.json` (written by `scripts/run_golden_set.py`) names the sha256 of:

- the configuration package in use (v6, `apps/api/app/config_package/v6.json`);
- the misconception library it pins (`apps/api/app/config_package/misconceptions/v1.json`);
- the routing table (`ehmf-routing-v1`, `app.services.ehmf.routing.routing_sha256()`);
- the golden set (`docs/evaluation/phase7/golden_set_v1.json`, `golden-set-v1`, 40 public-corpus or synthetic items,
  disjoint from ULQS).

CI runs `python scripts/run_golden_set.py --check docs/evaluation/phase7/golden_run_v1.json`:

1. any pinned sha256 differing from the record exits 6 (a change without a golden-set run);
2. the package's own `ehmf.golden_set.sha256` differing from the file exits 6;
3. a fresh run: an unmet expectation, or a delivered citation that does not resolve (13.9(a): 100%), exits 3; outcomes or
   inputs differing from the record exit 1 (drift blocks promotion).

`--write` refuses (exit 6) to replace a record whose package has the same `package_version` and a different sha256: a
record's `config_version` is its package version, and the rising-A/B stop (plan Phase 7 L) finds a change only where
`config_version` differs between records, so an edit that kept the version could never be compared before and after.

`--write` refuses (exit 4) a working tree that differs from HEAD unless `--allow-dirty` is passed. The record is committed in the same change as the code it covers, so it is written before that commit exists: run `--write` with `--allow-dirty` on the finished change, and the record's `commit` names the parent commit with the suffix `-dirty` (the tree it ran on differed from that commit). The code it ran is identified by `inputs.sha256` (every application module and the two runner scripts, LF-normalised), which `--check` compares with a fresh run. On a tree equal to HEAD (a record rewritten after its code was committed) `commit` is that commit, with no suffix.

The run uses its own in-memory database, the all-public-approved store, development settings (V1 enforce,
MODEL_GATEWAY=on, EHMF=on) and the development fake adapters. It is a change-control gate, not research results.

## The procedure

1. Edit the package, the library, the routing, a weight, the golden set or a threshold, and bump the package's
   `package_version` (every one of these edits changes the package's sha256: the library, routing and golden set are
   pinned in it). The version is the record's `config_version`; `--write` refuses an edit that keeps it (exit 6).
2. Rerun the golden set: `python scripts/config_package.py --rehash` (when the package or the library changed), then
   `python scripts/run_golden_set.py --write docs/evaluation/phase7/golden_run_v1.json --allow-dirty` on the finished
   change (the record names the parent commit with `-dirty`; its `inputs.sha256` identifies the code).
3. Commit the new record in the same commit or pull request as the change.
4. CI is green (`--check`, and every other validator).
5. The pull request review approves. With one maintainer the approver is the owner (P1-D-18); "the X6 auditor MUST NOT
   audit their own change" stays DI-99.

## Rollback

"Reload the prior package" (plan Phase 7 L): a stop only follows a change between two packages with an ehmf block
(6.x to 6.y), so the prior package is the earlier 6.x file the stop names in `from_config_version`: set
`CONFIG_PACKAGE_PATH` to it, or deploy the prior image digest. With it in force the stop state reads `reverted` and
`/ready` reports `ehmf.stop.revert_required` false. Reloading v5 (readable for one release, DI-112; no ehmf block) is
not a revert of the stop: it turns EHMF off (`/ready` `ehmf` null, no stop read). Record the stops first
(`python -m app.workers.ehmf status`; under a package without an ehmf block it logs `ehmf.status_refused` with the rows
and exits 2). Nothing writes configuration automatically (D-05): the rising-A/B stop only reports "revert required" on
`/ready` and raises the audit draw to 1/5; the revert is the operator's (plan L's automatic revert is DI-114).

## The library edit path

The misconception library is edited only by the Content Owner or from V3 (plan task 2). An entry's `editor` is
`content_owner` or `v3:<gold record hash>`; its `paraphrase` is a public-corpus paraphrase (never licensed text, E-95, at
most 280 characters, sharing no run of more than 8 words with a cited span); its `span_ids` resolve in the public corpus.
Library v1 ships with no production entries (Q-14 unavailable, A-18; DI-106). An edit is a change under this procedure:
edit the file, bump the package's `package_version`, rehash (the sidecar and the package pin), rerun the golden set,
commit the record.

## The V3 proposal path

`python -m app.workers.ehmf export-library-proposals --path <outside the checkout>` writes one proposal per Type C claim
label of an applied V3 item (`misconception-proposal-v1`: the claim id, its span ids and `editor_required:
content_owner`; no gold label, rationale or reviewer data). A proposal is never applied automatically: the Content Owner
writes the paraphrase and applies it as a library edit above (DI-113). B2/D spans enter the retrieval penalty lists the
same way (`ehmf.retrieval_penalty`, empty as shipped; D-06 owns the factor).

## Renumbering the Phase 7 package

Phase 8 is built in parallel (branch `phase8/learner-record-privacy`) and also wants the next package number and
Alembic head. If it reaches `main` first and takes v6 or adds an Alembic revision after `20261122_phase6_v3_audit`, the Phase 7 branch
merges `main` and renumbers before its pull request (Phase 7 spec 0.1, E16):

1. Rename `apps/api/app/config_package/v6.json` (and its sidecar) to the next free number, say `v7.json`; set its
   `package_version` to `7.0.0`, its `schema_version` to 7 and its `supersedes` to the package now on `main` (its
   version, path and sha256); carry over what that package added.
2. Set the two constants that hold the number, which must stay equal (`test_the_phase_7_package_number_is_read_from_one_constant_per_side`):
   `app.core.config_package.EHMF_SCHEMA_VERSION` (every schema-dependent rule of the loader, the package checks and
   `scripts/config_package.py` compares with it) and `app.services.ehmf.vocabulary.EHMF_FIRST_MAJOR` (the first major
   whose records read as their own `config_version`); set `ehmf.config_version.first_package` to `7.0.0`, and point
   `DEFAULT_PACKAGE_PATH` at the new file.
3. Alembic: set `down_revision` of `apps/api/alembic/versions/20261123_phase7_ehmf.py` to the head now on `main`,
   update `ledger.SCHEMA_REVISION` and the single-head and rollback tests, and run the suite on SQLite and on PostgreSQL
   under psycopg and pg8000.
4. Run `python scripts/config_package.py --rehash`, then rewrite the records: the golden run
   (`python scripts/run_golden_set.py --write docs/evaluation/phase7/golden_run_v1.json --allow-dirty`) and the
   fixture, replay and residual reports with their own scripts.
5. Edit every text naming v6 or 6.0.0 for Phase 7 (this document, the Phase 7 spec, ADR-010, the runbooks, the test
   strategy, the env example). Tests read the shipped version from the package (`ehmf_fakes.SHIPPED_VERSION`,
   `NEXT_PATCH`, `NEXT_MINOR`), so no test literal changes except the doc tests that quote file names.
