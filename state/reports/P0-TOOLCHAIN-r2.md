```
REVIEW: P0-TOOLCHAIN ROUND 2   VERDICT: CHANGES_REQUIRED
Evidence: R = /home/user/freelancer/carrier-mod/local/testruns/20261018T065307Z-review-P0-TOOLCHAIN-r2/
Branch reviewed: wp/P0-TOOLCHAIN @ 0bceb22 (r1 reviewed 9d320f3). Fresh build/ in my worktree.

R1 FINDINGS:
[MAJOR] EH (a)-(c): fixed — VERIFIED.
  - The /EHa comments are corrected (clang-cl-i686.cmake:42-47,62-66; overrides:1-4).
  - ABI.md §6.1-6.6 documents (a), (b) and (c), with a copy-paste flmod_seh_guard.
  - The probe exists and is run by load_proof.sh, as r1 allowed.
  - /clang:-mstackrealign is on every C/C++ TU of both presets, vendor libs included (36 TUs in A, 37 in B; ccflags check).
  - The engine facts are in the report.
[MINOR] delay imports not checked: fixed — VERIFIED. r1's real delaycommon.dll now gives "common.dll (delay) 1 FAIL / MISSING … NotInHde" (R/10). The fixture is real readobj output.
[MINOR] CRT DLL missing from syswow64 reported OK: fixed — VERIFIED. required=True for all msvcp140*/vcruntime140*; pytest test_missing_any_crt_dll_fails passes.
[MINOR] WILL_FAIL probes accept any failure: fixed — VERIFIED. ExpectFailure.cmake fails the test both for a wrong-reason failure (missing target) and for a command that succeeds.
[MINOR] header denylist too small: fixed — VERIFIED. An #ifdef _WIN32 <processthreadsapi.h> fails the host and trackB builds and passes after removal (R/11c, 11d). But the allowlist causes a regression: MAJOR F1.
[MINOR] /tests/ absolute filters, nested tests dirs, src/game doc: fixed — VERIFIED.
  - A checkout under …/tests/checkout builds and passes ctest (R/11a).
  - src/logic/core/tests/sub/*.cpp is compiled into host_tests (6 cases, R/11b).
  - The src/game rule is documented, with an inconsistency: MINOR F7.
[MINOR] fetch_vendor --verify downloads, checks stamps only: fixed — VERIFIED. 11/11 OK inside bwrap with a read-only / and no network. The metadata of vendor (25343 entries) and xwin (8562) is identical before and after.
[MINOR] FLUF upstream URLs: fixed — VERIFIED. HTTP 200, content-length 139359852 / 55651208 equal to the local files.
[MINOR] load_proof clone hard-coded: fixed — VERIFIED. --clone accepts only prefix-dev* names; "lane-1" and a path are rejected (rc 2).
[MINOR] ci.d protocol drift: fixed — VERIFIED. CI_REPO_ROOT, $CI_RUNDIR/NN-name/ and the $FLMOD_TESTRUNS default are used; the real ci.sh gives PASS (below).
[MINOR] 14.5x claim overstated: fixed — marked UNVERIFIED in NOTES.md:75-76 and PINS.md:41-43.
[MINOR] FLSDK code embedded in binaries: fixed — ABI.md §7 plus the PINS.md note.

COVERAGE:
REQ-P0-TOOLCHAIN-1: covered (setup_xwin --verify is offline and read-only, VERIFIED).
REQ-P0-TOOLCHAIN-2: covered. Per-TU flags and link flags VERIFIED (compile_commands, build.ninja).
REQ-P0-TOOLCHAIN-3: partial. The engine-free enforcement works, but it now also rejects doctest host-test files under src/logic/**/tests/ (MAJOR F1).
REQ-P0-TOOLCHAIN-4: covered.
REQ-P0-TOOLCHAIN-5: covered.
REQ-P0-TOOLCHAIN-6: covered. hello_a exports GetMajorVersion, GetMinorVersion and ModuleFactory; FLUF 189/189.
REQ-P0-TOOLCHAIN-7: covered.
REQ-P0-TOOLCHAIN-8: covered. Delay imports and missing CRT DLLs are now checked.
REQ-P0-TOOLCHAIN-9: covered.
REQ-P0-TOOLCHAIN-10: covered (reproduced).
REQ-P0-TOOLCHAIN-11: covered (5 golden IDs; 4 cases, 12 asserts).
REQ-P0-TOOLCHAIN-12: covered (real ci.sh). The stale-track gap is MINOR F4.

REPRODUCED:
- host and host-asan from an empty build/ — reproduced — ctest 5/5 each (R/01, R/02).
- win32-trackA and win32-trackB — reproduced — all 6 binaries are IMAGE_FILE_MACHINE_I386 with Magic 0x10B (R/05).
- check_imports on both tracks against the play prefix (read-only) — reproduced — PASS: FLUF 189/189, MSVCP140 15/15, VCRUNTIME140 10/10. hello_a without --allow-fluf FAILs (R/07, R/08, R/08b).
- pytest toolchain/tests — reproduced — 16/16 (R/09).
- fetch_vendor --verify and setup_xwin --verify — reproduced — rc 0 in the no-network, read-only sandbox; vendor and xwin metadata unchanged across the whole review (R/12*, vendor_/xwin_ *.tsv).
- load proof — reproduced — "hello_b CreateID(li02)=2745692751" on the console and in hello_b.log, exit 0. Run with the spec's manual steps on prefix-dev-review-toolchain, reflinked from prefix-dev-base-B, because load_proof.sh can only clone the play prefix (R/21).
- EH probe, track A and track B × builtin and native — reproduced — 24 PASS / 3 KNOWN-BROKEN / 0 FAIL each (R/22).
  - KNOWN-BROKEN: a_seh_regs_raw (CORRUPTED, c=1625043772) and b_catchall_av_inline/_call (rc 5).
  - +loaddll confirms the builtin run loads system32 builtins and the native run loads the app-local native DLLs (R/23).
- negative control — reproduced — ehprobe.cpp rebuilt with /clang:-mno-stackrealign (realigning prologues drop from 219 to 20) (R/24).
  - Builtin CRT: 4 FAIL, all rc 5 (c_rethrow_same_frame, c_throw_new_from_catch_same_frame, c_rethrow_cross_inlined, lib_rethrow_if_nested_in_catch).
  - Native CRT: 0 FAIL. The same source built with the flag: 0 FAIL.
- KNOWN-BROKEN unfixable by flags — reproduced with the shipped flags under both runtimes. The author's matrix (/EHa, /EHsc, /EHs, /Od, /Ob0, exe, native, -mstackrealign) covers the plausible switches. UNVERIFIED that no -mllvm option exists. §6.1 and §6.2 are rules an agent can follow: I compiled the §6.1 guard verbatim.
- extra EH patterns (my probe, R/probes/rvprobe.cpp) — 9/9 PASS under both runtimes (R/25-rvprobe.tsv; engine-fault case in R/26-*). The engine-fault entries in R/25-rvprobe.tsv are not valid: that first version called CreateID(nullptr), which did not raise (not investigated why); R/26 re-ran it with PhySys::DeactivatePhysics((CObject*)0x10).
  - Fault inside Common.dll under the guard: caught as 0xC0000005, registers INTACT.
  - Nested guards; __finally runs during unwind; C++ EH on a worker thread.
  - C++ exception and AV crossing msvcrt.dll qsort frames.
  - A catch inside a callback called from foreign code.
  - A VC6-style msvcrt!_CxxThrowException caught by catch(int) and by catch(...).
- CI stages 10/20/50 through wp/P0-REPO ci.sh @32ab66a — reproduced (R/40-47, ci-runs/).
  - --full from an empty build/: PASS / PASS / PASS.
  - Missing prerequisites give SKIP (exit 77): no CMakePresets.json, no vendor tree, no prefix, no build output. Without XWIN, stage 10 builds host only and PASSes with a note.
  - A build FAIL leaves import-check NOT RUN.
  - A bad DLL left in out/ is ignored; the same file checked directly FAILs.
- CRT recommendation evidence — reproduced, VERIFIED (R/27).
  - The 33 FLUF DLLs import 159 / 2 / 27 / 221 distinct msvcp140 / atomic_wait / vcruntime140 / api-ms-win-crt symbols. None is missing from the builtins or from the native 14.51 redist.
  - The redist's own imports resolve, except vccorlib140's WinRT imports (that DLL is unused).
  - DllOverrides native,builtin is present in the play prefix and in both dev baselines.
  - The syswow64 CRT DLLs carry the "Wine builtin DLL" marker. No CRT DLL is in the game tree or the FLUF package.
- check_public — reproduced — --tree: 142 files clean. --commits=main..wp/P0-TOOLCHAIN: 8 commits, 167 files clean. No .dll/.exe/.vsix/.msi/.lib in the tree or the branch history (R/30, R/31).
- GPU Recovery Action None before and after every Wine run. Only the clone's wineserver was killed, and the clone is deleted. No primary in-game scenario applies to this package.

FINDINGS (ordered by severity):
[MAJOR] F1. cmake/LogicIncludeLint.cmake:36-38; CMakeLists.txt:81,88; tests/host/LogicHeaderCheck.cmake:16 (regression from the allowlist fix)
  Problem: the lint scans all of src/logic recursively, including tests/, and does not allow <doctest/doctest.h>.
  - The plan puts host tests in src/logic/<area>/tests/: README:81 and :151, tests/host/main.cpp, BUILD_PLAN §6:237, W1-CORE.md:132, W1-CARRIER-DESIGN.md:132, W2-CARRIER-LOGIC/ENCOUNTER/REFLEX/YARD, W3-AMBUSH.
  - A doctest file there FAILS a fresh build: "Forbidden includes … core/tests/test_in_logic.cpp: #include <doctest/doctest.h>" (R/11e).
  - Incrementally the build passes, because the stamp's DEPENDS excludes tests/, but ctest logic_include_lint_passes then fails (R/11b). Fresh/CI and incremental builds disagree.
  - logic_header_check also compiles any tests/ helper header with only src/ and nlohmann on the include path.
  - Those packages don't own cmake/, so each would stall on it.
  Required change:
  - Exclude (^|/)tests/ from the lint and from FLMOD_LOGIC_HEADERS, or allow <doctest/…> under tests/.
  - Make the stamp depend on the same file set it lints.
  - Add a ctest fixture: a doctest file under a src/logic-style tests/ dir that must build and run.
[MINOR] F2. harness/ci.d/10-build.sh, 50-import-check.sh
  Problem: no CI stage runs ehprobe or checks that /clang:-mstackrealign and /EHa are on every win32 TU. Since cmake/ passes to ARCH-0, dropping the flag would fail nothing in CI.
  Required change: add a static compile_commands.json assertion to stage 10 or 50 (no Wine needed), and name the gate or stage that runs ehprobe.sh.
[MINOR] F3. src/module/ehprobe/ehprobe.cpp, toolchain/ehprobe_cases.tsv
  Problem: the probe lacks the hook-package patterns listed under REPRODUCED (extra EH patterns). They all work today, so this is missing regression coverage, not a defect.
  Not coverable without the game: exceptions crossing FLUF.dll frames, a VEH or SetUnhandledExceptionFilter crash handler, throws during DllMain or static initialisation.
  Required change: add the hostable cases (source in R/probes/rvprobe.cpp).
[MINOR] F4. harness/ci.d/50-import-check.sh:29
  Problem: stage 50 checks every build/win32-track*/flmod_binaries.txt, whatever stage 10 built. With FLMOD_TRACK=B it FAILs on a stale, unrebuilt trackA dir (R/42), and it could equally pass stale binaries.
  Required change: select tracks the same way stage 10 does.
[MINOR] F5. toolchain/ABI.md §6.2 vs §6.3
  Problem: §6.3 requires a top-level catch(...) in every hook. §6.2 says that under /EHa catch(...) can swallow an AV raised in an opaque call. No hook template resolves the two.
  Required change: give the hook template, e.g. the body runs through flmod_seh_guard inside the try, and any catch(...) hit is logged as possibly SEH.
[MINOR] F6. toolchain/ehprobe.sh:8,72,96-99
  Problem 1: --prefix accepts prefix-lane* without holding the lane lock, then runs deliberately crashing processes on a wineserver a game may share (guardrail 2).
  Problem 2: --crt native with no redist prints "skipped" and ends "result=PASS", exit 0, even when zero cases ran.
  Problem 3 (nit): refused invocations of ehprobe.sh and load_proof.sh leave empty run dirs, because mkdir runs before validation.
  Required change: require the lane lock or limit --prefix to prefix-dev*; exit 77 when a requested runtime can't run; validate before creating the run dir.
[MINOR] F7. toolchain/README.md:81-82
  Problem: "src/**/tests/** → host_tests" contradicts "src/game/** → nothing". src/game/<x>/tests/*.cpp is in fact built into host_tests, which W1-PLATFORM.md:132 wants. The suggested ARCH-0 module glob of src/game/*.cpp would also pull those doctest files into the DLL.
  Required change: document the src/game tests rule and require the module glob to exclude (^|/)(tests|scenarios)/.

NOTES for G0a / P0-TRACK-A (not findings; the recommendation to keep the builtin CRT holds up):
- The registry also sets ucrtbase, vcruntime140_1 and msvcp100/110/120 to native,builtin. The deploy step's stray-DLL assertion should therefore cover ucrtbase*, concrt140* and msvcp1?0*, not just msvcp140*/vcruntime140*.
- FLUF's low exposure to (c) rests on a source scan, which does not see library code inlined into FLUF.dll. A binary scan of FLUF's catch funclets for _CxxThrowException or rethrow calls would settle it.
- FLUF's own imports include d3dcompiler_47, opengl32, imm32, bcrypt, crypt32 and others. check_imports does not cover them (it checks only our binaries); confirm they resolve in the lane prefix.
```
