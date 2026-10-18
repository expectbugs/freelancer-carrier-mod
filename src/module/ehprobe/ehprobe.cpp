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
