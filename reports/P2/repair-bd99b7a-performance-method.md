# Performance evidence clarification

No running task was restarted. Both complete rounds and their original outputs
are retained, including every failed command in round 1.

## Actual driver commands

Both rounds used the same frozen snapshot, unchanged implementation and artifacts:

```text
python tools/measure_repair_perf.py --db build/snapshot-full-20bf5b3/knowledge.sqlite --bin dist/p2-repair-eac2c96/sknow-rs.exe --reused-bin rust/target/release/examples/bench_reused.exe --out reports/P2/repair-bd99b7a-perf-v1.json --samples 30
python tools/measure_repair_perf.py --db build/snapshot-full-20bf5b3/knowledge.sqlite --bin dist/p2-repair-eac2c96/sknow-rs.exe --reused-bin rust/target/release/examples/bench_reused.exe --out reports/P2/repair-bd99b7a-perf-v2.json --samples 30
```

Both used `PYTHONUTF8=1`, `PYTHONIOENCODING=utf-8`. Absolute executed argv,
stdout/stderr bytes (base64), hashes, exits and wall times are in each receipt.

### The corrected child argv

Python independent CLI search in v1, **incorrect**:

```text
python -c "from sakura_knowledge.cli import main;raise SystemExit(main())" search <absolute knowledge.sqlite> "a's_wonderland" --topk 10
```

Python independent CLI search in v2, **correct**:

```text
python -c "from sakura_knowledge.cli import main;raise SystemExit(main())" search <absolute knowledge.sqlite> "a's_wonderland" --limit 10
```

The same correction applies to the `孤独摇滚` FTS workload. Python's actual CLI
contract is `--limit`; Rust's CLI uses `--topk`. The v1 stderr explicitly reports
`UsageError: sknow: unrecognized arguments: --topk 10`, exit 2. These are measurement
invocation failures, not query-budget timeouts. Runtime code, S18 query, topk=10,
OR semantics, artifacts and all other workload arguments stayed unchanged.
The direct API calls in reused mode use topk=10 and were unchanged.

V1 is **FAIL**: 960 measured attempts, 900 successes, 60 failed Python CLI searches;
its 32 warmups include two more failed Python CLI search invocations. V1 raw is
`repair-bd99b7a-perf-v1.json`, unchanged. V2 is a new complete run after correcting
the measurement script, not selective retrying/merging good samples: 960/960
measured successes and 32/32 warmup successes. The current acceptance uses v2
only, with v1 separately retained in the history and delivery index.

## Predeclared method and limits

- Eight workloads, two runtimes, two modes, 30 measured attempts per group.
- Exactly one fixed warmup pass per mode/runtime, recorded with `round=-1` and
  `warmup=true`, excluded from percentiles, never used to decide retry counts.
- No retry loop and no success-conditioned repetition. Failed measured attempts
  remain in `attempted` and `failed_rounds`; success percentiles and failures are
  reported separately. All raw results remain, including stderr and nonzero exits.
- Inner runtime deadline: **5 seconds per public operation**, shared by nested
  calls. This is not increased by the benchmark.
- Independent CLI: **15-second subprocess hard limit per invocation**; killed on
  timeout and captured as failure. The outer limit does not replace the 5-second
  runtime gate.
- Reused mode: one Knowledge/Runtime object and connection per runtime, reading
  the whole fixed request sequence. **600-second subprocess hard limit for the
  entire batch**, while each request still has the inner 5-second operation
  deadline. It is not claimed to have a separate 15-second host timer per request.
  A stuck batch is killed; absent responses count as failures, not PASS.
- Concurrent pipe draining prevents output-pipe deadlock. RSS is a 5ms sampled
  observed process maximum; reused-mode RSS covers the entire batch. Neither is
  a precise per-query allocation or guaranteed whole-run peak measurement.
- Process startup/open/output are in independent CLI wall time; reused API timing
  and JSON serialization are separate. Neither mode claims an OS disk-cold cache.

See `repair-bd99b7a-perf-verification.json`: 992 v2 records, 496 paired complete
JSON outputs, 996 raw stream hashes verified. No failures were removed to produce
these totals.
