# P4 preparation STOP — NOT_READY / WAITING_REVIEW

## Blocking evidence

`trusted-corpus-coverage-audit.json` records actual command exit **2**, outer
status **FAIL**, inner coverage gate **BLOCKED**. This is not a benchmark FAIL
and not a passed coverage gate. P3 FULL exact bytes/hash were verified first;
read-only immutable SQL and sidecar checks performed, no source mutation.

Trusted current FTS/document projection contains **1,295,638** unique documents:

| source namespace | kind | documents |
|---|---|---:|
| bangumi.character | character | 221960 |
| bangumi.person | person | 102338 |
| bangumi.subject | subject | 690068 |
| danbooru.wiki | page | 281272 |

There are **no Moegirl document rows**. Local tag_wiki document rows exist only
as `no_reference` (601512) and `unverified_draft` (73377). Neither is eligible
for trusted semantic text; embedded raw payload claims cannot upgrade status.
The required four-family pilot cannot be produced within the authorized scope.
Do not silently narrow source coverage, generate descriptions from raw JSON,
promote drafts, change formal SQLite or rebuild P3 to force a PASS.

## What this delivery is

Offline preparation tooling/contracts and real blocked-source evidence, **not a
semantic runtime or completed P4**. Model/device configuration is specified for
future CPU/GPU caller selection; it is not evidence of Rust inference support.
Models are replaceable via matching pinned contracts/packs, not a promise that
arbitrary incompatible architectures can share vectors. Local assets belong in
project `model/`, excluded from Git. Production Python and Rust sources remain
unchanged; no Cargo semantic feature or native dependency was added prematurely.

The 120-case `retrieval-gold.json` remains **DRAFT_PRE_EMBEDDING**. Counts are
30 lexical / 40 semantic / 30 crosslingual / 20 ambiguous-negative. It reuses
primary targets across subsets, lacks mandatory source coverage and has not
been approved as a formal frozen benchmark. No embedding model authored labels.
No compliant pilot was exported, no quality metrics measured, no model selected,
no ANN backend frozen, no full build attempted, and no new runtime regressions
claimed. Default tests and synthetic prep tests do not substitute for those gates.

## Additional legacy preflight limitation

`legacy-baseline-freeze.json` is an offline preflight, not a regression run.
714 retained raw-reference occurrences were checked using repository-tracked
final-raw only. P2 135/135 original value hashes are reconstructable in memory
from installed-Python accepted JSON plus historical CRLF serialization; 16 other
contracts remain separately described. FULL gold **0/55 original oracle hashes**
were recovered. Accepted Rust responses and source assertions are available but
are not silently substituted for the missing independent full oracle bytes.
External P3 local-only preservation was never accessed. Full legacy execution
remains NOT_RUN; any future oracle strategy needs explicitly accepted provenance.

## Safety and continuation

- P3 FULL retained at authorized SHA256; no ALTER/patch/VACUUM/rebuild.
- FULL_SEMANTIC_BUILD_ATTEMPTS=0; FULL_SEMANTIC_PACK=NOT_RUN.
- No models, vectors or ONNX committed; no service/LLM/Tool integration.
- No SakuraPool edits or inspection; inherited Cargo target overridden per command.
- Main stays at P4 base; normal dev-only commits/pushes, no reset/rebase/amend/clean.
- See PREPARATION_LIMITATIONS.md and command receipts for historical preparation
  failures/skips. Exact final checks and SHA binding accompany the stop delivery.
- An incidental untracked uv.lock is preserved, not silently staged/deleted; its
  producer was not proven. Do not call the working tree clean while it remains.

Continuation requires a user decision on coverage (e.g. explicitly narrowed P4
scope, or separately authorized source-backed corpus work). Neither is assumed.
Do not restart embeddings, implement production semantic inference, build FULL,
merge main or enter another phase while this gate remains blocked.
