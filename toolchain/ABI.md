# ABI rules for module code

Short and binding for every C++ package that runs inside Freelancer.exe.

## 1. MSVC ABI only

- All module code is built by `toolchain/clang-cl-i686.cmake`: clang-cl 22, target `i686-pc-windows-msvc`, MSVC
  STL from xwin (CRT 14.51), `/MD` release CRT, `_ITERATOR_DEBUG_LEVEL=0`, `/EHa`, linked by lld-link.
- **mingw is not allowed for module code.** GCC uses Itanium mangling, a different vtable/RTTI layout and
  DWARF/SJLJ exceptions instead of MSVC EH/SEH, so it can neither link FLSDK's MSVC-mangled imports nor implement
  or call Freelancer's virtual interfaces (R4 §B9, VERIFIED).
- Never `/MDd`, never debug iterators. FLUF.dll and its modules use the release CRT.

## 2. Two C runtimes live in the process

| Who | Linker | C++ runtime | Heap |
|---|---|---|---|
| Freelancer.exe, Common.dll, Server.dll, dacom.dll (and friends) | VC6, linker 6.24 | **MSVCP60.dll + MSVCRT.dll** (Wine builtins in this prefix) | msvcrt.dll |
| Our DLLs, FLUF.dll | clang-cl / VS2026 | msvcp140 + vcruntime140 + UCRT (Wine builtins) | ucrtbase.dll |

(R4 §B9, VERIFIED from the PE headers.) The two STLs have different layouts and the two heaps are different.

## 3. The Common.dll boundary rule

**Anything that crosses the Common.dll (or Server.dll) boundary must use FLSDK's `st6::` containers, never `std::`
ones.** That means every container inside an engine struct, every container argument to or result from an engine
function, and any memory the engine may free or reallocate.

- Header: `$FLMOD_VENDOR/FLSDK/include/FLCore/st6.h` (FLSDK `ae8c857`), included through
  `<FLCore/FLCoreDefs.hpp>`.
- Types: `st6::vector`, `st6::list`, `st6::map`, `st6::basic_string`, with `st6::string` / `st6::wstring`
  (`st6.h:3023-3024`; case-insensitive char traits, like the engine's).
- Its `st6::allocator` resolves `malloc` and `free` from **`msvcrt.dll`** with
  `GetProcAddress(GetModuleHandleA("msvcrt.dll"), ...)` (`st6.h:43`, `st6.h:84`), so memory comes from the same heap
  the VC6 engine uses.
- Never pass `std::string`, `std::vector`, `std::map`, `std::shared_ptr`, … to an engine function or store them in
  an engine-owned struct. Convert at the boundary.
- Never `delete` / `free()` engine memory with our CRT, and never hand our `new`ed memory to the engine to free.

## 4. FLUF (Track A only)

FLUF's public API **does** pass modern MSVC STL types (`std::string_view`, `std::shared_ptr`, `std::format`
arguments, reflect-cpp types) between our module and FLUF.dll. That is fine because both sides use the same
`/MD` msvcp140 runtime and the same headers. It is why the must-match list in `flmod_fluf_module()`
(`cmake/FlmodVendor.cmake`) exists: the same defines (`IMGUI_USE_WCHAR32` changes ImGui layouts), the same
reflect-cpp commit, the release CRT, `_ITERATOR_DEBUG_LEVEL=0`, and never `FLUF` defined (that flips `FLUF_API`
to dllexport). The `st6::` rule above still applies to anything that reaches Common.dll.

## 5. Proof tools

- `toolchain/check_imports.py` (CI stage 50): every import must be on the allowlist and resolvable against the
  Wine builtins, the game's own DLLs and (Track A) the pinned FLUF.dll.
- `toolchain/load_proof.sh`: loads `hello_b.dll` under Wine in a throwaway prefix and calls Common.dll's
  `CreateID`.
