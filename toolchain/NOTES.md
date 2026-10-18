# P0-TOOLCHAIN working notes

Running log of decisions, surprises and bug hypotheses (ten-explanations rule, CLAUDE.md).

## Bug 1: load proof printed nothing on the console (2026-10-17)

**Observations** (run dir `$FLMOD_TESTRUNS/20261018T043727Z-toolchain-loadproof/`):

- `wine loadtest.exe hello_b.dll FlmodSelfTest > console.txt 2> stderr.txt` inside `timeout 180`, cwd = the clone's EXE dir.
- wine exit code 0.
- `hello_b.log` was written in the EXE dir with `hello_b CreateID(li02)=2745692751`. So the DLL loaded, the export
  was found and called, and Common.dll's CreateID ran.
- `console.txt` is empty (0 bytes). `stderr.txt` holds only `wineserver: using server-side synchronization.`
- loadtest and hello_b both `fflush(stdout)` after each line.

**Hypotheses** (each fits every observation above):

1. Wine gives a console-subsystem exe a fresh hidden console (conhost) instead of the Unix stdout when stdout is a
   regular file, so CRT writes go to that console.
2. Wine sets the std handles from Unix fds only when they are a tty or pipe; for a regular file it leaves
   STD_OUTPUT_HANDLE invalid, so writes fail silently.
3. The HDE prefix has a native `ucrtbase`/vcrun override whose stdio init differs (e.g. no valid stdout when no
   console is attached).
4. `timeout` runs wine in a background process group; wine detects it is not the foreground job and detaches the
   console.
5. The `wine` loader starts the process through `start.exe`-like behaviour and returns early; output is produced
   after the redirect target is closed. (Weak: hello_b.log existed and exit was 0 when we checked.)
6. Proton-specific patch: wine-proton redirects console output of GUI-session processes to its own log, not stdout.
7. `WINEDEBUG=-all` also silences something that carries console output in this build. (Weak.)
8. The CRT treats stdout as fully buffered and the flush is lost because the process is killed at exit before
   `_flushall` (contradicted by explicit `fflush`, but possible if the handle write fails).
9. The prefix registry sets something for the console (`HKCU\Console`, or an AppDefaults entry) that changes
   handle inheritance for console apps.
10. Output goes to the parent's stdout only when the parent is a Windows process; a Unix parent with a file fd gets
    nothing in wine-proton 11 (a regression or a Proton design choice).
11. stdout is opened in text mode on a handle Wine reports as a console (`GetFileType` = FILE_TYPE_CHAR) for
    which `WriteConsoleW` fails because no real console exists.

**Experiment** (one clone, several variants, each distinguishes a subset):

- V1 baseline repeat (file redirect), V2 pipe (`| cat`), V3 pty (`script`), V4 Windows-side redirect
  (`wine cmd /c "loadtest.exe … > out.txt"`), V5 `wine cmd /c echo` to a file, V6 exit-code propagation
  (`wine loadtest.exe` with no args must return 2), V7 baseline without `timeout`.

**Result** (`$FLMOD_TESTRUNS/20261018T043847Z-toolchain-console-exp/`):

| Variant | stdout captured |
|---|---|
| V1 file redirect, V7 same without `timeout` | 0 bytes |
| V5 `wine cmd /c echo` to a file | 0 bytes (so it is not our CRT or DLL) |
| V2 pipe (`\| cat`) | full output |
| V3 pty (`script`) | full output |
| V4 Windows-side redirect inside `cmd /c` | full output |
| V6 `wine loadtest.exe` (no args) | exit code 2 propagates; the run is synchronous |

So H3 (native ucrt), H4 (timeout), H5 (async start), H7 and H8 are ruled out. Wine-proton 11 does not hand a
console app a Unix stdout that is a **regular file**; pipes and ptys work (H2/H10 family; exact mechanism not
investigated). Fix: `load_proof.sh` pipes through `cat`. VERIFIED. Worth knowing for every harness script that
captures wine console output: pipe it, don't redirect it to a file.

## Note: hello_a cannot be loaded outside the game

`loadtest.exe hello_a.dll GetMajorVersion` with FLUF.dll + its DLLs next to it exits with code 5 and prints nothing
(`$FLMOD_TESTRUNS/20261018T043945Z-toolchain-hello-a-load/`). FLUF.dll's `DllMain` constructs the whole `Fluf`
object on `DLL_PROCESS_ATTACH` (FLUF `Source/Fluf.cpp:295-318`). I think that constructor assumes it runs inside
Freelancer.exe or FLServer.exe (UNVERIFIED: the exact failing call was not traced). Either way it is FLUF start-up
behaviour, not a loader/ABI fault in hello_a. Not required by the spec; the in-game load of a FLUF module is P0-TRACK-A's
first checklist item. The static proof stands: all 189 FLUF.dll imports of hello_a resolve against the shipped
FLUF.dll's export table (check_imports).

## Decisions (attempt 1, 2026-10-17; copied into the report for state/DECISIONS.md)

1. MSVC CRT/STL **14.51** + SDK **10.0.28000** (xwin `--manifest-version 18`, VS 2026 18.11) instead of xwin's
   default 14.44: FLUF's prebuilt static libs carry `/FAILIFMISMATCH:"annotate_optional=0"`, which only the v145
   STL emits, so FLUF was built with a 14.5x STL (VERIFIED). That our final link *needs* at least that is
   UNVERIFIED (no 14.44 link tried; /FAILIFMISMATCH fails only on conflicting values). Channel manifest copy
   pinned in `/home/user/opt/xwin-cache-18/pinned/`.
2. GitHub inputs are fetched as commit archive tarballs with sha256 pins (not git clones): simpler, cacheable for
   offline re-runs, and no git repos inside the shared vendor tree.
3. Dear ImGui `v1.92.9b-docking`, not the 3-day-old `v1.93.0`. doctest v2.5.3, MinHook v1.3.4, nlohmann 3.11.3.
4. `LIBUUID_CPP20_OR_GREATER` added to the FLUF define set (stduuid `<span>` selection; needed to compile).
5. Track B ImGui gets `IMGUI_DISABLE_WIN32_DEFAULT_IME_FUNCTIONS` so it never imports `imm32.dll` (outside the
   import allowlist; IME is irrelevant here).
6. Both tracks share one Win32 define set (`flmod::win32_defs` = the Win32 subset of FLUF's must-match list), so
   code behaves the same whichever track Gate 0a picks.
7. `check_imports.py` goes beyond the spec: delay imports, i386 check, `api-ms-win-crt-*` against `ucrtbase.dll`,
   Freelancer DLL imports against the game's own DLLs, FLUF imports against the pinned FLUF.dll.
8. Directory discovery by glob (`src/module/*/`, `spikes/*/`, `harness/devbridge/`) with self-guards
   (`flmod_track_only`, `flmod_win32_only`, `flmod_host_only`); feature packages never edit the root CMake.
9. `hello_b` builds only in `win32-trackB`, `hello_a` only in `win32-trackA`, `loadtest` in both.
   CI stage 10 builds both win32 tracks while `FLMOD_TRACK` is unset.
10. `flmod::flsdk_static` (FLSDK's own sources, our compiler) for Track B; Track A links FLUF's prebuilt
    `FreelancerSDK.lib`.
11. Vendor trees are chmod read-only after extraction.
12. DLLs keep DWARF (`/DEBUG:DWARF`) for `winedbg --gdb`; no stripped variant yet.

## Bug 2: exception handling under Wine (review r1 MAJOR, 2026-10-18)

Reviewer evidence: `$FLMOD_TESTRUNS/20261018T045813Z-review-P0-TOOLCHAIN-r1/` (R/13, 16, 23, 24, probe sources).

**Observations** (all with the toolchain flags, DLL loaded by loadtest in a prefix-dev clone):

- (a) At /O2 a function with `__try/__except` returns to its caller with EBX/ESI/EDI clobbered (caller values
  b=0, c=1637915484). Its prologue saves no callee-saved registers. INTACT at /Od, and INTACT with
  `__asm__ volatile("" ::: "ebx","esi","edi")` at the top of the `__try` function. (Cause VERIFIED by the reviewer's
  disassembly: clang codegen.)
- (b) `catch(...)` around `*(volatile int*)nullptr = 1` does not catch the access violation (exit code 5), even though
  `/EHa` passes `-fasync-exceptions` to cc1 (VERIFIED: `clang-cl -###`). `__try/__except` around the same store
  works with /EHa, and crashes with /EHsc.
- (c) An exception leaving a catch block (`throw;`), caught by an enclosing try **in the same function**, kills the
  process: /O2 and /Od, /EHa and /EHsc. The same pattern across a non-inlined call works; inlined, it crashes. The
  outer catch body runs ("caught" is printed) and the process dies afterwards.
- The reviewer's `WINEDEBUG=+seh` trace (R/14) for (c): cxx_frame_handler matches the inner catch(...), calls it;
  the rethrow goes through `catch_function_nested_handler` ("detect rethrow"), matches the outer catch(int), unwinds
  the nested frame, calls the outer catch, logs "done, continuing at 7BA9180E", then an access violation at
  7BA918A7 (inside the *inner* catch funclet) with ebp=7bb0b50f (an address in Wine's msvcrt code).

**Hypotheses for (b)** (each fits all observations):

- B1. The `try` body contains no call, so clang sees nothing that can throw and drops the try region: the faulting
  store lies outside every try state (async C++ EH in LLVM may be x64-only).
- B2. clang emits the FuncInfo with `EHFlags & 1` (FUNC_DESCR_SYNCHRONOUS) even under /EHa on x86, and Wine's
  `cxx_frame_handler` returns ContinueSearch for non-C++ exceptions.
- B3. Wine's `find_catch_handler` never matches `catch(...)` for a non-C++ exception (e.g. catch(...) flagged
  "std dot-dot" by clang).
- B4. The handler is found but the catch funclet then crashes (as in (c)). Weak: nothing from the catch body prints.
- B5. The trylevel/state is still -1 at the faulting instruction because clang stores the state number only before
  invokes.
- B6. Wine-proton's wow64 dispatch of 32-bit AVs skips C++ frame handlers. Weak: `__try/__except` works.
- B7. /O2 reorders or hoists the store out of the try region; /Od would catch it.
- B8. `-fasync-exceptions` is not forwarded on i686. Ruled out: `clang-cl -###` shows it.
- B9. Wine requires `_set_se_translator` to deliver SEH into C++ handlers. Weak: Wine's source has a catch(...)
  path for C exceptions.
- B10. Native vcruntime140's FH3 would catch it (Wine-specific).

**Hypotheses for (c)**:

- C1. LLVM's x86 catch funclets store their own ESP into the registration node's SavedESP at entry
  (`X86FrameLowering.cpp` llvmorg-22.1.8 lines 2137-2150: "If we're a catch funclet, we can be returned to via
  catchret. Save ESP into the registration node so that the runtime will restore it for us."). Wine's
  `call_catch_block` (proton_11.0 `dlls/msvcrt/except_i386.c`) snapshots `save_esp = frame[-1]` at its own start
  and `continue_after_catch` resumes with that ESP. In the nested call (exception leaving the inner catch) the
  snapshot is the inner funclet's ESP, so the parent's continuation runs on the funclet's stack and its epilogue
  pops garbage. Predicts: any exception leaving a catch block to a same-frame try breaks (rethrow, new throw,
  rethrow_exception), runtime-independent if MSVC's CallCatchBlock snapshots the same way.
- C2. Wine's rethrow detection destroys the exception object twice; the crash is in the destructor path.
- C3. clang emits wrong try-state ranges for nested trys in one function, so the wrong handler or unwind runs.
- C4. Wine's RtlUnwind of the nested catch frame unlinks the parent's registration from fs:0, so the epilogue
  restores a dead fs:0.
- C5. Callee-saved registers are clobbered at the continuation (like (a)).
- C6. Wine-specific: native vcruntime140 (MSVC's `__CxxFrameHandler3`) handles nested catches differently.
- C7. Only `throw;` (rethrow detection, `ExceptionInformation[1..2] == 0`) breaks; throwing a *new* exception
  from the catch block works.
- C8. /EHa-specific (async EH tables). Ruled out by the reviewer: /EHsc also breaks.
- C9. The funclet's `add $0xc, %ebp` frame conversion assumes Wine passes `&frame->ebp` = frame+12; nested calls
  pass a different ebp. Weak: the trace shows the same ebp 0050FED8 both times.
- C10. A try/catch nested *inside* the catch block (caught within the same funclet) also breaks.
- C11. Exe vs DLL matters (e.g. loader/TLS differences in the EH globals).

**Experiments** (one probe, `src/module/ehprobe/ehprobe.cpp`, built in variants; each case in its own process):

- X1 `ehp_b_catchall_av_call` (AV inside a noinline callee) vs `_inline`: B1/B5 vs B2/B3.
- X2 /Od variant: B7. X3 native vcruntime140 + msvcp140 from the 14.51 redist, app-local with
  `WINEDLLOVERRIDES=vcruntime140,msvcp140=n,b`: B10, C6. X4 `ehp_c_throw_new_from_catch_same_frame`: C7.
  X5 `ehp_base_catch_in_catch`: C10. X6 exe variant: C11. X7 /EHs, /EHsc, /EHsc+`-fasync-exceptions`, /Ob0
  variants. X8 `WINEDEBUG=+seh` on the b-case: B2/B3 (flags, whether cxx_frame_handler is called at all).

**Results** (run dirs under `$FLMOD_TESTRUNS/`: `20261018T053349Z-toolchain-eh-exp/` (full matrix, `matrix.txt`),
`20261018T053642Z-toolchain-eh-exp2/`, `20261018T053801Z-toolchain-eh-exp3/` (`matrix.txt`)). Values are the case's
return value; `rc5` = process killed by an unhandled exception. "native" = the 14.51.36231 `vcruntime140.dll` +
`msvcp140.dll` from `Microsoft.VC.14.51.CRT.Redist.X86.base.vsix`, app-local, `WINEDLLOVERRIDES=vcruntime140,msvcp140=n,b`
(`native_loaddll.txt` shows both loaded as `native`).

| Case (expected) | EHa O2 | EHsc O2 | EHs O2 | EHa Od | EHsc+async | EHa Ob0 | exe EHa | native EHa | **EHa O2 +`-mstackrealign`** |
|---|---|---|---|---|---|---|---|---|---|
| base_* (7 cases) | pass | pass | pass | pass | pass | pass | pass | pass | pass |
| a_seh_regs_raw (1 = intact) | 0 | rc5 | rc5 | 1 | rc5 | 0 | 0 | 0 | 0 |
| a_seh_regs_guarded (1) | 1 | 1 | 1 | 1 | 1 | 1 | 1 | 1 | 1 |
| b_catchall_av_inline (11) | rc5 | rc5 | rc5 | rc5 | rc5 | rc5 | rc5 | rc5 | rc5 |
| b_catchall_av_call, nounwind callee (12) | rc5 | rc5 | rc5 | rc5 | rc5 | rc5 | rc5 | rc5 | rc5 |
| b_catchall_av_opaque_call (13) | **13** | rc5 | – | – | – | – | – | 13 | 13 |
| c_rethrow_same_frame (2) | rc5 | rc5 | rc5 | rc5 | rc5 | rc5 | rc5 | **2** | **2** |
| c_throw_new_from_catch_same_frame (1) | rc5 | rc5 | rc5 | rc5 | rc5 | rc5 | rc5 | **1** | **1** |
| c_rethrow_cross_noinline (2) | 2 | 2 | 2 | 2 | 2 | 2 | 2 | 2 | 2 |
| c_rethrow_cross_inlined (2) | rc5 | rc5 | rc5 | 2 | rc5 | 2 | rc5 | **2** | **2** |
| c_rethrow_eptr_in_catch_same_frame (3) | 3 | 3 | 3 | 3 | 3 | 3 | 3 | 3 | 3 |
| lib_rethrow_if_nested_in_catch (5) | rc5 | rc5 | rc5 | rc5 | rc5 | rc5 | rc5 | **5** | **5** |
| lib_vector_insert_throw (4) | rc5 / 4 | rc5 / 4 | rc5 | 4 | rc5 | 4 | rc5 | 4 | 4 |
| json_parse_error (101), json_type_error (302), json_parse_no_exceptions (1) | pass | pass | pass | pass | pass | pass | pass | pass | pass |
| json_at_same_frame (401), json_at_wrapped (401) | pass | pass | pass | pass | pass | pass | pass | pass | pass |

(`lib_vector_insert_throw` "rc5 / 4": it crashed in the first build and passed once more cases were added to the
TU, which changed the inliner's decisions.) `-mstack-alignment=16` alone changed nothing for (c).

**Conclusions**

- (a) Not fixed by any flag or runtime (/Od only hides it in the probe's caller; loadtest's own registers are still
  corrupted). The clobber barrier fixes it everywhere (`a_seh_regs_guarded` = 1 in all 9 variants). It stays a
  coding rule (ABI.md §6.1). VERIFIED.
- (b) B1/B5 confirmed, B2/B3/B8/B10 ruled out. `catch(...)` does catch an access violation under /EHa when the fault
  happens inside a call the compiler cannot prove `nounwind` (`b_catchall_av_opaque_call` = 13, builtin and
  native). It never catches a fault in the function's own body or in a callee clang inferred `nounwind`: those
  instructions are outside every try state (`WINEDEBUG=+seh`: "handling C exception code c0000005 … trylevel -1",
  `seh_b_call.txt`). /EHsc never catches it. LLVM emits `EHFlags=0` under /EHa (`WinException.cpp:760-765`), so
  Wine is not filtering it. Rule: never rely on `catch(...)` for SEH (ABI.md §6.2). VERIFIED.
- (c) C1 confirmed: it is the interaction between LLVM's x86 catch-funclet ESP save and Wine's builtin
  `call_catch_block` `save_esp` snapshot. MSVC's own `__CxxFrameHandler3` (native vcruntime140) handles it, so C6 is
  true and the "runtime-independent" half of C1 is false. C7 ruled out (new throws break too), C10 ruled out
  (catch-in-catch works), C11 ruled out (exe = DLL), C8 ruled out. `std::rethrow_exception` inside a catch happened
  to work because of that function's epilogue shape.
- **Toolchain fix for (c): `-mstackrealign`.** With forced stack realignment every EH function addresses its frame
  through EBP/ESI, and the catchret continuation recomputes ESI from EBP and the epilogue restores ESP from EBP
  (`lea -0xc(%ebp),%esp`), so the wrong ESP Wine hands back is never used (disassembly of
  `ehp_c_rethrow_same_frame` in the exp3 build). All (c) cases pass with Wine's builtin CRT. It changes no
  calling convention, struct layout or name mangling (each function realigns its own frame), so the MSVC ABI and
  the FLUF must-match list are unaffected. Adopted in `clang-cl-i686.cmake` (attempt 1 fix round 1). VERIFIED.
- Prebuilt code that we do not compile (FLUF.dll, FLUF's dev `.lib`s including `FreelancerSDK.lib`, yaml-cpp,
  msgpack, zstd) does not get the flag. Under Wine's builtin CRT a same-frame catch-and-rethrow inside that code can
  still crash. The native-CRT option fixes that too, but it changes the runtime of every DLL in the game process,
  so it is a deployment decision for P0-HARNESS / P0-TRACK-A (reported as an open question).
- nlohmann 3.11.3: `json::parse` errors are thrown from normal code (the SAX DOM parser), not from a catch block, so
  they never hit (c) (`json_parse_error` = 101 in all variants). The only catch-and-throw site without
  `JSON_DIAGNOSTICS` is `basic_json::at(size_type)` (array `at()`, json.hpp:21249 and 21272). MSVC STL catch-and-
  rethrow sites (`_CATCH_ALL … _RERAISE`): `<vector>` range insert, `<istream>`/`__msvc_ostream.hpp` (`_CATCH_IO_END`),
  `<future>`, `<iterator>`, `<syncstream>`, `<stacktrace>`, `<xlocale>`, `<iosfwd>`, `<yvals.h>`; plus
  `std::throw_with_nested`/`std::rethrow_if_nested` when called inside a catch block. With `-mstackrealign` these
  are safe in our own code (probe cases `lib_*`, `json_at_*`).

## RESUME POINT (2026-10-18, review r1 fix round 1, paused for a reboot)

Branch `wp/P0-TOOLCHAIN`; the commit that adds this section is the resume SHA. Reviews: `state/reports/P0-TOOLCHAIN-r1.md`.

### Review r1 findings

| Finding | State |
|---|---|
| MAJOR EH: fix the /EHa comments | DONE (`clang-cl-i686.cmake`, `-overrides.cmake`) |
| MAJOR EH: (a)-(c) in ABI.md + verified (a) workaround | DONE (ABI.md §6.1-6.5, copy-paste `flmod_seh_guard`) |
| MAJOR EH: regression probe | DONE (`src/module/ehprobe`, `toolchain/ehprobe.sh`, `ehprobe_cases.tsv`; `load_proof.sh` runs it). Last runs: `$FLMOD_TESTRUNS/20261018T054636Z-toolchain-loadproof/` (B, both CRTs: 23 PASS / 3 KNOWN-BROKEN / 0 FAIL, before `a_seh_guard_cxx_exception` was added), `20261018T054744Z-ehprobe/` (B, both CRTs, 24/3/0), `20261018T054657Z-ehprobe/` (A, builtin, 23/3/0). Negative control without `-mstackrealign`: `20261018T054555Z-ehprobe/` (4 FAIL, exit 1) |
| MAJOR EH: ten hypotheses for (b),(c), experiments | DONE (Bug 2 above; matrices in the exp run dirs; the scripts `eh_exp*.sh` are copied into those run dirs) |
| MAJOR EH: toolchain-level fix | DONE for (c): `/clang:-mstackrealign` added to the common flags. (a), (b) stay rules |
| MAJOR EH: engine facts for TRACK-A/B | REMAINING: write them into the final fix report (see "Facts to report" below) |
| MINOR check_imports delay imports nested | DONE (parser + real-format fixture `REAL_DELAY_OUTPUT`; reviewer's `delaycommon.dll` now FAILs as it should) |
| MINOR any missing msvcp140*/vcruntime140* DLL = FAIL | DONE (+ test) |
| MINOR WILL_FAIL negative probes accept any failure | DONE (`tests/host/ExpectFailure.cmake`: non-zero exit AND specific text) |
| MINOR lint denylist too small | DONE (allowlist: standard headers, `<nlohmann/...>`, quoted includes resolving under src/logic or src/contracts; fixtures for synchapi.h behind #ifdef, io.h, tchar.h, unresolved quoted include) |
| MINOR /tests/ absolute-path filters, nested tests dirs | DONE (RELATIVE globs; `src/**/tests/**/*.cpp`, VERIFIED with a temporary nested test, removed) |
| MINOR src/game not discovered: document for ARCH-0 | PARTLY: root CMakeLists comment done; README "Adding a target" not yet |
| MINOR fetch_vendor --verify downloads / checks stamps only | DONE (offline, read-only; per-tree `.flmod-manifest`; tamper test FAILs, nothing written) |
| MINOR PINS FLUF upstream URLs | PARTLY: fallback URLs in `fetch_vendor.sh` (Codeberg API VERIFIED: nightly 139359852 B, stable 55651208 B); PINS.md table not yet updated |
| MINOR load_proof hard-coded clone | DONE (`--clone`, prefix-dev* only) |
| MINOR ci.d protocol drift | MOSTLY: 10/20/50 rewritten (artifacts in `$CI_RUNDIR/<NN>-<name>/`, `CI_REPO_ROOT`, default run dir under `$FLMOD_TESTRUNS`, stage 50 reads `build/win32-track*/flmod_binaries.txt` so stale out/ files are ignored). Stage 10 re-run PASS (`$FLMOD_TESTRUNS/20261018T0600Z-toolchain-ci-r1/`). Stages 20 and 50 not yet re-run under the new protocol, stale-file test for 50 not yet run |
| MINOR 14.5x STL claim overstated | DONE (marked UNVERIFIED in PINS.md and Decisions) |
| MINOR FLSDK code embedded in binaries (W5-SHIP) | DONE in ABI.md §7 (also MinHook BSD-2 notice); PINS.md cross-reference not yet |

### Exact next steps

1. `harness/ci.d/20-host-tests.sh` and `50-import-check.sh` with `CI_RUNDIR=<new $FLMOD_TESTRUNS dir> CI_REPO_ROOT=<worktree> CI_MODE=full`;
   then copy a stale DLL into `build/win32-trackB/out/` and confirm stage 50 ignores it; delete it.
2. Re-run `toolchain/load_proof.sh build/win32-trackB --clone prefix-dev-toolchain-r1` (24 PASS / 3 KNOWN-BROKEN expected
   per CRT) and `toolchain/ehprobe.sh --build build/win32-trackA --clone prefix-dev-toolchain-r1a --crt both`.
3. README: `-mstackrealign` in the flag list, `flmod_win32_dll`, `ehprobe.sh`, `fetch_vendor --verify` semantics,
   the lint allowlist, nested tests dirs, the src/game rule for ARCH-0, the ci.d protocol. PINS.md: FLUF upstream
   URLs, the `msvc-redist-x86` pin, the FLSDK-embedding note.
4. Re-run the full acceptance set from an empty `build/` (host, host-asan, both win32, check_imports, pytest
   `toolchain/tests` (16 tests, last PASS), negative probes, fetch_vendor/setup_xwin `--verify`), `check_public`
   (P0-REPO's copy at `.claude/worktrees/agent-af7c7d7da0b0d74b7/tools/check_public.py`, or main's if merged),
   commit, and send the fix report.

### Facts to report (engine facts for TRACK-A/B)

- (a) `__try` functions at /O2 clobber the caller's EBX/ESI/EDI after a handled fault; the clobber-barrier guard is
  INTACT (VERIFIED, both CRTs). (b) `catch(...)` sees an AV only under /EHa and only inside an opaque call (VERIFIED).
  (c) fixed by `-mstackrealign` for our code; still possible inside prebuilt FLUF/HDE code under Wine's builtin CRT;
  MSVC's native vcruntime140 also fixes it (VERIFIED). Open question for the orchestrator: deploy the native 14.51
  CRT app-local (`$FLMOD_VENDOR/msvc-redist/x86` + `WINEDLLOVERRIDES=vcruntime140,msvcp140=n,b`) for Track A, where
  FLUF.dll itself is clang-cl code without `-mstackrealign`?
- Wine's apisetschema maps api-ms-win-crt-* to ucrtbase; wine drops console stdout redirected to a regular file.

### Things outside the repo (all on the persistent root XFS, survive a reboot)

- `$FLMOD_VENDOR` (`/home/user/freelancer/carrier-mod/vendor`): this round re-extracted every tree to add
  `.flmod-manifest` files, and added `msvc-redist/x86/` (MSVC 14.51.36231 redist DLLs) plus its vsix in `.cache/dl/`.
  `toolchain/fetch_vendor.sh --verify` was PASS afterwards (11/11).
- `$XWIN_ROOT` (`/home/user/opt/xwin`) and `/home/user/opt/xwin-cache-18`: unchanged this round. `~/.cargo/bin/xwin` 0.10.0.
- Wine prefixes: every `prefix-dev-toolchain*` clone was deleted by its script (none left; `prefix-dev-base-A/B`
  belong to P0-HARNESS). No wine or background processes of mine are running.
- Scratch copies in this session's `/tmp/claude-1000/.../scratchpad/` (redist DLLs, Wine/LLVM source excerpts used
  for the analysis, experiment scripts) may not survive the reboot; nothing depends on them (scripts are copied into
  the run dirs; sources are public: Wine proton_11.0 `dlls/msvcrt/except_i386.c`, LLVM llvmorg-22.1.8
  `X86FrameLowering.cpp`, `X86WinEHState.cpp`, `WinException.cpp`).
