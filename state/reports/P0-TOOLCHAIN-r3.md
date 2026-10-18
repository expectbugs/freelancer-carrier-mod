I've run the round-3 review of wp/P0-TOOLCHAIN @ 370c47f. The verdict is **PASS**: all seven r2 findings are fixed and every acceptance check reproduced from an empty `build/`. The regression hunt turned up three new MINOR gaps in the new pieces, listed under NEW FINDINGS at the end.

```
REVIEW: P0-TOOLCHAIN ROUND 3   VERDICT: PASS
Evidence: R = /home/user/freelancer/carrier-mod/local/testruns/20261018T073223Z-review-P0-TOOLCHAIN-r3/
Checkout: a detached worktree of 370c47f with an empty build/ (removed afterwards; the main checkout is untouched).

R2 FINDINGS:
F1 [MAJOR] src/logic lint rejected doctest under tests/: fixed — VERIFIED.
  - My own reproduction now passes: a doctest .cpp, a doctest-including helper .hpp and a nested tests/sub/ file under src/logic/core/tests/.
    - Incremental (files added after a build, no reconfigure): build rc 0, 6 doctest cases run, ctest 5/5 (R/10-*).
    - Fresh: the same (R/11).
    - win32-trackB with the files present: builds (R/12).
  - The author's ctest logic_tests_dir_doctest passes on host and host-asan (incremental and fresh phases).
  - Mutation: with the tests/ exclusion removed from cmake/LogicLintFiles.cmake, that ctest FAILs with "Forbidden includes" (R/14). The test bites.
F2 [MINOR] no CI flag check: fixed — VERIFIED.
  - A spikes/ DLL with /clang:-mno-stackrealign /EHsc makes stage 10 FAIL with "win32-trackA:flags win32-trackB:flags". The log names both flags. Stage 10 PASSes again after removal (R/31*).
  - The real build is clean: 36 TUs (A) and 37 TUs (B) OK.
  - Edge cases remain: N3 below.
F3 [MINOR] probe lacked hook patterns: fixed — VERIFIED. 13 hook cases (the 9 hostable ones plus 4 hook_template_*) PASS on both tracks under both runtimes.
F4 [MINOR] stage 50 checked a stale track: fixed — VERIFIED (R/32-34).
  - FLMOD_TRACK=B with a bad stale trackA binary: PASS (ignored).
  - Control with FLMOD_TRACK unset: FAIL.
  - FLMOD_TRACK=C: stages 10 and 50 both FAIL.
  - FLMOD_TRACK=A with no trackA build: SKIP, not PASS on B.
F5 [MINOR] ABI §6.2 vs §6.3: fixed — VERIFIED. The §6.7 hook template is exercised by the 4 hook_template_* cases, which PASS with registers intact.
F6 [MINOR] ehprobe safety: fixed — VERIFIED.
  - 24 refusals return the documented exit code and create neither a run dir nor a clone (R/40-refusals.txt). They cover:
    - --prefix pointing at the play prefix, a baseline, a lane, a /../ path or a nested path;
    - --clone names that are a baseline, a lane or a path;
    - bad --from values, including a path-traversal one;
    - missing build outputs, and --crt native with no redist.
  - --crt both with the redist missing: the builtin cases run, then "result=SKIP", exit 77 (R/53).
F7 [MINOR] src/game rule: fixed — README:85-108 gives the module glob excluding (^|/)(tests|scenarios)/ and the host-tests rule.
Orchestrator addition (--from): works — VERIFIED.
  - The default clone source is prefix-dev-base-B.
  - A source in use is refused with exit 3 and nothing created: tested with WINEPREFIX set, WINEPREFIX with a trailing "/", and a process whose cwd is inside the source.
  - --from play is refused while a dummy process holds WINEPREFIX=play.
  - A full --from play run passed. The play prefix's metadata (20289 entries: size, mtime, ctime, mode) and baseline B's were unchanged afterwards (R/54, play_*/baseB_*.tsv).
  - "Idle" for play = tools/play_prefix_busy.sh: no process with cwd inside the prefix or WINEPREFIX equal to it. play.sh exports WINEPREFIX, so the game and its wineserver are both seen.

COVERAGE:
REQ-P0-TOOLCHAIN-1: covered. setup_xwin --verify rc 0 with a read-only / and no network.
REQ-P0-TOOLCHAIN-2: covered. Every TU's flags are checked statically in CI now.
REQ-P0-TOOLCHAIN-3: covered (minor loophole N1).
REQ-P0-TOOLCHAIN-4: covered.
REQ-P0-TOOLCHAIN-5: covered. fetch_vendor --verify 11/11 OK with a read-only / and no network; vendor and xwin metadata identical before and after the whole review.
REQ-P0-TOOLCHAIN-6: covered. hello_a exports GetMajorVersion, GetMinorVersion and ModuleFactory; FLUF 189/189.
REQ-P0-TOOLCHAIN-7: covered.
REQ-P0-TOOLCHAIN-8: covered.
REQ-P0-TOOLCHAIN-9: covered.
REQ-P0-TOOLCHAIN-10: covered.
REQ-P0-TOOLCHAIN-11: covered.
REQ-P0-TOOLCHAIN-12: covered.

REPRODUCED:
- host and host-asan, empty build/ — reproduced — ctest 6/6 each, including logic_tests_dir_doctest; doctest 4 cases / 12 asserts.
- win32-trackA and win32-trackB — reproduced — 6 binaries, all IMAGE_FILE_MACHINE_I386 with Magic 0x10B (R/60).
- check_imports — reproduced — B and A PASS: FLUF 189/189, MSVCP140 15/15, VCRUNTIME140 10/10.
- check_flags on the real build — reproduced — OK (36 TUs in A, 37 in B).
- pytest toolchain/tests — reproduced — 27/27.
- CI via wp/P0-REPO ci.sh @32ab66a — reproduced.
  - --full from an empty build/: build PASS, host-tests PASS (6/6 + 6/6), import-check PASS (A:3, B:3) (R/30).
  - Every missing-prerequisite case is SKIP, never FAIL (R/35, 36).
- load proof — reproduced — via load_proof.sh --clone prefix-dev-review-toolchain (default --from base-B): "LOAD: PASS (CreateID(li02)=2745692751)", then the clone was deleted.
  Run dir: $FLMOD_TESTRUNS/20261018T073836Z-toolchain-loadproof/ (the script's default location).
- EH probe, 2 tracks × 2 CRTs — reproduced — 37 PASS / 3 KNOWN-BROKEN / 0 FAIL / 0 SKIP in each of the 4 runs (R/51, R/52).
  - Track B ran inside load_proof.sh; track A via ehprobe.sh --clone.
  - The 3 KNOWN-BROKEN cases: a_seh_regs_raw, b_catchall_av_inline, b_catchall_av_call.
- check_public — reproduced — --tree: 148 files clean. --commits=main..wp/P0-TOOLCHAIN: 10 commits, 185 files clean. No .dll/.exe/.vsix/.msi/.lib anywhere in the branch history.
- Wine hygiene — GPU Recovery Action None before and after. The prefix-dev-review-toolchain clone is gone and no processes of it remain.

NEW FINDINGS (ordered by severity; none BLOCKER/MAJOR):
[MINOR] N1. cmake/LogicLintFiles.cmake:39 + cmake/LogicIncludeLint.cmake (quoted-include check)
  Problem: tests/ dirs are no longer linted, but non-test src/logic code may still `#include "tests/x.hpp"` (the quote resolves under src/logic, so it is allowed). Through that route <windows.h> behind #ifdef _WIN32 compiles into the win32 `logic` lib.
  - The lint, the host header check and the trackB build all pass (R/13-loophole-*.log, rc 0).
  - Control: the same include written directly in leak.hpp is rejected with "Forbidden includes".
  Required change: reject quoted includes from non-tests files that resolve into a tests/ dir.
[MINOR] N2. toolchain/prefix_clone.sh:17-27 (flmod_prefix_in_use)
  Problem: the check compares the raw WINEPREFIX string. These spellings all report IDLE even though the wine guard (realpath -m) and Wine treat them as the same prefix (R/40):
  - /home/user/freelancer//prefix-dev-base-B
  - /home/user/freelancer/./prefix-dev-base-B
  - /home/user/freelancer/prefix-dev-base-B/drive_c/..
  Required change: realpath -m both sides before comparing.
  Same weakness in tools/play_prefix_busy.sh (orchestrator-owned).
[MINOR] N3. toolchain/check_flags.py:73-75,90-98
  Problem 1: compile_commands entries whose command doesn't start with clang-cl are skipped silently whenever other TUs exist. A good TU plus a ccache-prefixed TU with no flags at all passes (R/20). A per-target CXX_COMPILER_LAUNCHER would disable the check for that target.
  Problem 2: /EHa neutralised by /clang:-fno-async-exceptions (or -Xclang) after it passes.
  Required change: parse past known launchers and FAIL on any other non-clang-cl entry; flag -fno-async-exceptions.

NOTES (orchestrator / P0-HARNESS, not P0-TOOLCHAIN findings):
- The in-use test only sees Wine users. harness/baseline.sh edits baselines in place without WINEPREFIX and with its cwd elsewhere: tweak apply, create --recreate (rm -rf then clone), fluf-init. lane.sh also clones baselines with no lock, and no baseline lock exists. A clone taken during a baseline refresh could be inconsistent; the source is never written. Suggest a shared baseline flock. At minimum, prefix_clone could require $src/BASELINE.json, as lane.sh does.
- The author's proposal stands and needs your decision: run `ehprobe.sh --crt both` in the P0-TRACK-A/B and W1-PLATFORM acceptance, and on any toolchain/ or cmake/ flag change.
- The DllOverrides list in ABI.md §6.6 is accurate: it also covers api-ms-win-crt-*, msvcr1?0, vcomp*, vccorlib140, and d3d8/9/10core/11/dxgi.
```
