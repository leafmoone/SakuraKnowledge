# Windows USearch native reader correction

This directory records a narrow two-path Windows correction and actual native
sparse-file regression. The original continuation FAIL and prior diagnostic are
immutable history. No ANN build, embeddings, continuation, manifest, pack runtime
qualification or quality acceptance is authorized here.

The registry USearch 2.26.2 source is vendored project-locally and selected by the
workspace-root `[patch.crates-io]`. Only mapping length and metadata seek/tell are
changed; serialization, metrics, scalars, dimensions and ANN policy are unchanged.

Python status: **BLOCKED_TOOLCHAIN**. Existing CPython3.14 is an MSVC Windows build;
no compatible MSVC compiler, Visual Studio setup/vcvars or Windows SDK was found
in the checked existing locations/PATH. UCRT64 GCC is used for actual native C++
and Rust tests, not passed off as a compatible rebuilt Python extension. The old
`.venv-p4-ann` is unchanged; its tests are not patched-Python validation.

Sparse metadata fixtures contain prefixes/holes/header/trailing byte and are
**not valid ANN indexes**. The regression invokes actual upstream/patched native
methods, not a Python stat/mmap substitute. FSCTL_SET_SPARSE and actual allocated
bytes are checked. Actual Windows64 tests are not evidence of a real 32-bit or
non-Windows build; mocked failure/overflow cases, if any, are separately labelled.

A first harness attempt used Python truncate and failed the sparse allocated-size
gate before native tests. That failure is retained. The corrected harness uses
Win32 SetFilePointerEx/SetEndOfFile; the unpatched old2 run passes8/17 and fails9/17,
including both matrix-prefix widths above2GiB and4GiB plus mapping at4GiB and above.

Any future read-only full path probe must bind fixed source and newly built loader,
run once, and retain failure without retry or buffer fallback. Such a probe is a
bottom-level reader test, not FULLSemanticRuntime E2E or production recovery.
