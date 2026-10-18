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

## Question 3: app-local native MSVC runtime for FLUF (Track A)? (2026-10-18, open question for G0a/W1-PLATFORM)

Run dirs: `$FLMOD_TESTRUNS/20261018T0650Z-toolchain-fluf-crt/` (static analysis, `fluf_crt_static.md`) and
`$FLMOD_TESTRUNS/20261018T0700Z-toolchain-fluf-crt-rerun/` (Wine runs E1–E3 and the FLUF source scan; the scripts
`fluf_crt_static.py`, `crt_exp.sh`, `catch_throw_scan.py` are copied there). The first dir's `E3_matrix.tsv` has a
wrong rc column (script bug, see its `README.txt`); use the rerun.

**Evidence**

1. What FLUF imports (33 DLLs: `EXE/fluf/*.dll` + `modules/*.dll` of the pinned nightly): 159 distinct
   `msvcp140` symbols, 2 `msvcp140_atomic_wait`, 27 `vcruntime140`, 221 `api-ms-win-crt-*`. **Wine's builtins
   export all of them (0 missing), and so does the native 14.51.36231 redist (0 missing).** VERIFIED (static,
   llvm-readobj against the play prefix's syswow64 and `$FLMOD_VENDOR/msvc-redist/x86`).
2. The native redist DLLs' own imports (`api-ms-win-crt-*` → Wine's builtin ucrtbase, `KERNEL32`, `ADVAPI32`,
   `api-ms-win-core-synch`) all resolve in this prefix; only `vccorlib140.dll` (C++/CX, never needed) lacks WinRT
   exports. The redist has no ucrtbase, so the UCRT stays Wine's either way. VERIFIED (static).
3. The play prefix's `user.reg` has `[Software\\Wine\\DllOverrides]` `msvcp140`, `msvcp140_1`, `msvcp140_2`,
   `msvcp140_atomic_wait`, `msvcp140_codecvt_ids`, `vcruntime140`, `vcruntime140_1`, `concrt140`, `ucrtbase` =
   `native,builtin`, and its `syswow64` copies are Wine builtins (all eight present carry the "Wine builtin DLL"
   marker; there is no 32-bit `vcruntime140_1.dll`, which is x64-only). No CRT
   DLL sits in the HDE EXE dir today. VERIFIED (read-only grep of the play prefix).
4. E1: native DLLs next to `loadtest.exe`, **no** `WINEDLLOVERRIDES`: `+loaddll` shows `VCRUNTIME140.dll … native`,
   `MSVCP140.dll … native`, `ucrtbase.dll … builtin`. E2: same dir with `WINEDLLOVERRIDES=vcruntime140,msvcp140=b`:
   both `builtin`. So dropping the files app-local is enough to switch the runtime, and the env var forces it back.
   VERIFIED (`E1_native_noenv_loaddll.txt`, `E2_builtin_forced_loaddll.txt`).
5. FLUF.dll is clang-cl code linked by lld-link (PE linker version 14.0, no Rich header; FLUF CI builds with
   `cli.py configure --clang` on an msvc-wine runner, `.forgejo/workflows/nightly-release.yml`), and FLUF's build
   files at `627ea2c` never pass `-mstackrealign` (grep of `CMakeLists.txt`, `cmake/`, `profiles/`). So FLUF.dll can
   in principle hit Bug 2 (c) under Wine's builtin CRT. VERIFIED (files); whether any FLUF code path actually does is
   UNVERIFIED.
6. E3 stand-in for "clang-cl code without the flag": `ehprobe.dll` rebuilt with `/clang:-mno-stackrealign` (realigning
   prologues 219 → 20). Under the builtin CRT `c_rethrow_same_frame`, `c_throw_new_from_catch_same_frame`,
   `c_rethrow_cross_inlined`, `lib_rethrow_if_nested_in_catch` die (rc 5); with the native DLLs app-local and no env
   var all four PASS; the other four c/lib cases PASS under both. VERIFIED (`E3_matrix.tsv`).
7. FLUF's own exposure is small: a brace-matching scan of `FLUF/`, `FLUFBoot/`, `DacomFix/`, `modules/` (524 files)
   finds 31 catch blocks and **0** `throw` statements inside them (`fluf_catch_throw_scan.txt`; positive control on
   `ehprobe.cpp` finds its 5). Remaining exposure: library code inlined into FLUF (STL range insert, stream
   exception masks, `rethrow_if_nested`), and calls inside catch blocks that themselves throw (e.g. a logging call
   hitting `std::format_error`/`bad_alloc`). UNVERIFIED that none of those runs.
8. A native runtime is process-wide: besides FLUF and our DLLs, 23 of the 106 PE files in the HDE EXE tree import
   msvcp140/vcruntime140 (FLHook.dll and 16 `plugins/*.dll`, fmt.dll, spdlog.dll, pcre2-*.dll, FL Save Convert.exe)
   and would switch too whenever they are loaded. VERIFIED (static scan, `fluf_crt_static.md` §3).

**Recommendation (for G0a / W1-PLATFORM; not decided here)**

- Keep **Wine's builtin CRT** as the default on both tracks; don't deploy the native DLLs. Our code is safe through
  `-mstackrealign` (probe 24/3/0 with either runtime), FLUF's imports are fully covered by the builtins, and FLUF's
  source has no catch-and-throw. Switching is a process-wide change that no game run has tested yet.
- Keep it as a **documented fallback** for P0-TRACK-A: if an in-game Track A run dies with the Bug 2 (c) signature
  inside FLUF or HDE frames (`WINEDEBUG=+seh`: a catch block "done, continuing at …" followed by an access violation
  inside the catch funclet), deploy all nine DLLs from `$FLMOD_VENDOR/msvc-redist/x86/` into the lane's EXE dir at
  deploy time (never into the play install, never committed). The prefix registry does the rest (E1); re-run the
  probe with `--crt native`. Copy the whole set so `msvcp140_atomic_wait`/`_1`/`_2` match the native `msvcp140`.
- Whatever is decided, the harness deploy step should assert that no stray MSVC runtime DLL sits in the EXE dir
  unless it was put there on purpose (E1 shows such a file silently changes the runtime). The registry sets
  `native,builtin` for more than the 140 set (review r2 note: also `ucrtbase`, `vcruntime140_1`, `concrt140`, the
  `api-ms-win-crt-*` sets and `msvcp1?0`/`msvcr1?0`), so the check should cover `msvcp1*`, `msvcr1*`,
  `vcruntime140*`, `concrt140*`, `ucrtbase*` and `api-ms-win-crt-*` (ABI.md §6.6).
- Still open (UNVERIFIED, for P0-TRACK-A): the source scan in point 7 does not see library code inlined into FLUF.dll;
  a binary scan of FLUF's catch funclets for `_CxxThrowException`/rethrow calls would settle it. FLUF's own non-CRT
  imports (`d3dcompiler_47`, `opengl32`, `imm32`, `bcrypt`, `crypt32`, …) are not covered by check_imports (it
  checks our binaries); confirm they resolve in the lane prefix.

## Review r2 fixes (2026-10-18)

Review: `state/reports/P0-TOOLCHAIN-r2.md` (reviewer evidence `$FLMOD_TESTRUNS/20261018T065307Z-review-P0-TOOLCHAIN-r2/`).

- **F1 (MAJOR) lint vs doctest files under `src/logic/**/tests/`.** Cause VERIFIED by the reviewer (R/11b, R/11e)
  and by my negative control: the r1 allowlist lint scanned tests/ dirs, and its stamp DEPENDS used a different file
  set (sources without tests/, headers with tests/), so fresh and incremental builds disagreed. No hypothesis list:
  the cause was shown directly, not inferred. Decision: exclude `(^|/)tests/` from the lint and the header check
  rather than allow `<doctest/...>` under tests/, because tests/ code is host-only (never in `logic` or a win32
  binary), also needs quoted helpers from `tests/host/`, and the host compile already rejects Windows headers there.
  One function (`cmake/LogicLintFiles.cmake`) now defines the set for the lint script, the stamp's DEPENDS and the
  header check. Fixture ctest `logic_tests_dir_doctest` (`tests/host/LogicTestsDirFixture.cmake`) PASS (6.5 s);
  negative control with the exclusion commented out: FAIL "Forbidden includes … zz_fixture/tests/…"
  (`$FLMOD_TESTRUNS/20261018T0730Z-toolchain-r2-f1/negative_control_no_tests_exclusion.log`).
- **F2** `toolchain/check_flags.py` in stage 10 (pytest 11 cases); negative: a spike TU with
  `-mno-stackrealign /EHsc` makes stage 10 FAIL `win32-trackB:flags`, PASS after removal
  (`$FLMOD_TESTRUNS/20261018T0750Z-toolchain-r2-ci/negatives.txt`). Who runs ehprobe: README + ABI.md §6.5 (proposal).
- **F3/F5** 13 `hook` cases in the probe (the reviewer's 9 patterns + 4 hook-template paths); ABI.md §6.7 template,
  §6.8 in-game items. 37 PASS / 3 KNOWN-BROKEN / 0 FAIL / 0 SKIP per runtime on both tracks.
- **F4** `toolchain/ci_tracks.sh` shared by stages 10/50; FLMOD_TRACK=B ignores a stale trackA list (PASS), unset
  checks it (FAIL, control), invalid value FAILs (`negatives.txt`).
- **F6** + orchestrator `--from`: `toolchain/prefix_clone.sh`; 23 refused invocations give the right exit code and
  create no run dir or clone (`$FLMOD_TESTRUNS/20261018T0745Z-toolchain-r2-f6/refusals.txt`); in-use detection test
  (`prefix_in_use_test.txt`); `--crt both` without the redist ends `result=SKIP`, exit 77, and a prefix without the
  game dir reports the engine case as SKIP (`skip_paths/`).
- **F7** README "The src/game rule" (module glob must exclude `(^|/)(tests|scenarios)/`).

## RESUME POINT (2026-10-18, review r3 PASS + polish round on N1-N3: COMPLETE)

Branch `wp/P0-TOOLCHAIN`. Reviews: `state/reports/P0-TOOLCHAIN-r1.md` (all findings DONE; the per-finding table is in
this file at commit `0bceb22`), `state/reports/P0-TOOLCHAIN-r2.md` (all findings DONE, "Review r2 fixes" above) and
`state/reports/P0-TOOLCHAIN-r3.md` (PASS; its three new MINORs are done, below). Nothing is pending; the merge waits
for P0-REPO. D110 adopted the ehprobe proposal.

### Review r3 polish (N1-N3)

Evidence dir: `$FLMOD_TESTRUNS/20261018T0800Z-toolchain-r3-polish/`.

| Finding | Change | Test / evidence | State |
|---|---|---|---|
| N1 quoted include from linted code into a tests/ dir | `cmake/LogicIncludeLint.cmake`: a quoted include that resolves inside a `tests/` dir (relative to the allowed root) is a violation | fixture `tests/host/negative/lint_fixture/bad_tests_include.hpp` → `tests/leak_helper.hpp` added to ctest `logic_rejects_forbidden_includes_lint`; the reviewer's loophole in the real tree now fails host and trackB, passes after removal (`n1_loophole.txt`) | DONE |
| N2 in-use check on raw strings; baseline consistency | `toolchain/prefix_clone.sh`: `realpath -m` on both sides (D110); a `prefix-dev-base-*` source needs `BASELINE.json` | `toolchain/tests/test_prefix_clone.py` (20 cases: `//`, `/./`, `x/..`, trailing `/`, `pfx2/../pfx`, odd spellings of the argument, cwd inside, sibling prefix not counted, BASELINE.json missing/present, baseline in use, bad `--from`); the previous version fails 9 of them (`n2_negative_control_old_prefix_clone.txt`); real baselines accepted (`n2_real_baselines.txt`); 23 refusals unchanged (`refusals.txt`) | DONE |
| N3 check_flags launchers and EH neutralisation | `toolchain/check_flags.py`: parses past ccache/sccache, FAILs any other non-clang-cl entry (only `.rc` entries for llvm-rc are skipped), FAILs `-fno-async-exceptions`/`-fno-exceptions`/`-fno-cxx-exceptions` in any spelling; later `/EHsc`, `/EHs-`, `/EHa-` already FAIL (last /EH must be /EHa) | 8 new pytest cases (19 in the file) | DONE |

Re-runs: P0-REPO `ci.sh` (32ab66a) `--full --only public,build,host-tests,import-check` from an empty `build/`: PASS x4
(`$FLMOD_TESTRUNS/20261018T074640Z-ci/`; ctest host 6/6, host-asan 6/6; check_flags 36/37 TUs, 0 other entries);
pytest `toolchain/tests` 55/55 (`pytest.txt`). No Wine run: the probe is unchanged.

### Review r2 findings

| Finding | State / evidence |
|---|---|
| F1 MAJOR lint rejects doctest files under src/logic/**/tests/ | DONE: `cmake/LogicLintFiles.cmake`; ctest `logic_tests_dir_doctest` PASS (host + host-asan); negative control FAIL (`20261018T0730Z-toolchain-r2-f1/`) |
| F2 static flag assertion; who runs ehprobe | DONE: `toolchain/check_flags.py` in stage 10; negative in `20261018T0750Z-toolchain-r2-ci/negatives.txt`; README + ABI.md §6.5 |
| F3 reviewer's hostable EH cases | DONE: 9 `hook_*` cases; not-hostable items in ABI.md §6.8 |
| F4 stage 50 track selection | DONE: `toolchain/ci_tracks.sh`; `negatives.txt` N1a-c |
| F5 hook template | DONE: ABI.md §6.7, compiled and run as `hook_template_*` (4 cases) |
| F6 ehprobe --prefix, exit 77, validation order | DONE: `20261018T0745Z-toolchain-r2-f6/` |
| F7 src/game tests rule | DONE: README "The src/game rule", root CMakeLists comment |
| Orchestrator: load_proof/ehprobe `--from` (default a dev baseline) | DONE: default `prefix-dev-base-B`; the play prefix only with `--from play` |

### Final acceptance (fix round 2)

- From an empty `build/`: P0-REPO's real `ci.sh` (wp/P0-REPO @ 32ab66a) `--full --only public,build,host-tests,import-check`:
  PASS / PASS / PASS / PASS (`$FLMOD_TESTRUNS/20261018T072821Z-ci/`), plus the remaining acceptance items
  (`20261018T072821Z-toolchain-acceptance-r2/`, 11 steps rc 0: PE32 i386 headers, hello_a exports, check_imports
  both tracks, pytest 27/27, both `--verify`, check_flags, manual windows.h negative test, ctest 6/6).
- Wine (no D3D device; GPU Recovery Action None before and after): load proof B from `prefix-dev-base-B`
  `20261018T072930Z-toolchain-loadproof/` (LOAD PASS, EH both CRTs 37/3/0/0); EH probe A `20261018T072950Z-ehprobe/`
  (both CRTs 37/3/0/0).

### Things outside the repo

- `$FLMOD_VENDOR`, `$XWIN_ROOT`, `/home/user/opt/xwin-cache-18`: unchanged (`--verify` PASS).
- Wine prefixes: every `prefix-dev-toolchain*` clone of this session was deleted; none left. The dev baselines were
  only read (reflink source). No wine processes of mine are running.
