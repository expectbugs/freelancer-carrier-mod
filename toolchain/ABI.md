# ABI rules for module code

Short and binding for every C++ package that runs inside Freelancer.exe.

## 1. MSVC ABI only

- All module code is built by `toolchain/clang-cl-i686.cmake`: clang-cl 22, target `i686-pc-windows-msvc`, MSVC
  STL from xwin (CRT 14.51), `/MD` release CRT, `_ITERATOR_DEBUG_LEVEL=0`, `/EHa`, `-mstackrealign`, linked by
  lld-link. Don't override these per target (§6 depends on `/EHa` and `-mstackrealign`).
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
  `CreateID`, then runs the EH probe (§6.5).

## 6. Exceptions and SEH under Wine (binding; evidence `toolchain/NOTES.md` "Bug 2")

Probe: `src/module/ehprobe/ehprobe.cpp`, cases and expectations in `toolchain/ehprobe_cases.tsv`. Everything below
is VERIFIED under wine-proton 11 with both Wine's builtin `vcruntime140`/`msvcp140` and MSVC's own 14.51 DLLs.

**Works** (probe PASS): ordinary `throw`/`catch` by value and by `const&`, across frames and DLL calls; destructor
unwinding; `std::` exceptions thrown inside msvcp140 (`std::stoi`); `std::exception_ptr` / `std::rethrow_exception`;
try/catch nested inside a catch block; nlohmann `json::parse` errors (101), `type_error` (302), array `at()`
`out_of_range` (401); exceptions leaving a catch block (rethrow, new throw, `std::throw_with_nested`), including
into a try of the same function, thanks to `-mstackrealign` (§6.3).

### 6.1 SEH guards: one small `noinline` function with the clobber barrier

A function containing `__try/__except` compiled at /O2 returns to its caller with **EBX/ESI/EDI clobbered** after an
exception was handled: clang does not save callee-saved registers in such a function, and the SEH dispatcher
overwrites them before it resumes at `__except` (`a_seh_regs_raw`: KNOWN-BROKEN; no flag fixes it). The caller's
local variables silently change. The verified fix is a clobber barrier that forces the function to save and restore
them (`a_seh_regs_guarded`: PASS). Rules:

- `__try` appears **only** in small wrapper functions like the one below: `__declspec(noinline)`, the barrier as the
  first statement, one `__try`, no C++ objects with destructors, no `try`/`catch`, no other work.
- Everything risky runs in the callback. The guard returns the SEH exception code (0 = no fault). A C++ exception
  thrown inside the callback is swallowed too, as code `0xE06D7363`, and its destructors do run
  (`a_seh_guard_cxx_exception`: PASS), so catch C++ exceptions inside the callback if you care about them.
- `/EHa` stays on: without it a fault raised by an instruction in the `__try` function itself is not caught at all.

Copy-paste pattern (ARCH-0 turns it into a contract helper; until then copy it verbatim):

```cpp
#include <windows.h>

// Forces this function to save/restore EBX/ESI/EDI, which the SEH dispatcher clobbers before it resumes at
// __except. clang i686 does not save them otherwise (toolchain/ABI.md §6.1). Keep it the first statement.
#define FLMOD_SEH_CLOBBER_BARRIER() __asm__ volatile("" ::: "ebx", "esi", "edi")

using flmod_seh_fn = void (*)(void* ctx);

// Runs fn(ctx). Returns 0, or the SEH exception code if it faulted (0xC0000005 = access violation).
__declspec(noinline) unsigned long flmod_seh_guard(flmod_seh_fn fn, void* ctx)
{
    FLMOD_SEH_CLOBBER_BARRIER();
    unsigned long code = 0;
    __try
    {
        fn(ctx);
    }
    __except (code = GetExceptionCode(), EXCEPTION_EXECUTE_HANDLER)
    {
    }
    return code;
}

// Usage: a captureless lambda converts to flmod_seh_fn.
struct ReadCtx { const int* p; int value; };
ReadCtx rc{ptr, 0};
if (flmod_seh_guard([](void* c) { auto* r = static_cast<ReadCtx*>(c); r->value = *r->p; }, &rc) != 0)
{
    // fault: log it, keep going
}
```

### 6.2 Never rely on `catch(...)` to catch an access violation

`catch(...)` never sees an access violation raised in the function's own body or in a callee that clang proved
cannot throw (`b_catchall_av_inline`, `b_catchall_av_call`: KNOWN-BROKEN, the process dies). Under `/EHa` it does
see one raised inside an opaque call (`b_catchall_av_opaque_call`: PASS), which means a `catch(...)` around a
callback can *also* swallow a crash and carry on in a corrupt state. Rules:

- Use `flmod_seh_guard` (§6.1) for anything that may fault (engine pointers, patched memory, foreign callbacks).
- Write `catch(...)` only as the last handler of a C++ try, never as a crash guard. Because it may have swallowed a
  fault, treat a `catch(...)` hit as "unknown exception, possibly SEH": log it as such, skip the rest of the work and
  fall back. In hooks this is exactly the template in §6.7.

### 6.3 Exceptions leaving a catch block

Without `-mstackrealign`, an exception that leaves a catch block (`throw;`, a new `throw`,
`std::throw_with_nested`, a call that throws) and is caught by a try **in the same function** (after inlining)
kills the process under Wine's builtin CRT: LLVM's x86 catch funclets store their ESP into the EH registration
node, Wine's `call_catch_block` resumes the parent with that ESP, and the parent's ESP-relative epilogue then pops
garbage. MSVC's own vcruntime140 copes with it. `-mstackrealign` makes every EH function restore ESP from EBP, so
the toolchain now handles it (`c_*`, `lib_*` cases: PASS with both runtimes; FAIL without the flag, VERIFIED by
the negative control in NOTES.md). Rules:

- Never remove `-mstackrealign` or override the toolchain's compile flags per target. The probe's `c_*` cases FAIL
  if it goes missing.
- Code we don't compile does not have the flag: FLUF.dll, FLUF's dev libs (`FreelancerSDK.lib`, `yaml-cpp.lib`,
  `msgpack-c.lib`, `zstd_static.lib`) and HDE's DLLs. A catch-and-rethrow inside them can still crash under Wine's
  builtin CRT. Don't build control flow on exceptions passing through them.
- No C++ exception may propagate into Freelancer (VC6) or FLUF frames. Every engine callback, hook and FLUF event
  handler we implement follows the hook template (§6.7): its work runs under `flmod_seh_guard`, catches
  `const std::exception&` and `...` inside the guarded body, and the handler logs and returns normally.

### 6.4 Library code that rethrows internally

These catch an exception and rethrow it (or throw a new one) from inside a catch block. They are the §6.3 pattern
and are safe in code we compile; keep them away from prebuilt code's frames:

- MSVC STL 14.51: `std::vector` range `insert` (`_CATCH_ALL … _RERAISE`, `<vector>`), stream extractors and
  inserters (`_CATCH_IO_END` in `<istream>` and `__msvc_ostream.hpp`), `<future>`, `<iterator>`, `<syncstream>`,
  `<stacktrace>`, `<xlocale>`, `<iosfwd>`/`<yvals.h>` helpers; `std::throw_with_nested` and
  `std::rethrow_if_nested` when called inside a catch block.
- nlohmann/json 3.11.3: only array `basic_json::at(size_type)` (catches `std::out_of_range`, throws
  `json::out_of_range`; json.hpp:21249 and 21272), plus the `JSON_DIAGNOSTICS` self-check (off). `json::parse`
  does **not** rethrow: its errors are thrown from normal code. Prefer `json::parse(text, nullptr, false)` +
  `is_discarded()` and `contains()`/`value()` over exceptions on untrusted input.
- `std::thread` entry points terminate on an escaping exception; catch inside thread functions.

### 6.5 The EH probe (regression check)

`toolchain/ehprobe.sh --build build/<win32 preset> (--clone <prefix-dev-name> [--from prefix-dev-base-B|prefix-dev-base-A|play]
| --prefix <prefix-dev-*>) [--crt builtin|native|both]`. It runs every case of `ehprobe_cases.tsv` in its own
`loadtest.exe` process and prints one line per case, `EHPROBE crt=… case=… group=base|a|b|c|lib|parse|hook
status=PASS|KNOWN-BROKEN|FAIL|SKIP …`, plus a summary line, and writes `results.tsv`/`results.json`. Exit 0 = no FAIL
and every requested runtime ran; 1 = FAIL; 77 = a prerequisite or a requested runtime is missing (never a PASS with
zero cases). `--prefix` takes only throwaway `prefix-dev-*` prefixes, never a baseline or a lane (a lane's
wineserver may be running the game); `--clone` copies a dev baseline by default, so it never needs the play prefix.
`toolchain/load_proof.sh` runs it after the CreateID proof. A FAIL means a working feature broke (or a flag went
missing); an unexpected PASS of a KNOWN-BROKEN case means a rule above may be obsolete: update this section.

Who runs it: not CI (it needs Wine). CI stage 10 statically checks the flags it depends on
(`toolchain/check_flags.py`: `-mstackrealign`, `/EHa`, `/MD`, `_ITERATOR_DEBUG_LEVEL=0` on every TU). Proposed for the
orchestrator: P0-TRACK-A/B and W1-PLATFORM acceptance run `ehprobe.sh --build build/win32-track<T> --clone … --crt
both`, and so does any change to `toolchain/` or `cmake/` flags.

The `hook` group covers what a game-hook package does (VERIFIED, both runtimes, both tracks): a fault inside the
game's `Common.dll` caught by `flmod_seh_guard` with the caller's registers intact; nested guards; `__finally`
running while a fault unwinds to an outer guard; C++ EH on a worker thread; a C++ exception or an AV leaving our
callback through `msvcrt.dll`'s (VC6 runtime) `qsort` frames; a try/catch inside a callback that foreign code calls;
a VC6-style `msvcrt!_CxxThrowException` caught by `catch(int)` and `catch(...)`; and every path of the §6.7 template.

### 6.6 Which msvcp140/vcruntime140 the game process gets

- Default: **Wine's builtins**. They export every symbol our binaries and the whole FLUF nightly import
  (check_imports; `NOTES.md` "Question 3").
- The play prefix and all its clones (both dev baselines included) carry registry `DllOverrides` = `native,builtin`
  for `msvcp140*`, `vcruntime140*`, `concrt140`, `ucrtbase`, the `api-ms-win-crt-*` sets and the older
  `msvcp1?0`/`msvcr1?0` runtimes. A native `vcruntime140.dll`/`msvcp140.dll` in the exe's directory therefore
  replaces the builtins for **every** DLL in the process that imports them (FLUF, its modules, ours, and HDE's
  FLHook, fmt, spdlog and pcre2 DLLs whenever they are loaded) without any environment variable. Only deploy them
  on purpose; the decision belongs to G0a/W1-PLATFORM. A deploy step should refuse stray `msvcp1*`, `msvcr1*`,
  `vcruntime140*`, `concrt140*`, `ucrtbase*` and `api-ms-win-crt-*` DLLs in the EXE dir.
- Nothing in §6.1–6.4 may depend on which runtime is loaded: every rule holds under both (probe `--crt both`).

### 6.7 The hook template (binding for every engine hook, callback and FLUF event handler)

§6.1–6.3 together mean: the work runs under `flmod_seh_guard` (faults never escape, registers survive); the
C++ `try` sits **inside** the guarded body (the guard also catches C++ exceptions, but only as code `0xE06D7363`,
losing the message); a `catch(...)` hit is logged as "possibly SEH" (§6.2); and the handler always returns
normally to the engine. Compiled and exercised in `src/module/ehprobe` (`hook_template_*` cases: normal path, a
`std::exception`, an AV in the body's own code (reaches the guard), an AV inside an opaque call (reaches
`catch(...)`); all PASS with registers intact under both runtimes).

```cpp
enum class HookStatus : int { ok, cxx_exception, unknown_exception };

struct FooCall  // trivially destructible: it lives in the hook's frame across the guard
{
    int arg;          // the hook's inputs ...
    int result;       // ... and outputs
    HookStatus status;
    char what[96];
};

void foo_body(void* p)  // runs under flmod_seh_guard; nothing may escape it
{
    auto& c = *static_cast<FooCall*>(p);
    try
    {
        c.result = foo_work(c.arg);  // the real work: ordinary C++, may throw
        c.status = HookStatus::ok;
    }
    catch (const std::exception& e)
    {
        c.status = HookStatus::cxx_exception;
        strncpy_s(c.what, e.what(), _TRUNCATE);
    }
    catch (...)
    {
        // A non-std C++ exception, or an SEH fault raised inside an opaque call (/EHa; §6.2).
        c.status = HookStatus::unknown_exception;
    }
}

int __stdcall hook_foo(int arg)  // what the engine (or FLUF) calls
{
    FooCall c{arg, 0, HookStatus::ok, {}};
    const unsigned long code = flmod_seh_guard(&foo_body, &c);  // a fault in foo_body's own code lands here
    if (code == 0 && c.status == HookStatus::ok)
        return c.result;
    try
    {
        if (code != 0)
            FLMOD_LOG_ERROR("hook foo: SEH exception 0x{:08X}; fell back", code);
        else if (c.status == HookStatus::cxx_exception)
            FLMOD_LOG_ERROR("hook foo: exception: {}; fell back", c.what);
        else
            FLMOD_LOG_ERROR("hook foo: unknown exception, possibly SEH (catch(...) under /EHa); fell back");
    }
    catch (...)
    {
        // reporting must never throw into the engine
    }
    return foo_fallback(arg);  // e.g. call the original function, or a safe default
}
```

`FLMOD_LOG_ERROR` stands for the module logger (`[carrier] <subsystem>: …`, CLAUDE.md guardrail 8); ARCH-0 turns
the guard and this shape into contract helpers. Keep `foo_work` free of `__try`; put engine-memory reads that may
fault in their own `flmod_seh_guard` call if the hook must continue after them.

### 6.8 Not covered by the probe (needs the game; items for P0-TRACK-A/B)

`loadtest.exe` cannot reproduce these; check them in game and record the results as ENGINE_FACTS:

- C++ exceptions crossing **FLUF.dll** frames (a FLUF event handler that throws; FLUF calling back into us inside its
  own try). FLUF.dll is clang-cl code without `-mstackrealign` (`NOTES.md` "Question 3"), so §6.3 applies to it.
- **Crash handlers** installed by others: HDE's crash catcher plugin, FLUF.CrashWalker, or any vectored exception
  handler / `SetUnhandledExceptionFilter`. A first-chance VEH runs before our `__except` filter and could log, or
  terminate on, a fault that `flmod_seh_guard` would have handled. Verify a guarded fault inside a hook is
  survivable with the game's real handler chain.
- Exceptions thrown during **DllMain** or static initialisation of our DLL as the game (dacom `[Libraries]` or FLUF)
  loads it, and on unload at exit.
- The §6.7 template on real engine hooks (calling conventions `__thiscall`/`__fastcall`, detours through MinHook or
  FLUF's hooking), including a fault inside the original function called as the fallback.

## 7. Licensing of what ends up inside our binaries (for W5-SHIP)

- Track B DLLs **compile FLSDK's own sources** into the binary (`flmod::flsdk_static`, whenever a target links
  it), and Track A modules **statically link FLUF's prebuilt `FreelancerSDK.lib`** (FLSDK code built by FLUF CI).
  So a built DLL embeds FLSDK code, not just references to its import libs. FLSDK has no license file (PINS.md).
  W5-SHIP must account for this before attaching any binary to a release (CONVENTIONS §11).
- Track A modules also embed reflect-cpp (MIT, its LICENSE) and FLUF's static `yaml-cpp.lib` (MIT per upstream;
  the dev package carries no license text), `msgpack-c.lib` (Boost Software License 1.0, per `msgpack.h`) and
  `zstd_static.lib` (BSD-style or GPLv2, per `zstd.h`), and import FLUF.dll (AGPL-3.0, like this repo).
- Track B embeds MinHook (BSD-2-Clause: its copyright notice and license text must accompany any binary release)
  and Dear ImGui (MIT); everything links nlohmann/json (MIT).
- Source distribution of this repo is unaffected: none of these files are committed.
