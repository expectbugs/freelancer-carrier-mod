// Host tests for the devbridge core: fake filesystem + fake wall clock, no real I/O.
#define DOCTEST_CONFIG_IMPLEMENT_WITH_MAIN
#include "doctest.h"

#include <cstdint>
#include <filesystem>
#include <map>
#include <memory>
#include <set>
#include <stdexcept>
#include <string>
#include <thread>
#include <vector>

#include "../devbridge_core.hpp"

namespace {

using devbridge::Cmd;
using devbridge::CmdResult;

struct Disk {
  std::map<std::string, std::string> files;  // full path -> content
  std::set<std::string> dirs;
  std::vector<std::string> log;
  bool logOpen = false;
  std::string logPath;
  std::set<std::string> failRead;      // full paths whose Read fails
  std::set<std::string> failRemove;    // full paths whose Remove fails (file stays)
  std::set<std::string> lagOnRemove;   // full paths still listed once after removal (Wine delete lag)
  std::set<std::string> ghosts;        // currently lagging entries
  std::vector<std::string> removed;    // full paths, in order
  int reads = 0;
};

std::string Parent(const std::string& p) { return std::filesystem::path(p).parent_path().string(); }
std::string Name(const std::string& p) { return std::filesystem::path(p).filename().string(); }

class FakeFs final : public devbridge::Fs {
 public:
  explicit FakeFs(std::shared_ptr<Disk> d) : d_(std::move(d)) {}
  bool Exists(const std::string& p) override { return d_->files.count(p) || d_->dirs.count(p); }
  bool CreateDirs(const std::string& dir) override {
    d_->dirs.insert(dir);
    return true;
  }
  std::vector<std::string> List(const std::string& dir) override {
    std::vector<std::string> out;
    for (const auto& [p, _] : d_->files)
      if (Parent(p) == dir) out.push_back(Name(p));
    for (const auto& g : d_->ghosts)
      if (Parent(g) == dir) out.push_back(Name(g));
    d_->ghosts.clear();
    return out;
  }
  std::optional<std::string> Read(const std::string& p, std::size_t maxBytes) override {
    ++d_->reads;
    if (d_->failRead.count(p)) return std::nullopt;
    auto it = d_->files.find(p);
    if (it == d_->files.end()) return std::nullopt;
    return it->second.substr(0, maxBytes + 1);
  }
  bool Remove(const std::string& p) override {
    if (d_->failRemove.count(p)) return false;
    d_->files.erase(p);
    d_->removed.push_back(p);
    if (d_->lagOnRemove.count(p)) d_->ghosts.insert(p);
    return true;
  }
  bool OpenLog(const std::string& p) override {
    d_->logOpen = true;
    d_->logPath = p;
    return true;
  }
  bool AppendLine(std::string_view line) override {
    REQUIRE(d_->logOpen);
    d_->log.emplace_back(line);
    return true;
  }
  void CloseLog() override { d_->logOpen = false; }

 private:
  std::shared_ptr<Disk> d_;
};

const std::string kExe = "/game/EXE";
const std::string kDir = "/game/SAVE/devbridge";

std::string CmdPath(std::uint64_t seq) { return kDir + "/" + devbridge::CmdFileName(seq); }

// Strips "HARNESS t=... wall=... " so assertions can compare payloads.
std::string Payload(const std::string& line) {
  REQUIRE(line.rfind("HARNESS t=", 0) == 0);
  const auto wall = line.find(" wall=");
  REQUIRE(wall != std::string::npos);
  const auto sp = line.find(' ', wall + 1);
  return sp == std::string::npos ? std::string() : line.substr(sp + 1);
}

struct Bridge {
  std::shared_ptr<Disk> disk = std::make_shared<Disk>();
  std::shared_ptr<std::int64_t> now = std::make_shared<std::int64_t>(1700000000000);
  double t = 0;

  explicit Bridge(bool marker = true) {
    DevbridgeShutdown();
    if (marker) disk->files[kExe + "/devbridge.enabled"] = "";
  }
  ~Bridge() { DevbridgeShutdown(); }

  void Init() {
    auto clock = now;
    DevbridgeInitWithFs(kExe.c_str(), std::make_unique<FakeFs>(disk), [clock] { return *clock; });
  }
  void Put(std::uint64_t seq, const std::string& text) { disk->files[CmdPath(seq)] = text; }
  void Tick(int n = 1) {
    for (int i = 0; i < n; ++i) {
      t += 0.016;
      DevbridgeTick(t);
    }
  }
  std::vector<std::string> Payloads() const {
    std::vector<std::string> out;
    for (const auto& l : disk->log) out.push_back(Payload(l));
    return out;
  }
  // Payloads after the ready line.
  std::vector<std::string> After() const {
    auto all = Payloads();
    if (!all.empty() && all[0].rfind("ev=devbridge_ready", 0) == 0) all.erase(all.begin());
    return all;
  }
  bool Has(const std::string& payload) const {
    for (const auto& p : Payloads())
      if (p == payload) return true;
    return false;
  }
};

}  // namespace

TEST_CASE("inactive when the marker file is missing") {
  Bridge b(false);
  b.Put(1, "a ping");
  b.Init();
  CHECK_FALSE(DevbridgeActive());
  b.Tick(25);
  Harness("ev=should_not_appear");
  DevbridgeData("a", "x=1");
  CHECK(b.disk->log.empty());
  CHECK_FALSE(b.disk->logOpen);
  CHECK(b.disk->files.count(CmdPath(1)) == 1);  // untouched
  CHECK(b.disk->dirs.empty());
}

TEST_CASE("ready event, stale files deleted at init and never executed late") {
  Bridge b;
  b.Put(3, "s1 ping");
  b.Put(7, "s2 ping");
  b.disk->files[kDir + "/cmd-junk.txt"] = "s3 ping";
  b.disk->lagOnRemove.insert(CmdPath(7));  // Wine shows it once more after deletion
  b.Init();
  REQUIRE(DevbridgeActive());
  REQUIRE(b.disk->log.size() == 1);
  CHECK(b.Payloads()[0] == "ev=devbridge_ready version=1 stale_cmds=3 last_seq=7 poll_frames=10 dir=" + kDir);
  CHECK(b.disk->logPath == kDir + "/log.txt");
  CHECK(b.disk->files.count(CmdPath(3)) == 0);
  CHECK(b.disk->files.count(CmdPath(7)) == 0);
  b.Tick(1);
  for (const auto& p : b.After()) CHECK(p.find("ack") == std::string::npos);
  CHECK(b.Has("ev=cmd_dup file=cmd-0000000007.txt last_seq=7"));
}

TEST_CASE("line format: t with 3 decimals and wall ms") {
  Bridge b;
  b.Init();
  *b.now = 1700000000123;
  b.Put(1, "a ping");
  DevbridgeTick(1.5);
  REQUIRE(b.disk->log.size() == 2);
  CHECK(b.disk->log[1] == "HARNESS t=1.500 wall=1700000000123 ack id=a ok=1 verb=ping pong=1");
  CHECK(devbridge::FormatSeconds(0) == "0.000");
  CHECK(devbridge::FormatSeconds(12.3456) == "12.346");
  CHECK(devbridge::FormatSeconds(-0.25) == "-0.250");
  CHECK(devbridge::FormatSeconds(0.0004) == "0.000");
}

TEST_CASE("files are processed in seq order and deleted after reading") {
  Bridge b;
  b.Init();
  b.Put(12, "c ping");
  b.Put(2, "a ping");
  b.Put(9, "b ping");
  b.Tick(1);
  const auto p = b.After();
  REQUIRE(p.size() == 3);
  CHECK(p[0] == "ack id=a ok=1 verb=ping pong=1");
  CHECK(p[1] == "ack id=b ok=1 verb=ping pong=1");
  CHECK(p[2] == "ack id=c ok=1 verb=ping pong=1");
  CHECK(b.disk->files.count(CmdPath(2)) == 0);
  CHECK(b.disk->files.count(CmdPath(9)) == 0);
  CHECK(b.disk->files.count(CmdPath(12)) == 0);
  CHECK(b.disk->removed == std::vector<std::string>{CmdPath(2), CmdPath(9), CmdPath(12)});
}

TEST_CASE("polls the directory every 10 frames") {
  Bridge b;
  b.Init();
  b.Tick(1);  // frame 1 polls (empty)
  b.Put(1, "a ping");
  const int readsBefore = b.disk->reads;
  b.Tick(9);  // frames 2..10: no poll
  CHECK(b.After().empty());
  CHECK(b.disk->reads == readsBefore);
  b.Tick(1);  // frame 11 polls
  CHECK(b.After() == std::vector<std::string>{"ack id=a ok=1 verb=ping pong=1"});
}

TEST_CASE("duplicate and stale seqs are ignored and deleted (Wine delete lag)") {
  Bridge b;
  b.Init();
  b.Put(5, "a ping");
  b.disk->lagOnRemove.insert(CmdPath(5));
  b.Tick(1);
  REQUIRE(b.After().size() == 1);
  b.Tick(10);  // the deleted file is listed once more
  b.Put(5, "dup ping");  // re-appears with content
  b.Put(4, "old ping");
  b.Tick(10);
  b.Tick(10);
  int acks = 0, dups5 = 0, dups4 = 0;
  for (const auto& p : b.After()) {
    if (p.rfind("ack ", 0) == 0) ++acks;
    if (p == "ev=cmd_dup file=cmd-0000000005.txt last_seq=5") ++dups5;
    if (p == "ev=cmd_dup file=cmd-0000000004.txt last_seq=5") ++dups4;
  }
  CHECK(acks == 1);
  CHECK(dups5 == 1);  // reported once per name, not every poll
  CHECK(dups4 == 1);
  CHECK(b.disk->files.count(CmdPath(5)) == 0);
  CHECK(b.disk->files.count(CmdPath(4)) == 0);
  CHECK_FALSE(b.Has("ack id=dup ok=1 verb=ping pong=1"));
  CHECK_FALSE(b.Has("ack id=old ok=1 verb=ping pong=1"));
}

TEST_CASE("remove failure is reported once and the file is not re-executed") {
  Bridge b;
  b.Init();
  b.Put(1, "a ping");
  b.disk->failRemove.insert(CmdPath(1));
  b.Tick(1);
  b.Tick(10);
  b.Tick(10);
  int acks = 0, errs = 0;
  for (const auto& p : b.After()) {
    if (p.rfind("ack ", 0) == 0) ++acks;
    if (p == "ev=fs_error op=remove file=cmd-0000000001.txt") ++errs;
  }
  CHECK(acks == 1);
  CHECK(errs == 1);
}

TEST_CASE("unreadable file is retried in order, then dropped") {
  Bridge b;
  b.Init();
  b.Put(1, "a ping");
  b.Put(2, "b ping");
  b.disk->failRead.insert(CmdPath(1));
  b.Tick(1);
  CHECK(b.After().empty());  // b must not overtake a
  b.disk->failRead.clear();
  b.Tick(10);
  auto p = b.After();
  REQUIRE(p.size() == 2);
  CHECK(p[0] == "ack id=a ok=1 verb=ping pong=1");
  CHECK(p[1] == "ack id=b ok=1 verb=ping pong=1");

  b.Put(3, "c ping");
  b.disk->failRead.insert(CmdPath(3));
  b.Tick(10 * devbridge::kMaxReadRetries);
  CHECK(b.Has("ev=bad_cmd file=cmd-0000000003.txt reason=unreadable"));
  CHECK(b.disk->files.count(CmdPath(3)) == 0);
}

TEST_CASE("quoting and tokenizing round-trip") {
  using devbridge::Quote;
  CHECK(Quote("plain") == "plain");
  CHECK(Quote("") == "\"\"");
  CHECK(Quote("a b") == "\"a b\"");
  CHECK(Quote("x=y") == "\"x=y\"");
  CHECK(Quote("say \"hi\"") == "\"say \\\"hi\\\"\"");
  CHECK(Quote("C:\\dir") == "C:\\dir");  // bare backslash stays literal
  CHECK(Quote("C:\\my dir\\") == "\"C:\\\\my dir\\\\\"");
  CHECK(Quote("two\nlines\tx") == "\"two lines x\"");  // control chars -> space
  CHECK(DevbridgeQuote("a b") == "\"a b\"");

  const std::vector<std::string> values = {"plain", "", "a b", "x=y", "say \"hi\"", "C:\\my dir\\", "\\\"", "  lead",
                                           "trail  ", "uni \xC3\xA9"};
  for (const auto& v : values) {
    std::vector<std::string> toks;
    std::string err;
    REQUIRE(devbridge::Tokenize("k " + Quote(v) + " end", toks, &err));
    REQUIRE(toks.size() == 3);
    CHECK(toks[1] == v);
    CHECK(toks[2] == "end");
  }
  std::vector<std::string> toks;
  REQUIRE(devbridge::Tokenize("  a\t\"b c\" tag=\"x y\" C:\\p \"e\\\"f\" \"g\\h\" ", toks, nullptr));
  CHECK(toks == std::vector<std::string>{"a", "b c", "tag=x y", "C:\\p", "e\"f", "g\\h"});
  std::string err;
  CHECK_FALSE(devbridge::Tokenize("a \"open", toks, &err));
  CHECK(err == "unterminated quote");
}

TEST_CASE("command parsing: ids, raw, args, CRLF, BOM") {
  auto pc = devbridge::ParseCmdText("\xEF\xBB\xBFh1 echo  hello \"big world\"  \r\n", 4);
  CHECK(pc.error.empty());
  CHECK(pc.hasId);
  CHECK(pc.cmd.id == "h1");
  CHECK(pc.cmd.verb == "echo");
  CHECK(pc.cmd.raw == "hello \"big world\"");
  CHECK(pc.cmd.args == std::vector<std::string>{"hello", "big world"});
  CHECK(pc.cmd.seq == 4);

  CHECK(devbridge::ParseCmdText("", 1).error == "empty");
  CHECK(devbridge::ParseCmdText(" \r\n\n", 1).error == "empty");
  auto bad = devbridge::ParseCmdText("bad\"id ping", 1);
  CHECK(bad.error == "bad id");
  CHECK_FALSE(bad.hasId);
  auto nv = devbridge::ParseCmdText("lonely", 1);
  CHECK(nv.error == "missing verb");
  CHECK(nv.hasId);
  auto ml = devbridge::ParseCmdText("a ping\nb ping\n", 1);
  CHECK(ml.error == "multiple lines");
  CHECK(ml.cmd.id == "a");

  CHECK(devbridge::ParseCmdFileName("cmd-0000000042.txt") == std::optional<std::uint64_t>(42));
  CHECK(devbridge::ParseCmdFileName("cmd-7.txt") == std::optional<std::uint64_t>(7));
  CHECK_FALSE(devbridge::ParseCmdFileName("cmd-.txt"));
  CHECK_FALSE(devbridge::ParseCmdFileName("cmd-12a.txt"));
  CHECK_FALSE(devbridge::ParseCmdFileName(".tmp-cmd-0000000001"));
  CHECK(devbridge::CmdFileName(42) == "cmd-0000000042.txt");
  CHECK(devbridge::DirForExe("/x/y/EXE") == "/x/y/SAVE/devbridge");
  CHECK(devbridge::DirForExe("/x/y/EXE/") == "/x/y/SAVE/devbridge");
}

TEST_CASE("data lines precede the ack, all carrying the id") {
  Bridge b;
  b.Init();
  DevbridgeRegister("lines", [](const Cmd& c) {
    for (int i = 1; i <= 3; ++i) DevbridgeData(c.id, "i=" + std::to_string(i));
    return CmdResult::Ok("count=3");
  });
  b.Put(1, "q lines");
  b.Tick(1);
  CHECK(b.After() == std::vector<std::string>{"data id=q i=1", "data id=q i=2", "data id=q i=3",
                                              "ack id=q ok=1 verb=lines count=3"});
}

TEST_CASE("built-ins: echo raw, seq, sleep_frames usage") {
  Bridge b;
  b.Init();
  b.Put(1, "e echo  hello \"big world\" a=b ");
  b.Put(2, "s seq");
  b.Put(3, "z sleep_frames x");
  b.Put(4, "z0 sleep_frames 0");
  b.Tick(1);
  CHECK(b.After() == std::vector<std::string>{
                         "ack id=e ok=1 verb=echo text=\"hello \\\"big world\\\" a=b\"",
                         "ack id=s ok=1 verb=seq last_seq=4",
                         "ack id=z ok=0 err=\"usage: sleep_frames <n>\" verb=sleep_frames",
                         "ack id=z0 ok=1 verb=sleep_frames frames=0",
                     });
}

TEST_CASE("async commands block the FIFO until they complete") {
  Bridge b;
  b.Init();
  b.Put(1, "s sleep_frames 5");
  b.Put(2, "p ping");
  b.Tick(1);  // frame 1: sleep starts (framesWaited 0)
  CHECK(b.After().empty());
  b.Tick(4);  // frames 2..5: framesWaited 1..4
  CHECK(b.After().empty());
  b.Tick(1);  // frame 6: framesWaited 5 -> ack, then ping in the same tick
  CHECK(b.After() == std::vector<std::string>{"ack id=s ok=1 verb=sleep_frames frames=5",
                                              "ack id=p ok=1 verb=ping pong=1"});
}

TEST_CASE("async timeout: default 60 s wall clock and per-command budget") {
  Bridge b;
  b.Init();
  int polls = 0;
  DevbridgeRegisterAsync("forever", [&polls](const Cmd&, int) -> std::optional<CmdResult> {
    ++polls;
    return std::nullopt;
  });
  DevbridgeRegisterAsync("short", [](const Cmd&, int frames) -> std::optional<CmdResult> {
    if (frames == 0) return CmdResult::Pending(2.0);
    return std::nullopt;
  });
  b.Put(1, "f forever");
  b.Put(2, "p ping");
  b.Tick(1);
  *b.now += 59'000;
  b.Tick(3);
  // only the keep-alive (one per 5 s of wall time; the clock jumped 59 s at once, so one line)
  CHECK(b.After() == std::vector<std::string>{"ev=pending id=f verb=forever elapsed_s=59"});
  *b.now += 1'000;
  b.Tick(1);
  CHECK(b.After() == std::vector<std::string>{"ev=pending id=f verb=forever elapsed_s=59",
                                              "ack id=f ok=0 err=\"timeout\" verb=forever timeout_s=60.000",
                                              "ack id=p ok=1 verb=ping pong=1"});
  CHECK(polls == 5);

  b.Put(3, "s short");
  b.Tick(10);
  *b.now += 1'999;
  b.Tick(1);
  CHECK_FALSE(b.Has("ack id=s ok=0 err=\"timeout\" verb=short timeout_s=2.000"));
  *b.now += 1;
  b.Tick(1);
  CHECK(b.Has("ack id=s ok=0 err=\"timeout\" verb=short timeout_s=2.000"));
}

TEST_CASE("unknown verb") {
  Bridge b;
  b.Init();
  b.Put(1, "u frobnicate 1 2");
  b.Tick(1);
  CHECK(b.After() == std::vector<std::string>{"ack id=u ok=0 err=\"unknown verb frobnicate\" verb=frobnicate"});
}

TEST_CASE("malformed command files") {
  Bridge b;
  b.Init();
  b.Put(1, "");
  b.Put(2, "lonely");
  b.Put(3, "q echo \"open");
  b.Put(4, "bad\"id ping");
  b.Put(5, "a ping\nb ping");
  b.disk->files[kDir + "/cmd-xyz.txt"] = "k ping";
  b.disk->files[kDir + "/.tmp-cmd-0000000009"] = "t ping";  // harness temp file: ignored
  b.Put(6, "ok ping");
  b.Tick(1);
  const auto p = b.After();
  CHECK(b.Has("ev=bad_cmd file=cmd-xyz.txt reason=\"bad file name\""));
  CHECK(b.Has("ev=bad_cmd file=cmd-0000000001.txt reason=empty"));
  CHECK(b.Has("ev=bad_cmd file=cmd-0000000002.txt reason=\"missing verb\" id=lonely"));
  CHECK(b.Has("ack id=lonely ok=0 err=\"bad_cmd: missing verb\" verb=\"\""));
  CHECK(b.Has("ev=bad_cmd file=cmd-0000000003.txt reason=\"unterminated quote\" id=q"));
  CHECK(b.Has("ack id=q ok=0 err=\"bad_cmd: unterminated quote\" verb=echo"));
  CHECK(b.Has("ev=bad_cmd file=cmd-0000000004.txt reason=\"bad id\""));
  CHECK(b.Has("ack id=a ok=0 err=\"bad_cmd: multiple lines\" verb=ping"));
  CHECK(p.back() == "ack id=ok ok=1 verb=ping pong=1");
  CHECK(b.disk->files.count(kDir + "/cmd-xyz.txt") == 0);
  CHECK(b.disk->files.count(kDir + "/.tmp-cmd-0000000009") == 1);

  b.Put(7, std::string("big ping ") + std::string(devbridge::kMaxCmdBytes, 'x'));
  b.Tick(10);
  CHECK(b.Has("ev=bad_cmd file=cmd-0000000007.txt reason=\"too large\""));
}

TEST_CASE("exceptions in handlers become ok=0") {
  Bridge b;
  b.Init();
  DevbridgeRegister("boom", [](const Cmd&) -> CmdResult { throw std::runtime_error("kaboom"); });
  DevbridgeRegister("boom2", [](const Cmd&) -> CmdResult { throw 42; });
  DevbridgeRegisterAsync("aboom", [](const Cmd&, int frames) -> std::optional<CmdResult> {
    if (frames == 2) throw std::logic_error("late");
    return std::nullopt;
  });
  DevbridgeRegister("bad_pending", [](const Cmd&) { return CmdResult::Pending(); });
  b.Put(1, "x boom");
  b.Put(2, "y boom2");
  b.Put(3, "z aboom");
  b.Put(4, "w bad_pending");
  b.Tick(3);
  CHECK(b.After() == std::vector<std::string>{
                         "ack id=x ok=0 err=\"exception: kaboom\" verb=boom",
                         "ack id=y ok=0 err=\"exception: unknown\" verb=boom2",
                         "ack id=z ok=0 err=\"exception: late\" verb=aboom",
                         "ack id=w ok=0 err=\"sync handler returned pending\" verb=bad_pending",
                     });
}

TEST_CASE("re-registering replaces; user verbs override built-ins; sync/async share a namespace") {
  Bridge b;
  b.Init();
  DevbridgeRegister("v", [](const Cmd&) { return CmdResult::Ok("n=1"); });
  DevbridgeRegister("v", [](const Cmd&) { return CmdResult::Ok("n=2"); });
  DevbridgeRegister("ping", [](const Cmd&) { return CmdResult::Ok("custom=1"); });
  DevbridgeRegisterAsync("w", [](const Cmd&, int) -> std::optional<CmdResult> { return CmdResult::Ok("a=1"); });
  DevbridgeRegister("w", [](const Cmd&) { return CmdResult::Ok("s=1"); });
  b.Put(1, "a v");
  b.Put(2, "b ping");
  b.Put(3, "c w");
  b.Tick(1);
  CHECK(b.After() == std::vector<std::string>{"ack id=a ok=1 verb=v n=2", "ack id=b ok=1 verb=ping custom=1",
                                              "ack id=c ok=1 verb=w s=1"});
}

TEST_CASE("handler args and Harness events; mirror sees every line") {
  std::vector<std::string> mirrored;  // must outlive b: ~Bridge's shutdown line is mirrored too
  Bridge b;
  b.Init();
  DevbridgeSetMirror([&mirrored](const std::string& l) { mirrored.push_back(l); });
  DevbridgeRegister("args", [](const Cmd& c) {
    Harness("ev=custom n=" + std::to_string(c.args.size()));
    std::string kv = "count=" + std::to_string(c.args.size());
    for (std::size_t i = 0; i < c.args.size(); ++i) kv += " a" + std::to_string(i) + "=" + DevbridgeQuote(c.args[i]);
    return CmdResult::Ok(kv);
  });
  b.Put(1, "a args near=player tag=\"x y\"");
  b.Tick(1);
  CHECK(b.After() == std::vector<std::string>{"ev=custom n=2",
                                              "ack id=a ok=1 verb=args count=2 a0=\"near=player\" a1=\"tag=x y\""});
  REQUIRE(mirrored.size() == 2);
  CHECK(mirrored[1] == b.disk->log.back());
  Harness("ev=multi\nline");
  CHECK(Payload(b.disk->log.back()) == "ev=multi line");
}

TEST_CASE("failure kv and err defaults") {
  Bridge b;
  b.Init();
  DevbridgeRegister("f", [](const Cmd&) { return CmdResult::Fail("", "code=7"); });
  b.Put(1, "a f");
  b.Tick(1);
  CHECK(b.After() == std::vector<std::string>{"ack id=a ok=0 err=\"error\" verb=f code=7"});
}

TEST_CASE("shutdown acks queued and pending commands") {
  Bridge b;
  b.Init();
  b.Put(1, "s sleep_frames 100");
  b.Put(2, "p ping");
  b.Tick(1);
  DevbridgeShutdown();
  CHECK_FALSE(DevbridgeActive());
  CHECK_FALSE(b.disk->logOpen);
  CHECK(b.After() == std::vector<std::string>{"ack id=s ok=0 err=\"shutdown\" verb=sleep_frames",
                                              "ack id=p ok=0 err=\"shutdown\" verb=ping", "ev=devbridge_shutdown"});
}

TEST_CASE("handlers registered before init survive init; shutdown clears them") {
  {
    Bridge b;  // Bridge() calls DevbridgeShutdown(), which clears handlers; register before Init
    DevbridgeRegister("early", [](const Cmd&) { return CmdResult::Ok("e=1"); });
    b.Init();
    b.Put(1, "a early");
    b.Tick(1);
    CHECK(b.After() == std::vector<std::string>{"ack id=a ok=1 verb=early e=1"});
  }
  Bridge b2;
  b2.Init();
  b2.Put(1, "a early");
  b2.Tick(1);
  CHECK(b2.After() == std::vector<std::string>{"ack id=a ok=0 err=\"unknown verb early\" verb=early"});
}

TEST_CASE("pending keep-alive: ev=pending every 5 s while an async command runs (D111)") {
  Bridge b;
  b.Init();
  DevbridgeRegisterAsync("long", [](const Cmd&, int frames) -> std::optional<CmdResult> {
    if (frames == 0) return CmdResult::Pending(30.0);
    return std::nullopt;
  });
  b.Put(1, "L long 75");
  b.Tick(1);
  for (int s = 1; s <= 12; ++s) {
    *b.now += 1'000;
    b.Tick(1);
  }
  CHECK(b.After() == std::vector<std::string>{"ev=pending id=L verb=long elapsed_s=5",
                                              "ev=pending id=L verb=long elapsed_s=10"});
  *b.now += 18'000;  // 30 s budget reached
  b.Tick(1);
  CHECK(b.Has("ack id=L ok=0 err=\"timeout\" verb=long timeout_s=30.000"));
  // a quick command never emits a keep-alive
  b.Put(2, "p ping");
  b.Tick(10);
  CHECK(b.After().back() == "ack id=p ok=1 verb=ping pong=1");
}

TEST_CASE("ack key order and err quoting (D111): err right after ok, always quoted, escapes") {
  Bridge b;
  b.Init();
  DevbridgeRegister("q", [](const Cmd&) { return CmdResult::Fail("say \"hi\" a\\b", "x=1"); });
  DevbridgeRegister("plain", [](const Cmd&) { return CmdResult::Fail("nope"); });
  b.Put(1, "a q");
  b.Put(2, "b plain");
  b.Tick(1);
  CHECK(b.After() == std::vector<std::string>{"ack id=a ok=0 err=\"say \\\"hi\\\" a\\\\b\" verb=q x=1",
                                              "ack id=b ok=0 err=\"nope\" verb=plain"});
  CHECK(devbridge::QuoteAlways("") == "\"\"");
  CHECK(devbridge::QuoteAlways("t") == "\"t\"");
}

TEST_CASE("before the first Tick only the Init thread may call in; a Tick on another thread is flagged") {
  {
    Bridge b;
    b.Init();
    std::thread([] { Harness("ev=early_other_thread"); }).join();
    b.Tick(1);
    CHECK_FALSE(b.Has("ev=early_other_thread"));
    CHECK(b.Has("ev=devbridge_wrong_thread dropped=1"));
  }
  {
    Bridge b;
    b.Init();
    std::thread([] {
      DevbridgeTick(1.0);   // first Tick on a thread other than Init's: becomes the owner, flagged
      DevbridgeShutdown();  // main-thread-only calls go to the owner
    }).join();
    bool flagged = false;
    for (const auto& l : b.disk->log)
      if (l.find("ev=devbridge_thread_mismatch init_thread_differs=1") != std::string::npos) flagged = true;
    CHECK(flagged);
  }
}

TEST_CASE("calls from a non-owner thread are dropped and reported") {
  Bridge b;
  b.Init();
  b.Tick(1);  // fixes the owner thread
  std::thread([] {
    Harness("ev=from_other_thread");
    DevbridgeTick(99.0);
  }).join();
  b.Tick(1);
  CHECK_FALSE(b.Has("ev=from_other_thread"));
  CHECK(b.Has("ev=devbridge_wrong_thread dropped=2"));
}
