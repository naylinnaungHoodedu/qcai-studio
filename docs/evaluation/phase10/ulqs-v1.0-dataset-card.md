# ULQS v1.0 dataset card (template)

A template: fields, rules and policies only. It holds no item, question, claim, gold answer or evidence text. The PI fills
the bracketed values in the research plane at freeze; the filled card stays there until a release is approved (DI-139).

## Identity

- Dataset: ULQS v1.0 (`dataset_version` `ULQS-v1.0`, records `schema_version` 1.1, schema `lqs/ulqs-v1.0.schema.json`).
- Corpus version: [one `QCAI-CORPUS-YYYY-MM-DD` value]; it is a field of each item, never part of an id (R-19).
- Freeze record: [dataset sha256; rules sha256; agreement-record sha256] (`scripts/validate_ulqs.py --freeze --freeze-out`).
- Source: ULQS v1.0-rc1 (88 items, one author), migrated with `scripts/migrate_ulqs_rc1.py` and the table
  `lqs/ulqs-rc1-to-v1.0-mapping.json`.

## Fields

The required and optional fields, vocabularies and stratum rules are those of `lqs/ulqs-v1.0.schema.json` and
`evaluation/qcai_eval/ulqs.py` (spec 3.1). Answerable units carry evidence pointers and atomic claims; abstaining units carry
a negative-evidence record and an abstention rationale; S6 items are dialogues of at least two turns; S7 items carry a base
question and three replays (beginner, intermediate, advanced).

## States

draft -> candidate -> review -> frozen -> release, and retired from any state. An item leaves review for frozen only with
`validation.human_reviewed` true, all validation flags true and `item_kind` marked; frozen and released content is immutable.

## Strata (provisional, PD-63; the PI's choice, DI-136)

| Letter | Paper | Name | Target |
|---|---|---|---|
| A | S1 | Single source | 40 items |
| B | S2 | Multi-hop | 25 items |
| C | S3 | Near-miss | 20 items |
| D | S4 | Adversarial (correct the premise or abstain) | 15 items |
| E | S5 | Unanswerable | 15 items |
| F | S6 | Multi-turn | 20 dialogues |
| G | S7 | Invariance | 25 items |

The rc1 card's allocation (A44 B28 C20 D14 E14 F12 G28) is recorded in the freeze-rules file as the conflicting source.

## Freeze conditions

120-200 non-retired items, each stratum exactly at its target, every item frozen and human-reviewed with its validation
flags true and `item_kind` marked, at least 4/5 at Bloom "understand" or above, at most 1/10 bibliographic, one corpus
version, every pointer resolved and checked against the corpus text character for character, every item's move from the
previous set (the review set or the last frozen set) allowed by the state machine with no frozen content changed, and a
current agreement record with
Krippendorff's alpha (nominal) of at least 0.667 and at least a quarter of items second-rated (and ceil(n/4) per stratum).

## Rated units

Each gold claim, and one abstention unit per abstaining item or turn (`<id>-abstention`), labelled by pseudonymous raters
(`R1`, `R2`, ...) under `lqs/rubric.md`. Ratings files are private (`lqs/ratings/*.private.jsonl` or outside the repository).

## Pointer policy, release and licence

- Evidence is referenced by pointer only: `EV-...` ids resolve through the research-plane evidence catalog, `span-...` ids
  through the Phase 2 span records. No span text is stored in an item.
- A released benchmark carries pointers only (plan H; paper Sec. VIII-F). No release is cut (DI-139).
- Licence class: `private_eval_full_span`. Access: the research plane only, under the access log (`access-log-format.md`).

## Contamination statement

- Before and after every run, the salted fingerprints of the licensed corpus and the ULQS are scanned over every
  research-plane log, and the contamination report records zero matches (`contamination-report-template.md`).
- Limitation (R-25): the scan finds reuse of the corpus and the ULQS in our own outputs and logs; it cannot detect
  pre-training contamination of the pinned models, which is reported as a limitation.
