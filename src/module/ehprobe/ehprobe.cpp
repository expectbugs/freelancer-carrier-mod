// src/module/ehprobe/ehprobe.cpp: exception-handling regression probe for the clang-cl i686 toolchain
// under Wine. Each case is an exported `extern "C" int ehp_<case>()`. toolchain/ehprobe.sh runs every case in
// its own `loadtest.exe ehprobe.dll ehp_<case>` process (a broken case kills the process) and classifies the
// result as PASS / KNOWN-BROKEN / FAIL against the expectations in toolchain/ehprobe_cases.tsv.
// Background and the coding rules these cases back up: toolchain/ABI.md §6, toolchain/NOTES.md "Bug 2".
//
// Convention: a case returns its expected value when the C++/SEH feature works. A case that hits a known
// toolchain/runtime defect either returns something else or kills the process (loadtest exit code 5).
#include <windows.h>

#include <nlohmann/json.hpp>

#include <cstdio>
#include <cstring>
#include <exception>
#include <stdexcept>
#include <string>
#include <typeinfo>
#include <vector>

#define EHP extern "C" __declspec(dllexport)

// The recommended SEH-guard pattern (toolchain/ABI.md §6.1), compiled exactly as documented.
#define FLMOD_SEH_CLOBBER_BARRIER() __asm__ volatile("" ::: "ebx", "esi", "edi")
using flmod_seh_fn = void (*)(void* ctx);
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

namespace {

int g_dtors = 0;
struct Dtor
{
    ~Dtor() { ++g_dtors; }
};

__declspec(noinline) void throw_logic() { throw std::logic_error("deep"); }
__declspec(noinline) void do_av() { *(volatile int*)nullptr = 1; }
void av_cb(void*) { *(volatile int*)nullptr = 2; }
void ok_cb(void* ctx) { *static_cast<int*>(ctx) = 42; }
void cxx_throw_cb(void*)
{
    Dtor d;
    throw std::runtime_error("through the guard");
}

// Keeps four values live across fn() in callee-saved registers and checks them afterwards.
__declspec(noinline) int keep_regs(int (*fn)())
{
    volatile int seed = 1234;
    int a = seed * 3, b = seed * 5, c = seed * 7, d = seed * 11;
    const int r = fn();
    const bool ok = (a == 3702 && b == 6170 && c == 8638 && d == 13574);
    std::printf("keep_regs: fn=%d a=%d b=%d c=%d d=%d -> %s\n", r, a, b, c, d, ok ? "INTACT" : "CORRUPTED");
    std::fflush(stdout);
    return ok ? 1 : 0;
}

// (a) raw __try function: no barrier. Known broken: it returns to its caller with EBX/ESI/EDI clobbered.
__declspec(noinline) int seh_raw()
{
    __try
    {
        *(volatile int*)nullptr = 0;
    }
    __except (EXCEPTION_EXECUTE_HANDLER)
    {
        return 9;
    }
    return 0;
}
// (a) the recommended guard.
__declspec(noinline) int seh_guarded() { return flmod_seh_guard(&av_cb, nullptr) == EXCEPTION_ACCESS_VIOLATION ? 9 : 0; }

// (c) helpers.
__declspec(noinline) void rethrower_noinline()
{
    try
    {
        throw 2;
    }
    catch (...)
    {
        throw;
    }
}
inline void rethrower_inline()
{
    try
    {
        throw 2;
    }
    catch (...)
    {
        throw;
    }
}

struct Thrower
{
    int v;
    explicit Thrower(int x) : v(x) {}
    Thrower(const Thrower& o) : v(o.v)
    {
        if (o.v == 13)
            throw std::runtime_error("copy");
    }
    Thrower& operator=(const Thrower&) = default;
};

__declspec(noinline) int json_at_wrapped_impl(const nlohmann::json& j) { return j.at(5).get<int>(); }

// Opaque to the optimizer: a call through it is always an invoke (it may throw), so the try state is set.
void (*volatile g_av_fp)() = &do_av;

__declspec(noinline) void vector_insert_impl(std::vector<Thrower>& v, const Thrower* first, const Thrower* last)
{
    v.insert(v.begin(), first, last);
}

}  // namespace

// ------------------------------------------------------------------------------------------- baseline
EHP int ehp_base_throw_int()
{
    try
    {
        throw 1;
    }
    catch (int v)
    {
        return 7 + v;  // 8
    }
}
EHP int ehp_base_std_exception()
{
    try
    {
        throw std::runtime_error("abc");
    }
    catch (const std::exception& e)
    {
        return (int)std::strlen(e.what());  // 3
    }
}
EHP int ehp_base_cross_frame()
{
    try
    {
        throw_logic();
    }
    catch (const std::logic_error& e)
    {
        return (int)std::strlen(e.what());  // 4
    }
    return 0;
}
EHP int ehp_base_dtor_unwind()
{
    g_dtors = 0;
    try
    {
        Dtor d;
        throw 4;
    }
    catch (int)
    {
        return g_dtors;  // 1
    }
}
EHP int ehp_base_stoi()
{
    try
    {
        return std::stoi("abc");
    }
    catch (const std::invalid_argument&)
    {
        return 5;
    }
}
EHP int ehp_base_eptr_outside_catch()
{
    std::exception_ptr p;
    try
    {
        throw std::runtime_error("x");
    }
    catch (...)
    {
        p = std::current_exception();
    }
    try
    {
        std::rethrow_exception(p);
    }
    catch (const std::exception& e)
    {
        return (int)std::strlen(e.what());  // 1
    }
    return 0;
}
EHP int ehp_base_catch_in_catch()
{
    int r = 0;
    try
    {
        throw 1;
    }
    catch (int)
    {
        try
        {
            throw 2;
        }
        catch (int v)
        {
            r = v;
        }
    }
    return r;  // 2
}

// ----------------------------------------------------------------------------- (a) SEH __try / __except
EHP int ehp_a_seh_regs_raw() { return keep_regs(&seh_raw); }  // 1 = INTACT
EHP int ehp_a_seh_regs_guarded() { return keep_regs(&seh_guarded); }
EHP int ehp_a_seh_guard_cxx_exception()
{
    // A C++ exception thrown inside the guard is swallowed as code 0xE06D7363; the destructor still runs.
    g_dtors = 0;
    const unsigned long code = flmod_seh_guard(&cxx_throw_cb, nullptr);
    return g_dtors * 10 + (code == 0xE06D7363UL ? 1 : 0);  // 11
}
EHP int ehp_a_seh_guard_no_fault()
{
    int v = 0;
    return flmod_seh_guard(&ok_cb, &v) == 0 ? v : -1;  // 42
}

// ------------------------------------------------------------------- (b) catch(...) vs access violation
EHP int ehp_b_catchall_av_inline()
{
    try
    {
        *(volatile int*)nullptr = 1;
    }
    catch (...)
    {
        return 11;
    }
    return 0;
}
EHP int ehp_b_catchall_av_call()
{
    try
    {
        do_av();
    }
    catch (...)
    {
        return 12;
    }
    return 0;
}

EHP int ehp_b_catchall_av_opaque_call()
{
    try
    {
        g_av_fp();
    }
    catch (...)
    {
        return 13;
    }
    return 0;
}

// ------------------------------------------------------- (c) exceptions leaving a catch block, same frame
EHP int ehp_c_rethrow_same_frame()
{
    try
    {
        try
        {
            throw 2;
        }
        catch (...)
        {
            throw;
        }
    }
    catch (int v)
    {
        return v;  // 2
    }
    return 0;
}
EHP int ehp_c_throw_new_from_catch_same_frame()
{
    try
    {
        try
        {
            throw 2;
        }
        catch (...)
        {
            throw std::runtime_error("x");
        }
    }
    catch (const std::exception& e)
    {
        return (int)std::strlen(e.what());  // 1
    }
    return 0;
}
EHP int ehp_c_rethrow_cross_noinline()
{
    try
    {
        rethrower_noinline();
    }
    catch (int v)
    {
        return v;  // 2
    }
    return 0;
}
EHP int ehp_c_rethrow_cross_inlined()
{
    try
    {
        rethrower_inline();
    }
    catch (int v)
    {
        return v;  // 2
    }
    return 0;
}
EHP int ehp_c_rethrow_eptr_in_catch_same_frame()
{
    try
    {
        try
        {
            throw 3;
        }
        catch (...)
        {
            std::rethrow_exception(std::current_exception());
        }
    }
    catch (int v)
    {
        return v;  // 3
    }
    return 0;
}
// --------------------------------------------------------------------- library code that rethrows
EHP int ehp_lib_rethrow_if_nested_in_catch()
{
    try
    {
        try
        {
            throw std::logic_error("inner");
        }
        catch (const std::exception& e)
        {
            std::rethrow_if_nested(e);  // not nested: returns normally
            std::throw_with_nested(std::runtime_error("outer"));
        }
    }
    catch (const std::runtime_error& e)
    {
        return (int)std::strlen(e.what());  // 5
    }
    return 0;
}
EHP int ehp_lib_vector_insert_throw()
{
    try
    {
        std::vector<Thrower> v;
        v.reserve(8);
        v.emplace_back(1);
        v.emplace_back(2);
        const Thrower src[2] = {Thrower(7), Thrower(13)};
        v.insert(v.begin(), src, src + 2);  // copy of 13 throws inside _TRY_BEGIN ... _RERAISE
    }
    catch (const std::runtime_error& e)
    {
        return (int)std::strlen(e.what());  // 4
    }
    return 0;
}
EHP int ehp_lib_vector_insert_throw_wrapped()
{
    try
    {
        std::vector<Thrower> v;
        v.reserve(8);
        v.emplace_back(1);
        v.emplace_back(2);
        const Thrower src[2] = {Thrower(7), Thrower(13)};
        vector_insert_impl(v, src, src + 2);  // the STL catch-and-rethrow stays in vector_insert_impl's frame
    }
    catch (const std::runtime_error& e)
    {
        return (int)std::strlen(e.what());  // 4
    }
    return 0;
}
EHP int ehp_json_parse_error()
{
    try
    {
        auto j = nlohmann::json::parse("{\"a\": [1, 2,");
        return (int)j.size();
    }
    catch (const nlohmann::json::parse_error& e)
    {
        return e.id;  // 101
    }
}
EHP int ehp_json_parse_no_exceptions()
{
    auto j = nlohmann::json::parse("{\"a\": [1, 2,", nullptr, /*allow_exceptions=*/false);
    return j.is_discarded() ? 1 : 0;  // 1
}
EHP int ehp_json_type_error()
{
    try
    {
        nlohmann::json j = "text";
        return j.get<int>();
    }
    catch (const nlohmann::json::type_error& e)
    {
        return e.id;  // 302
    }
}
EHP int ehp_json_at_same_frame()
{
    try
    {
        const nlohmann::json j = nlohmann::json::array({1, 2});
        return j.at(5).get<int>();  // at() catches std::out_of_range and throws json::out_of_range
    }
    catch (const nlohmann::json::out_of_range& e)
    {
        return e.id;  // 401
    }
}
EHP int ehp_json_at_wrapped()
{
    try
    {
        const nlohmann::json j = nlohmann::json::array({1, 2});
        return json_at_wrapped_impl(j);
    }
    catch (const nlohmann::json::out_of_range& e)
    {
        return e.id;  // 401
    }
}

// ================================================================================================================
// Hook-package patterns (review r2 F3, from the reviewer's probe): a fault inside the game's own Common.dll, nested
// guards, __finally during unwinding, C++ EH on a worker thread, callbacks called by the VC6-era msvcrt.dll (the
// runtime the engine uses), and C++ exceptions thrown the VC6 way. Plus the hook template of toolchain/ABI.md §6.7
// (cases hook_template_*). A case returns -77 when a prerequisite is missing (ehprobe.sh reports SKIP).
namespace {

constexpr int kSkip = -77;

// Like keep_regs, but returns fn()'s value when the caller's callee-saved registers survived, -1 otherwise.
__declspec(noinline) int keep_regs_value(int (*fn)())
{
    volatile int seed = 1234;
    int a = seed * 3, b = seed * 5, c = seed * 7, d = seed * 11;
    const int r = fn();
    const bool ok = (a == 3702 && b == 6170 && c == 8638 && d == 13574);
    std::printf("keep_regs: fn=%d a=%d b=%d c=%d d=%d -> %s\n", r, a, b, c, d, ok ? "INTACT" : "CORRUPTED");
    std::fflush(stdout);
    return ok ? r : -1;
}

// The game's Common.dll, from the directory toolchain/ehprobe.sh passes in FLMOD_EHPROBE_GAME_EXE.
HMODULE game_common_dll()
{
    char dir[MAX_PATH] = {};
    const DWORD n = GetEnvironmentVariableA("FLMOD_EHPROBE_GAME_EXE", dir, sizeof(dir));
    if (n == 0 || n >= sizeof(dir) - 16)
        return nullptr;
    const std::string path = std::string(dir) + "\\common.dll";
    return LoadLibraryExA(path.c_str(), nullptr, LOAD_WITH_ALTERED_SEARCH_PATH);
}

using CreateIdFn = unsigned int(__cdecl*)(const char*);   // CreateID(const char*), Common.dll
using DeactivatePhysicsFn = void(__cdecl*)(void*);         // PhySys::DeactivatePhysics(CObject*), Common.dll
DeactivatePhysicsFn g_deactivate = nullptr;

void engine_fault_cb(void*) { g_deactivate(reinterpret_cast<void*>(0x10)); }  // faults inside Common.dll
__declspec(noinline) int engine_fault_guarded()
{
    const unsigned long code = flmod_seh_guard(&engine_fault_cb, nullptr);
    std::printf("engine fault: guard code=0x%08lX\n", code);
    return code == EXCEPTION_ACCESS_VIOLATION ? 9 : 0;
}

void nested_cb(void* ctx) { *static_cast<unsigned long*>(ctx) = flmod_seh_guard(&av_cb, nullptr); }

volatile int g_flag = 0;
void finally_cb(void*)
{
    __try
    {
        *(volatile int*)nullptr = 3;
    }
    __finally
    {
        g_flag = 7;
    }
}

DWORD WINAPI thread_proc(LPVOID p)
{
    try
    {
        throw std::runtime_error("thread");
    }
    catch (const std::exception& e)
    {
        *static_cast<int*>(p) = static_cast<int>(std::strlen(e.what()));  // 6
    }
    return 0;
}

using QsortFn = void(__cdecl*)(void*, size_t, size_t, int(__cdecl*)(const void*, const void*));
QsortFn msvcrt_qsort()   // the VC6-era msvcrt.dll the engine links against (a Wine builtin here)
{
    HMODULE m = LoadLibraryA("msvcrt.dll");
    return m ? reinterpret_cast<QsortFn>(reinterpret_cast<void*>(GetProcAddress(m, "qsort"))) : nullptr;
}
int __cdecl cmp_throw(const void*, const void*) { throw 5; }
int __cdecl cmp_av(const void*, const void*) { return *(volatile int*)nullptr; }
int __cdecl cmp_catch_inside(const void* a, const void* b)
{
    try
    {
        throw std::runtime_error("cb");
    }
    catch (...)
    {
        g_flag = g_flag + 1;
    }
    return *static_cast<const int*>(a) - *static_cast<const int*>(b);
}
void qsort_av_cb(void*)
{
    int v[4] = {4, 3, 2, 1};
    msvcrt_qsort()(v, 4, sizeof(int), &cmp_av);
}

// A C++ exception thrown the VC6 way: msvcrt.dll!_CxxThrowException with a hand-built ThrowInfo for `int`.
struct PMD { int mdisp, pdisp, vdisp; };
struct CatchableType { unsigned properties; const void* pType; PMD thisDisplacement; int sizeOrOffset; void* copyFunction; };
struct CatchableTypeArray { int n; const CatchableType* types[1]; };
struct ThrowInfo { unsigned attributes; void* pmfnUnwind; void* pForwardCompat; const CatchableTypeArray* pCTA; };
const CatchableType g_ct_int{1u, &typeid(int), {0, -1, 0}, static_cast<int>(sizeof(int)), nullptr};
const CatchableTypeArray g_cta_int{1, {&g_ct_int}};
const ThrowInfo g_ti_int{0, nullptr, nullptr, &g_cta_int};
__declspec(noinline) void vc6_style_throw(int v)
{
    using CxxThrowFn = void(__stdcall*)(void*, const ThrowInfo*);
    static int obj;
    obj = v;
    auto f = reinterpret_cast<CxxThrowFn>(
        reinterpret_cast<void*>(GetProcAddress(LoadLibraryA("msvcrt.dll"), "_CxxThrowException")));
    if (f)
        f(&obj, &g_ti_int);
}

// ---- the hook template (toolchain/ABI.md §6.7), as documented apart from logging -------------------------------
enum class HookStatus : int { ok, cxx_exception, unknown_exception };

struct FooCall  // trivially destructible: it lives in the hook's frame across the guard
{
    int arg;
    int result;
    HookStatus status;
    char what[96];
};

__declspec(noinline) int foo_work(int arg)  // the hook's real work: ordinary C++
{
    if (arg == 1)
        throw std::runtime_error("bad arg");
    if (arg == 3)
        g_av_fp();  // probe only: a fault inside an opaque call
    return 42;
}

void foo_body(void* p)  // runs under flmod_seh_guard; nothing may escape it
{
    auto& c = *static_cast<FooCall*>(p);
    try
    {
        if (c.arg == 2)
            *(volatile int*)nullptr = 1;  // probe only: a fault in the body's own code
        c.result = foo_work(c.arg);
        c.status = HookStatus::ok;
    }
    catch (const std::exception& e)
    {
        c.status = HookStatus::cxx_exception;
        strncpy_s(c.what, e.what(), _TRUNCATE);
    }
    catch (...)
    {
        // A non-std C++ exception, or an SEH fault raised inside an opaque call (/EHa; ABI.md §6.2).
        c.status = HookStatus::unknown_exception;
    }
}

struct HookReport
{
    bool hit;
    unsigned long code;
    HookStatus status;
    char what[96];
};
HookReport g_report{};
void report_hook_failure(const char*, unsigned long code, const FooCall& c)  // stands in for the logger
{
    g_report.hit = true;
    g_report.code = code;
    g_report.status = c.status;
    strncpy_s(g_report.what, c.what, _TRUNCATE);
}

__declspec(noinline) int __stdcall hook_foo(int arg)  // what the engine (or FLUF) calls
{
    FooCall c{arg, 0, HookStatus::ok, {}};
    const unsigned long code = flmod_seh_guard(&foo_body, &c);  // a fault in foo_body's own code lands here
    if (code == 0 && c.status == HookStatus::ok)
        return c.result;
    try
    {
        report_hook_failure("foo", code, c);
    }
    catch (...)
    {
        // reporting must never throw into the engine
    }
    return -1;  // the fallback (a real hook calls the original function here)
}

int g_hook_arg = 0;
int call_hook() { return hook_foo(g_hook_arg); }

// Runs hook_foo(arg) between register checks. Returns the hook's result, or -100 when registers were corrupted.
int run_hook(int arg)
{
    g_report = HookReport{};
    g_hook_arg = arg;
    const int r = keep_regs_value(&call_hook);
    std::printf("hook_foo(%d) -> %d; report hit=%d code=0x%08lX status=%d what='%s'\n", arg, r, g_report.hit ? 1 : 0,
                g_report.code, static_cast<int>(g_report.status), g_report.what);
    std::fflush(stdout);
    return r;
}

}  // namespace

EHP int ehp_hook_engine_fault_guarded_regs()
{
    HMODULE common = game_common_dll();
    if (!common)
        return kSkip;
    auto create_id = reinterpret_cast<CreateIdFn>(reinterpret_cast<void*>(GetProcAddress(common, "?CreateID@@YAIPBD@Z")));
    g_deactivate = reinterpret_cast<DeactivatePhysicsFn>(
        reinterpret_cast<void*>(GetProcAddress(common, "?DeactivatePhysics@PhySys@@YAXPAUCObject@@@Z")));
    if (!create_id || !g_deactivate)
        return -2;
    std::printf("Common.dll CreateID(\"li02\")=%u\n", create_id("li02"));
    return keep_regs_value(&engine_fault_guarded);  // 9: AV inside Common.dll caught, registers intact
}
EHP int ehp_hook_nested_guards()
{
    unsigned long inner = 0;
    const unsigned long outer = flmod_seh_guard(&nested_cb, &inner);
    return (outer == 0 && inner == EXCEPTION_ACCESS_VIOLATION) ? 1 : 0;  // 1
}
EHP int ehp_hook_finally_runs()
{
    g_flag = 0;
    const unsigned long code = flmod_seh_guard(&finally_cb, nullptr);
    return (code == EXCEPTION_ACCESS_VIOLATION ? 10 : 0) + g_flag;  // 17
}
EHP int ehp_hook_thread_eh()
{
    int out = 0;
    HANDLE h = CreateThread(nullptr, 0, &thread_proc, &out, 0, nullptr);
    if (!h)
        return -1;
    WaitForSingleObject(h, 10000);
    CloseHandle(h);
    return out;  // 6
}
EHP int ehp_hook_cxx_through_msvcrt_qsort()
{
    QsortFn q = msvcrt_qsort();
    if (!q)
        return kSkip;
    int v[4] = {4, 3, 2, 1};
    try
    {
        q(v, 4, sizeof(int), &cmp_throw);
    }
    catch (int x)
    {
        return x;  // 5
    }
    return 0;
}
EHP int ehp_hook_av_through_msvcrt_qsort_guarded()
{
    if (!msvcrt_qsort())
        return kSkip;
    return flmod_seh_guard(&qsort_av_cb, nullptr) == EXCEPTION_ACCESS_VIOLATION ? 1 : 0;  // 1
}
EHP int ehp_hook_catch_inside_foreign_callback()
{
    QsortFn q = msvcrt_qsort();
    if (!q)
        return kSkip;
    g_flag = 0;
    int v[4] = {4, 3, 2, 1};
    q(v, 4, sizeof(int), &cmp_catch_inside);
    return (v[0] == 1 && v[3] == 4 && g_flag > 0) ? 1 : 0;  // 1
}
EHP int ehp_hook_catch_vc6_thrown_int()
{
    try
    {
        vc6_style_throw(21);
    }
    catch (int v)
    {
        return v;  // 21
    }
    return 0;
}
EHP int ehp_hook_catchall_vc6_thrown()
{
    try
    {
        vc6_style_throw(1);
    }
    catch (...)
    {
        return 22;  // 22
    }
    return 0;
}

// The hook template: every path returns normally to the "engine" with its registers intact.
EHP int ehp_hook_template_ok()
{
    const int r = run_hook(0);
    return (r == 42 && !g_report.hit) ? 1 : 0;  // 1
}
EHP int ehp_hook_template_cxx()
{
    const int r = run_hook(1);
    const bool ok = r == -1 && g_report.hit && g_report.code == 0 && g_report.status == HookStatus::cxx_exception &&
                    std::strcmp(g_report.what, "bad arg") == 0;
    return ok ? 2 : 0;  // 2
}
// A fault may reach the guard (SEH code) or, under /EHa, the body's catch(...) ("possibly SEH"); both are handled.
EHP int ehp_hook_template_av_body()
{
    const int r = run_hook(2);
    const bool ok = r == -1 && g_report.hit &&
                    (g_report.code == EXCEPTION_ACCESS_VIOLATION || g_report.status == HookStatus::unknown_exception);
    return ok ? 3 : 0;  // 3
}
EHP int ehp_hook_template_av_opaque()
{
    const int r = run_hook(3);
    const bool ok = r == -1 && g_report.hit &&
                    (g_report.code == EXCEPTION_ACCESS_VIOLATION || g_report.status == HookStatus::unknown_exception);
    return ok ? 4 : 0;  // 4
}

#ifdef EHPROBE_EXE
// Experiment-only variant: the same cases linked into an .exe (NOTES.md "Bug 2", experiment X6).
int main(int argc, char** argv)
{
    if (argc < 2)
        return 2;
    auto fn = reinterpret_cast<int (*)()>(reinterpret_cast<void*>(GetProcAddress(GetModuleHandleA(nullptr), argv[1])));
    if (!fn)
        return 4;
    const int r = fn();
    std::printf("loadtest: %s() returned %d (unsigned %u, 0x%08X)\nloadtest: exit=0\n", argv[1], r, (unsigned)r, (unsigned)r);
    std::fflush(stdout);
    return 0;
}
#else
BOOL WINAPI DllMain(HMODULE module, DWORD reason, LPVOID)
{
    if (reason == DLL_PROCESS_ATTACH)
        DisableThreadLibraryCalls(module);
    return TRUE;
}
#endif
