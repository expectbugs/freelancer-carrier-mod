```
REVIEW: P0-TOOLCHAIN ROUND 1   VERDICT: CHANGES_REQUIRED
Evidence: R = /home/user/freelancer/carrier-mod/local/testruns/20261018T045813Z-review-P0-TOOLCHAIN-r1/

COVERAGE:
REQ-P0-TOOLCHAIN-1: covered. setup_xwin.sh + PINS.md. xwin 0.10.0, flags checked against `xwin --help`. --verify OK. Offline re-splat into a temp root is byte-identical (diff -rq rc 0, R/19-*).
REQ-P0-TOOLCHAIN-2: covered. Every TU's compile_commands entry has -MD -Z7 -gdwarf /EHa /utf-8 /permissive- -D_ITERATOR_DEBUG_LEVEL=0 -std=c++23. Link line has /SAFESEH:NO /INCREMENTAL:NO /OPT:REF /OPT:ICF /DEBUG:DWARF. Exception handling (EH) behaviour: see MAJOR.
REQ-P0-TOOLCHAIN-3: covered. host.cmake, host-asan, logic_header_check + LogicIncludeLint. Negative test reproduced.
REQ-P0-TOOLCHAIN-4: covered. 4 presets, FLMOD_TRACK, logic/hello_a/hello_b/loadtest/host_tests, build/<preset>/out.
REQ-P0-TOOLCHAIN-5: covered. 10 sha256 pins, FLMOD_VENDOR from env or cache. Re-run is idempotent and offline re-extract is byte-identical. FLUF URLs missing (MINOR).
REQ-P0-TOOLCHAIN-6: covered. All must-match defines, include dirs and libs are on hello_a's compile and link lines, and FLUF is never defined. Exports GetMajorVersion/GetMinorVersion/ModuleFactory. FLUF imports 189/189. Runtime load is P0-TRACK-A's job, per spec.
REQ-P0-TOOLCHAIN-7: covered. flmod_dacom_dll (FLSDK libs incl. RemoteClient, static MinHook, static ImGui, d3d9/dxguid/user32). ABI.md states the st6 rule with the st6.h path.
REQ-P0-TOOLCHAIN-8: covered. Allowlist, msvcp140/vcruntime140/atomic_wait symbol checks and summary table work. The extra checks have holes (MINOR 1-2).
REQ-P0-TOOLCHAIN-9: covered.
REQ-P0-TOOLCHAIN-10: covered (reproduced).
REQ-P0-TOOLCHAIN-11: covered. All 5 golden CreateIDs.
REQ-P0-TOOLCHAIN-12: covered. Some drift from the P0-REPO protocol (MINOR).

REPRODUCED:
- host configure/build/ctest — reproduced — 5/5 tests, 4 cases/12 asserts (R/01-host.log). ×20 ctest and ×20 doctest (host + asan): no flakes (R/22).
- host-asan — reproduced — 5/5 (R/02).
- win32-trackB build — reproduced — hello_b.dll and loadtest.exe are IMAGE_FILE_MACHINE_I386, magic 0x10B (PE32) (R/03).
- win32-trackA build — reproduced — exports ModuleFactory, GetMajorVersion, GetMinorVersion (R/04).
- check_imports hello_b + loadtest, --prefix play (read-only) — reproduced — PASS (R/08).
- check_imports hello_a --allow-fluf — reproduced — PASS: FLUF 189/189, MSVCP140 15/15, VCRUNTIME140 10/10 (R/09).
- runtime load proof — reproduced — "hello_b CreateID(li02)=2745692751", exit 0. Run with my own clone prefix-dev-review-toolchain by the spec's manual steps (load_proof.sh hard-codes its clone path). Its wineserver was stopped and the clone deleted (R/06).
- error paths — reproduced — loadtest exits 2/3/4 for usage / LoadLibrary / GetProcAddress failures.
- wine stdout-to-file engine fact — reproduced — 0 bytes when redirected to a file, full output through a pipe (R/07).
- negative windows.h test — reproduced — in an exported copy, an `#ifdef _WIN32 #include <windows.h>` in src/logic fails both the host and trackB builds with "Forbidden includes"; both pass again after removal.
- pytest toolchain/tests — reproduced — 13/13, ×20 no flakes.
- CI drop-ins, full mode — reproduced — PASS. SKIP paths exit 77 (R/ci/).
- fetch_vendor --verify and setup_xwin --verify — reproduced — PASS. Vendor tree metadata identical before and after. Re-run on a reflink copy reports all "up to date". Offline rebuild from the cache alone is byte-identical (R/17-18).
- check_public — reproduced — --tree: 134 files clean. --commits main..wp/P0-TOOLCHAIN: 5 commits, 136 files clean (R/20-21).
- Decision 1 Wine compatibility — supported — a broad 14.51 STL probe imports 149 msvcp140, 13 msvcp140_atomic_wait, 1 msvcp140_1 and 15 vcruntime140 symbols; the Wine builtins export all of them (R/11). 28/30 features ran under Wine; the 2 failures are MAJOR (c) (R/12).
- primary in-game scenario — none for this package. harness/lane.sh is on neither main nor the branch.

FINDINGS (ordered by severity):

[MAJOR] toolchain/clang-cl-i686.cmake:53,57; toolchain/clang-cl-i686-overrides.cmake:2-3; toolchain/ABI.md:8
Problem: exception handling in DLLs built by this toolchain is broken under wine-proton 11, and the stated reason for /EHa ("required to catch SEH") is false. The probes were built with the exact toolchain flags and run through loadtest in a prefix-dev clone (R/13, 16, 23, 24; sources in R/ehprobe*.cpp):
(a) At /O2, a function using __try/__except returns to its caller with EBX/ESI/EDI clobbered. The caller's values read back as b=0, c=1637915484 (CORRUPTED) in 3/3 runs. Disassembly shows the __try function saves no callee-saved registers, while its C++ try/catch twin does and stays INTACT. Any SEH crash guard (FLUF-style) would silently corrupt state.
(b) catch(...) does not catch an access violation, despite /EHa passing -fasync-exceptions. The process dies with 0xC0000005 (exit code 5).
(c) A rethrow (or rethrow_exception) inside a catch block, caught by an enclosing try in the same function, kills the process. This happens at /O2 and /Od, with /EHa and /EHsc. An ordinary cross-function `catch(...){ throw; }` helper hits it as soon as /O2 inlines it (r_cross_inlined → exit 5). The noinline version works.
What works: plain throw/catch, destructor unwinding, std::stoi exceptions, throwing from a catch block to a caller, and exception_ptr rethrow outside a catch block.
Cause: (a) is clang codegen, VERIFIED by disassembly. (b) and (c) are UNVERIFIED (clang x86 WinEH vs Wine's nested-frame handling).
Required change:
- Fix the /EHa comments.
- Document (a)-(c) in ABI.md, with the verified workaround for (a): `__asm__ volatile("" ::: "ebx","esi","edi");` at the top of every __try function (INTACT, R/23).
- Add an EH regression probe (extra hello_b exports, or a probe DLL run by load_proof.sh) so CI keeps checking these facts.
- Report them as ENGINE FACTS for TRACK-A and TRACK-B.

[MINOR] toolchain/check_imports.py:99-121; toolchain/tests/test_check_imports.py:39-50
Problem: delay-import symbols are never checked. Real llvm-readobj 22 nests each delay-imported symbol in its own `Import {}` block inside `DelayImport {}`; the parser opens a nameless module for each and drops it. A DLL that delay-loads a symbol missing from Common.dll reports "common.dll (delay) 0/0 OK"; the direct-import version FAILs (R/10). The test fixture uses an invented flat format.
Required change: parse the nested blocks and use real readobj output as the fixture.

[MINOR] toolchain/check_imports.py:243-261
Problem: a CRT-pattern DLL (msvcp140*/vcruntime140*) that is absent from syswow64 and outside the required set (e.g. msvcp140d.dll, vcruntime140_1.dll) is reported "OK allowed", although the load would fail.
Required change: FAIL when any imported CRT DLL is missing from syswow64.

[MINOR] tests/host/LogicHeaderCheck.cmake:46,51
Problem: the WILL_FAIL negative probes accept any failure, including a broken toolchain or missing target.
Required change: add PASS/FAIL_REGULAR_EXPRESSION matching "'windows.h' file not found" / "Forbidden includes".

[MINOR] cmake/LogicIncludeLint.cmake:112-115
Problem: the denylist misses many Windows-only headers (synchapi.h, processthreadsapi.h, libloaderapi.h, shellapi.h, winternl.h, tchar.h, io.h, process.h, xinput.h, dinput.h, …). An `#ifdef _WIN32` include of one of them passes both the lint and the host header check.
Required change: use an allowlist, or extend the list.

[MINOR] CMakeLists.txt:68,113; toolchain/README.md ("Adding a target")
Problem:
- The /tests/ filters match absolute paths, so a checkout under any .../tests/... path silently drops every logic source.
- src/**/tests/<subdir>/*.cpp is compiled nowhere (VERIFIED).
- src/game/** is not discovered by the root CMake (VERIFIED), and the README doesn't say the module target must glob it.
Glob discovery itself works without editing the root (VERIFIED): src/logic/<area>/*.cpp goes into logic, src/logic/<area>/tests/*.cpp and tests/host/<area>/*.cpp go into host_tests, and spikes/<id>/ produces its DLL.
Required change: filter relative paths, glob or document nested tests dirs, and document the src/game rule for ARCH-0.

[MINOR] toolchain/fetch_vendor.sh:133-144
Problem: --verify promises to change nothing, but it calls fetch_cached, which downloads into $FLMOD_VENDOR/.cache when a cache file is missing. It also checks only the stamps, not the extracted trees.
Required change: make verify offline and read-only.

[MINOR] toolchain/PINS.md:77-78
Problem: the FLUF nightly and stable pins give only a local refs path.
Required change: add the upstream release-asset URLs.

[MINOR] toolchain/load_proof.sh:24
Problem: the clone path is hard-coded, so the script can't run under another prefix-dev* name, and concurrent runs collide.
Required change: add a --clone argument limited to prefix-dev*.

[MINOR] harness/ci.d/10-build.sh:10-11,42 (same pattern in 20 and 50)
Problem: drift from P0-REPO's ci.d README protocol.
- Artifacts are written to $CI_RUNDIR/NN-*.log, not $CI_RUNDIR/<NN>-<name>/.
- The repo root comes from BASH_SOURCE, not CI_REPO_ROOT.
- Run standalone, the default run dir is a /tmp mktemp dir, not under $FLMOD_TESTRUNS (CONVENTIONS §5).
- Stage 50 also checks stale binaries left in out/.
Required change: reconcile at merge.

[MINOR] toolchain/NOTES.md:75; toolchain/PINS.md:41
Problem: the "VERIFIED" claim that the final link needs at least the 14.5x STL is overstated. /FAILIFMISMATCH fails only when two objects carry conflicting values, and no 14.44 link was tried. The 14.51 choice itself is sound.
Required change: mark the claim UNVERIFIED.

[MINOR] toolchain/PINS.md:100-101; toolchain/ABI.md
Problem: Track B compiles FLSDK's sources into the DLL (flsdk_static) and Track A statically links FreelancerSDK.lib. Binaries therefore embed unlicensed FLSDK code, which is more than CONVENTIONS §11's "linked against import libs".
Required change: state this for W5-SHIP.
No license blocks AGPL source distribution: the repo and FLUF are AGPL-3.0, nlohmann/doctest/imgui/magic_enum/reflect-cpp are MIT, and MinHook is BSD-2 (its notice is needed in any binary release).

AUDIT NOTES:
- Engine safety: only the hello DLLs touch the engine.
  - CreateID is a pure function.
  - hello_a logs from OnApplicationStart, which FLUF runs on the main thread.
  - hello_b's file I/O runs only under loadtest.
  - Only a const char* crosses Common.dll, and there are no spawns.
- Contracts: no frozen contracts exist yet, and there are no edits outside the package's ownership. tests/host/core/ will become W1-CORE's area; note it in OWNERSHIP.
- Data hygiene: no game files are committed, and no nicknames were added (so no hash scan was needed). The play prefix is UNCHANGED (play_prefix_manifest verify after the review), and the review clone was deleted.
- Design fidelity and game failure paths (sidecar absent, JSON, pre-mod saves, death, F1, alt-tab): not applicable to a toolchain.
- Toolchain failure paths: a missing vendor tree, xwin splat or FLMOD_TRACK gives a clear FATAL_ERROR, and CI reports SKIP with exit 77 (verified).
```
