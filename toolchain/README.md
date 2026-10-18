# Toolchain: building the mod on this Gentoo host

32-bit Windows DLLs for Freelancer are cross-built on Linux with **clang-cl 22 + lld-link + llvm-rc** against the
MSVC CRT/STL and Windows SDK fetched by **xwin** (no MSVC, no Windows, no Wine in the build loop). The engine-free
code in `src/logic/` also builds natively with clang++ for fast host tests. Everything third-party is pinned
(`PINS.md`). ABI rules: `ABI.md`.

## From scratch

```bash
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
python3 -I toolchain/check_imports.py build/win32-trackB/out/*.dll build/win32-trackB/out/*.exe --prefix /home/user/freelancer/prefix
python3 -I toolchain/check_imports.py build/win32-trackA/out/*.dll --prefix /home/user/freelancer/prefix --allow-fluf
# 5. Runtime load proof in a throwaway prefix clone (prefix-dev-toolchain; created and deleted)
toolchain/load_proof.sh build/win32-trackB
```

Only P0-TOOLCHAIN (later: whoever owns `toolchain/`) runs steps 1–2; they write the shared trees. Everyone else
just builds. Worktrees have no `vendor/`; CMake finds it through `FLMOD_VENDOR` (env or cache variable, default
`/home/user/freelancer/carrier-mod/vendor`) and the SDK through `XWIN_ROOT` (default `/home/user/opt/xwin`).

## Presets

| Preset | Toolchain file | What it builds | Output |
|---|---|---|---|
| `host` | `toolchain/host.cmake` (clang++ 22, C++23, `-Wall -Wextra -Werror=return-type`, RelWithDebInfo) | `logic`, `logic_header_check`, `host_tests` | `build/host/out/host_tests` |
| `host-asan` | same + `FLMOD_SANITIZE=ON` (ASan + UBSan, Debug) | same | `build/host-asan/out/` |
| `win32-trackA` | `toolchain/clang-cl-i686.cmake`, `FLMOD_TRACK=A`, Release | `logic`, `loadtest.exe`, `hello_a.dll`, Track A modules/spikes | `build/win32-trackA/out/` |
| `win32-trackB` | `toolchain/clang-cl-i686.cmake`, `FLMOD_TRACK=B`, Release | `logic`, `loadtest.exe`, `hello_b.dll`, Track B DLLs/spikes | `build/win32-trackB/out/` |

Build presets and test presets (`host`, `host-asan`) have the same names. Each worktree builds into its own
`build/`.

win32 compile flags (all targets): `--target=i686-pc-windows-msvc /winsysroot $XWIN_ROOT /MD /EHa /Z7 -gdwarf
/utf-8 /permissive- -D_ITERATOR_DEBUG_LEVEL=0 -Wno-microsoft-cast -Wno-cast-function-type-mismatch /O2`, C++23
(`-std=c++23`). Link: `/winsysroot:$XWIN_ROOT /SAFESEH:NO /INCREMENTAL:NO /OPT:REF /OPT:ICF /DEBUG:DWARF
/machine:X86`. DLLs carry DWARF for `winedbg --gdb`; they are larger than a stripped build (hello_a.dll ≈ 1.6 MB).

## Adding a target (spikes, modules, tools)

The root `CMakeLists.txt` discovers directories by glob, so packages never edit it:

| Put a `CMakeLists.txt` in | It is added in |
|---|---|
| `src/module/<name>/` | every build (guard it, see below) |
| `spikes/<id>/` | every build (guard it) |
| `harness/devbridge/` | every build (guard it) |

Sources are discovered too: `src/logic/**/*.cpp` → `logic`; `tests/host/**/*.cpp` and `src/**/tests/*.cpp` →
`host_tests`. (Re-run `cmake --preset …` after adding files; `CONFIGURE_DEPENDS` usually does it for you.)

Guards and helpers (`cmake/FlmodFunctions.cmake`):

| Call | Effect |
|---|---|
| `flmod_track_only(A)` / `flmod_track_only(B)` | skip the rest of this CMakeLists.txt unless it is a win32 build of that track |
| `flmod_win32_only()` / `flmod_host_only()` | skip in host / win32 builds |
| `flmod_fluf_module(<t>)` | Track A FLUF module: full FLUF must-match define set, include dirs, `FLUF.lib`, `FreelancerSDK.lib`, FLSDK import libs, reflectcpp (FLUF's commit, built static with our compiler), `yaml-cpp.lib`, `msgpack-c.lib`, `zstd_static.lib`, `dsound ws2_32 dxguid`. Never define `FLUF`. Your `.cpp` ends with `SETUP_MODULE(Type, ModuleMajorVersion::Two, ModuleMinorVersion::Zero);` |
| `flmod_dacom_dll(<t>)` | plain dacom-style DLL: FLSDK headers + `FLCoreCommon/Server/DALib/DACom/RemoteClient.lib`, static MinHook (`flmod::minhook`), static Dear ImGui with dx9 + win32 backends in Track B (`flmod::imgui_static`, `IMGUI_API` empty, no IME), `d3d9 dxguid user32`. No FLUF. |
| `flmod_win32_exe(<t>)` | win32 console tool in `out/` |
| `flmod_rc_includes(<t>)` | lets `.rc` files include `<winres.h>` / `<windows.h>` |
| `flmod_host_tests(SOURCES … LIBS …)` | add doctest files outside the auto-globbed dirs to `host_tests` |

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

Every DLL/EXE ends up in `build/<preset>/out/` and is import-checked by CI stage 50.

## The `src/logic` rule

`src/logic/` is engine-free: no Windows, Freelancer, FLUF, ImGui or MinHook headers. Two mechanisms enforce it:

1. `cmake/LogicIncludeLint.cmake` runs in every build (host and win32) and fails it on a forbidden `#include`.
2. Host builds compile every `src/logic` header on its own, twice, with only `src/` and nlohmann/json on the
   include path (`tests/host/LogicHeaderCheck.cmake`, target `logic_header_check`, ctest
   `logic_headers_standalone`).

ctest also runs negative probes that must fail (`logic_rejects_windows_h_compile`, `logic_rejects_windows_h_lint`).

## Host tests

doctest 2.5.3, one main (`tests/host/main.cpp`). Put tests in `tests/host/<area>/test_*.cpp` or
`src/<area>/tests/*.cpp`. `ctest --preset host` runs `host_tests` plus the header and lint checks.
Sample: `tests/host/core/test_flhash.cpp` tests `src/logic/core/flhash.hpp` (`flmod::logic::create_id`, the
engine's CreateID) against five values the engine produced.

## CI stages (`harness/ci.d/`, protocol in `harness/ci.d/README.md`)

| Stage | Does | SKIPs (exit 77) when |
|---|---|---|
| `10-build.sh` | configure + build `host` and the win32 preset(s): `FLMOD_TRACK=A\|B` picks one; unset builds both | cmake/ninja/clang or the vendor tree is missing; win32 part skipped (noted) without clang-cl/XWIN_ROOT |
| `20-host-tests.sh` | `ctest --preset host`; with `CI_MODE=full` also `host-asan` | same prerequisites |
| `50-import-check.sh` | `check_imports.py` over `build/win32-track*/out/*.{dll,exe}` (`--allow-fluf` for Track A) | no win32 output, no `llvm-readobj`, or no prefix (`FLMOD_IMPORT_CHECK_PREFIX`, default the play prefix, read-only) |

Logs and JSON go to `$CI_RUNDIR`.

## check_imports.py

`python3 -I toolchain/check_imports.py <bin>... --prefix <wineprefix> [--allow-fluf] [--fluf-dll P]
[--game-exe-dir D] [--json out.json]`. Fails when a binary is not PE32 i386, imports a module outside the
allowlist (Freelancer DLLs, FLUF.dll with `--allow-fluf`, `msvcp140*`/`vcruntime140*`/`api-ms-win-crt-*`, and
`kernel32 user32 gdi32 advapi32 ws2_32 d3d9 dsound ole32 oleaut32 shell32 winmm version psapi dbghelp`), or
imports a symbol missing from: the prefix's `syswow64/msvcp140*.dll` / `vcruntime140*.dll`; `syswow64/ucrtbase.dll`
for `api-ms-win-crt-*` (Wine's apisetschema maps them there); the game's `Common.dll` etc.; FLUF.dll. Tests:
`$FLMOD_VENV/bin/python -I -m pytest toolchain/tests -q`.

## Gotchas found here

- **Wine drops a console app's stdout when it is redirected to a regular file.** Pipe it instead
  (`wine app.exe | cat > out.txt`); ptys and Windows-side redirects also work. Details: `NOTES.md` "Bug 1".
- A FLUF module cannot be loaded by `loadtest.exe` outside the game: FLUF.dll's `DllMain` builds the whole
  framework and the process exits (code 5). Test FLUF modules in game (P0-TRACK-A).
- CMake's Windows platform module appends `/EHsc`; `clang-cl-i686-overrides.cmake` replaces it with `/EHa`.
- `llvm-rc` does not understand `/winsysroot`; use `flmod_rc_includes()` for `.rc` files.
- Don't use FLUF's `profiles/` or `module_tools/` (hardcoded `/usr/bin` tools, msvc-wine layout, stale shims).
