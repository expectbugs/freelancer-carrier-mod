# Pinned build inputs

Every third-party input of the C++ build, with the exact version and hash. Recorded 2026-10-17 by P0-TOOLCHAIN.
The scripts are the source of truth (`toolchain/fetch_vendor.sh` `PINS=(...)`, `toolchain/setup_xwin.sh`); keep
this file in sync when a pin moves. None of these files is committed: they live in `$FLMOD_VENDOR`
(`/home/user/freelancer/carrier-mod/vendor`, gitignored, shared by all worktrees) and `$XWIN_ROOT`
(`/home/user/opt/xwin`).

## Host tools (VERIFIED `--version`, 2026-10-17)

| Tool | Version | Path |
|---|---|---|
| clang-cl, clang, clang++ | 22.1.8 | `/usr/lib/llvm/22/bin/` |
| lld-link | LLD 22.1.8 | `/usr/lib/llvm/22/bin/lld-link` |
| llvm-rc, llvm-lib, llvm-mt, llvm-readobj | LLVM 22.1.8 | `/usr/lib/llvm/22/bin/` |
| cmake / ctest | 4.3.4 | `/usr/bin/` |
| ninja | 1.13.2 | `/usr/bin/ninja` |
| cargo | 1.97.1 (gentoo) | |
| xwin | 0.10.0 (`cargo install xwin --locked`) | `~/.cargo/bin/xwin` |

## MSVC CRT/STL + Windows SDK (xwin)

Splat command (run by `toolchain/setup_xwin.sh`):

```
xwin --accept-license --arch x86 --crt-version 14.51 --sdk-version 10.0.28000 \
     --cache-dir /home/user/opt/xwin-cache-18 --manifest /home/user/opt/xwin-cache-18/pinned/manifest_18.json \
     splat --use-winsysroot-style --preserve-ms-arch-notation --copy --output /home/user/opt/xwin
```

| Item | Value |
|---|---|
| VS channel manifest | `VisualStudio.18.Release/18.11.0+12306.390` (VS 2026 18.11.0), `manifest_18.json` sha256 `b526439707f8c93c8a59636849a9cf995d74bce9e75a9fe9845fd13baade4437`; pinned copy at `/home/user/opt/xwin-cache-18/pinned/manifest_18.json` |
| MSVC CRT/STL | **14.51.36231** (splat dir `VC/Tools/MSVC/14.51`), `_MSVC_STL_VERSION 145`, `_MSVC_STL_UPDATE 202604L` |
| Windows SDK | **10.0.28000** (Win11 SDK, Aug 2026 servicing) |
| Layout | `/winsysroot`: `$XWIN_ROOT/VC/Tools/MSVC/14.51/{include,lib/x86}`, `$XWIN_ROOT/Windows Kits/10/{Include,Lib}/10.0.28000/...`; xwin case symlinks on (`Windows.h`/`windows.h`, `Psapi.h`/`psapi.h`, `DSOUND.lib`/`dsound.lib`, ...) |

Why 14.51 and not the xwin default (manifest 17 = CRT 14.44): FLUF's prebuilt static libs
(`FreelancerSDK.lib`, `yaml-cpp.lib`, `msgpack-c.lib`, `zstd_static.lib`) carry `/FAILIFMISMATCH:"annotate_optional=0"`
and `/alternatename:__Avx2WmemEnabled=…`. `annotate_optional` exists in the 14.51 STL headers and not in 14.44,
so FLUF was built with a v145 (VS 2026) STL (VERIFIED by grep of both header sets, 2026-10-17). That our final
link *needs* an STL at least that new is UNVERIFIED: `/FAILIFMISMATCH` only fails on conflicting values, and no
14.44 link was tried. Matching FLUF's STL generation is the conservative choice.

Package hashes (cache `dl/`):

| Package | sha256 |
|---|---|
| Microsoft.VC.14.51.CRT.Headers.base.vsix | `e6d9cc5f0750cbc40a6b2468991c57ed0044fa2e242295a6d51bc02d72502b05` |
| Microsoft.VC.14.51.CRT.x86.Desktop.base.vsix | `89c26aad297f1fbf57094c29c33cb56cdf72e13a038db7ec88b63ceb751f9f05` |
| Microsoft.VC.14.51.CRT.x86.Store.base.vsix | `263a156aaf004505f44006ff161d96e16349ff53f5f295b5f7de7852ec4e2d6f` |
| ucrt.msi | `3b67e52e49a0ddd12536f04482cc0b6fb80672ee434532c16b2702b65e519a1a` |
| Win11SDK_10.0.28000_headers.msi | `db9eb6aaef919be38fa032b12d3bd00ebc8cd84988a1e28d3fd1a2990b64826d` |
| Win11SDK_10.0.28000_libs_x86.msi | `9b2270b048348d6c2a0cd838ff7010c029a26c0c4c17fcd6e4f2efbb501eeb5f` |
| Win11SDK_10.0.28000_store_headers.msi | `e24134999699e536b37f698223c5098c62497bd99ff996e53cb357010091fed9` |
| Win11SDK_10.0.28000_store_headers_onecoreuap.msi | `440fff00ece41c9ce126d4dc6f2be3970ea485aeec85896753682bd5b9647cbe` |
| Win11SDK_10.0.28000_store_libs.msi | `5b09fb2cce1a589edb0cabadc8b48bfb276b6be411cdec383015377dc08d6a25` |
| Win11SDK_10.0.28000_uap_headers.msi | `397a727ee6551a1e6b8e4a12922ca0a470c02e30ca05b5614063979741ee9092` |

Key files in the splat (VERIFIED present):

| File | Path under `$XWIN_ROOT` |
|---|---|
| `vcruntime.h` | `VC/Tools/MSVC/14.51/include/vcruntime.h` |
| `msvcrt.lib`, `msvcprt.lib`, `vcruntime.lib` (x86) | `VC/Tools/MSVC/14.51/lib/x86/` |
| `windows.h` (+ `Windows.h` symlink) | `Windows Kits/10/Include/10.0.28000/um/` |
| `d3d9.h` | `Windows Kits/10/Include/10.0.28000/shared/d3d9.h` |
| `ucrt.lib` (x86) | `Windows Kits/10/Lib/10.0.28000/ucrt/x86/` |
| `kernel32.lib`, `d3d9.lib`, `dsound.lib`, `dxguid.lib`, `ws2_32.lib` (x86) | `Windows Kits/10/Lib/10.0.28000/um/x86/` |

Re-running offline from the cache reproduces the splat byte for byte (VERIFIED: `setup_xwin.sh --offline` into a
temp root, `diff -rq` against the original showed only the `.flmod-pin` stamp).

## Vendor tree (`toolchain/fetch_vendor.sh` → `$FLMOD_VENDOR`)

| Name | Pin | Source | sha256 / commit | Dest |
|---|---|---|---|---|
| FLUF | `nightly-2026-10-16-03-03`, FLUF commit `627ea2c` | `/home/user/freelancer/refs/FLUF-release-nightly-2026-10-16/FLUF.tar.xz` (local); upstream release asset `https://codeberg.org/TheStarport/FLUF/releases/download/nightly-2026-10-16-03-03/FLUF.tar.xz` (used when the local file is missing) | `74a8147de6a957de67f910cc16b951e9047e68a8a848087168bd515f7ecd3a65` | `FLUF/` (`DATA`, `EXE`, `development`) |
| FLUF-stable (fallback only) | `stable-2026-03-28-18-16` | `/home/user/freelancer/refs/FLUF-release-stable-2026-03-28/FLUF.tar.xz` (local); upstream `https://codeberg.org/TheStarport/FLUF/releases/download/stable-2026-03-28-18-16/FLUF.tar.xz` | `bd5635f2bcaa625258d9a0f7867c3151c6f29017491d3c83524d7841d830b390` | `FLUF-stable/` |
| FLSDK | commit `ae8c85781e06dfe3b23546822d67bb07767670cd` | `git archive` of `/home/user/freelancer/refs/FLUF/vendor/FLSDK` (HEAD = that commit, VERIFIED); fallback clone `https://codeberg.org/TheStarport/FLSDK` | commit | `FLSDK/` |
| reflect-cpp | commit `6bba1e2c4fa8de704c88d3f1712c157bbb6edc23` (FLUF's submodule pin, VERIFIED `git submodule status`) | `https://github.com/getml/reflect-cpp/archive/6bba1e2c4fa8de704c88d3f1712c157bbb6edc23.tar.gz` | `b8310d97a85ff8d6edb1de81350562d5bb20ad6fc29836d342cd77f7b57d0056` | `reflect-cpp/` |
| magic_enum | v0.9.8 | `https://github.com/Neargye/magic_enum/releases/download/v0.9.8/magic_enum-v0.9.8.tar.gz` | `88709dc8a9697168a75e039470d73ed0cffbc17567976eb5e096f946a2c0d521` | `magic_enum/` |
| Dear ImGui (Track B) | `v1.92.9b-docking` (commit `b48d1afbe8ee8b238e2961dc363a949dd7304e23`) | `https://github.com/ocornut/imgui/archive/b48d1afbe8ee8b238e2961dc363a949dd7304e23.tar.gz` | `747c5a465a05c4ef5b4a09e2e0e3d0ce2bc76b31420f0f5af33df470907cf893` | `imgui/` |
| MinHook | v1.3.4 (commit `c3fcafdc10146beb5919319d0683e44e3c30d537`) | `https://github.com/TsudaKageyu/minhook/archive/c3fcafdc10146beb5919319d0683e44e3c30d537.tar.gz` | `31757833475be039c16359d4e276e718db6ba2ba61a6b870053a112106015822` | `minhook/` |
| doctest | v2.5.3 (commit `2d0a9359a60c51affe2a9bebb1be1dca47868151`) | `https://github.com/doctest/doctest/archive/2d0a9359a60c51affe2a9bebb1be1dca47868151.tar.gz` | `e64542c4ea68e9f381ccf6eae924cfdd652567c87c142d76fe92644fb4608149` | `doctest/` |
| nlohmann/json | v3.11.3 single header | `https://github.com/nlohmann/json/releases/download/v3.11.3/json.hpp` | `9bea4c8066ef4a1c206b2be5a36302f8926f7fdc6087af5d20b417d0cf103ea6` | `nlohmann_json/include/nlohmann/json.hpp` |
| nlohmann/json fwd | v3.11.3 | `https://github.com/nlohmann/json/releases/download/v3.11.3/json_fwd.hpp` | `5cefbba751baf5243033fd894c70be9b37103d64b3d3a959e4173197d71137b9` | `nlohmann_json/include/nlohmann/json_fwd.hpp` |
| msvc-redist-x86 (tests; optional Track A fallback) | MSVC CRT redist **14.51.36231** x86 (VS package `Microsoft.VC.14.51.CRT.Redist.X86.base` 14.51.36247; same CRT version as the xwin splat's headers and libs) | `https://download.visualstudio.microsoft.com/download/pr/3984a6ef-2ffc-4c07-962e-bf9e9b862819/f13add6a0613d85b1ae6fbb52d9592dc1df6b43791ea375f2c32dda605e7aaec/Microsoft.VC.14.51.CRT.Redist.X86.base.vsix`; only `Contents/VC/Redist/MSVC/14.51.36231/x86/Microsoft.VC145.CRT/` is extracted | `f13add6a0613d85b1ae6fbb52d9592dc1df6b43791ea375f2c32dda605e7aaec` | `msvc-redist/x86/` (`vcruntime140.dll`, `vcruntime140_threads.dll`, `msvcp140.dll`, `msvcp140_1.dll`, `msvcp140_2.dll`, `msvcp140_atomic_wait.dll`, `msvcp140_codecvt_ids.dll`, `concrt140.dll`, `vccorlib140.dll`) |

FLUF upstream URLs: both return HTTP 200 with a `content-length` equal to the local file's size (139359852 and
55651208 bytes; VERIFIED 2026-10-18 with `curl -sIL`). Their sha256 was not re-checked against the upstream bytes
(UNVERIFIED); `fetch_vendor.sh` refuses any download whose sha256 differs from the pin.

The MSVC redist DLLs are a test input (`toolchain/ehprobe.sh --crt native`) and the optional app-local runtime
discussed in `NOTES.md` "Question 3". They are Microsoft binaries: never commit them, never put them in a release.

Notes:

- Downloads are cached in `$FLMOD_VENDOR/.cache/dl/`; `fetch_vendor.sh --offline` re-extracts everything from the
  cache and `/home/user/freelancer/refs` without network (VERIFIED for doctest + nlohmann_json, 2026-10-17).
  `fetch_vendor.sh --verify` is offline and read-only: it re-hashes every source that is present, checks every
  stamp, and re-hashes every installed tree against its `.flmod-manifest` (VERIFIED 11/11 OK, 2026-10-18).
- Vendor trees are made read-only after extraction, so an accidental write from a build fails loudly.
- FLSDK at `ae8c857` already contains `include/magic_enum/` (v0.9.8, VERIFIED `MAGIC_ENUM_VERSION_*`). The
  separate magic_enum pin exists so FLSDK's own CMake (`fetch_release(MAGIC_ENUM …)`) could run offline with
  `-DFETCHCONTENT_SOURCE_DIR_MAGIC_ENUM=$FLMOD_VENDOR/magic_enum`. Our build never runs FLSDK's CMake (it would
  write into the shared tree); `flmod::flsdk_static` compiles FLSDK's sources directly.
- ImGui: v1.93.0 (released 2026-10-14, three days before pinning) was skipped in favour of the last 1.92 point
  release (2026-07-31). Bumping is a one-line change in `fetch_vendor.sh`.
- FLSDK has no license file (`README.md` has no license line; VERIFIED 2026-10-17). Its headers and import libs
  are build inputs only and never committed. Built binaries are a different matter: Track B DLLs compile FLSDK's
  own sources in (`flmod::flsdk_static`) and Track A modules statically link FLUF's prebuilt `FreelancerSDK.lib`,
  so our DLLs embed FLSDK code. W5-SHIP must account for that before attaching any binary to a release:
  `ABI.md` §7 (with the other licenses that end up inside the binaries, e.g. MinHook's BSD-2 notice).
- The FLUF dev package needs one define beyond R1's must-match list: `LIBUUID_CPP20_OR_GREATER` (stduuid's
  `<uuid.h>`, pulled in by FLUF's `Utils/Random.hpp`, otherwise includes `<gsl/span>`, which the package lacks).
