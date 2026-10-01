# P4 selection v2: capped quality target, frozen evidence

## Exact contract diff

`configs/p4-benchmark-v2.json` is a copy of v1 with exactly two JSON changes:

1. `contract_version`: `p4-retrieval-engineering-v1` → `p4-retrieval-engineering-v2`.
2. Added `selection.semantic_crosslingual_recall10_target_rule` with value
   `min(1, baseline + 0.10)`.

Only the semantic and crosslingual recall@10 gate target changes. The baseline is
BM25_ONLY on the same subset. The rule is independent of model identity and applies
equally to A and B. Lexical maximum losses remain 1/30 macro recall@10, 0.03 MRR@10,
and 0.03 nDCG@10. Semantic/crosslingual MRR@10 and nDCG@10 must not regress.
Identity-promotion error rates must be zero (including negative cases); zero-case
negative denominators must have null values, not invented zero measurements.
No epsilon relaxations are applied at gate boundaries.

All other v1 fields are unchanged, including fusion, CPU evidence requirements,
comparability and tie-break rules, model pins, and the one-attempt full-build cap.
The quality-only verifier does not execute those later performance-selection steps.
All v1 configs and results, including their original STOP decision, remain intact.

## Evidence and verifier

`tools/p4_selection_v2.py` reads the original
`reports/P4/continuation-pilot-quality.json`. Its raw-byte SHA256 must equal
`05c44cfffab21235fd584c1fa289b976179a1b7ae92bfd06875b79c449ee2284`, derived beforehand
from `git show ffff13b:reports/P4/continuation-pilot-quality.json` using a byte-preserving
subprocess. The expected value is pinned, never inferred from the receipt being checked.

The verifier reads `configs/p4-pilot-score-job.json` and checks **every** receipt binding:
gold, corpus, lexical, dense_a, dense_b, config (v1), and summary (job key
`model_summary`). Large inputs are streamed for hashing only. Missing files, missing or
extra bindings, hash mismatches, invalid JSON, duplicate keys, nonfinite or out-of-range
metrics, incorrect counts/denominators, and model-provenance mismatches fail closed.
Model repository/revision strings come from the hash-bound frozen model summary and
must match the config. No model assets, database, retrieval engine, or embeddings are
loaded. No relevance judgments or fusion results are recomputed.

Each A/B gate is calculated from receipt metrics, independently of the receipt's old
selection or gate-failure fields. The output records baseline/value/target and pass/fail,
all failures, source SHA256, all input hash validations, and job/v2-config hashes. A
quality-only selected repository and revision are emitted only for a unique passing
model. Zero or two passers produce no selected model; performance tie-breaking is not
fabricated. This is not a final model selection or authorization for a full build.

After explicit authorization, run from the repository root:

```text
python tools/p4_selection_v2.py
```

There are no input/output override flags. The sole output is
`reports/P4/selection-v2-recompute.json`, opened exclusively; an existing receipt is
never overwritten. Validation completes before the output is opened. The receipt
explicitly records no retrieval/embedding/fusion reruns, no gold or fusion changes,
and CPU/full-build evidence as NOT_RUN. Implementation tests exercise arithmetic and
temporary files; they do not run the real verifier or produce the real receipt.

## Frozen limitations, not model-specific exceptions

The original semantic BM25 recall@10 is 0.975 (97.5%). Its uncapped v1 target was
1.075, which is unattainable; v2 caps that target at 1.0, not at 0.975. A candidate
still must reach perfect semantic recall and preserve MRR/nDCG.

The frozen crosslingual MODEL_B exact-dense recall@10 is 26/30 (86.67%), while its
RRF hybrid is 22/30 (73.33%), a 13.33 percentage-point loss from dense to hybrid.
This is a frozen fusion limitation, not a reason to retune fusion or special-case B.
The report derives cap activity and dense-versus-hybrid values from metrics for both
models. Frozen arithmetic implies A retains crosslingual recall/MRR/nDCG failures and
B is the unique quality passer under v2; this is not a claim that provenance verification
or CPU qualification has been run. No v1 evidence is replaced by that interpretation.
