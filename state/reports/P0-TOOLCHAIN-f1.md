**PACKAGE: P0-TOOLCHAIN, ATTEMPT 1, fix round r1: DONE**, branch `wp/P0-TOOLCHAIN` @ `0bceb22`.

All 15 review findings are fixed and the full acceptance set passes from an empty `build/`. No GPU fault this session: `nvidia-smi` showed Recovery Action `None` before and after every Wine run.

Run dirs below are under `$FLMOD_TESTRUNS` (`/home/user/freelancer/carrier-mod/local/testruns/`).

## 1. Fix report

| Finding | Change | Test / evidence | State |
|---|---|---|---|
| MAJOR EH: wrong /EHa comments | `clang-cl-i686.cmake`, `-overrides.cmake` | — | DONE |
| MAJOR EH: document (a)–(c) and the (a) workaround | ABI.md §6.1–6.6, `flmod_seh_guard` pattern | probe `a_seh_regs_guarded` | DONE |
| MAJOR EH: regression probe | `src/module/ehprobe`, `toolchain/ehprobe.sh`, `ehprobe_cases.tsv`; `load_proof.sh` runs it | B: `20261018T064132Z-toolchain-loadproof/`; A: `20261018T064149Z-ehprobe/`. Both tracks, both runtimes: 24 PASS / 3 KNOWN-BROKEN / 0 FAIL | DONE |
| MAJOR EH: toolchain fix for (c) | `/clang:-mstackrealign` on every C/C++ TU of both builds | `…acceptance-r1/12-flags-tu.txt`; without the flag 4 cases die (`…fluf-crt-rerun/E3_matrix.tsv`) | DONE |
| MAJOR EH: engine facts | below | — | DONE |
| Delay imports not checked | nested-block parser, real readobj fixture | pytest 16/16 | DONE |
| Imported CRT DLL missing from syswow64 passed | now FAIL | pytest | DONE |
| Negative probes accepted any failure | `ExpectFailure.cmake` needs the exit code and the exact error text | ctest 5/5 | DONE |
| Header denylist too small | replaced by an allowlist | ctest lint probe + manual windows.h test (`13-negative.log`) | DONE |
| `/tests/` filters matched absolute paths; nested tests dirs not built | relative globs, `src/**/tests/**` | build + ctest | DONE |
| `src/game` rule for ARCH-0 | root CMake comment + README | — | DONE |
| `fetch_vendor --verify` could download | now offline and read-only, with per-tree manifests | `10-fetch-verify.log` 11/11 | DONE |
| FLUF upstream URLs | added to PINS.md; both return HTTP 200 with sizes matching the local files | `curl -sIL` | DONE |
| `load_proof` clone path hard-coded | `--clone` (`prefix-dev*` only) | loadproof run | DONE |
| ci.d protocol drift | stages 10/20/50 run through P0-REPO's real `ci.sh` (`wp/P0-REPO@4e02754`) | `20261018T063859Z-ci/` PASS/PASS/PASS. Stale-file test: stage 50 ignored a bad DLL left in `out/`, which fails when checked directly (`20261018T063947Z-ci/`) | DONE |
| 14.5x STL claim overstated | marked UNVERIFIED | — | DONE |
| FLSDK code embedded in our binaries | ABI.md §7 + PINS.md cross-reference | — | DONE |

The two Wine-only steps create no D3D device (no d3d9/dxgi imports), so they used no renderer.

## 2. Standard report

```
PACKAGE: P0-TOOLCHAIN   ATTEMPT: 1   RESULT: DONE
BRANCH: wp/P0-TOOLCHAIN @ 0bceb22
SUMMARY: r1 fix round complete; full acceptance from an empty build/; open CRT question answered with evidence.
FILES: toolchain/{README,PINS,ABI,NOTES}.md this session; earlier fix commits: check_imports.py, ehprobe.sh,
  load_proof.sh, fetch_vendor.sh, clang-cl-i686*.cmake, cmake/LogicIncludeLint.cmake, tests/host/*,
  src/module/ehprobe/, harness/ci.d/{10,20,50}*.sh
TESTS: acceptance set (host+asan ctest 5/5, win32 A/B, PE32 i386, hello_a exports, check_imports both tracks,
  pytest 16/16, both --verify, negative test) — PASS — 20261018T064024Z-toolchain-acceptance-r1/
  CI 10/20/50 via real ci.sh — PASS — 20261018T063859Z-ci/
  load proof CreateID(li02)=2745692751 — PASS — 20261018T064132Z-toolchain-loadproof/
  EH probe A+B, builtin+native — PASS (24/3/0) — above + 20261018T064149Z-ehprobe/
  check_public --tree (142 files) and --commits main..HEAD (8 commits) — PASS — acceptance dir cp_*.txt
DECISIONS: -mstackrealign in the common flags; SEH/catch(...) coding rules (ABI.md §6); stage 50 checks only
  build/*/flmod_binaries.txt; include allowlist for src/logic; msvc-redist-x86 14.51.36231 pinned
  (test input only, never committed); --verify is offline and read-only. No sudo used.
ENGINE FACTS LEARNED (all VERIFIED; evidence in the run dirs above, analysis in toolchain/NOTES.md
  "Bug 2" and "Question 3"):
  (a) __try at /O2 returns with EBX/ESI/EDI clobbered after a handled fault; a clobber barrier fixes it, either runtime.
  (b) catch(...) sees an access violation only under /EHa and only inside an opaque call; never in its own body.
  (c) an exception leaving a catch block into a try in the same function kills the process under Wine's builtin
      vcruntime140; -mstackrealign or native vcruntime140 fixes it.
  Wine drops console stdout redirected to a regular file (pipes work).
  The play prefix has DllOverrides msvcp140*/vcruntime140/ucrtbase/concrt140 = native,builtin, so a native CRT
      DLL next to the exe switches the whole process with no env var (+loaddll, E1/E2).
  FLUF.dll is clang-cl/lld-link code built without -mstackrealign.
OPEN QUESTIONS / BLOCKERS: none blocking. Native MSVC runtime for FLUF (Track A), recommendation below.
KNOWN ISSUES: (a) and (b) stay coding rules (no flag fixes them). Prebuilt code we don't compile (FLUF and its
  dev libs, HDE DLLs) can still hit (c) under the builtin runtime.
```

**Recommendation for G0a / W1-PLATFORM: keep Wine's built-in runtime by default on both tracks.**
- **Coverage.** FLUF's 33 DLLs import 159 msvcp140, 2 atomic_wait, 27 vcruntime140 and 221 UCRT symbols. Both Wine's builtins and the native 14.51 DLLs export all of them, and the native DLLs' own imports all resolve in this prefix (VERIFIED, static).
- **FLUF's own exposure to (c) is small.** Its source has 31 catch blocks and none of them throws (VERIFIED by scan). Library code inlined into FLUF could still do it (UNVERIFIED).
- **Our code is already safe** through `-mstackrealign`.
- **Native is process-wide.** It would also switch 23 HDE files (FLHook and plugins, fmt, spdlog, pcre2), and no game run has tested that.
- **Fallback for P0-TRACK-A.** If an in-game run shows the (c) signature in FLUF or HDE frames, copy all nine DLLs from `$FLMOD_VENDOR/msvc-redist/x86` into the lane's EXE dir at deploy time and re-run the probe with `--crt native`. The prefix registry switches the runtime on its own.
- **For the harness deploy step:** it should assert that no stray CRT DLL sits in the EXE dir, since one silently switches the runtime.

No `prefix-dev-toolchain*` clones are left and no Wine processes of mine are running. The vendor tree and the xwin splat are unchanged this session.
