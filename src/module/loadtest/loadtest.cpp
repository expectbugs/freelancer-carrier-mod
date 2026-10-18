// src/module/loadtest/loadtest.cpp: tiny win32 console tool for load proofs without the game.
//   loadtest.exe <dll> [export]
// LoadLibraryA(<dll>); if <export> is given, GetProcAddress it and call it as `int __cdecl fn()`.
// Prints the load address, the call result and the exit code. Exit codes: 0 ok, 2 usage,
// 3 LoadLibrary failed, 4 export not found.
#include <windows.h>

#include <cstdio>

namespace {

int finish(int code)
{
    std::printf("loadtest: exit=%d\n", code);
    std::fflush(stdout);
    return code;
}

}  // namespace

int main(int argc, char** argv)
{
    if (argc < 2)
    {
        std::printf("usage: loadtest.exe <dll> [export]\n");
        return finish(2);
    }

    HMODULE module = LoadLibraryA(argv[1]);
    if (!module)
    {
        std::printf("loadtest: LoadLibraryA(%s) failed, GetLastError=%lu\n", argv[1], GetLastError());
        return finish(3);
    }
    std::printf("loadtest: loaded %s at %p\n", argv[1], static_cast<void*>(module));
    std::fflush(stdout);

    int code = 0;
    if (argc >= 3)
    {
        FARPROC proc = GetProcAddress(module, argv[2]);
        if (!proc)
        {
            std::printf("loadtest: GetProcAddress(%s) failed, GetLastError=%lu\n", argv[2], GetLastError());
            code = 4;
        }
        else
        {
            using Fn = int(__cdecl*)();
            const int result = reinterpret_cast<Fn>(reinterpret_cast<void*>(proc))();
            std::printf("loadtest: %s() returned %d (unsigned %u, 0x%08X)\n", argv[2], result,
                        static_cast<unsigned>(result), static_cast<unsigned>(result));
        }
    }

    FreeLibrary(module);
    return finish(code);
}
