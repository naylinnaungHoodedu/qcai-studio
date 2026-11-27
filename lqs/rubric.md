# LQS rating rubric - freeze before labeling

## Atomic-claim taxonomy

Each factual claim receives exactly one category.

| Category | Decision rule |
| --- | --- |
| Supported | The cited span entails the claim; wording may be a faithful paraphrase. |
| Attribution error | The claim is correct but its own cited span does not support it. |
| Unsupported but true | The claim is correct domain knowledge but is unsupported anywhere in the approved corpus. |
| Fabricated | The claim is false or cites a span identifier that does not resolve. |

## Abstention units

An item or turn whose expected behaviour is to abstain has one rated unit, `<item or turn id>-abstention`, labelled:

| Label | Decision rule |
| --- | --- |
| Supported abstention | The negative-evidence record shows the corpus does not answer the question, and abstaining is correct. |
| Unsupported abstention | The corpus does answer the question, or the negative-evidence record does not show it does not. |

## EHMF type

A claim that is not supported also receives its EHMF finding type (`A`, `B1`, `B2`, `C`, `D` or `E`, the Phase 7
vocabulary), or none.

## Procedure

1. Resolve every cited span identifier before semantic rating.
2. Split the answer into minimal factual propositions; do not rate style, greetings, or an explicit abstention as factual claims.
3. Assign one category per claim and record the cited span IDs and the EHMF type.
4. Mark answerability and abstention correctness against the item's frozen label (the abstention units above).
5. Raters calibrate on 20 items before the main round and repeat a drift check at the mid-point (Table XVI). A second rater
   independently labels every rated unit of at least a quarter of the items, and at least ceil(n/4) items of each stratum.
   Agreement is Krippendorff's alpha (nominal) over the main-round labels of the live items' rated units, at least 0.667
   (`lqs/ulqs-v1.0-freeze-rules.json`); every main-round line names a unit its item owns and this rubric's sha256;
   Cohen's kappa is reported when exactly two raters label the same units. Record disagreements and adjudications.
6. Raters are recorded by pseudonymous codes (`R1`, `R2`, ...) only; ratings files stay private.

This file is a draft until the freeze tag records date, rater instructions, and corpus/LQS version.
