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

The run uses its own in-memory database, the all-public-approved store, development settings (V1 enforce,
MODEL_GATEWAY=on, EHMF=on) and the development fake adapters. It is a change-control gate, not research results.

## The procedure

1. Edit the package, the library, the routing, a weight, the golden set or a threshold.
2. Rerun the golden set: `python scripts/config_package.py --rehash` (when the package or the library changed), then
   `python scripts/run_golden_set.py --write docs/evaluation/phase7/golden_run_v1.json` on a clean tree.
3. Commit the new record in the same pull request.
4. CI is green (`--check`, and every other validator).
5. The pull request review approves. With one maintainer the approver is the owner (P1-D-18); "the X6 auditor MUST NOT
   audit their own change" stays DI-99.

## Rollback

"Reload the prior package" (plan Phase 7 L): set `CONFIG_PACKAGE_PATH` to the prior file (v5 stays readable for one
release, DI-112), or deploy the prior image digest. Nothing writes configuration automatically (D-05): the rising-A/B stop
only reports "revert required" on `/ready` and raises the audit draw to 1/5; the revert is the operator's.

## The library edit path

The misconception library is edited only by the Content Owner or from V3 (plan task 2). An entry's `editor` is
`content_owner` or `v3:<gold record hash>`; its `paraphrase` is a public-corpus paraphrase (never licensed text, E-95, at
most 280 characters, sharing no run of more than 8 words with a cited span); its `span_ids` resolve in the public corpus.
Library v1 ships with no production entries (Q-14 unavailable, A-18; DI-106). An edit is a change under this procedure:
edit the file, rehash (the sidecar and the package pin), rerun the golden set, commit the record.

## The V3 proposal path

`python -m app.workers.ehmf export-library-proposals --path <outside the checkout>` writes one proposal per Type C claim
label of an applied V3 item (`misconception-proposal-v1`: the claim id, its span ids and `editor_required:
content_owner`; no gold label, rationale or reviewer data). A proposal is never applied automatically: the Content Owner
writes the paraphrase and applies it as a library edit above (DI-113). B2/D spans enter the retrieval penalty lists the
same way (`ehmf.retrieval_penalty`, empty as shipped; D-06 owns the factor).
