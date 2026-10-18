# Toolchain: building the mod on this Gentoo host

32-bit Windows DLLs for Freelancer are cross-built on Linux with **clang-cl 22 + lld-link + llvm-rc** against the
MSVC CRT/STL and Windows SDK fetched by **xwin** (no MSVC, no Windows, no Wine in the build loop). The engine-free
code in `src/logic/` also builds natively with clang++ for fast host tests. Everything third-party is pinned
(`PINS.md`). ABI and exception-handling rules: `ABI.md` (binding for every C++ package).

## From scratch

```bash
source /home/user/freelancer/carrier-mod/tools/env.sh   # FLMOD_* paths, wine guards first on PATH
# 1. MSVC CRT/STL 14.51 + Windows SDK 10.0.28000 for x86 -> /home/user/opt/xwin (accepts the MS license)
toolchain/setup_xwin.sh            # idempotent; --verify checks, --offline uses the cache only
# 2. Pinned third-party inputs -> /home/user/freelancer/carrier-mod/vendor (shared by all worktrees)
toolchain/fetch_vendor.sh          # idempotent; --verify, --offline, --list, --force [name...]
# 3. Build and test
cmake --preset host && cmake --build --preset host && ctest --preset host
cmake --preset host-asan && cmake --build --preset host-asan && ctest --preset host-asan
cmake --preset win32-trackA && cmake --build --preset win32-trackA     # FLUF module (Track A)
cmake --preset win32-trackB && cmake --build --preset win32-trackB     # plain dacom DLL (Track B)
# 4. Import check (reads the prefix's syswow64 and the game's EXE dir; never writes)
$FLMOD_VENV/bin/python -I toolchain/check_imports.py build/win32-trackB/out/*.dll build/win32-trackB/out/*.exe --prefix /home/user/freelancer/prefix
$FLMOD_VENV/bin/python -I toolchain/check_imports.py build/win32-trackA/out/*.dll --prefix /home/user/freelancer/prefix --allow-fluf
# 5. Runtime load proof + EH probe in a throwaway reflink clone of the play prefix (created and deleted)
toolchain/load_proof.sh build/win32-trackB --clone prefix-dev-toolchain-$USER
toolchain/ehprobe.sh --build build/win32-trackA --clone prefix-dev-toolchain-a --crt both
```

Only P0-TOOLCHAIN (later: whoever owns `toolchain/`) runs steps 1–2; they write the shared trees. Everyone else
just builds. Worktrees have no `vendor/`; CMake finds it through `FLMOD_VENDOR` (env or cache variable, default
`/home/user/freelancer/carrier-mod/vendor`) and the SDK through `XWIN_ROOT` (default `/home/user/opt/xwin`).

Both `--verify` modes are **offline and read-only** (nothing is downloaded or rewritten):

- `fetch_vendor.sh --verify` re-hashes every source file that is present (local tarball, download cache), checks
  every pin stamp, and re-hashes every installed tree against the `.flmod-manifest` written at install time. A
  modified, added or missing vendor file is a FAIL.
- `setup_xwin.sh --verify` checks the sha256 of every cached xwin package, the splat's key files and its pin stamp.

Vendor trees are read-only on disk, so a build that tries to write into them fails loudly.

## Presets

| Preset | Toolchain file | What it builds | Output |
|---|---|---|---|
| `host` | `toolchain/host.cmake` (clang++ 22, C++23, `-Wall -Wextra -Werror=return-type`, RelWithDebInfo) | `logic`, `logic_header_check`, `host_tests` | `build/host/out/host_tests` |
| `host-asan` | same + `FLMOD_SANITIZE=ON` (ASan + UBSan, Debug) | same | `build/host-asan/out/` |
| `win32-trackA` | `toolchain/clang-cl-i686.cmake`, `FLMOD_TRACK=A`, Release | `logic`, `loadtest.exe`, `ehprobe.dll`, `hello_a.dll`, Track A modules/spikes | `build/win32-trackA/out/` |
| `win32-trackB` | `toolchain/clang-cl-i686.cmake`, `FLMOD_TRACK=B`, Release | `logic`, `loadtest.exe`, `ehprobe.dll`, `hello_b.dll`, Track B DLLs/spikes | `build/win32-trackB/out/` |

Build presets and test presets (`host`, `host-asan`) have the same names. Each worktree builds into its own
`build/`.

win32 compile flags (every C/C++ TU): `--target=i686-pc-windows-msvc /winsysroot $XWIN_ROOT /MD /Z7 -gdwarf
/utf-8 /permissive- -D_ITERATOR_DEBUG_LEVEL=0 -Wno-microsoft-cast -Wno-cast-function-type-mismatch
/clang:-mstackrealign /O2`, plus `/EHa -std=c++23` for C++. Link: `/winsysroot:$XWIN_ROOT /SAFESEH:NO
/INCREMENTAL:NO /OPT:REF /OPT:ICF /DEBUG:DWARF /machine:X86`. DLLs carry DWARF for `winedbg --gdb`; they are larger
than a stripped build (hello_a.dll ≈ 1.6 MB).

**Never override `/EHa` or `-mstackrealign` per target** (no `target_compile_options` that drop or replace them,
no `CMAKE_CXX_FLAGS` overrides). `-mstackrealign` is what makes an exception leaving a catch block survive under
Wine's builtin vcruntime140; `/EHa` is what lets `__try/__except` catch a fault in its own function. Details and
the coding rules that no flag fixes: `ABI.md` §6. The EH probe's `c_*` cases FAIL if the flag goes missing.

## Adding a target (spikes, modules, tools)

The root `CMakeLists.txt` discovers directories by glob, so packages never edit it:

| Put a `CMakeLists.txt` in | It is added in |
|---|---|
| `src/module/<name>/` | every build (guard it, see below) |
| `spikes/<id>/` | every build (guard it) |
| `harness/devbridge/` | every build (guard it) |

Sources are discovered too (globs are relative to their root, so it does not matter where the checkout lives):

| Files | Go into |
|---|---|
| `src/logic/**/*.cpp` (except under any `tests/` dir) | the `logic` static library (host and win32) |
| `tests/host/**/*.cpp` (except `tests/host/negative/`) | `host_tests` |
| `src/**/tests/**/*.cpp`, at any depth (`src/logic/<area>/tests/`, `src/logic/<area>/tests/<sub>/`, …) | `host_tests` |
| `src/game/**` | **nothing, on purpose.** Engine-facing code is compiled by the module DLL that ships it: ARCH-0's `src/module/<mod>/CMakeLists.txt` must `file(GLOB_RECURSE … CONFIGURE_DEPENDS "${PROJECT_SOURCE_DIR}/src/game/*.cpp")` into its target. |

Re-run `cmake --preset …` after adding files; `CONFIGURE_DEPENDS` usually does it for you.

Guards and helpers (`cmake/FlmodFunctions.cmake`):

| Call | Effect |
|---|---|
| `flmod_track_only(A)` / `flmod_track_only(B)` | skip the rest of this CMakeLists.txt unless it is a win32 build of that track |
| `flmod_win32_only()` / `flmod_host_only()` | skip in host / win32 builds |
| `flmod_fluf_module(<t>)` | Track A FLUF module: full FLUF must-match define set, include dirs, `FLUF.lib`, `FreelancerSDK.lib`, FLSDK import libs, reflectcpp (FLUF's commit, built static with our compiler), `yaml-cpp.lib`, `msgpack-c.lib`, `zstd_static.lib`, `dsound ws2_32 dxguid`. Never define `FLUF`. Your `.cpp` ends with `SETUP_MODULE(Type, ModuleMajorVersion::Two, ModuleMinorVersion::Zero);` |
| `flmod_dacom_dll(<t>)` | plain dacom-style DLL: FLSDK headers + `FLCoreCommon/Server/DALib/DACom/RemoteClient.lib`, static MinHook (`flmod::minhook`), static Dear ImGui with dx9 + win32 backends in Track B (`flmod::imgui_static`, `IMGUI_API` empty, no IME), `d3d9 dxguid user32`. No FLUF. |
| `flmod_win32_dll(<t>)` | plain win32 DLL with no Freelancer or hook libraries (tools, probes such as `ehprobe.dll`) |
| `flmod_win32_exe(<t>)` | win32 console tool in `out/` |
| `flmod_rc_includes(<t>)` | lets `.rc` files include `<winres.h>` / `<windows.h>` |
| `flmod_host_tests(SOURCES … LIBS …)` | add doctest files outside the auto-globbed dirs to `host_tests` |

**Every win32 DLL/EXE must go through one of the four DLL/EXE helpers.** They register the binary in
`build/<preset>/flmod_binaries.txt`, which is exactly what CI stage 50 import-checks; a bare `add_library(SHARED)`
is never checked, and stale files left in `out/` are ignored.

Other targets you can link: `logic` (engine-free static lib, both builds), `flmod::nlohmann_json` (the JSON
library, all builds), `flmod::doctest` (host), `flmod::win32_defs` (the shared Win32 defines),
`flmod::flsdk_headers`, `flmod::flcore`, `flmod::flsdk_static` (FLSDK's own sources — X86Math, Utils, INI
helpers — built with our compiler; Track A links FLUF's prebuilt `FreelancerSDK.lib` instead), `flmod::fluf`.

Example, a Track B spike DLL with its own static platform lib:

```cmake
# spikes/track_b/CMakeLists.txt
flmod_track_only(B)
add_library(spike_platform_b STATIC platform/platform.cpp)
target_link_libraries(spike_platform_b PUBLIC flmod::win32_defs flmod::flsdk_headers flmod::flcore flmod::minhook flmod::imgui_static)
add_library(spike_b SHARED spike_b.cpp)
flmod_dacom_dll(spike_b)
target_link_libraries(spike_b PRIVATE spike_platform_b logic)
```

Example, a Track A module:

```cmake
# spikes/track_a/CMakeLists.txt
flmod_track_only(A)
add_library(spike_a SHARED spike_a.cpp)
flmod_fluf_module(spike_a)
```

Every DLL/EXE ends up in `build/<preset>/out/`.

## The `src/logic` rule

`src/logic/` is engine-free: no Windows, Freelancer, FLUF, ImGui or MinHook headers. Two mechanisms enforce it:

1. `cmake/LogicIncludeLint.cmake` runs in every build (host and win32) and fails it on any `#include` outside an
   **allowlist**: C++23 standard headers and the C compatibility headers (`<cstdio>`, `<stdio.h>`, …),
   `<nlohmann/...>`, and quoted includes that resolve to a file under `src/logic/` or `src/contracts/`. Anything
   else fails, including a Windows-only header hidden behind `#ifdef _WIN32` (`<synchapi.h>`, `<io.h>`,
   `<tchar.h>`, …) and a quoted include that does not resolve.
2. Host builds compile every `src/logic` header on its own, twice, with only `src/` and nlohmann/json on the
   include path (`tests/host/LogicHeaderCheck.cmake`, target `logic_header_check`, ctest
   `logic_headers_standalone`).

ctest also runs negative probes that must fail **with the expected message** (`tests/host/ExpectFailure.cmake`):
`logic_rejects_windows_h_compile` ("'windows.h' file not found") and `logic_rejects_forbidden_includes_lint`
("Forbidden includes", over the fixtures in `tests/host/negative/lint_fixture/`). A broken toolchain or a missing
target does not count as the expected failure.

## Host tests

doctest 2.5.3, one main (`tests/host/main.cpp`). Put tests in `tests/host/<area>/test_*.cpp` or
`src/<area>/tests/**/*.cpp`. `ctest --preset host` runs `host_tests` plus the header and lint checks.
Sample: `tests/host/core/test_flhash.cpp` tests `src/logic/core/flhash.hpp` (`flmod::logic::create_id`, the
engine's CreateID) against five values the engine produced. (`tests/host/core/` becomes W1-CORE's area.)

## CI stages (`harness/ci.d/`, protocol in `harness/ci.d/README.md`)

`harness/ci.sh` runs each stage with cwd = `CI_REPO_ROOT` (the tree under test) and `CI_MODE`, `CI_LANES`,
`CI_RUNDIR`, `CI_REPO_ROOT`, `CI_STAGE` set. Each stage builds and tests `CI_REPO_ROOT`, writes its artifacts to
`$CI_RUNDIR/<NN>-<name>/`, prints one `CI <name>: PASS|FAIL|SKIP (<reason>)` line and exits 0 / 1 / 77. Run
standalone (no `CI_RUNDIR`), a stage writes to `$FLMOD_TESTRUNS/<UTC stamp>-ci-<name>/` and tests the tree it
lives in.

| Stage | Does | SKIPs (exit 77) when |
|---|---|---|
| `10-build.sh` | configure + build `host` and the win32 preset(s): `FLMOD_TRACK=A\|B` picks one; unset builds both | cmake/ninja/clang or the vendor tree is missing; win32 part skipped (noted) without clang-cl/XWIN_ROOT, Track A without the FLUF vendor tree |
| `20-host-tests.sh` | `ctest --preset host`; with `CI_MODE=full` also `host-asan` | same prerequisites |
| `50-import-check.sh` | `check_imports.py` over the binaries listed in `build/win32-track*/flmod_binaries.txt` (`--allow-fluf` for Track A); a listed but missing binary is a FAIL | no win32 build output, no `llvm-readobj`, or no prefix (`FLMOD_IMPORT_CHECK_PREFIX`, default the play prefix, read-only) |

## check_imports.py

`$FLMOD_VENV/bin/python -I toolchain/check_imports.py <bin>... --prefix <wineprefix> [--allow-fluf]
[--fluf-dll P] [--game-exe-dir D] [--json out.json]`. Fails when a binary is not PE32 i386, imports a module
(directly or **delay-loaded**) outside the allowlist (Freelancer DLLs, FLUF.dll with `--allow-fluf`,
`msvcp140*`/`vcruntime140*`/`api-ms-win-crt-*`, and `kernel32 user32 gdi32 advapi32 ws2_32 d3d9 dsound ole32
oleaut32 shell32 winmm version psapi dbghelp`), imports any `msvcp140*`/`vcruntime140*` DLL that the prefix's
`syswow64` does not have (e.g. `msvcp140d.dll`), or imports a symbol missing from: the prefix's
`syswow64/msvcp140*.dll` / `vcruntime140*.dll`; `syswow64/ucrtbase.dll` for `api-ms-win-crt-*` (Wine's apisetschema
maps them there); the game's `Common.dll` etc.; FLUF.dll. Tests (the delay-import fixture is real llvm-readobj
22 output):
`$FLMOD_VENV/bin/python -I -m pytest toolchain/tests -q`.

## Load proof and EH probe (Wine, no game)

- `toolchain/load_proof.sh <win32-trackB build dir> [--clone <prefix-dev-name>] [--keep] [--crt builtin|native|both]`:
  refuses unless the play prefix is idle (`tools/play_prefix_busy.sh`), reflink-clones it to
  `/home/user/freelancer/<clone>` (name must start with `prefix-dev`; use a unique name for concurrent runs),
  runs `loadtest.exe hello_b.dll FlmodSelfTest` (expects `CreateID(li02)=2745692751`), then the EH probe, then
  `wineserver -k` for that clone only and deletes it. Output: `$FLMOD_TESTRUNS/<stamp>-toolchain-loadproof/`.
- `toolchain/ehprobe.sh --build <win32 build dir> (--prefix <prefix-dev*/prefix-lane*> | --clone <prefix-dev-name>)
  [--crt builtin|native|both] [--run-dir D]`: runs every case of `ehprobe_cases.tsv` (`src/module/ehprobe/`) in its
  own `loadtest.exe` process and prints `EHPROBE crt=… case=… status=PASS|KNOWN-BROKEN|FAIL …` lines plus a summary.
  Exit 0 = no FAIL, 1 = FAIL, 77 = prerequisites missing. With `--prefix` it uses a scratch dir inside that prefix,
  removes it afterwards and never kills the prefix's wineserver (a lane may be running the game). `--crt native`
  copies MSVC's 14.51 redist DLLs (`$FLMOD_VENDOR/msvc-redist/x86`) next to the exe. Expected today: 24 PASS,
  3 KNOWN-BROKEN, 0 FAIL per runtime, on both tracks. What the KNOWN-BROKEN cases mean: `ABI.md` §6.

Neither creates a D3D device, so the renderer (DXVK or wined3d) plays no part.

## Gotchas found here

- **Wine drops a console app's stdout when it is redirected to a regular file.** Pipe it instead
  (`wine app.exe | cat > out.txt`); ptys and Windows-side redirects also work. Details: `NOTES.md` "Bug 1".
- **The play prefix (and every clone of it) has `DllOverrides` `msvcp140*`, `vcruntime140*`, `concrt140`,
  `ucrtbase` = `native,builtin`, while `syswow64` holds Wine's builtins.** So a `vcruntime140.dll`/`msvcp140.dll`
  dropped next to `Freelancer.exe` switches the whole process to that native runtime with no environment variable
  (VERIFIED with `WINEDEBUG=+loaddll`, `NOTES.md` "Question 3"). Never leave CRT DLLs in a lane's EXE dir by
  accident; `WINEDLLOVERRIDES=vcruntime140,msvcp140=b` forces the builtins back.
- A FLUF module cannot be loaded by `loadtest.exe` outside the game: FLUF.dll's `DllMain` builds the whole
  framework and the process exits (code 5). Test FLUF modules in game (P0-TRACK-A).
- CMake's Windows platform module appends `/EHsc`; `clang-cl-i686-overrides.cmake` replaces it with `/EHa`.
- `llvm-rc` does not understand `/winsysroot`; use `flmod_rc_includes()` for `.rc` files.
- Don't use FLUF's `profiles/` or `module_tools/` (hardcoded `/usr/bin` tools, msvc-wine layout, stale shims).
