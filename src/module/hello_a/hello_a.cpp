// src/module/hello_a/hello_a.cpp: Track A shape smoke module (minimal FlufCombinedModule).
//
// Proves the FLUF ABI must-match build: it includes FLUF's public headers, links FLUF.lib and the
// FLUF dev package, and exports GetMajorVersion / GetMinorVersion / ModuleFactory through
// SETUP_MODULE. On load FLUF calls OnApplicationStart, which logs CreateID("li02") (2745692751).
#include <Common/FlufCombinedModule.hpp>
#include <Common/Logging.hpp>
#include <Fluf.hpp>

class HelloA final : public FlufCombinedModule
{
    void OnApplicationStart() override
    {
        INFO("hello_a loaded CreateID(li02)={}", CreateID("li02"));
    }

  public:
    static constexpr std::string_view moduleName = "hello_a";
    std::string_view GetModuleName() override { return moduleName; }
};

BOOL WINAPI DllMain(const HMODULE module, [[maybe_unused]] const DWORD reason, [[maybe_unused]] LPVOID reserved)
{
    DisableThreadLibraryCalls(module);
    return TRUE;
}

SETUP_MODULE(HelloA, ModuleMajorVersion::Two, ModuleMinorVersion::Zero);
