# Stage Status (SakuraKnowledge)

## Current f99a115 nine-finding repair — READY_FOR_REVIEW / WAITING_REVIEW

Submission evidence: `reports/P2/review-f99-delivery.json` and
`reports/P2/review-f99-nine-findings.md`. This proposes readiness, not external approval.
The f99a115 review was **CHANGES_REQUIRED / NOT_READY**; its passing aggregate tests
were insufficient and remain historical. Its checkout-byte receipt index is superseded
by `review-f99-historical-binding.json`, not silently treated as a committed-byte index.

- Implementation/reference/clean artifact source: `5305e48bcc0f7d794bc21155cb834033256911d4`.
- Failure-first regression:24 FAIL/5 PASS before; final pytest150/Rust5, seven checks exit0.
- New formal151 PASS=135 full-value+16error contracts; zero retries/timeouts,604 raw hashes verified.
- New performance960/960 measured+32fixed warmups;496 pairs/996 stream hashes verified.
- New wheel/binary source-external8 pairs plus2 reviewer real-query counterexamples pass.
- New25-receipt binding hashes exact committed bytes at `1d5954fb233a63ef01f39ab0cd16def1f45399ce`.
- Snapshot unchanged; P1/main/old receipts untouched, R4 not reopened, P3 not started.
- Local-only artifacts; Linux/Pi/full human review/dbstat/Pool/live refresh NOT_RUN.
- Final push SHA is verified independently and reported with submission, without a self-referential file hash.

## Historical bd99b7a repair — superseded by f99a115 CHANGES_REQUIRED review

Current evidence: `reports/P2/repair-bd99b7a-delivery.json` (R1–R6 and all gates).
This is implementation/validation readiness, **not external review approval**.
Final submission/origin SHA is verified after the normal dev push; main is not merged.

- Final Python/Rust implementation: `199af7595fa60a5af9d8e5daa9fc80be1e382d5d`.
- Clean artifact source: `eac2c9685e81ab33c0ff1390dfc29ae179456611`.
- Formal parity v3: 151/151 accepted, **135 actual full JSON comparisons + 16
  expected-error contracts**, no retries/timeouts. Repaired v1/v2 failures retained.
- Independent and integration pytest: 108 passed; Rust: 4 passed; full seven-command
  check matrix exit 0. Synthetic expected behavior is separate from real-source facts.
- Performance v2: 960 measured successes + 32 excluded fixed warmups; 8 workloads,
  2 runtimes, reused-connection API and independent CLI, 30 measured per group.
  Perf v1 remains FAIL because its Python search CLI used invalid `--topk`; v2 fixes
  the measurement to `--limit`, without changing runtime or artifact bytes.
- New wheel/standalone Rust: source-external validation 8 paired full JSON cases,
  help/errors and verified UTF-8 pass. New artifacts are **local-only**, not Git downloads.
- Frozen snapshot SHA remains `4c5ebae18fc941df3f7b1037539fb084b2af79220bb06b8eb810c43f26b51073`.
- P1 CLOSED_AND_MERGED; no snapshot rebuild, main changes, Pool or P3 work.
- Linux, Pi runtime, full human fact review, dbstat scan and upstream refresh NOT_RUN.

## Historical submission below — not the current conclusion

The following records the earlier submission (`reports/P2/p2-delivery.json`).
Its claims and failed receipts are retained as historical context, not current acceptance.

## Stage matrix

| Stage | Scope | Status | Evidence |
|---|---|---|---|
| P1 build | Full 4-source snapshot (bangumi archive, moegirl, mapping, danbooru + tag_wiki) | DONE | `reports/P1/full-reconciliation-20bf5b3.json`, snapshot sha256 `4c5ebae1…`, verify EXIT 0 |
| P1 quality | Query performance, reconciliation, trust split | DONE | `reports/P1/` receipts |
| P2 A | Reference fixes (trust split, ask templates, identity boundary) | DONE | commit `e5c4fd9` |
| P2 B/C | Rust runtime + CLI + 26-case parity | DONE (replaced by v2/v4/v6 151-case parity) | commits `abc3a8f`, `7f529b1` |
| P2 review remediation | Parity 151, compat receipt, wheel/dist, perf, docs | IN PROGRESS — this document set | `reports/P2/` receipts below |

## P2 review remediation — item status

1. **151-case parity** — `reports/P2/rust-parity-20bf5b3-v6.json`: 150 EQUAL + S18
   `RUST_BUDGET_EXCEEDED` (Rust 25/25 attempts > 5 s budget; every attempt
   recorded in `attempt_trail`). Honest result: overall **FAIL**, exit 1.
   The Rust reference is budget-boundary on `a's_wonderland` — not a
   semantic mismatch, but not PASS either.
2. **Docs + delivery JSON** — this file, `runtime-contract.md`,
   `rust-migration.md`, `reports/P2/p2-delivery.json`.
3. **Wheel 0.2.0 in isolated venv** — `reports/P2/p2-wheel-cli-20bf5b3.json`:
   fresh `--without-pip` venv, `pip --no-index` install, 11-command matrix
   incl. a GBK-console sample (code-page independence), all strict UTF-8
   (0 U+FFFD), success stdout parses as full JSON, error stderr is JSON
   (`UsageError` contract on both runtimes), in-process Unicode cross-check
   8/8. overall PASS.
4. **sknow-rs outside source tree** — binary copied to
   `dist/p2/sknow-rs-0.2.0-win64/`, same matrix, hash manifest
   `reports/P2/p2-artifact-manifest.json`, binary sha256 `a8f8cdb9…`.
5. **Read-only snapshot compatibility** —
   `reports/P2/snapshot-compatibility-20bf5b3.json`: sha256 identical
   before/after, python write attempt blocked, Rust `SQLITE_OPEN_READ_ONLY`
   inspect ok, required columns verified, inspect error path both runtimes.
   **dbstat: NOT AVAILABLE** in this system's SQLite build (recorded, not
   faked).
6. **Performance** — `reports/P2/p2-perf-20bf5b3.json` + raw JSONL
   `reports/P2/raw/perf/p2-perf-samples.jsonl` (1,596 end-to-end CLI
   samples, no retries, 120 s hard bound). Rust p50 ≈ 40–45 ms vs Python
   ≈ 190–240 ms (interpreter start dominates). Budget failures are failure
   samples: S18 rust 6/6 rounds, python 4/6; S17 once each on round 0;
   S01 python once on round 0.
7. **A-evidence** — `tests/test_evidence.py` (occurrence dataset partition,
   nullable `sample_count`, invalid frequency rejected-not-published,
   `source_fields` bounded projection, read-only write blocking); CLI
   UTF-8 reconfiguration fix in `sakura_knowledge.cli.main` (GBK console
   no longer raises `UnicodeEncodeError`).

## NOT_RUN (explicit)

- Rust gold eval (ask-template quality on held-out human-expected set) —
  not run; templates verified by parity only.
- Pi Skill runtime integration — not run.
- Full human source-fact review — not run.
- SakuraPool integration — not run.
- Live upstream refresh — not run; everything above is on the frozen
  snapshot `20bf5b3`.

## Environment of record

- Windows, gnu toolchain rustc/cargo 1.98.1, GCC 16.2.0 (w64devkit).
- Python 3.14.5, SQLite 3.50.4 (FTS5 yes; **dbstat no**).
- Machine: see `reports/P2/p2-perf-20bf5b3.json` `host`.
