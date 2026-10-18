// devbridge_core.cpp: implementation of the devbridge core (wire protocol v1, see PROTOCOL.md).
#include "devbridge_core.hpp"

#include <algorithm>
#include <atomic>
#include <chrono>
#include <cmath>
#include <deque>
#include <exception>
#include <filesystem>
#include <fstream>
#include <map>
#include <cassert>
#include <thread>
#include <utility>

namespace stdfs = std::filesystem;

namespace devbridge {
namespace {

bool IsWs(char c) { return c == ' ' || c == '\t' || c == '\r' || c == '\n' || c == '\v' || c == '\f'; }

std::string_view Trim(std::string_view s) {
  while (!s.empty() && IsWs(s.front())) s.remove_prefix(1);
  while (!s.empty() && IsWs(s.back())) s.remove_suffix(1);
  return s;
}

stdfs::path ToPath(std::string_view s) {
  std::u8string u(s.size(), u8'\0');
  std::transform(s.begin(), s.end(), u.begin(), [](char c) { return static_cast<char8_t>(c); });
  return stdfs::path(u);
}

std::string FromPath(const stdfs::path& p) {
  const std::u8string u = p.u8string();
  std::string s(u.size(), '\0');
  std::transform(u.begin(), u.end(), s.begin(), [](char8_t c) { return static_cast<char>(c); });
  return s;
}

// Replace control characters so a value can never break the line-based log.
std::string Sanitize(std::string_view v) {
  std::string s(v);
  for (char& c : s) {
    const auto u = static_cast<unsigned char>(c);
    if (u < 0x20 || u == 0x7f) c = ' ';
  }
  return s;
}

class StdFs final : public Fs {
 public:
  bool Exists(const std::string& path) override {
    std::error_code ec;
    return stdfs::exists(ToPath(path), ec);
  }
  bool CreateDirs(const std::string& dir) override {
    std::error_code ec;
    stdfs::create_directories(ToPath(dir), ec);
    return stdfs::is_directory(ToPath(dir), ec);
  }
  std::vector<std::string> List(const std::string& dir) override {
    std::vector<std::string> out;
    std::error_code ec;
    stdfs::directory_iterator it(ToPath(dir), ec);
    const stdfs::directory_iterator end;
    while (!ec && it != end) {
      out.push_back(FromPath(it->path().filename()));
      it.increment(ec);
    }
    return out;
  }
  std::optional<std::string> Read(const std::string& path, std::size_t maxBytes) override {
    std::ifstream f(ToPath(path), std::ios::binary);
    if (!f.is_open()) return std::nullopt;
    std::string s(maxBytes + 1, '\0');
    f.read(s.data(), static_cast<std::streamsize>(s.size()));
    if (f.bad()) return std::nullopt;
    s.resize(static_cast<std::size_t>(f.gcount()));
    return s;
  }
  bool Remove(const std::string& path) override {
    std::error_code ec;
    stdfs::remove(ToPath(path), ec);  // false + no error = already gone
    return !ec;
  }
  bool OpenLog(const std::string& path) override {
    log_.open(ToPath(path), std::ios::binary | std::ios::app);
    return log_.is_open();
  }
  bool AppendLine(std::string_view line) override {
    if (!log_.is_open()) return false;
    log_.clear();
    log_.write(line.data(), static_cast<std::streamsize>(line.size()));
    log_.put('\n');
    log_.flush();
    return static_cast<bool>(log_);
  }
  void CloseLog() override {
    if (log_.is_open()) log_.close();
  }

 private:
  std::ofstream log_;
};

// ---- core state ----------------------------------------------------------------------------

struct Entry {
  Cmd cmd;
  std::string file;
  bool hasId = true;
  std::string bad;  // non-empty: malformed command file
};

struct Pending {
  Cmd cmd;
  AsyncPoll poll;
  int frames = 0;
  std::int64_t startMs = 0;
  double timeoutS = kDefaultTimeoutS;
  std::int64_t lastBeatMs = 0;  // last ev=pending keep-alive (starts at startMs)
};

enum : unsigned { kRepDup = 1, kRepBad = 2, kRepRmFail = 4 };

struct Core {
  bool active = false;
  std::unique_ptr<Fs> fs;
  std::function<std::int64_t()> wallMs;
  std::function<void(const std::string&)> mirror;
  std::string dir;
  double t = 0;
  std::uint64_t frame = 0;
  std::uint64_t lastSeq = 0;
  std::deque<Entry> queue;
  std::optional<Pending> pending;
  std::map<std::string, SyncHandler, std::less<>> sync;
  std::map<std::string, AsyncPoll, std::less<>> async;
  std::map<std::string, unsigned, std::less<>> reported;  // file name -> kRep* already logged
  std::string readFailName;
  int readFailCount = 0;
  bool inTick = false;
  bool haveOwner = false;
  std::thread::id owner;
  bool haveInitThread = false;
  std::thread::id initThread;  // DevbridgeInit's thread: the owner until the first Tick fixes it
  std::uint64_t wrongThreadReported = 0;
};

Core& G() {
  static Core c;
  return c;
}

std::atomic<std::uint64_t> g_wrongThread{0};

// Main-thread rule: before the first Tick the Init thread is the owner, afterwards the Tick thread.
bool OnOwner() {
  Core& c = G();
  const std::thread::id me = std::this_thread::get_id();
  if (c.haveOwner ? me == c.owner : (!c.haveInitThread || me == c.initThread)) return true;
  g_wrongThread.fetch_add(1, std::memory_order_relaxed);
  return false;
}

std::int64_t Wall() {
  Core& c = G();
  if (c.wallMs) return c.wallMs();
  using namespace std::chrono;
  return duration_cast<milliseconds>(system_clock::now().time_since_epoch()).count();
}

void EmitLine(std::string_view payload) {
  Core& c = G();
  if (!c.active || !c.fs) return;
  std::string line = "HARNESS t=" + FormatSeconds(c.t) + " wall=" + std::to_string(Wall());
  const std::string p = Sanitize(Trim(payload));
  if (!p.empty()) {
    line += ' ';
    line += p;
  }
  c.fs->AppendLine(line);
  if (c.mirror) {
    try {
      c.mirror(line);
    } catch (...) {
    }
  }
}

// Ack key order (D111, CONVENTIONS §4): ack id=<id> ok=1|0 [err="<text>"] verb=<verb> [<result keys>...].
// err comes right after ok and is always double-quoted (\" and \\ escaped).
void Ack(const Cmd& cmd, const CmdResult& r) {
  std::string p = "ack id=" + cmd.id + (r.ok ? " ok=1" : " ok=0");
  if (!r.ok) p += " err=" + QuoteAlways(r.err.empty() ? std::string("error") : r.err);
  p += " verb=" + Quote(cmd.verb);
  if (!r.kv.empty()) {
    p += ' ';
    p += r.kv;
  }
  EmitLine(p);
}

void MarkReported(const std::string& name, unsigned bit, const std::string& payload) {
  unsigned& flags = G().reported[name];
  if (flags & bit) return;
  flags |= bit;
  EmitLine(payload);
}

void RemoveFile(const std::string& name) {
  Core& c = G();
  if (!c.fs->Remove(Join(c.dir, name))) MarkReported(name, kRepRmFail, "ev=fs_error op=remove file=" + Quote(name));
}

template <class F>
CmdResult Protect(F&& f) {
  try {
    return f();
  } catch (const std::exception& e) {
    return CmdResult::Fail(std::string("exception: ") + e.what());
  } catch (...) {
    return CmdResult::Fail("exception: unknown");
  }
}

template <class F>
std::optional<CmdResult> ProtectOpt(F&& f) {
  try {
    return f();
  } catch (const std::exception& e) {
    return CmdResult::Fail(std::string("exception: ") + e.what());
  } catch (...) {
    return CmdResult::Fail("exception: unknown");
  }
}

double SaneTimeout(double s) {
  if (!std::isfinite(s) || s <= 0) return kDefaultTimeoutS;
  return std::min(s, 86400.0);
}

// ---- built-in verbs ------------------------------------------------------------------------

CmdResult BuiltinPing(const Cmd&) { return CmdResult::Ok("pong=1"); }
CmdResult BuiltinEcho(const Cmd& cmd) { return CmdResult::Ok("text=" + Quote(cmd.raw)); }
CmdResult BuiltinSeq(const Cmd&) { return CmdResult::Ok("last_seq=" + std::to_string(G().lastSeq)); }

std::optional<CmdResult> BuiltinSleepFrames(const Cmd& cmd, int frames) {
  long long n = -1;
  if (cmd.args.size() == 1 && !cmd.args[0].empty() && cmd.args[0].size() <= 7 &&
      std::all_of(cmd.args[0].begin(), cmd.args[0].end(), [](char ch) { return ch >= '0' && ch <= '9'; })) {
    n = std::stoll(cmd.args[0]);
  }
  if (n < 0) return CmdResult::Fail("usage: sleep_frames <n>");
  if (frames >= n) return CmdResult::Ok("frames=" + std::to_string(n));
  return std::nullopt;
}

// ---- execution -----------------------------------------------------------------------------

void FinishOrPark(Pending p, const std::optional<CmdResult>& r) {
  Core& c = G();
  if (r && !r->pending) {
    Ack(p.cmd, *r);
    return;
  }
  if (r && r->pending) p.timeoutS = SaneTimeout(r->timeout_s);
  const std::int64_t now = Wall();
  if (now - p.startMs >= static_cast<std::int64_t>(p.timeoutS * 1000.0)) {
    Ack(p.cmd, CmdResult::Fail("timeout", "timeout_s=" + FormatSeconds(p.timeoutS)));
    return;
  }
  // keep-alive (D111): a command pending longer than kPendingBeatS says so every kPendingBeatS, so the log
  // keeps growing (the harness' hang signal) while a legitimate long command runs
  const std::int64_t beatMs = static_cast<std::int64_t>(kPendingBeatS * 1000.0);
  if (now - p.startMs >= beatMs && now - p.lastBeatMs >= beatMs) {
    p.lastBeatMs = now;
    EmitLine("ev=pending id=" + p.cmd.id + " verb=" + Quote(p.cmd.verb) +
             " elapsed_s=" + std::to_string((now - p.startMs) / 1000));
  }
  c.pending = std::move(p);
}

void StartAsync(const Cmd& cmd, AsyncPoll poll) {
  const std::int64_t start = Wall();
  Pending p{cmd, std::move(poll), 0, start, kDefaultTimeoutS, start};
  const std::optional<CmdResult> r = ProtectOpt([&] { return p.poll(p.cmd, 0); });
  FinishOrPark(std::move(p), r);
}

void PollPending() {
  Core& c = G();
  Pending p = std::move(*c.pending);
  c.pending.reset();
  ++p.frames;
  const std::optional<CmdResult> r = ProtectOpt([&] { return p.poll(p.cmd, p.frames); });
  FinishOrPark(std::move(p), r);
}

void RunSync(const Cmd& cmd, const SyncHandler& h) {
  CmdResult r = Protect([&] { return h(cmd); });
  if (r.pending) r = CmdResult::Fail("sync handler returned pending");
  Ack(cmd, r);
}

void Run(const Entry& e) {
  Core& c = G();
  if (!e.bad.empty()) {
    std::string ev = "ev=bad_cmd file=" + Quote(e.file) + " reason=" + Quote(e.bad);
    if (e.hasId) ev += " id=" + e.cmd.id;
    EmitLine(ev);
    if (e.hasId) Ack(e.cmd, CmdResult::Fail("bad_cmd: " + e.bad));
    return;
  }
  const Cmd& cmd = e.cmd;
  if (auto it = c.sync.find(cmd.verb); it != c.sync.end()) {
    const SyncHandler h = it->second;  // copy: the handler may re-register itself
    RunSync(cmd, h);
    return;
  }
  if (auto it = c.async.find(cmd.verb); it != c.async.end()) {
    StartAsync(cmd, it->second);
    return;
  }
  if (cmd.verb == "ping") return RunSync(cmd, BuiltinPing);
  if (cmd.verb == "echo") return RunSync(cmd, BuiltinEcho);
  if (cmd.verb == "seq") return RunSync(cmd, BuiltinSeq);
  if (cmd.verb == "sleep_frames") return StartAsync(cmd, BuiltinSleepFrames);
  Ack(cmd, CmdResult::Fail("unknown verb " + cmd.verb));
}

void Drain() {
  Core& c = G();
  while (c.active && !c.pending && !c.queue.empty()) {
    Entry e = std::move(c.queue.front());
    c.queue.pop_front();
    Run(e);
  }
}

void Scan() {
  Core& c = G();
  const std::vector<std::string> names = c.fs->List(c.dir);
  // Forget report flags for names that are no longer listed.
  for (auto it = c.reported.begin(); it != c.reported.end();) {
    if (std::find(names.begin(), names.end(), it->first) == names.end()) {
      it = c.reported.erase(it);
    } else {
      ++it;
    }
  }
  std::vector<std::pair<std::uint64_t, std::string>> cmds;
  for (const std::string& n : names) {
    if (!IsCmdFileName(n)) continue;
    const std::optional<std::uint64_t> seq = ParseCmdFileName(n);
    if (!seq) {
      MarkReported(n, kRepBad, "ev=bad_cmd file=" + Quote(n) + " reason=\"bad file name\"");
      RemoveFile(n);
      continue;
    }
    cmds.emplace_back(*seq, n);
  }
  std::sort(cmds.begin(), cmds.end());
  std::size_t taken = 0;
  for (const auto& [seq, n] : cmds) {
    if (seq <= c.lastSeq) {  // already processed (Wine delete lag) or stale
      MarkReported(n, kRepDup, "ev=cmd_dup file=" + Quote(n) + " last_seq=" + std::to_string(c.lastSeq));
      RemoveFile(n);
      continue;
    }
    if (taken >= kMaxFilesPerPoll) break;
    const std::optional<std::string> content = c.fs->Read(Join(c.dir, n), kMaxCmdBytes);
    if (!content) {
      if (c.readFailName == n) {
        ++c.readFailCount;
      } else {
        c.readFailName = n;
        c.readFailCount = 1;
      }
      if (c.readFailCount < kMaxReadRetries) break;  // keep seq order: retry this file next poll
      c.readFailName.clear();
      c.readFailCount = 0;
      c.lastSeq = seq;
      ++taken;
      EmitLine("ev=bad_cmd file=" + Quote(n) + " reason=unreadable");
      RemoveFile(n);
      continue;
    }
    c.readFailName.clear();
    c.readFailCount = 0;
    RemoveFile(n);
    c.lastSeq = seq;
    ++taken;
    Entry e;
    if (content->size() > kMaxCmdBytes) {
      e.hasId = false;
      e.bad = "too large";
    } else {
      ParsedCmd pc = ParseCmdText(*content, seq);
      e.cmd = std::move(pc.cmd);
      e.hasId = pc.hasId;
      e.bad = std::move(pc.error);
    }
    e.cmd.seq = seq;
    e.file = n;
    c.queue.push_back(std::move(e));
  }
}

}  // namespace

// ---- helpers -------------------------------------------------------------------------------

std::unique_ptr<Fs> MakeStdFs() { return std::make_unique<StdFs>(); }

std::string Join(std::string_view dir, std::string_view name) { return FromPath(ToPath(dir) / ToPath(name)); }

std::string DirForExe(std::string_view exeDir) {
  return FromPath((ToPath(exeDir) / ".." / "SAVE" / "devbridge").lexically_normal());
}

std::string MarkerForExe(std::string_view exeDir) { return Join(exeDir, "devbridge.enabled"); }

std::string CmdFileName(std::uint64_t seq) {
  std::string digits = std::to_string(seq);
  if (digits.size() < 10) digits.insert(0, 10 - digits.size(), '0');
  return "cmd-" + digits + ".txt";
}

bool IsCmdFileName(std::string_view name) {
  return name.size() >= 8 && name.substr(0, 4) == "cmd-" && name.substr(name.size() - 4) == ".txt";
}

std::optional<std::uint64_t> ParseCmdFileName(std::string_view name) {
  if (!IsCmdFileName(name)) return std::nullopt;
  const std::string_view digits = name.substr(4, name.size() - 8);
  if (digits.empty() || digits.size() > 19) return std::nullopt;
  std::uint64_t v = 0;
  for (char ch : digits) {
    if (ch < '0' || ch > '9') return std::nullopt;
    v = v * 10 + static_cast<std::uint64_t>(ch - '0');
  }
  return v;
}

bool ValidId(std::string_view id) {
  if (id.empty() || id.size() > 64) return false;
  return std::all_of(id.begin(), id.end(), [](char ch) {
    return (ch >= 'a' && ch <= 'z') || (ch >= 'A' && ch <= 'Z') || (ch >= '0' && ch <= '9') || ch == '_' ||
           ch == '-' || ch == '.' || ch == ':';
  });
}

std::string Quote(std::string_view v) {
  const std::string s = Sanitize(v);
  bool need = s.empty();
  for (char ch : s) {
    if (ch == ' ' || ch == '"' || ch == '=') {
      need = true;
      break;
    }
  }
  if (!need) return s;
  std::string out = "\"";
  for (char ch : s) {
    if (ch == '"' || ch == '\\') out += '\\';
    out += ch;
  }
  out += '"';
  return out;
}

std::string QuoteAlways(std::string_view v) {
  const std::string s = Sanitize(v);
  std::string out = "\"";
  for (char ch : s) {
    if (ch == '"' || ch == '\\') out += '\\';
    out += ch;
  }
  out += '"';
  return out;
}

std::string FormatSeconds(double s) {
  if (!std::isfinite(s) || std::fabs(s) > 9.0e15) return "nan";
  const long long total = std::llround(std::fabs(s) * 1000.0);
  std::string frac = std::to_string(total % 1000);
  frac.insert(0, 3 - frac.size(), '0');
  return std::string(s < 0 && total != 0 ? "-" : "") + std::to_string(total / 1000) + "." + frac;
}

bool Tokenize(std::string_view s, std::vector<std::string>& out, std::string* err) {
  out.clear();
  std::size_t i = 0;
  const std::size_t n = s.size();
  while (true) {
    while (i < n && IsWs(s[i])) ++i;
    if (i >= n) break;
    std::string tok;
    bool inq = false;
    while (i < n) {
      const char ch = s[i];
      if (inq) {
        if (ch == '\\' && i + 1 < n && (s[i + 1] == '"' || s[i + 1] == '\\')) {
          tok += s[i + 1];
          i += 2;
          continue;
        }
        if (ch == '"') {
          inq = false;
          ++i;
          continue;
        }
        tok += ch;
        ++i;
      } else {
        if (IsWs(ch)) break;
        if (ch == '"') {
          inq = true;
          ++i;
          continue;
        }
        tok += ch;
        ++i;
      }
    }
    if (inq) {
      if (err) *err = "unterminated quote";
      return false;
    }
    out.push_back(std::move(tok));
  }
  return true;
}

ParsedCmd ParseCmdText(std::string_view text, std::uint64_t seq) {
  ParsedCmd pc;
  pc.cmd.seq = seq;
  if (text.size() >= 3 && text.substr(0, 3) == "\xEF\xBB\xBF") text.remove_prefix(3);
  // Collect non-blank lines (LF or CRLF).
  std::vector<std::string_view> lines;
  std::size_t start = 0;
  while (start <= text.size()) {
    std::size_t nl = text.find('\n', start);
    if (nl == std::string_view::npos) nl = text.size();
    const std::string_view line = Trim(text.substr(start, nl - start));
    if (!line.empty()) lines.push_back(line);
    start = nl + 1;
  }
  if (lines.empty()) {
    pc.error = "empty";
    return pc;
  }
  std::string_view line = lines[0];
  std::size_t sp = 0;
  while (sp < line.size() && !IsWs(line[sp])) ++sp;
  const std::string_view id = line.substr(0, sp);
  if (!ValidId(id)) {
    pc.error = "bad id";
    return pc;
  }
  pc.cmd.id = std::string(id);
  pc.hasId = true;
  line = Trim(line.substr(sp));
  sp = 0;
  while (sp < line.size() && !IsWs(line[sp])) ++sp;
  pc.cmd.verb = std::string(line.substr(0, sp));
  if (pc.cmd.verb.empty()) {
    pc.error = "missing verb";
    return pc;
  }
  pc.cmd.raw = std::string(Trim(line.substr(sp)));
  if (lines.size() > 1) {
    pc.error = "multiple lines";
    return pc;
  }
  std::string err;
  if (!Tokenize(pc.cmd.raw, pc.cmd.args, &err)) pc.error = err;
  return pc;
}

}  // namespace devbridge

// ---- public API ----------------------------------------------------------------------------

using namespace devbridge;

void DevbridgeInitWithFs(const char* exeDir, std::unique_ptr<Fs> fsys, std::function<std::int64_t()> wallMs) {
  Core& c = G();
  if (c.active || exeDir == nullptr || !fsys) return;
  try {
    const std::string exe(exeDir);
    if (!fsys->Exists(MarkerForExe(exe))) return;  // inactive: touch nothing
    const std::string dir = DirForExe(exe);
    if (!fsys->CreateDirs(dir)) return;
    if (!fsys->OpenLog(Join(dir, "log.txt"))) return;
    c.fs = std::move(fsys);
    c.wallMs = std::move(wallMs);
    c.dir = dir;
    c.t = 0;
    c.frame = 0;
    c.lastSeq = 0;
    c.queue.clear();
    c.pending.reset();
    c.reported.clear();
    c.readFailName.clear();
    c.readFailCount = 0;
    c.haveOwner = false;
    c.initThread = std::this_thread::get_id();
    c.haveInitThread = true;
    c.wrongThreadReported = g_wrongThread.load();
    c.active = true;
    // Files present before init are stale: delete them, and never execute a late copy of one.
    std::size_t stale = 0;
    for (const std::string& n : c.fs->List(dir)) {
      if (!IsCmdFileName(n)) continue;
      if (const auto seq = ParseCmdFileName(n)) c.lastSeq = std::max(c.lastSeq, *seq);
      RemoveFile(n);
      ++stale;
    }
    EmitLine("ev=devbridge_ready version=" + std::to_string(kProtocolVersion) + " stale_cmds=" +
             std::to_string(stale) + " last_seq=" + std::to_string(c.lastSeq) +
             " poll_frames=" + std::to_string(kPollEveryFrames) + " dir=" + Quote(dir));
  } catch (...) {
    c.active = false;
    c.fs.reset();
  }
}

void DevbridgeInit(const char* exeDir) {
  try {
    DevbridgeInitWithFs(exeDir, MakeStdFs(), {});
  } catch (...) {
  }
}

void DevbridgeShutdown() {
  Core& c = G();
#ifndef NDEBUG
  assert(!c.active || OnOwner());  // main thread only (the owner thread), see devbridge_core.hpp
#endif
  try {
    if (c.active) {
      if (c.pending) {
        const Cmd cmd = c.pending->cmd;
        c.pending.reset();
        Ack(cmd, CmdResult::Fail("shutdown"));
      }
      while (!c.queue.empty()) {
        const Entry e = std::move(c.queue.front());
        c.queue.pop_front();
        if (e.hasId) Ack(e.cmd, CmdResult::Fail("shutdown"));
      }
      EmitLine("ev=devbridge_shutdown");
      c.fs->CloseLog();
    }
  } catch (...) {
  }
  c.active = false;
  c.fs.reset();
  c.wallMs = nullptr;
  c.mirror = nullptr;
  c.queue.clear();
  c.pending.reset();
  c.sync.clear();
  c.async.clear();
  c.reported.clear();
  c.haveOwner = false;
  c.haveInitThread = false;
  c.inTick = false;
}

bool DevbridgeActive() { return G().active; }

void DevbridgeTick(double gameSeconds) {
  Core& c = G();
  if (!c.active) return;
  if (!c.haveOwner) {
    c.owner = std::this_thread::get_id();
    c.haveOwner = true;
    // Init should have run on this (the main) thread; say so if not. From now on only this thread may call in.
    if (c.haveInitThread && c.owner != c.initThread) EmitLine("ev=devbridge_thread_mismatch init_thread_differs=1");
  }
  if (!OnOwner() || c.inTick) return;
  c.inTick = true;
  try {
    c.t = gameSeconds;
    ++c.frame;
    const std::uint64_t wrong = g_wrongThread.load(std::memory_order_relaxed);
    if (wrong != c.wrongThreadReported) {
      EmitLine("ev=devbridge_wrong_thread dropped=" + std::to_string(wrong - c.wrongThreadReported));
      c.wrongThreadReported = wrong;
    }
    if (c.pending) PollPending();
    if ((c.frame - 1) % kPollEveryFrames == 0) Scan();
    Drain();
  } catch (...) {
  }
  c.inTick = false;
}

void DevbridgeRegister(const char* verb, std::function<CmdResult(const Cmd&)> fn) {
  Core& c = G();
  if (verb == nullptr || !fn || (c.active && !OnOwner())) return;
  try {
    c.async.erase(std::string(verb));
    c.sync[verb] = std::move(fn);
  } catch (...) {
  }
}

void DevbridgeRegisterAsync(const char* verb,
                            std::function<std::optional<CmdResult>(const Cmd&, int framesWaited)> poll) {
  Core& c = G();
  if (verb == nullptr || !poll || (c.active && !OnOwner())) return;
  try {
    c.sync.erase(std::string(verb));
    c.async[verb] = std::move(poll);
  } catch (...) {
  }
}

void Harness(std::string_view kv) {
  if (!G().active || !OnOwner()) return;
  try {
    EmitLine(kv);
  } catch (...) {
  }
}

void DevbridgeData(std::string_view id, std::string_view kv) {
  if (!G().active || !OnOwner()) return;
  try {
    std::string p = "data id=" + std::string(id);
    if (!kv.empty()) {
      p += ' ';
      p += kv;
    }
    EmitLine(p);
  } catch (...) {
  }
}

void DevbridgeSetMirror(std::function<void(const std::string& line)> fn) {
  try {
    G().mirror = std::move(fn);
  } catch (...) {
  }
}

std::string DevbridgeQuote(std::string_view v) {
  try {
    return Quote(v);
  } catch (...) {
    return "\"\"";
  }
}
