// src/module/hello_b/hello_b.cpp: Track B shape smoke DLL (plain dacom-style DLL, no FLUF).
//
// Proves the toolchain end to end: built with clang-cl i686 /MD, links Common.dll through FLSDK's
// FLCoreCommon.lib, loads under Wine, and calls into the game's own code. FlmodSelfTest() returns
// CreateID("li02") (expected 2745692751, R3 §10) and writes it to hello_b.log in the current dir.
#include <FLCore/FLCoreDefs.hpp>

#include <cstdio>

BOOL WINAPI DllMain(HMODULE module, DWORD reason, LPVOID /*reserved*/)
{
    if (reason == DLL_PROCESS_ATTACH)
    {
        DisableThreadLibraryCalls(module);
    }
    return TRUE;
}

extern "C" __declspec(dllexport) int FlmodSelfTest()
{
    const u32 id = CreateID("li02");

    char line[64];
    std::snprintf(line, sizeof(line), "hello_b CreateID(li02)=%u\n", static_cast<unsigned>(id));

    if (FILE* f = std::fopen("hello_b.log", "w"))
    {
        std::fputs(line, f);
        std::fclose(f);
    }
    std::fputs(line, stdout);
    std::fflush(stdout);
    return static_cast<int>(id);
}
