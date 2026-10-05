# Current delivery status

## Selectable source packs: corrected global semantic fusion

Current change baseline: `a7e0922e7929dc94506a65a9bad4617f280e1e33` on `dev`.
Core + optional Danbooru/Bangumi/Moegirl/tag-wiki packs + one shared BGE-M3 model
remain independently copyable from `build/modular-components/`. Only Core binaries
changed: no source DB, FTS, membership, mapping, model, embedding, ANN graph or
ANN parameters changed. Mother/FP32/old monolithic I8 and old modular receipts
are preserved. Frozen local audit is not live refresh. Rights NOT_CLEARED; no
large upload, Pi/Pool integration, archives, RSS measurement or model training.

### Ranking behavior

For multiple compatible semantic packs, one shared encoding feeds bounded raw
ANN chunk hits. Actual Cos distances are globally sorted, tied by complete typed
identity then document/chunk, deduplicated into best-hit entries (all selected
proofs retained), with global semantic entry depth 100. This contributes **one**
semantic RRF60 branch. Each source contributes its own lexical branch using
original raw document rank, never cross-source BM25 values. Trusted exact/alias
pins precede scores; distinct trusted identities remain unresolved. Contracts
must agree on exact model revision, query/encoder semantics, dimension1024,
Cos/I8 distance representation; missing/nonfinite distances fail closed.

Single-semantic-source retrieval retains the original local path and ordering.
Structured merge/resolve are unchanged. New candidate `global_semantic_rank`,
`best_distance`, and source-qualified `backend_ranks` are diagnostic ranking
fields, not verified identity assertions. Raw ANN pools are internal; public
`dense_hits`/`lexical_hits` for multi-pack retrieval are intentionally empty,
not complete rankings. Candidate provenance/citations/documents carry actual
selected evidence; local numeric IDs are never cross-pack identity.

### Three-version frozen gold comparison

A = saved monolithic I8; B = old modular a7e0922; C = corrected global distance.
Values are Recall@10 / MRR@10 / nDCG@10. Gold unchanged; no tuned weights.

| Group | A | B | C |
|---|---|---|---|
| lexical (30) | 1/.97778/.98333 | 1/.97333/.97956 | 1/.97778/.98333 |
| semantic (40) | .975/.90833/.92559 | .975/.61458/.70667 | .975/.89375/.91463 |
| crosslingual (30) | .53333/.29976/.35667 | .56667/.26306/.33587 | .53333/.25889/.32641 |
| ambiguous-positive (10, accepted targets nonempty) | .65/.41444/.41915 | .4/.34333/.28076 | .6/.37/.38776 |

Semantic: **20 former monolithic rank-1 cases restored from B**, no new rank-1
regression vs B, no additional R10 losses vs A or B. One rank-1 regression vs A
remains: P4-066 (A1/B3/C2); target is global dense1 but Danbooru lexical12,
so lexical competition still wins. Crosslingual **P4-095 loses R10 versus B**
(A nohit/B2/C19): target global dense8, no lexical contribution, displaced by
lexically supported candidates. C has no new crosslingual R10 loss vs A, but
crosslingual quality remains limited. Ambiguous-positive losses vs A are
P4-103/P4-110; none additional vs B. Negative ten have no accepted targets,
are not included in positive metrics; identity promotion remains prohibited.

**Engineering PASS is not overall quality PASS or lossless monolithic equivalence.**
Full per-case A/B/C and actual distance/rank/provenance diagnostics:
`build/federation-three-version-comparison.json` (42 changed cases). Unrecorded
local history is NOT_RECORDED, not inferred from global order. Split ANN graph
and per-source FTS remain different from monolithic assets.

### Actual runtime evidence and checks

`python -m tools.modular_semantic_validate --root 'D:/Sakura 模块化 测试/Core 可选 来源 G' --output build/federation-all120-final`
completed exit0, **120 engineering PASS**, one model session, one encoding each
(cumulative120), actual independent typed entry/document/source/evidence closure,
request-to-complete-line <=5s, <=1048576 UTF-8 bytes including newline. Startup
11752.561ms; E2E p50/p95/max 667.07855/2296.0959/2555.9523ms versus B
740.47995/2232.8282/2571.4677ms. Response p95/max 383583/635848 bytes versus B
495869/752147. Independent checker time 3.08473s total, excluded from runtime
performance. EOF exit0, reader joined, no active termination. PK/indexed readonly
checker retained; no per-proof full scans. Final binary subsequently added only
multiple-trusted-identities warning, no rank changes; tests/rebuild passed. Final
binary targeted P4-001 retains three distinct trusted keys with warning, no
identity promotion, independent closure PASS, one encoding, 328642 bytes,
natural EOF0; P4-103 no pins/no warning also PASS (306524 bytes). Receipts:
`build/federation-final-multipin.json`, `build/federation-final-warning.json`.

Small real P4-032/034/035 changed old rank2 → new1 with actual global dense1
(distances .32763952/.37481487/.34285116), closure PASS, natural EOF0:
`build/federation-small.json`. Actual wrong source/document/typed key/cross-pack
closure tampering rejected. Single Danbooru and Bangumi eight saved queries each
compare **whole business JSON equal**, excluding only `timings_ms` and
`pack_timings_ms`, exit0: `build/federation-singlepack-equality.json`.

Rust library **52 tests PASS** (42 existing +10 new pure fusion tests), release
build passed. Tests cover global distance over local ranks, pack-order-independent
ties, same-key best distance/all proofs, raw BM25 scale immunity, trusted pins,
lexical-only branches, depth100, malformed distance and incompatible contracts;
existing source-selection/shared encoding behavior and real 120 provide additional
coverage. Affected Python/native tests **60 PASS**, Ruff src/tests/tools PASS,
`git diff --check` PASS. Earlier modular full suite remains 1227 PASS/18 Win1314
symlink skips/55 subtests, not rerun or relabeled for this focused change.

### Components and boundaries

Final Core actual runtime bytes: **65,356,781**. Other component bytes unchanged:
model 2,284,443,838; Danbooru 1,894,324,211; Bangumi 10,723,650,815;
Moegirl 181,699,717; tag-wiki 1,718,178,889. Counts include licenses; build-only
positions.u64le is not copied. Final binaries synchronized into Core and actual
external roots; model/source manifests unchanged. Source IDs/counts remain in
`docs/source-groups.json`. Model revision
`5617a9f61b028005a4858fdac845db406aefb181`.

Moegirl/tag-wiki remain exact/alias lexical only, trusted FTS documents0.
Tag-wiki 601512 no_reference /73377 unverified_draft are not upgraded; local tag
aggregate is not native danbooru.tag. Earlier 151 structured evidence remains
134 strict equal +16 independently source-proof-checked search rank differences
+1 physical SQLite page/freelist difference, **not 151 JSON-identical**.
This task does not restore tag text provenance or change trust/FTS. No subsequent
text-trust investigation/implementation is authorized by this delivery. README
copy/assembly/selection commands remain unchanged; public quality limits above
must accompany candidate use.
