# RevB §§8.1-8.5 evaluation protocol

1. Freeze corpus manifest/version, LQS version, rubric, model/provider version, retrieval configuration, and policy version before run collection.
2. Use the same questions, model, seed/settings, and rubric in arm A (no retrieval), B (lexical), C (semantic/no abstention), and D (semantic/abstention).
3. Label atomic factual claims only as supported, attribution error, unsupported-but-true, or fabricated. Resolve every cited span ID automatically before human rating.
4. Report citation faithfulness, attribution error, fabrication, correct abstention, and multi-turn abstention decay per arm with Wilson intervals. Compare paired outcomes with McNemar’s test and report effect sizes/multiplicity.
5. For RQ2 replay each progress-conditioned item at low/medium/high mastery. Compare factual-claim and cited-span sets only; record presentation differences separately.

The evaluator implementation is in `evaluation/qcai_eval`. This protocol does not permit publication of restricted evidence text.
