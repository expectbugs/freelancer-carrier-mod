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
   STL emits, so FLUF was built with a 14.5x STL and our final link needs at least that. Channel manifest copy
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
