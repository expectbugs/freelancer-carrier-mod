**Fix round 2 (attempt 1): DONE.** All seven review findings plus your `--from` request are fixed on `wp/P0-TOOLCHAIN` @ `370c47f`, and the full acceptance set from an empty `build/` passes. No GPU fault: `nvidia-smi` Recovery Action was `None` before and after every Wine run.

The acceptance ran at `d84daae`; `370c47f` only changes `toolchain/NOTES.md`. All run dirs below are under `$FLMOD_TESTRUNS`.

## 1. Fix report

| Finding | Change | Test / evidence | State |
|---|---|---|---|
| F1 MAJOR: the include lint rejected doctest files under `src/logic/**/tests/` | New `cmake/LogicLintFiles.cmake` is the one definition of the file set, with `tests/` dirs excluded. The lint script, the lint stamp's DEPENDS and the header check all use it, so fresh and incremental builds see the same files. I excluded `tests/` rather than allow `<doctest/…>`: that code is host-only, also needs helpers from `tests/host/`, and the host compile already rejects Windows headers there. | New ctest `logic_tests_dir_doctest`: on a scratch copy of the tree it adds a doctest file plus a doctest-including helper header under a `tests/` dir, builds incrementally and fresh, runs the test case and the lint/header tests. PASS on host and host-asan. With the exclusion removed it FAILs ("Forbidden includes"): `20261018T0730Z-toolchain-r2-f1/` | DONE |
| F2 MINOR: no static flag check; nobody named for ehprobe | `toolchain/check_flags.py` runs in stage 10 on each win32 `compile_commands.json`. It requires `-mstackrealign`, `/MD` and `_ITERATOR_DEBUG_LEVEL=0` on every TU, and `/EHa` on every C++ TU. README and ABI.md §6.5 name who should run ehprobe (proposal below). | 11 pytest cases. A spike TU built with `-mno-stackrealign /EHsc` makes stage 10 FAIL with `win32-trackB:flags`; PASS after removal: `20261018T0750Z-toolchain-r2-ci/negatives.txt` | DONE |
| F3 MINOR: reviewer's hostable EH patterns | All 9 added as the `hook` group in the probe (fault inside Common.dll under the guard, nested guards, `__finally`, thread EH, exceptions through msvcrt `qsort`, VC6-style throws). The ones that need the game are listed in ABI.md §6.8 for P0-TRACK-A/B. | All PASS on both tracks × both runtimes | DONE |
| F4 MINOR: stage 50 checked tracks stage 10 didn't build | `toolchain/ci_tracks.sh` is now shared by stages 10 and 50; an invalid `FLMOD_TRACK` FAILs both | `FLMOD_TRACK=B` with a stale trackA dir: PASS. Unset: FAIL (control). `C`: FAIL (`negatives.txt`) | DONE |
| F5 MINOR: §6.2 vs §6.3 conflict | ABI.md §6.7 hook template: the work runs under `flmod_seh_guard`, the try/catch sits inside the guarded body, and a `catch(...)` hit is logged as "possibly SEH" | 4 `hook_template_*` cases: normal path, C++ exception, fault in the body itself (reaches the guard), fault in an opaque call (reaches `catch(...)`). All PASS with the caller's registers intact | DONE |
| F6 MINOR: ehprobe safety | `--prefix` accepts only throwaway `prefix-dev-*` prefixes (no baselines, no lanes). Exit 77 when a requested runtime can't run (never PASS with zero cases). Arguments are validated before any run dir or clone is created, in both scripts. | 23 refused invocations give the right exit code and create nothing (`20261018T0745Z-toolchain-r2-f6/refusals.txt`). `--crt both` with no redist ends SKIP, exit 77; a prefix without the game dir reports the engine case as SKIP (`skip_paths/`) | DONE |
| F7 MINOR: `src/game` tests rule | README "The src/game rule": ARCH-0's module glob must exclude `(^|/)(tests|scenarios)/`; `src/game/<area>/tests/*.cpp` go to `host_tests` | docs | DONE |
| Your addition: `--from` | `load_proof.sh` and `ehprobe.sh` clone `prefix-dev-base-B` by default; `prefix-dev-base-A` or `play` (only while idle) are options. A source in use is refused with exit 3. | Load proof cloned from `prefix-dev-base-B` | DONE |

## 2. Standard report

```
PACKAGE: P0-TOOLCHAIN   ATTEMPT: 1 (fix round 2)   RESULT: DONE
BRANCH: wp/P0-TOOLCHAIN @ 370c47f
SUMMARY: all r2 findings fixed; full acceptance from an empty build/ passes; Wine runs clone a dev baseline.
FILES: cmake/LogicLintFiles.cmake (new), cmake/LogicIncludeLint.cmake, CMakeLists.txt,
  tests/host/{LogicHeaderCheck,LogicTestsDirFixture}.cmake, toolchain/{check_flags.py, ci_tracks.sh,
  prefix_clone.sh, ehprobe.sh, load_proof.sh, ehprobe_cases.tsv, tests/test_check_flags.py, ABI.md, README.md,
  NOTES.md}, src/module/ehprobe/ehprobe.cpp, harness/ci.d/{10-build,50-import-check}.sh
TESTS:
  ci.sh (wp/P0-REPO@32ab66a) --full public/build/host-tests/import-check, empty build/ — PASS x4 — 20261018T072821Z-ci/
  acceptance (PE32 headers, hello_a exports, check_imports A/B, pytest 27/27, both --verify, check_flags,
    windows.h negative test, ctest 6/6) — PASS — 20261018T072821Z-toolchain-acceptance-r2/
  load proof B, CreateID(li02)=2745692751 + EH probe both CRTs 37/3/0/0 — PASS — 20261018T072930Z-toolchain-loadproof/
  EH probe A both CRTs 37/3/0/0 — PASS — 20261018T072950Z-ehprobe/
  check_public --tree (148 files) and --commits main..HEAD (10 commits), snapshot and 32ab66a versions — PASS —
    acceptance-r2/30-32*.txt
DECISIONS: src/logic lint and header check skip tests/ dirs (one shared definition); stage 10 also enforces /MD
  and _ITERATOR_DEBUG_LEVEL=0; an invalid FLMOD_TRACK FAILs stages 10 and 50; Wine clones come from
  prefix-dev-base-B by default; ehprobe --prefix takes only prefix-dev-* (no baselines, no lanes); a probe case
  returns -77 for SKIP; exit 3 means the clone source is in use. No sudo.
ENGINE FACTS LEARNED (VERIFIED, run dirs above, both CRTs, both tracks):
  A fault inside Common.dll (PhySys::DeactivatePhysics(0x10)) is caught by flmod_seh_guard with the caller's
  registers intact. Nested guards, __finally during unwinding, thread EH, C++ exceptions and faults crossing
  msvcrt.dll qsort frames, and VC6-style _CxxThrowException caught by catch(int)/catch(...) all work.
  In the hook template, a fault in the body's own code reaches the guard (0xC0000005); a fault in an opaque call
  reaches catch(...).
OPEN QUESTIONS / BLOCKERS: Proposal: add "run toolchain/ehprobe.sh --crt both" to the P0-TRACK-A/B and
  W1-PLATFORM acceptance (I don't own those specs).
KNOWN ISSUES: (a)/(b) are still coding rules. The in-game EH items in ABI.md §6.8 are untested (they need the game).
  FLUF catch-funclet binary scan and FLUF's non-CRT imports are UNVERIFIED (NOTES Question 3).
```

No `prefix-dev-toolchain*` clones are left and no Wine processes of mine are running. The dev baselines were only read.
