# LQS rating rubric - freeze before labeling

## Atomic-claim taxonomy

Each factual claim receives exactly one category.

| Category | Decision rule |
| --- | --- |
| Supported | The cited span entails the claim; wording may be a faithful paraphrase. |
| Attribution error | The claim is correct but its own cited span does not support it. |
| Unsupported but true | The claim is correct domain knowledge but is unsupported anywhere in the approved corpus. |
| Fabricated | The claim is false or cites a span identifier that does not resolve. |

## Procedure

1. Resolve every cited span identifier before semantic rating.
2. Split the answer into minimal factual propositions; do not rate style, greetings, or an explicit abstention as factual claims.
3. Assign one category per claim and record the cited span IDs.
4. Mark answerability and abstention correctness against the item’s frozen label.
5. A second rater independently labels a stratified random subsample of at least 25 percent. Record disagreements and adjudications; report Cohen’s kappa with confidence interval.

This file is a draft until the freeze tag records date, rater instructions, and corpus/LQS version.
