# P0-TOOLCHAIN: MSVC-ABI cross toolchain, vendor pins, host test build, import checker

- **Type:** impl
- **Wave:** Phase 0
- **Depends on:** — → **Unblocks:** P0-TRACK-A, P0-TRACK-B, every C++ package.

## Goal

Build 32-bit Windows DLLs on this Gentoo host (no MSVC, no Windows) that are ABI-compatible with Freelancer and, for Track A, with the pinned FLUF build. Also build the same engine-free C++ (`src/logic/`) natively on Linux for fast unit tests. All third-party inputs are pinned and reproducible. A checker proves every built DLL only imports what Wine-proton 11 provides.

## Requirements

- **REQ-P0-TOOLCHAIN-1: MSVC CRT/STL + Windows SDK via xwin.**
  - Install with `cargo install xwin --locked` (to `~/.cargo/bin`).
  - Splat x86 to **`$XWIN_ROOT` (`/home/user/opt/xwin`, CONVENTIONS §1)**. Verify the exact flags with `xwin --help` and `xwin splat --help`; the R1 §5.3 step 1 flags (`--use-winsysroot-style`, `--preserve-ms-arch-notation`, `--arch x86`) are UNVERIFIED. Accepting the Microsoft license (`--accept-license`) is pre-authorized (AUTONOMY §1).
  - Record the MSVC CRT version and SDK version that xwin downloaded in `toolchain/PINS.md`.
  - **Fallback**, if xwin fails or lacks x86 pieces: mstorsjo/msvc-wine `vsdownload.py --accept-license --architecture x86 --dest ~/opt/msvc`. It needs `msiextract` (msitools). sudo is granted, so try `sudo emerge --ask=n app-arch/msitools` if a package exists (check `eix msitools` / `emerge -s msitools`); otherwise build msitools from source under `~/opt`. Log every sudo command in your report (the orchestrator records it in DECISIONS).
- **REQ-P0-TOOLCHAIN-2: `toolchain/clang-cl-i686.cmake`.**
  - System and tools:
    - `CMAKE_SYSTEM_NAME Windows`, `CMAKE_SYSTEM_PROCESSOR x86`
    - C/CXX compiler `/usr/lib/llvm/22/bin/clang-cl`, target `i686-pc-windows-msvc`
    - linker `lld-link` (`CMAKE_LINKER_TYPE LLD` or an explicit `CMAKE_LINKER`)
    - `CMAKE_RC_COMPILER /usr/lib/llvm/22/bin/llvm-rc`, `CMAKE_AR llvm-lib`, `CMAKE_MT llvm-mt`
    - `CMAKE_MSVC_RUNTIME_LIBRARY MultiThreadedDLL` (**/MD, release CRT**)
  - Compile flags: `/EHa /Z7 -gdwarf /utf-8 /permissive- -Wno-microsoft-cast -Wno-cast-function-type-mismatch`, plus `/winsysroot $XWIN_ROOT` (or `/vctoolsdir`+`/winsdkdir`, depending on the splat layout). Read `XWIN_ROOT` from the environment, with `/home/user/opt/xwin` as the default.
  - C++ standard 23 (clang-cl emits `/std:c++latest`; that's fine, FLUF CI does the same — R1 §5.3 unknowns).
  - Link flags: `/SAFESEH:NO /INCREMENTAL:NO /OPT:REF /OPT:ICF /DEBUG:DWARF` (or `/DEBUG` plus DWARF, whatever lld-link 22 accepts; verify).
  - `_ITERATOR_DEBUG_LEVEL=0`. Release CRT only; never `/MDd`.
  - **Do not use** FLUF's `profiles/` or `module_tools/` as-is: they hardcode `/usr/bin` tool paths and the msvc-wine layout, and `module_tools` is stale (R1 §5.1 "Bugs that hit this host", §8.11 VERIFIED).
- **REQ-P0-TOOLCHAIN-3: `toolchain/host.cmake`.** Native Linux clang++ (`/usr/lib/llvm/22/bin/clang++`) with C++23, `-Wall -Wextra -Werror=return-type`, ASan and UBSan in a `host-asan` preset.
  - `src/logic/**` must compile both here and with clang-cl. CMake must enforce that `src/logic` never includes Windows or FL headers: a test target compiles every `src/logic` header standalone on the host.
- **REQ-P0-TOOLCHAIN-4: root `CMakeLists.txt` + `CMakePresets.json`.**
  - Presets: `win32-trackA`, `win32-trackB`, `host`, `host-asan`.
  - Option `FLMOD_TRACK=A|B` selects platform libraries.
  - Targets:
    - `logic` (static lib from `src/logic`; empty placeholder for now);
    - `hello_a` (FLUF module DLL, Track A);
    - `hello_b` (plain dacom DLL, Track B);
    - `loadtest` (a tiny win32 console exe);
    - `host_tests` (doctest).
  - Output DLLs go to `build/<preset>/out/`.
- **REQ-P0-TOOLCHAIN-5: pinned vendor inputs**, fetched or extracted by `toolchain/fetch_vendor.sh` into **`$FLMOD_VENDOR` (`/home/user/freelancer/carrier-mod/vendor`, absolute, gitignored)**. This is one shared tree, read-only for every other package and worktree (CONVENTIONS §1).
  - CMake locates it via `FLMOD_VENDOR` (env or cache variable), never a relative `$FLMOD_VENDOR/`, because worktrees don't have it.
  - Write sha256s and versions to `toolchain/PINS.md` (committed).
  - Each input must be re-runnable offline from `/home/user/freelancer/refs` where possible.

  | Input | Pin | Source | Notes |
  |---|---|---|---|
  | FLUF nightly | `nightly-2026-10-16-03-03`, FLUF commit `627ea2c` (R1 §5.3 step 0, VERIFIED) | `/home/user/freelancer/refs/FLUF-release-nightly-2026-10-16/FLUF.tar.xz` → `$FLMOD_VENDOR/FLUF/` (`development/include`, `development/lib`, `EXE`, `DATA`) | |
  | FLUF stable 2.0 (fallback only) | `stable-2026-03-28-18-16` | `/home/user/freelancer/refs/FLUF-release-stable-2026-03-28/FLUF.tar.xz` → `$FLMOD_VENDOR/FLUF-stable/` | |
  | FLSDK | `ae8c85781e06dfe3b23546822d67bb07767670cd` (R1 §2.5, VERIFIED) | `/home/user/freelancer/refs/FLUF/vendor/FLSDK` (check `git -C … rev-parse HEAD`; if it isn't that commit, clone `https://codeberg.org/TheStarport/FLSDK` at it) | Headers `include/FLCore/*`, import libs `lib/FLCoreCommon.lib`, `FLCoreServer.lib`, `FLCoreDALib.lib`, `FLCoreDACom.lib`, `FLCoreRemoteClient.lib`, `FLCoreFLServerEXE.lib` (VERIFIED present). License: none found in the tree (`README.md` has no license line; VERIFIED 2026-10-17). Use the headers and libs as build inputs only; don't vendor them into the public repo (`$FLMOD_VENDOR/` is gitignored). |
  | reflect-cpp | `6bba1e2…` (full SHA from `git -C /home/user/freelancer/refs/FLUF submodule status`) | `https://github.com/getml/reflect-cpp` | Track A only (exported FLUF signatures use rfl types — R1 §5.3 step 6) |
  | magic_enum | v0.9.8 | — | FLSDK's CMake downloads it at configure time (R1 §2.5); pre-fetch it so configure works offline |
  | Dear ImGui | latest stable tag ≥ v1.91, docking branch or tag, MIT | — | **Track B only.** Track A must use FLUF's exported ImGui |
  | MinHook | latest tag, BSD-2 | — | Track B detours |
  | doctest | latest tag, MIT | — | the host test framework (CONVENTIONS §3) |
  | nlohmann/json | v3.11.x single header, MIT | — | **The** JSON library for all our C++ on both tracks (CONVENTIONS §3). Track A uses reflect-cpp only where FLUF's exported API requires rfl types. |
- **REQ-P0-TOOLCHAIN-6: Track A ABI must-match list** (R1 §5.3 step 4 and §5.4, VERIFIED from FLUF `cmake/Utils.cmake:76-97` and `profiles/linux*`). Encode it in a CMake function `flmod_fluf_module(<target>)`.
  - **Defines:** `WIN32 WIN32_LEAN_AND_MEAN UNICODE _UNICODE NOMINMAX _CRT_SECURE_NO_WARNINGS _SILENCE_CXX17_CODECVT_HEADER_DEPRECATION_WARNING WINVER=0x0A00 _WIN32_WINNT=0x0A00 FLUF_SDK YAML_CPP_STATIC_DEFINE IMGUI_DEFINE_MATH_OPERATORS IMGUI_ENABLE_FREETYPE IMGUI_USE_STB_SPRINTF IMGUI_USE_WCHAR32 "IMGUI_API=__declspec(dllimport)" "IMPLOT_API=__declspec(dllimport)" "STBIDEF=__declspec(dllimport)"`.
  - **Never define `FLUF`** (that flips `FLUF_API` to dllexport).
  - **Include dirs:** `$FLMOD_VENDOR/FLUF/development/include`, `…/include/FLUF`, `…/include/imgui`, `…/include/imcp`, `…/include/yaml-cpp`, `…/include/msgpack-c`, `…/include/zstd`, `$FLMOD_VENDOR/FLSDK/include`, `$FLMOD_VENDOR/reflect-cpp/include`, `$FLMOD_VENDOR/reflect-cpp/include/rfl/thirdparty`.
  - **reflect-cpp:** build as a static lib with the same compiler and `REFLECTCPP_YAML=ON REFLECTCPP_MSGPACK=ON REFLECTCPP_BUILD_SHARED=OFF REFLECTCPP_USE_STD_EXPECTED=ON`. Feed its `find_package(yaml-cpp)` / `find_package(msgpack-c)` with shims pointing at `development/include` + `development/lib/yaml-cpp.lib` and `msgpack-c.lib`. The old `module_tools/cmake/*-config.cmake` shims assume a `dependencies/` directory that this release lacks (R1 §5.3 step 6, VERIFIED).
  - **Link:** `$FLMOD_VENDOR/FLUF/development/lib/FLUF.lib`, `FreelancerSDK.lib`, the FLSDK `FLCoreCommon.lib FLCoreServer.lib FLCoreDALib.lib FLCoreDACom.lib` (+ `FLCoreRemoteClient.lib`), reflectcpp, `yaml-cpp.lib`, `msgpack-c.lib`, `zstd_static.lib` (FlufPayload inlines ZSTD), `dsound.lib ws2_32.lib dxguid.lib`.
  - **Module export:** `SETUP_MODULE(Name, ModuleMajorVersion::Two, ModuleMinorVersion::Zero)` hard-codes `/EXPORT:ModuleFactory=?ModuleFactory@@YA?AV?$shared_ptr@VFlufModule@@@std@@XZ` (`FlufModule.hpp:191-206`; clang-cl mangles identically — R1 §5.4).
- **REQ-P0-TOOLCHAIN-7: Track B linking.** Plain FLSDK headers and import libs (`FLCoreCommon.lib`, `FLCoreServer.lib`, `FLCoreDALib.lib`, `FLCoreDACom.lib`, `FLCoreRemoteClient.lib`), plus static MinHook and static ImGui (`IMGUI_API` empty). No FLUF anything. Also `d3d9.lib dxguid.lib user32.lib`.
  - Common.dll and Freelancer.exe are VC6-era (linker 6.24, **MSVCP60** + MSVCRT, R4 §B9 VERIFIED). Anything crossing the Common.dll boundary must use FLSDK `st6::` containers (malloc/free resolved from `msvcrt.dll`). Add a short doc `toolchain/ABI.md` stating this rule with the FLSDK `st6.h` path.
  - **mingw is not allowed** for module code (R4 §B9: name mangling, vtables, EH and SEH incompatible).
- **REQ-P0-TOOLCHAIN-8: `toolchain/check_imports.py <dll>... --prefix <wineprefix>`** (python3 -I, uses `llvm-readobj --coff-imports` / `--coff-exports` from `/usr/lib/llvm/22/bin`).
  - Fails if a DLL imports any module outside the allowlist: Freelancer's own DLLs (`common.dll server.dll dalib.dll dacom.dll remoteclient.dll rp8.dll`, FLUF.dll for Track A), MSVC runtime (`msvcp140*.dll vcruntime140*.dll api-ms-win-crt-*.dll`), and Win32 system DLLs (`kernel32 user32 gdi32 advapi32 ws2_32 d3d9 dsound ole32 oleaut32 shell32 winmm version psapi dbghelp`).
  - Fails if any imported symbol from `msvcp140.dll`, `vcruntime140.dll` or `msvcp140_atomic_wait.dll` is missing from the export table of that DLL in `<prefix>/drive_c/windows/syswow64/`. Wine builtins; R1 §7 and R4 §B9 VERIFIED 159/159, 27/27, 2/2 for the FLUF nightly.
  - Prints a summary table.
- **REQ-P0-TOOLCHAIN-9: hello targets.**
  - `hello_b.dll` (Track B shape):
    - `DllMain` only calls `DisableThreadLibraryCalls`.
    - An exported `extern "C" __declspec(dllexport) int FlmodSelfTest()` calls `CreateID("li02")` from Common.dll and writes `hello_b CreateID(li02)=<n>` to `hello_b.log` in the current directory.
    - Expected value `2745692751`, per R3 §10 (VERIFIED: matches `newplayer.fl`; `CreateID` is case-insensitive).
  - `hello_a.dll` (Track A shape): a minimal `FlufCombinedModule` that logs `INFO("hello_a loaded CreateID(li02)={}", CreateID("li02"))` in `OnApplicationStart`, using the R1 §9.1 skeleton.
  - `loadtest.exe <dll> [export]`: `LoadLibraryA`, `GetProcAddress`, call the export, print the result and exit code.
- **REQ-P0-TOOLCHAIN-10: runtime load proof without running the game.**
  - Make a throwaway clone `prefix-dev-toolchain` (allowed pattern): `cp -a --reflink=always /home/user/freelancer/prefix /home/user/freelancer/prefix-dev-toolchain`, only while the play prefix is idle (`tools/play_prefix_busy.sh` exits 1).
  - Copy `loadtest.exe` and `hello_b.dll` into its `drive_c/Games/Freelancer HD Edition/EXE/`.
  - Run, with `cwd` = that EXE dir: `source tools/env.sh; WINEPREFIX=/home/user/freelancer/prefix-dev-toolchain wine loadtest.exe hello_b.dll FlmodSelfTest`.
  - Expect `CreateID(li02)=2745692751`. Then `wineserver -k` for that prefix and delete the clone.
- **REQ-P0-TOOLCHAIN-11: host test scaffold.** `tests/host/` with doctest main, plus one sample test of a pure function in `src/logic/core/` (e.g. an FL `CreateID` port, golden-tested against the 5 VERIFIED hashes in R3 §10). `ctest` runs it.
- **REQ-P0-TOOLCHAIN-12:** add the CI drop-ins this package owns, per CONVENTIONS §5 and the P0-REPO protocol:
  - `harness/ci.d/10-build.sh`: configure and build `host` and the `win32` preset of the chosen or available track;
  - `harness/ci.d/20-host-tests.sh`: ctest;
  - `harness/ci.d/50-import-check.sh`: `check_imports.py` over every built DLL.

  Each exits 77 (SKIP) when its prerequisites are absent. If P0-REPO hasn't merged yet, create the files anyway (same paths); the orchestrator reconciles at merge.

## Context pack

- `/home/user/freelancer/carrier-mod/CLAUDE.md`
- `/home/user/freelancer/carrier-mod/docs/plan/CONVENTIONS.md` §1 (paths), §3 (JSON lib, doctest), §5 (CI), §14 (ownership), §15 (wine safety)
- `$FLMOD_RESEARCH/R1-fluf.md` §5 (Build: entire section) and §9.1 (module skeleton)
- `$FLMOD_RESEARCH/R4-lore-and-testloop.md` §B9 (ABI facts, mingw rejection, xwin/msvc-wine options, CRT under Wine)
- `$FLMOD_RESEARCH/R5-sp-architecture.md` §2: two entry points (dacom `[Libraries]` DLL vs `[Initial SP DLLs]`)
- `/home/user/freelancer/refs/FLUF/cmake/Utils.cmake`, `/home/user/freelancer/refs/FLUF/profiles/clang-cl-linux.cmake`, `/home/user/freelancer/refs/FLUF/profiles/linux-clang`: reference for flags only
- `/home/user/freelancer/refs/FLUF/vendor/FLSDK/` (`CMakeLists.txt`, `include/FLCore/st6.h`, `lib/`)
- `/home/user/freelancer/refs/FLUF/modules/autobuy/`: a small real module, for the `hello_a` structure
- `/home/user/freelancer/refs/FLUF-release-nightly-2026-10-16/listing.txt`: release contents (VERIFIED: `development/lib/FLUF.lib`, `FreelancerSDK.lib`, module libs, `EXE/fluf/*`)

## Ownership

- **Owns:** `toolchain/`, root `CMakeLists.txt`, `CMakePresets.json` and `cmake/` (handed to ARCH-0 afterwards; CONVENTIONS §14), the contents of `$FLMOD_VENDOR` (gitignored; the only writer), the `tests/host/` scaffold, `src/logic/core/flhash.{hpp,cpp}` (sample), `src/module/hello_a/`, `src/module/hello_b/`, `src/module/loadtest/`, and `harness/ci.d/{10-build,20-host-tests,50-import-check}.sh`.
- **Reads:** refs, research, the play prefix (read-only, only to clone).
- **Must not touch:** the play prefix, `~/.wine`, `docs/plan/`, `state/`, `tools/` scripts and guards (orchestrator-owned).

## Contract

- **Provides:**
  - CMake presets and toolchain files;
  - the `flmod_fluf_module()` and `flmod_dacom_dll()` CMake functions;
  - the `logic` library target convention;
  - `check_imports.py`, `fetch_vendor.sh`, `PINS.md`, `ABI.md`.
- **Consumes:** —

## Tasks

1. Verify the tools: `/usr/lib/llvm/22/bin/{clang-cl,lld-link,llvm-rc,llvm-lib,llvm-mt,llvm-readobj} --version`, `cmake --version`, `ninja --version`, `cargo --version`.
2. Install xwin and splat (REQ-1). Find `vcruntime.h`, `windows.h`, `d3d9.h`, `msvcprt.lib` / `msvcrt.lib` (x86) in the splat and record their paths.
3. Write `fetch_vendor.sh` and run it. Record sha256s.
4. Write the toolchain files, the root CMake and the presets.
5. Build `hello_b`, `loadtest` and `host_tests`. Run `ctest`. Run `check_imports.py` on `hello_b.dll` against the play prefix's `syswow64` (read-only access is fine).
6. Run REQ-10's runtime load proof.
7. Build `hello_a` against the FLUF dev package. Run `check_imports.py` with FLUF.dll allowed. Confirm with `llvm-readobj --coff-exports hello_a.dll` that `GetMajorVersion`, `GetMinorVersion` and `ModuleFactory` are exported (R1 §5.3 step 8).
8. Write `toolchain/README.md`: exact commands to rebuild from scratch on this host.

## Acceptance (automated; attach evidence)

- `cmake --preset host && cmake --build --preset host && ctest --preset host`: all pass, including the 5 golden CreateID values (`Li01_to_Li02`→2830511361, `Ew06_01_Base`→3094908802, `Li02`→2745692751, `ew0601_monkey_003_m`→2318074572, `Br05`→2945937410; R3 §10 VERIFIED).
- `cmake --preset win32-trackB && cmake --build …` produces `hello_b.dll` and `loadtest.exe` (PE32, `machine: x86` — show `llvm-readobj --file-headers`).
- `check_imports.py hello_b.dll --prefix /home/user/freelancer/prefix` → PASS.
- The runtime load proof prints `CreateID(li02)=2745692751`. Attach the console output.
- `cmake --preset win32-trackA` builds `hello_a.dll`; it exports `GetMajorVersion`, `GetMinorVersion`, `ModuleFactory`; `check_imports.py` → PASS (FLUF.dll allowed).
- `tests/host` contains a standalone-header test proving `src/logic` headers compile without Windows headers.
- **Negative test:** a deliberately bad target that includes `<windows.h>` from `src/logic` makes the host build fail. Show that, then remove it.

## Engine facts to rely on / verify

- VERIFIED (R4 §B9): FL binaries are VC6 linker 6.24 and import MSVCP60 + MSVCRT, which are Wine builtins in this prefix.
- VERIFIED (R1 §7): Wine-proton 11 builtin msvcp140, vcruntime140 and msvcp140_atomic_wait export every symbol the FLUF nightly imports.
- UNVERIFIED: whether clang-cl 22 plus the xwin STL version builds FLUF's headers cleanly, and whether newer STL headers import msvcp140 symbols Wine lacks. The import checker settles the second.

## Pitfalls

- FLUF CI's `clang-cl-linux.cmake` has a copy-paste bug (`llvm-rc-22` sets `-21`) and hard-fails without `/usr/bin/llvm-rc`; don't use it.
- `CMAKE_CXX_STANDARD 23` with clang-cl may emit `/std:c++latest`; that's fine.
- Case sensitivity: xwin creates case-folding symlinks, but some SDK headers include `Windows.h` vs `windows.h` inconsistently. If includes fail, generate a clang `-vfsoverlay` like FLUF's `scripts/clang_linux.py` does (R1 §5.1).
- Never use `/MDd` or debug iterators (`_ITERATOR_DEBUG_LEVEL` must be 0, to match FLUF).
- Never run wine without an allowed `WINEPREFIX` (`~/.wine` incident, R4 Incidents). The guards in `tools/bin/` exist (VERIFIED). Always `source tools/env.sh` and call `wine`/`wineserver` through them. **Never call `/usr/lib/wine-proton-11.0.1/bin/*` or `/etc/eselect/wine/bin/*` directly** (CONVENTIONS §15).

## Fallbacks and degrade path

1. If xwin fails, use msvc-wine `vsdownload.py` (+ msitools via emerge or source).
2. If clang-cl can't compile FLUF headers, try the FLUF stable 2.0 package headers. If those also fail, Track A is blocked at the toolchain level: report `RESULT: PARTIAL` with the exact errors. G0a then treats Track A as failing build items. **Track B must not be blocked by Track A issues.**

## Report

AGENT_BRIEF_TEMPLATE format. Include `PINS.md` content, the splat paths, the exact preset commands, and import-check output for both hello DLLs.

## Gate-time addendum

(Orchestrator: attempt number, commit trailer.)
