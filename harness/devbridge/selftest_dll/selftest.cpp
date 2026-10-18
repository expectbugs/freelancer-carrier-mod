// selftest.cpp: THROWAWAY Track-B-style dacom DLL that proves the devbridge core in game before
// the track spikes exist. Listed in EXE/dacom.ini [Libraries]; all work happens in DllMain attach.
// Inert unless <exe dir>\devbridge.enabled exists. The track spike DLLs replace it.
//
// Hook: Freelancer.exe's per-frame function 0x5B2890, void __cdecl (double dt), main thread, runs
// every frame (menus, docked, space, F1 pause). Its first 5 bytes are whole instructions with no
// relative operands (51 push ecx / 55 push ebp / 56 push esi / 33 ED xor ebp,ebp), so the trampoline
// is a plain copy + jmp back to 0x5B2895. The bytes are verified before patching; on mismatch the
// DLL logs ev=selftest_hook_failed and stays inert.
#ifndef WIN32_LEAN_AND_MEAN
#define WIN32_LEAN_AND_MEAN
#endif
#ifndef NOMINMAX
#define NOMINMAX
#endif
#include <windows.h>

#include <algorithm>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <optional>
#include <string>
#include <vector>

#include "../devbridge_core.hpp"

namespace {

using devbridge::Cmd;
using devbridge::CmdResult;

// ---- Freelancer.exe facts (HDE exe: ImageBase 0x400000, relocations stripped) ---------------
constexpr std::uintptr_t kExeBase = 0x400000;
constexpr std::uintptr_t kFrameFn = 0x5B2890;  // void __cdecl Frame(double dt)
constexpr unsigned char kFramePrologue[5] = {0x51, 0x55, 0x56, 0x33, 0xED};
constexpr std::size_t kStolen = sizeof kFramePrologue;
constexpr std::uintptr_t kIsPausedFn = 0x42D740;   // bool __cdecl IsPaused(void)
constexpr std::uintptr_t kLoadGameFn = 0x5B2C70;   // void __cdecl LoadGame(const CHARACTER_ID&, bool)
constexpr std::uintptr_t kIServerPtr = 0x67ECD0;   // IServer* (SP: rpclocal IServerImpl)
constexpr std::uintptr_t kSystemId = 0x673354;     // client mirrors (R5 §1.2)
constexpr std::uintptr_t kBaseId = 0x673358;
constexpr std::uintptr_t kCash = 0x673364;
constexpr std::uintptr_t kShipId = 0x673378;

using FrameFn = void(__cdecl*)(double);
using IsPausedFn = bool(__cdecl*)();
struct CharacterId {
  char file[512];
};
using LoadGameFn = void(__cdecl*)(const CharacterId&, bool);
using GetUserDataPathFn = bool(__cdecl*)(char*);  // Common.dll ?GetUserDataPath@@YA_NQAD@Z

FrameFn g_original = nullptr;  // trampoline
double g_gameSeconds = 0;
bool g_quit = false;
LARGE_INTEGER g_qpcFreq{};
LARGE_INTEGER g_lastFrame{};
bool g_perfActive = false;
LARGE_INTEGER g_perfStart{};
std::vector<float> g_perfFrameMs;

template <class T>
T ReadAbs(std::uintptr_t addr) {
  T v;
  std::memcpy(&v, reinterpret_cast<const void*>(addr), sizeof v);
  return v;
}

std::string Hex(const unsigned char* p, std::size_t n) {
  static const char* digits = "0123456789ABCDEF";
  std::string s;
  for (std::size_t i = 0; i < n; ++i) {
    s += digits[p[i] >> 4];
    s += digits[p[i] & 15];
  }
  return s;
}

// Locale-independent fixed-point formatting (the game's CRT locale is not ours to trust).
std::string Fixed(double v, int decimals) {
  if (!(v == v) || v > 1e12 || v < -1e12) return "nan";
  long long scale = 1;
  for (int i = 0; i < decimals; ++i) scale *= 10;
  const bool neg = v < 0;
  const long long total = static_cast<long long>((neg ? -v : v) * static_cast<double>(scale) + 0.5);
  std::string frac = std::to_string(total % scale);
  frac.insert(0, static_cast<std::size_t>(decimals) - frac.size(), '0');
  return std::string(neg && total ? "-" : "") + std::to_string(total / scale) + (decimals ? "." + frac : "");
}

double QpcSeconds(const LARGE_INTEGER& from, const LARGE_INTEGER& to) {
  return g_qpcFreq.QuadPart ? static_cast<double>(to.QuadPart - from.QuadPart) / static_cast<double>(g_qpcFreq.QuadPart)
                            : 0.0;
}

std::optional<double> ParseDouble(const std::string& s) {
  if (s.empty() || s.size() > 32) return std::nullopt;
  char* end = nullptr;
  const double v = std::strtod(s.c_str(), &end);
  if (end == nullptr || *end != '\0') return std::nullopt;
  return v;
}

// ---- verbs -----------------------------------------------------------------------------------

CmdResult VerbState(const Cmd&) {
  const auto base = ReadAbs<std::uint32_t>(kBaseId);
  const auto system = ReadAbs<std::uint32_t>(kSystemId);
  const auto ship = ReadAbs<std::uint32_t>(kShipId);
  const auto cash = ReadAbs<std::int32_t>(kCash);
  const bool paused = reinterpret_cast<IsPausedFn>(kIsPausedFn)();
  const char* state = base != 0 ? "docked" : (system != 0 ? "space" : "menu");
  // rank via Server.dll pub::Player::GetRank(const uint& client, int& rank); SP client id is 1. Only in game.
  int rank = -1;
  int rankRc = -1;
  if (base != 0 || system != 0) {
    using GetRankFn = int(__cdecl*)(const unsigned int&, int&);
    if (HMODULE srv = GetModuleHandleA("server.dll")) {
      if (auto fn = reinterpret_cast<GetRankFn>(GetProcAddress(srv, "?GetRank@Player@pub@@YAHABIAAH@Z"))) {
        const unsigned int client = 1;
        rankRc = fn(client, rank);
      }
    }
  }
  return CmdResult::Ok(std::string("state=") + state + " base=- system=- ship=- hull=-1 cash=" + std::to_string(cash) +
                       " paused=" + (paused ? "1" : "0") + " base_id=" + std::to_string(base) +
                       " system_id=" + std::to_string(system) + " ship_id=" + std::to_string(ship) +
                       " rank=" + std::to_string(rank) + " rank_rc=" + std::to_string(rankRc));
}

CmdResult VerbQuit(const Cmd&) {
  g_quit = true;  // ExitProcess at the start of the next frame, after this ack is flushed
  return CmdResult::Ok("exit_next_tick=1");
}

CmdResult VerbShot(const Cmd&) { return CmdResult::Fail("unsupported", "hint=harness/shot.sh"); }

CmdResult VerbVmstat(const Cmd&) {
  SYSTEM_INFO si{};
  GetSystemInfo(&si);
  const std::uint64_t lo = std::max<std::uint64_t>(0x10000, reinterpret_cast<std::uintptr_t>(si.lpMinimumApplicationAddress));
  const std::uint64_t hi = static_cast<std::uint64_t>(reinterpret_cast<std::uintptr_t>(si.lpMaximumApplicationAddress)) + 1;
  std::uint64_t freeB = 0, largest = 0, committed = 0, reserved = 0;
  std::uint64_t addr = lo;
  while (addr < hi) {
    MEMORY_BASIC_INFORMATION mbi{};
    if (VirtualQuery(reinterpret_cast<LPCVOID>(static_cast<std::uintptr_t>(addr)), &mbi, sizeof mbi) == 0) break;
    const std::uint64_t base = reinterpret_cast<std::uintptr_t>(mbi.BaseAddress);
    std::uint64_t end = base + mbi.RegionSize;
    if (end > hi) end = hi;
    if (end <= addr) break;
    const std::uint64_t size = end - addr;
    if (mbi.State == MEM_FREE) {
      freeB += size;
      largest = std::max(largest, size);
    } else if (mbi.State == MEM_COMMIT) {
      committed += size;
    } else if (mbi.State == MEM_RESERVE) {
      reserved += size;
    }
    addr = end;
  }
  char vamax[24];
  std::snprintf(vamax, sizeof vamax, "0x%08llX", static_cast<unsigned long long>(hi - 1));
  constexpr std::uint64_t mb = 1024 * 1024;
  return CmdResult::Ok("va_free_mb=" + std::to_string(freeB / mb) + " va_largest_free_mb=" + std::to_string(largest / mb) +
                       " va_committed_mb=" + std::to_string(committed / mb) +
                       " va_reserved_mb=" + std::to_string(reserved / mb) + " va_max=" + vamax);
}

// perf <seconds>: samples frame times in the frame detour; fps_p1 = 1000 / (99th-percentile frame ms).
std::optional<CmdResult> PollPerf(const Cmd& cmd, int frames) {
  const std::optional<double> secs = cmd.args.size() == 1 ? ParseDouble(cmd.args[0]) : std::nullopt;
  if (!secs || *secs < 0.1 || *secs > 600) {
    g_perfActive = false;
    return CmdResult::Fail("usage: perf <seconds 0.1..600>");
  }
  LARGE_INTEGER now;
  QueryPerformanceCounter(&now);
  if (frames == 0) {
    g_perfFrameMs.clear();
    g_perfFrameMs.reserve(static_cast<std::size_t>(*secs * 400));
    g_perfStart = now;
    g_perfActive = true;
    return CmdResult::Pending(*secs + 30);
  }
  const double elapsed = QpcSeconds(g_perfStart, now);
  if (elapsed < *secs) return std::nullopt;
  g_perfActive = false;
  std::vector<float> ms = g_perfFrameMs;
  if (ms.empty()) return CmdResult::Fail("no frames sampled");
  std::sort(ms.begin(), ms.end());
  const std::size_t n = ms.size();
  const std::size_t p99 = std::min(n - 1, static_cast<std::size_t>((static_cast<double>(n) * 0.99 + 0.999999)) - 1);
  return CmdResult::Ok("fps_avg=" + Fixed(static_cast<double>(n) / elapsed, 1) + " fps_p1=" + Fixed(1000.0 / ms[p99], 1) +
                       " frame_ms_max=" + Fixed(ms.back(), 2) + " frames=" + std::to_string(n) +
                       " window_s=" + Fixed(elapsed, 3));
}

// EXPERIMENTAL load <savefile.fl>: calls LoadGame (0x5B2C70) the way adoxa's console `load` does,
// deferred one tick. ABI from disassembly (cdecl, CHARACTER_ID = char[512]); main-menu behaviour
// is UNVERIFIED.
std::optional<CmdResult> PollLoad(const Cmd& cmd, int frames) {
  if (cmd.args.size() != 1) return CmdResult::Fail("usage: load <savefile.fl>");
  std::string file = cmd.args[0];
  if (file.empty() || file.size() > 200 || file.find_first_of("\\/:") != std::string::npos || file.find("..") != std::string::npos)
    return CmdResult::Fail("bad save file name (bare file name expected)");
  if (file.size() < 3 || _stricmp(file.c_str() + file.size() - 3, ".fl") != 0) file += ".fl";
  if (frames == 0) {
    const HMODULE common = GetModuleHandleA("common.dll");
    const auto gudp = common ? reinterpret_cast<GetUserDataPathFn>(GetProcAddress(common, "?GetUserDataPath@@YA_NQAD@Z"))
                             : nullptr;
    if (gudp == nullptr) return CmdResult::Fail("GetUserDataPath not found");
    char dir[1024] = {};
    if (!gudp(dir)) return CmdResult::Fail("GetUserDataPath failed");
    const std::string full = std::string(dir) + "\\Accts\\SinglePlayer\\" + file;
    if (GetFileAttributesA(full.c_str()) == INVALID_FILE_ATTRIBUTES)
      return CmdResult::Fail("save not found", "path=" + DevbridgeQuote(full));
    return std::nullopt;  // call on the next tick
  }
  CharacterId cid{};
  std::memcpy(cid.file, file.c_str(), file.size() + 1);
  const bool haveServer = ReadAbs<std::uintptr_t>(kIServerPtr) != 0;  // LoadGame derefs it when the flag is set
  reinterpret_cast<LoadGameFn>(kLoadGameFn)(cid, haveServer);
  return CmdResult::Ok("file=" + DevbridgeQuote(file) + " skip_autosave=" + (haveServer ? "1" : "0") + " experimental=1");
}

// ---- frame hook ------------------------------------------------------------------------------

void __cdecl FrameDetour(double dt) {
  if (g_quit) {
    DevbridgeShutdown();
    ExitProcess(0);
  }
  g_original(dt);
  LARGE_INTEGER now;
  QueryPerformanceCounter(&now);
  if (g_perfActive && g_lastFrame.QuadPart != 0) g_perfFrameMs.push_back(static_cast<float>(QpcSeconds(g_lastFrame, now) * 1000.0));
  g_lastFrame = now;
  if (dt > 0 && dt < 10) g_gameSeconds += dt;
  DevbridgeTick(g_gameSeconds);
  // ev=hb every 10 s of wall time (CONVENTIONS §4; W1-CORE emits the same): lets the harness tell a frozen game
  // from an idle one even when nothing is pending. The frame function also runs while paused (F1).
  static LARGE_INTEGER lastHb{};
  if (lastHb.QuadPart == 0) lastHb = now;
  if (QpcSeconds(lastHb, now) >= 10.0) {
    lastHb = now;
    Harness("ev=hb");
  }
}

bool InstallFrameHook() {
  if (reinterpret_cast<std::uintptr_t>(GetModuleHandleW(nullptr)) != kExeBase) {
    Harness("ev=selftest_hook_failed reason=\"exe base is not 0x400000\"");
    return false;
  }
  auto* target = reinterpret_cast<unsigned char*>(kFrameFn);
  MEMORY_BASIC_INFORMATION mbi{};
  if (VirtualQuery(target, &mbi, sizeof mbi) == 0 || mbi.State != MEM_COMMIT) {
    Harness("ev=selftest_hook_failed reason=\"frame function not mapped\"");
    return false;
  }
  if (std::memcmp(target, kFramePrologue, kStolen) != 0) {
    Harness("ev=selftest_hook_failed bytes=" + Hex(target, 8));
    return false;
  }
  auto* tramp = static_cast<unsigned char*>(VirtualAlloc(nullptr, 32, MEM_COMMIT | MEM_RESERVE, PAGE_EXECUTE_READWRITE));
  if (tramp == nullptr) {
    Harness("ev=selftest_hook_failed reason=VirtualAlloc");
    return false;
  }
  std::memcpy(tramp, target, kStolen);
  tramp[kStolen] = 0xE9;  // jmp rel32 back to the rest of the original
  const auto back = static_cast<std::int32_t>(reinterpret_cast<std::uintptr_t>(target + kStolen) -
                                              reinterpret_cast<std::uintptr_t>(tramp + kStolen + 5));
  std::memcpy(tramp + kStolen + 1, &back, 4);
  FlushInstructionCache(GetCurrentProcess(), tramp, kStolen + 5);
  g_original = reinterpret_cast<FrameFn>(tramp);

  DWORD old = 0;
  if (!VirtualProtect(target, kStolen, PAGE_EXECUTE_READWRITE, &old)) {
    Harness("ev=selftest_hook_failed reason=VirtualProtect");
    return false;
  }
  unsigned char patch[kStolen];
  patch[0] = 0xE9;
  const auto rel = static_cast<std::int32_t>(reinterpret_cast<std::uintptr_t>(&FrameDetour) -
                                             reinterpret_cast<std::uintptr_t>(target + 5));
  std::memcpy(patch + 1, &rel, 4);
  std::memcpy(target, patch, kStolen);
  VirtualProtect(target, kStolen, old, &old);
  FlushInstructionCache(GetCurrentProcess(), target, kStolen);
  char where[16];
  std::snprintf(where, sizeof where, "0x%08X", static_cast<unsigned>(reinterpret_cast<std::uintptr_t>(tramp)));
  Harness(std::string("ev=selftest_hooked fn=0x5B2890 stolen=5 trampoline=") + where);
  return true;
}

std::string ExeDirUtf8() {
  std::wstring buf(32768, L'\0');
  const DWORD n = GetModuleFileNameW(nullptr, buf.data(), static_cast<DWORD>(buf.size()));
  if (n == 0 || n >= buf.size()) return {};
  buf.resize(n);
  const std::size_t slash = buf.find_last_of(L"\\/");
  if (slash == std::wstring::npos) return {};
  buf.resize(slash);
  const int len = WideCharToMultiByte(CP_UTF8, 0, buf.c_str(), static_cast<int>(buf.size()), nullptr, 0, nullptr, nullptr);
  std::string out(static_cast<std::size_t>(len > 0 ? len : 0), '\0');
  if (len > 0) WideCharToMultiByte(CP_UTF8, 0, buf.c_str(), static_cast<int>(buf.size()), out.data(), len, nullptr, nullptr);
  return out;
}

void Start() {
  const std::string exeDir = ExeDirUtf8();
  if (exeDir.empty()) return;
  DevbridgeInit(exeDir.c_str());
  if (!DevbridgeActive()) return;  // no devbridge.enabled: stay inert
  QueryPerformanceFrequency(&g_qpcFreq);
  DevbridgeRegister("state", VerbState);
  DevbridgeRegister("quit", VerbQuit);
  DevbridgeRegister("shot", VerbShot);
  DevbridgeRegister("vmstat", VerbVmstat);
  DevbridgeRegisterAsync("perf", PollPerf);
  DevbridgeRegisterAsync("load", PollLoad);
  if (!InstallFrameHook()) DevbridgeShutdown();  // the failure line is already in log.txt
}

}  // namespace

BOOL WINAPI DllMain(HINSTANCE inst, DWORD reason, LPVOID) {
  if (reason == DLL_PROCESS_ATTACH) {
    DisableThreadLibraryCalls(inst);
    try {
      Start();
    } catch (...) {
    }
  }
  return TRUE;
}
