All three polish items are fixed on `wp/P0-TOOLCHAIN`, HEAD **`5825345`**. The CI stages, ctest and pytest re-runs all pass. Evidence files are in `$FLMOD_TESTRUNS/20261018T0800Z-toolchain-r3-polish/`.

| Finding | Change | Test and evidence | Status |
|---|---|---|---|
| **N1:** code in `src/logic` could include a header from a `tests/` dir and pull `<windows.h>` into the win32 `logic` library | The include lint now rejects any quoted include from linted code that lands inside a `tests/` dir ("resolves into a tests/ dir, which is not linted"). | New negative fixture `tests/host/negative/lint_fixture/bad_tests_include.hpp`, which includes `tests/leak_helper.hpp`; the existing failing-lint ctest now expects it. The reviewer's loophole rebuilt in the real tree: host and trackB builds both fail, and both pass after removal (`n1_loophole.txt`). | DONE |
| **N2:** the "prefix in use" check compared raw paths; no baseline check | `toolchain/prefix_clone.sh` runs `realpath -m` on both sides before comparing, as in D110. A `prefix-dev-base-*` clone source must contain `BASELINE.json`, as `lane.sh` requires. | New `toolchain/tests/test_prefix_clone.py`, 20 cases. They cover `//`, `/./` and `x/..` spellings and odd spellings of the prefix argument. They also cover a process running inside the prefix, and that a similarly named neighbour prefix doesn't count. BASELINE.json present and missing, a baseline in use, and bad `--from` values are tested too. The previous version fails 9 of them (`n2_negative_control_old_prefix_clone.txt`). Both real baselines are still accepted (`n2_real_baselines.txt`). The 23 refused invocations still give the right exit code and create nothing (`refusals.txt`). | DONE |
| **N3:** `check_flags.py` gaps | It now looks past `ccache`/`sccache` and fails any entry that isn't clang-cl. Only `.rc` entries run through llvm-rc are skipped. It fails `-fno-async-exceptions`, `-fno-exceptions` and `-fno-cxx-exceptions` written as `/clang:`, `-clang:` or `-Xclang`. A later `/EHsc`, `/EHs-` or `/EHa-` still fails, because the last `/EH` flag must be `/EHa`. | 8 new pytest cases (19 in the file). The real build is still clean: 36 TUs in A and 37 in B, no other entries. | DONE |

**Re-runs:**
- **CI:** P0-REPO's real `ci.sh` (`wp/P0-REPO@32ab66a`), stages public, build, host-tests and import-check, from an empty `build/`: all four PASS (`20261018T074640Z-ci/`).
- **ctest:** 6/6 on host and 6/6 on host-asan (run inside CI stage 20).
- **pytest** on `toolchain/tests`: 55/55.
- **check_public:** `--tree` clean (151 files). `--commits=main..HEAD` clean (11 commits) with both the local snapshot and the `32ab66a` checker.

No Wine run this round, since the probe didn't change. No `prefix-dev-toolchain*` clones are left. The NOTES RESUME POINT is updated and marked complete.
