// host_sim: runs the real devbridge core (real filesystem) in a simulated frame loop, so the
// Python client can be tested end to end without the game.
//
//   host_sim <exe_dir> [--fps N] [--frames N] [--max-wall-s S]
//
// <exe_dir> plays the game's EXE directory: the bridge is active only if
// <exe_dir>/devbridge.enabled exists, and it uses <exe_dir>/../SAVE/devbridge/.
// Exit codes: 0 after `quit` or --frames; 5 when --max-wall-s elapses; 64 on usage errors.
//
// Fake verbs (besides the core built-ins ping/echo/sleep_frames/seq):
//   state            -> state=menu base=- system=- ship=- hull=-1 cash=0 paused=0 ...
//   quit             -> ack, then the loop exits before the next frame (like the selftest DLL)
//   lines <n>        -> n data lines (i=<k> text="line <k>"), then ack count=<n>
//   throw            -> handler throws std::runtime_error("boom")
//   never [timeout]  -> async verb that never completes (budget = timeout seconds, default 60)
//   emit <payload>   -> writes <payload> as its own HARNESS line, then acks
#include <chrono>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <stdexcept>
#include <string>
#include <thread>

#include "../devbridge_core.hpp"

namespace {

bool g_quit = false;

[[noreturn]] void Usage() {
  std::fprintf(stderr, "usage: host_sim <exe_dir> [--fps N] [--frames N] [--max-wall-s S]\n");
  std::exit(64);
}

void RegisterFakeVerbs() {
  using devbridge::Cmd;
  using devbridge::CmdResult;
  DevbridgeRegister("state", [](const Cmd&) {
    return CmdResult::Ok("state=menu base=- system=- ship=- hull=-1 cash=0 paused=0 base_id=0 system_id=0 ship_id=0");
  });
  DevbridgeRegister("quit", [](const Cmd&) {
    g_quit = true;
    return CmdResult::Ok();
  });
  DevbridgeRegister("lines", [](const Cmd& c) {
    const int n = c.args.empty() ? 0 : std::atoi(c.args[0].c_str());
    if (n < 0 || n > 1000) return CmdResult::Fail("usage: lines <0..1000>");
    for (int i = 1; i <= n; ++i)
      DevbridgeData(c.id, "i=" + std::to_string(i) + " text=" + DevbridgeQuote("line " + std::to_string(i)));
    return CmdResult::Ok("count=" + std::to_string(n));
  });
  DevbridgeRegister("throw", [](const Cmd&) -> CmdResult { throw std::runtime_error("boom"); });
  DevbridgeRegisterAsync("never", [](const Cmd& c, int frames) -> std::optional<CmdResult> {
    if (frames == 0) return CmdResult::Pending(c.args.empty() ? devbridge::kDefaultTimeoutS : std::atof(c.args[0].c_str()));
    return std::nullopt;
  });
  DevbridgeRegister("emit", [](const Cmd& c) {
    Harness(c.raw);
    return CmdResult::Ok();
  });
}

}  // namespace

int main(int argc, char** argv) {
  if (argc < 2) Usage();
  const char* exeDir = argv[1];
  double fps = 200;
  long long maxFrames = -1;
  double maxWall = 120;
  for (int i = 2; i < argc; ++i) {
    const std::string a = argv[i];
    if (i + 1 >= argc) Usage();
    if (a == "--fps") {
      fps = std::atof(argv[++i]);
    } else if (a == "--frames") {
      maxFrames = std::atoll(argv[++i]);
    } else if (a == "--max-wall-s") {
      maxWall = std::atof(argv[++i]);
    } else {
      Usage();
    }
  }
  if (fps <= 0 || fps > 10000) Usage();

  RegisterFakeVerbs();
  DevbridgeInit(exeDir);
  std::fprintf(stderr, "host_sim: devbridge %s, fps=%.0f\n", DevbridgeActive() ? "active" : "inactive", fps);

  const auto start = std::chrono::steady_clock::now();
  const auto dt = std::chrono::duration<double>(1.0 / fps);
  double gameSeconds = 0;
  for (long long frame = 0; maxFrames < 0 || frame < maxFrames; ++frame) {
    if (g_quit) {  // quit acked during the previous frame: exit before running another one
      DevbridgeShutdown();
      std::fprintf(stderr, "host_sim: quit\n");
      return 0;
    }
    gameSeconds += dt.count();
    DevbridgeTick(gameSeconds);
    if (std::chrono::steady_clock::now() - start > std::chrono::duration<double>(maxWall)) {
      DevbridgeShutdown();
      std::fprintf(stderr, "host_sim: max wall time reached\n");
      return 5;
    }
    std::this_thread::sleep_for(dt);
  }
  DevbridgeShutdown();
  return 0;
}
