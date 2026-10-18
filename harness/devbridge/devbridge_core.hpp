// devbridge_core.hpp: engine-agnostic devbridge core (wire protocol v1, see PROTOCOL.md).
//
// A file-based command channel for tests. The harness drops cmd-<seq>.txt files into
// <exe dir>\..\SAVE\devbridge\ and reads replies from the append-only log.txt there.
// Active only if <exe dir>\devbridge.enabled exists; otherwise every call is a no-op.
//
// Threading: everything here is main-thread only: DevbridgeInit, DevbridgeShutdown, DevbridgeTick,
// Harness, DevbridgeData and the Register calls. Until the first Tick the thread that called Init owns the
// core; the first Tick fixes the owner for good (ev=devbridge_thread_mismatch if it is not the Init
// thread). Calls from any other thread are dropped and counted (ev=devbridge_wrong_thread); debug builds
// also assert() that Shutdown runs on the owner. Handlers run inside DevbridgeTick, on that thread.
//
// No exception escapes this API: a throwing handler becomes "ack ... ok=0 err=\"exception: ...\"".
//
// Portable C++20 (libstdc++ on Linux, MSVC STL via clang-cl /MD on i686 Windows). No Windows
// headers. Paths are UTF-8 std::strings.
#pragma once

#include <cstddef>
#include <cstdint>
#include <functional>
#include <memory>
#include <optional>
#include <string>
#include <string_view>
#include <vector>

namespace devbridge {

inline constexpr int kProtocolVersion = 1;
inline constexpr std::uint64_t kPollEveryFrames = 10;  // directory poll cadence (frames)
inline constexpr std::size_t kMaxCmdBytes = 64 * 1024;  // larger cmd files are rejected
inline constexpr std::size_t kMaxFilesPerPoll = 64;     // cmd files read per poll
inline constexpr double kDefaultTimeoutS = 60.0;       // async command budget (wall clock)
inline constexpr int kMaxReadRetries = 5;              // polls before an unreadable file is dropped
inline constexpr double kPendingBeatS = 5.0;           // ev=pending keep-alive period for a pending command (D111)

struct Cmd {
  std::string id;                 // [A-Za-z0-9_.:-]{1,64}
  std::string verb;               // second token, verbatim
  std::vector<std::string> args;  // tokens after the verb, quotes removed
  std::string raw;                // rest of the line after the verb, verbatim, trimmed
  std::uint64_t seq = 0;          // from the file name
};

// Result of a handler. kv is appended to the ack verbatim; build values with DevbridgeQuote.
// The ack keys id/ok/verb/err are reserved. Ack line (D111): ack id=<id> ok=1|0 [err="<text>"] verb=<verb> <kv>. pending=true is only meaningful from an async poll
// (meaning "still running; my budget is timeout_s seconds from the command's start"); from a
// sync handler it is an error (ack ok=0).
struct CmdResult {
  bool ok = true;
  std::string kv;
  std::string err;
  bool pending = false;
  double timeout_s = kDefaultTimeoutS;

  static CmdResult Ok(std::string kv = {}) { return CmdResult{true, std::move(kv), {}, false, kDefaultTimeoutS}; }
  static CmdResult Fail(std::string err, std::string kv = {}) {
    return CmdResult{false, std::move(kv), std::move(err), false, kDefaultTimeoutS};
  }
  static CmdResult Pending(double timeout_s = kDefaultTimeoutS) { return CmdResult{true, {}, {}, true, timeout_s}; }
};

using SyncHandler = std::function<CmdResult(const Cmd&)>;
// Called once when the command starts (framesWaited = 0) and then once per tick (every frame)
// until it returns a CmdResult with pending=false. std::nullopt means "still pending".
using AsyncPoll = std::function<std::optional<CmdResult>(const Cmd&, int framesWaited)>;

// Filesystem seam (tests inject a fake). Paths are UTF-8.
struct Fs {
  virtual ~Fs() = default;
  virtual bool Exists(const std::string& path) = 0;
  virtual bool CreateDirs(const std::string& dir) = 0;                 // true if the dir exists afterwards
  virtual std::vector<std::string> List(const std::string& dir) = 0;  // entry names (no dir part)
  virtual std::optional<std::string> Read(const std::string& path, std::size_t maxBytes) = 0;  // <= maxBytes+1 bytes
  virtual bool Remove(const std::string& path) = 0;                    // true if gone afterwards
  virtual bool OpenLog(const std::string& path) = 0;                   // append mode, opened once
  virtual bool AppendLine(std::string_view line) = 0;                  // writes line + '\n', flushes
  virtual void CloseLog() = 0;
};
std::unique_ptr<Fs> MakeStdFs();  // std::filesystem + fstream

// Helpers (exposed for tests and track code).
std::string Join(std::string_view dir, std::string_view name);
std::string DirForExe(std::string_view exeDir);     // <exeDir>/../SAVE/devbridge, normalized
std::string MarkerForExe(std::string_view exeDir);  // <exeDir>/devbridge.enabled
std::string CmdFileName(std::uint64_t seq);         // cmd-0000000042.txt
std::optional<std::uint64_t> ParseCmdFileName(std::string_view name);  // nullopt unless cmd-<digits>.txt
bool IsCmdFileName(std::string_view name);          // cmd-*.txt (any middle)
bool ValidId(std::string_view id);
std::string Quote(std::string_view v);              // same as DevbridgeQuote (quotes only when needed)
std::string QuoteAlways(std::string_view v);        // always "...", with \" and \\ escaped (ack err values)
std::string FormatSeconds(double s);                // "%.3f", locale-independent
// Shell-like tokenizer used for command args: whitespace-separated; "..." groups (may appear
// anywhere in a token); inside quotes \" -> " and \\ -> \, any other backslash is literal.
bool Tokenize(std::string_view s, std::vector<std::string>& out, std::string* err);

struct ParsedCmd {
  Cmd cmd;
  bool hasId = false;  // cmd.id is valid (an ack can be sent)
  std::string error;   // empty when the command is well formed
};
ParsedCmd ParseCmdText(std::string_view fileContent, std::uint64_t seq);

}  // namespace devbridge

// Lifecycle. exeDir is the directory containing the game exe (UTF-8).
void DevbridgeInit(const char* exeDir);
void DevbridgeInitWithFs(const char* exeDir, std::unique_ptr<devbridge::Fs> fs,
                         std::function<std::int64_t()> wallMs = {});
void DevbridgeShutdown();  // acks queued/pending commands with err="shutdown", closes the log, clears handlers
bool DevbridgeActive();

void DevbridgeTick(double gameSeconds);  // call every frame from the platform tick, main thread

// Re-registering a verb replaces it (sync and async share one namespace; user verbs override
// the built-ins). Registration is recorded even before Init.
void DevbridgeRegister(const char* verb, std::function<devbridge::CmdResult(const devbridge::Cmd&)> fn);
void DevbridgeRegisterAsync(const char* verb,
                            std::function<std::optional<devbridge::CmdResult>(const devbridge::Cmd&, int framesWaited)> poll);

void Harness(std::string_view kv);                        // one line: HARNESS t=.. wall=.. <kv>
void DevbridgeData(std::string_view id, std::string_view kv);  // one line: ... data id=<id> <kv>
void DevbridgeSetMirror(std::function<void(const std::string& line)> fn);  // e.g. module logger
std::string DevbridgeQuote(std::string_view v);
