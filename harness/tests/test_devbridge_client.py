"""Tests for harness/devbridge.py: unit tests plus end-to-end tests against host_sim (the real C++
core in a simulated frame loop). Everything runs in pytest tmp dirs; no game, no Wine."""
from __future__ import annotations

import fnmatch
import os
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

HARNESS = Path(__file__).resolve().parents[1]
WT = HARNESS.parent
sys.path.insert(0, str(HARNESS))
import devbridge as dbm  # noqa: E402

BUILD_SCRIPT = HARNESS / "devbridge" / "tests" / "build_and_run.sh"
HOST_SIM = WT / "build" / "devbridge_host" / "host_sim"
HOST_SIM_SOURCES = [HARNESS / "devbridge" / n for n in ("devbridge_core.cpp", "devbridge_core.hpp")] + [
    HARNESS / "devbridge" / "tests" / "host_sim.cpp"]
CXX = os.environ.get("CXX", "/usr/lib/llvm/22/bin/clang++")
CLI = [sys.executable, "-I", str(HARNESS / "devbridge.py")]


# ---- unit: line format ---------------------------------------------------------------------

def test_parse_line_ack():
    p = dbm.parse_line('HARNESS t=1.500 wall=1700000000123 ack id=h1 ok=1 verb=echo text="a \\"b\\" c" e=""\n')
    assert p == {"t": 1.5, "wall": 1700000000123, "words": ["ack"],
                 "kv": {"id": "h1", "ok": "1", "verb": "echo", "text": 'a "b" c', "e": ""}}


def test_parse_line_ack_d111_order_and_err_escapes():
    p = dbm.parse_line('HARNESS t=2.000 wall=9 ack id=a ok=0 err="say \\"hi\\" a\\\\b" verb=q x=1')
    assert list(p["kv"]) == ["id", "ok", "err", "verb", "x"]
    assert p["kv"]["err"] == 'say "hi" a\\b' and p["kv"]["verb"] == "q" and p["kv"]["x"] == "1"
    ev = dbm.parse_line("HARNESS t=7.000 wall=9 ev=pending id=h4 verb=perf elapsed_s=5")
    assert ev["kv"] == {"ev": "pending", "id": "h4", "verb": "perf", "elapsed_s": "5"}


def test_parse_line_prefix_short_form_and_non_harness():
    p = dbm.parse_line("[carrier] devbridge: HARNESS t=0.000 wall=5 ev=devbridge_ready version=1 dir=\"C:\\\\a b\"")
    assert p["kv"] == {"ev": "devbridge_ready", "version": "1", "dir": "C:\\a b"}
    short = dbm.parse_line('HARNESS ack id=x ok=0 err="timeout"')
    assert short["t"] is None and short["wall"] is None and short["kv"]["err"] == "timeout"
    assert dbm.parse_line("no marker here") is None
    assert dbm.parse_line("HARNESSX t=1") is None
    bare = dbm.parse_line("HARNESS t=1 wall=2 data id=q file=C:\\x\\y.fl \"quoted word\" =odd")
    assert bare["words"] == ["data", "quoted word", "=odd"]
    assert bare["kv"] == {"id": "q", "file": "C:\\x\\y.fl"}


@pytest.mark.parametrize("value, expected", [
    ("plain", "plain"), ("", ""), ("a b", "a b"), ("x=y", "x=y"), ('say "hi"', 'say "hi"'),
    ("C:\\my dir\\", "C:\\my dir\\"), ('\\"', '\\"'), ("two\nlines\tx", "two lines x"), ("uni é", "uni é"),
])
def test_quote_roundtrip(value, expected):
    p = dbm.parse_line("HARNESS t=0.000 wall=0 k=" + dbm.quote(value) + " end=1")
    assert p["kv"]["k"] == expected
    assert p["kv"]["end"] == "1"


def test_quote_matches_core_examples():
    # Same expectations as the C++ doctest "quoting and tokenizing round-trip".
    assert dbm.quote("plain") == "plain"
    assert dbm.quote("") == '""'
    assert dbm.quote("x=y") == '"x=y"'
    assert dbm.quote('say "hi"') == '"say \\"hi\\""'
    assert dbm.quote("C:\\dir") == "C:\\dir"
    assert dbm.quote("C:\\my dir\\") == '"C:\\\\my dir\\\\"'
    assert dbm.quote_arg("near=player") == "near=player"
    assert dbm.quote_arg("a b") == '"a b"'


def test_tokenize_matches_core_rules():
    s = '  a\t"b c" tag="x y" C:\\p "e\\"f" "g\\h" '
    assert dbm.tokenize(s) == ["a", "b c", "tag=x y", "C:\\p", 'e"f', "g\\h"]
    for v in ["plain", "", "a b", 'q"q', "back\\slash and space", "k=v w"]:
        assert dbm.tokenize("x " + dbm.quote_arg(v) + " y") == ["x", v, "y"]
    with pytest.raises(ValueError):
        dbm.tokenize('a "open')


# ---- unit: seq allocation and atomic writes -------------------------------------------------

def test_seq_allocation(tmp_path):
    db = dbm.Devbridge(tmp_path)
    seq, cid, start = db.submit("ping")
    assert (seq, cid, start) == (1, "h1", 0)
    assert (tmp_path / "cmd-0000000001.txt").read_text() == "h1 ping\n"
    assert (tmp_path / ".seq").read_text().strip() == "1"
    (tmp_path / ".seq").write_text("7\n")
    assert db.submit("ping")[0] == 8
    (tmp_path / "cmd-0000000012.txt").write_text("x ping\n")  # pending file beyond the counter
    assert db.submit("ping")[0] == 13
    (tmp_path / ".seq").write_text("garbage")
    for f in tmp_path.glob("cmd-*.txt"):
        f.unlink()
    assert db.submit("ping", id="mine")[:2] == (1, "mine")
    with pytest.raises(ValueError):
        db.submit("ping", id="bad id")
    with pytest.raises(ValueError):
        db.submit("two\nlines")


def test_bump_seq(tmp_path):
    db = dbm.Devbridge(tmp_path)
    db.bump_seq(41)
    assert db.submit("ping")[0] == 42
    db.bump_seq(5)  # never lowers
    assert db.submit("ping")[0] == 43


def test_submit_is_atomic(tmp_path, monkeypatch):
    seen = []
    real_replace = os.replace

    def spy(src, dst):
        src_name, dst_name = os.path.basename(src), os.path.basename(dst)
        if fnmatch.fnmatch(dst_name, "cmd-*.txt"):
            assert not fnmatch.fnmatch(src_name, "cmd-*.txt"), "temp name must not look like a cmd file"
            assert src_name.startswith(".tmp-cmd-")
            with open(src, encoding="utf-8") as f:
                seen.append(f.read())
            assert not os.path.exists(dst)
        real_replace(src, dst)

    monkeypatch.setattr("os.replace", spy)
    db = dbm.Devbridge(tmp_path)
    db.submit('echo "hello world"')
    assert seen == ['h1 echo "hello world"\n']
    assert sorted(p.name for p in tmp_path.iterdir()) == [".seq", ".seq.lock", "cmd-0000000001.txt"]


def test_concurrent_submit_unique_ordered(tmp_path):
    clients = [dbm.Devbridge(tmp_path) for _ in range(4)]
    results: list[int] = []
    lock = threading.Lock()

    def worker(db):
        for _ in range(25):
            seq = db.submit("ping")[0]
            with lock:
                results.append(seq)

    threads = [threading.Thread(target=worker, args=(c,)) for c in clients]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sorted(results) == list(range(1, 101))
    assert len(list(tmp_path.glob("cmd-*.txt"))) == 100
    assert not list(tmp_path.glob(".tmp-cmd-*"))


# ---- unit: reading and waiting --------------------------------------------------------------

def test_read_complete_partial_and_truncation(tmp_path):
    db = dbm.Devbridge(tmp_path)
    log = tmp_path / "log.txt"
    log.write_bytes(b"HARNESS a=1\r\nHARNESS b=2\nHARNESS c=")
    lines, off = db._read_complete(0)
    assert [ln for ln, _ in lines] == ["HARNESS a=1", "HARNESS b=2"]
    assert off == len(b"HARNESS a=1\r\nHARNESS b=2\n")
    with open(log, "ab") as f:
        f.write(b"3\n")
    lines, off2 = db._read_complete(off)
    assert [ln for ln, _ in lines] == ["HARNESS c=3"]
    log.write_bytes(b"HARNESS new=1\n")  # recreated (smaller than our offset)
    lines, _ = db._read_complete(off2)
    assert [ln for ln, _ in lines] == ["HARNESS new=1"]
    assert db.lines() == ["HARNESS new=1"]


def test_wait_for_regex_predicate_since_and_timeout(tmp_path):
    log = tmp_path / "log.txt"
    log.write_text("HARNESS t=0.000 wall=1 ev=devbridge_ready version=1 last_seq=9\nHARNESS t=1.000 wall=2 ev=x n=1\n")
    db = dbm.Devbridge(tmp_path)
    hit = db.wait_for(r"ev=x n=\d", timeout=1)
    assert hit["kv"]["n"] == "1" and hit["end"] == log.stat().st_size
    assert db.wait_for(lambda p: p["kv"].get("ev") == "x", timeout=1)["t"] == 1.0
    ready = db.wait_ready(timeout=1)
    assert ready["kv"]["version"] == "1"
    assert db.submit("ping")[0] == 10  # wait_ready raised the counter to the game's last_seq
    with pytest.raises(dbm.WaitTimeout):
        db.wait_for(r"ev=x", timeout=0.2, since=hit["end"])
    late = dbm.Devbridge(tmp_path, since="end")
    with pytest.raises(dbm.WaitTimeout):
        late.wait_ready(timeout=0.2)


class FakeGame(threading.Thread):
    """Minimal pure-Python responder (no C++): ack every command; `lines <n>` adds data lines."""

    def __init__(self, d: Path, delay_s: float = 0.0):
        super().__init__(daemon=True)
        self.d, self.delay_s, self.stop = d, delay_s, threading.Event()

    def run(self):
        while not self.stop.is_set():
            for n in sorted(os.listdir(self.d)):
                if not dbm.CMD_RE.match(n):
                    continue
                p = self.d / n
                text = p.read_text()
                p.unlink()
                cid, verb, *rest = text.split()
                time.sleep(self.delay_s)
                out = []
                if verb == "lines":
                    out = [f"HARNESS t=0.000 wall=0 data id={cid} i={i}" for i in range(1, int(rest[0]) + 1)]
                    out.append(f"HARNESS t=0.000 wall=0 ack id={cid} ok=1 verb=lines count={rest[0]}")
                elif verb == "fail":
                    out = [f'HARNESS t=0.000 wall=0 ack id={cid} ok=0 err="no good" verb=fail']
                elif verb == "slow":  # D111 keep-alives, then the ack
                    out = [f"HARNESS t=0.000 wall=0 ev=pending id={cid} verb=slow elapsed_s={s}" for s in (5, 10)]
                    out.append(f"HARNESS t=0.000 wall=0 ack id={cid} ok=1 verb=slow fps_avg=60.0")
                else:
                    out = [f"HARNESS t=0.000 wall=0 ack id={cid} ok=1 verb={verb}"]
                with open(self.d / "log.txt", "a", encoding="utf-8") as f:
                    # another command's line first: the client must match on id
                    f.write("HARNESS t=0.000 wall=0 ack id=someone_else ok=1 verb=ping\n")
                    f.write("".join(line + "\n" for line in out))
            time.sleep(0.005)


@pytest.fixture
def fake_game(tmp_path):
    g = FakeGame(tmp_path)
    g.start()
    yield g
    g.stop.set()
    g.join(2)


def test_send_with_fake_responder(tmp_path, fake_game):
    db = dbm.Devbridge(tmp_path)
    r = db.send("lines", 3, timeout=5)
    assert r.ok and r.id == "h1" and r.seq == 1 and r.kv["count"] == "3"
    assert [d["kv"]["i"] for d in r.data] == ["1", "2", "3"]
    assert r.line.endswith("ack id=h1 ok=1 verb=lines count=3")
    assert r.end == (tmp_path / "log.txt").stat().st_size
    bad = db.send("fail", timeout=5, id="custom")
    assert not bad.ok and bad.err == "no good" and bad.id == "custom"
    slow = db.send("slow", timeout=5)  # ev=pending lines with the same id are not the ack
    assert slow.ok and slow.kv["verb"] == "slow" and slow.kv["fps_avg"] == "60.0"


def test_send_timeout_withdraws_unclaimed_file(tmp_path):
    db = dbm.Devbridge(tmp_path)
    with pytest.raises(dbm.AckTimeout) as ei:
        db.send("ping", timeout=0.2)
    assert ei.value.picked_up is False
    assert not list(tmp_path.glob("cmd-*.txt"))


def test_alive_false_raises_game_gone(tmp_path):
    db = dbm.Devbridge(tmp_path)
    with pytest.raises(dbm.GameGone):
        db.send("ping", timeout=5, alive=lambda: False)


def test_lane_dir(tmp_path, monkeypatch):
    (tmp_path / "lane-2.env").write_text(
        "export LANE=2\nexport WINEPREFIX='/x/prefix-lane2'\n"
        "export FL_DEVBRIDGE_DIR='/x/prefix-lane2/drive_c/Games/Freelancer HD Edition/SAVE/devbridge'\n")
    assert dbm.lane_dir(2, locks=str(tmp_path)).endswith("Freelancer HD Edition/SAVE/devbridge")
    monkeypatch.setenv("FLMOD_LOCKS", str(tmp_path))
    assert dbm.lane_dir("2").startswith("/x/prefix-lane2/")
    with pytest.raises(OSError):
        dbm.lane_dir(9)


def test_cli_send_timeout_and_usage_exit_codes(tmp_path):
    r = subprocess.run(CLI + ["--dir", str(tmp_path), "send", "ping", "--timeout", "0.3"],
                       capture_output=True, text=True, timeout=30)
    assert r.returncode == 2, r.stderr
    assert "withdrawn" in r.stderr
    assert not list(tmp_path.glob("cmd-*.txt"))
    r = subprocess.run(CLI + ["--dir", str(tmp_path), "bogus"], capture_output=True, text=True, timeout=30)
    assert r.returncode == 64
    env = {k: v for k, v in os.environ.items() if k != "FL_DEVBRIDGE_DIR"}
    r = subprocess.run(CLI + ["offset"], capture_output=True, text=True, timeout=30, env=env)
    assert r.returncode == 64
    r = subprocess.run(CLI + ["offset"], capture_output=True, text=True, timeout=30,
                       env=dict(env, FL_DEVBRIDGE_DIR=str(tmp_path)))
    assert r.returncode == 0 and r.stdout.strip() == "0"


def test_cli_send_with_fake_responder(tmp_path, fake_game):
    r = subprocess.run(CLI + ["--dir", str(tmp_path), "send", "--timeout", "5", "lines", "2"],
                       capture_output=True, text=True, timeout=30)
    assert r.returncode == 0, r.stderr
    out = r.stdout.splitlines()
    assert len(out) == 3 and "data id=h1 i=1" in out[0] and "ack id=h1 ok=1" in out[2]
    r = subprocess.run(CLI + ["--dir", str(tmp_path), "send", "fail", "--id", "f1"], capture_output=True, text=True,
                       timeout=30)
    assert r.returncode == 1 and "ack id=f1 ok=0" in r.stdout


# ---- end to end against host_sim ------------------------------------------------------------

def _needs_build() -> bool:
    if not HOST_SIM.exists():
        return True
    built = HOST_SIM.stat().st_mtime
    return any(s.stat().st_mtime > built for s in HOST_SIM_SOURCES)


@pytest.fixture(scope="module")
def host_sim():
    if not (os.access(CXX, os.X_OK) or shutil.which("clang++")):
        pytest.skip(f"clang++ not found ({CXX}): cannot build host_sim")
    if _needs_build():
        r = subprocess.run(["bash", str(BUILD_SCRIPT), "--build-only"], capture_output=True, text=True, timeout=900)
        if r.returncode == 3:
            pytest.skip("host_sim build skipped: " + r.stderr.strip())
        assert r.returncode == 0, r.stdout + r.stderr
    return str(HOST_SIM)


class Game:
    def __init__(self, root: Path, binary: str, marker: bool = True, frames: int | None = None):
        self.exe = root / "EXE"
        self.exe.mkdir(parents=True)
        if marker:
            (self.exe / "devbridge.enabled").write_text("")
        self.dir = root / "SAVE" / "devbridge"
        self.binary, self.frames, self.proc = binary, frames, None
        self.db = dbm.Devbridge(self.dir)
        self.stderr = open(root / "host_sim.stderr", "w")

    def start(self):
        args = [self.binary, str(self.exe), "--fps", "200", "--max-wall-s", "60"]
        if self.frames is not None:
            args += ["--frames", str(self.frames)]
        self.proc = subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=self.stderr)
        return self

    def alive(self) -> bool:
        return self.proc is not None and self.proc.poll() is None

    def close(self):
        if self.alive():
            try:
                self.db.send("quit", timeout=5, alive=self.alive)
                self.proc.wait(5)
            except (dbm.DevbridgeError, subprocess.TimeoutExpired):
                self.proc.kill()
                self.proc.wait(5)
        self.stderr.close()


@pytest.fixture
def game(tmp_path, host_sim):
    g = Game(tmp_path, host_sim)
    g.dir.mkdir(parents=True)
    (g.dir / "cmd-0000000003.txt").write_text("stale1 ping\n")  # left over from an earlier run
    g.start()
    g.ready = g.db.wait_ready(10, alive=g.alive)
    yield g
    g.close()


def test_e2e_ready_stale_cleanup(game):
    kv = game.ready["kv"]
    assert kv["version"] == "1" and kv["stale_cmds"] == "1" and kv["last_seq"] == "3" and kv["poll_frames"] == "10"
    assert not (game.dir / "cmd-0000000003.txt").exists()
    r = game.db.send("ping", timeout=5)
    assert r.seq == 4  # wait_ready raised the client's counter past the stale file
    assert not any("id=stale1" in ln for ln in game.db.lines())


def test_e2e_ping_echo_seq_state(game):
    db = game.db
    r = db.send("ping", timeout=5, alive=game.alive)
    assert r.ok and r.kv["pong"] == "1" and r.kv["verb"] == "ping" and r.err is None
    assert r.line.startswith("HARNESS t=") and " wall=" in r.line
    assert db.send("echo", "hello", "big", "world", timeout=5).kv["text"] == "hello big world"
    # echo returns the raw text after the verb, so an arg that needed quotes keeps them
    assert db.send("echo", "a b", "c\\d", timeout=5).kv["text"] == '"a b" c\\d'
    assert db.send_line('echo  say "hi there" ', timeout=5).kv["text"] == 'say "hi there"'
    s = db.send("seq", timeout=5)
    assert s.kv["last_seq"] == str(s.seq)
    st = db.send("state", timeout=5)
    assert st.kv["state"] == "menu" and st.kv["hull"] == "-1"


def test_e2e_sleep_frames_blocks_fifo(game):
    db = game.db
    s_seq, s_id, start = db.submit("sleep_frames 30")
    p_seq, p_id, _ = db.submit("ping")
    sl = db.wait_ack(s_id, start, timeout=10, seq=s_seq)
    pg = db.wait_ack(p_id, start, timeout=10, seq=p_seq)
    assert sl.ok and sl.kv["frames"] == "30" and pg.ok
    lines = db.lines(start)
    i_sleep = next(i for i, ln in enumerate(lines) if f"ack id={s_id} " in ln)
    i_ping = next(i for i, ln in enumerate(lines) if f"ack id={p_id} " in ln)
    assert i_sleep < i_ping
    assert dbm.parse_line(lines[i_sleep])["t"] <= dbm.parse_line(lines[i_ping])["t"]


def test_e2e_errors(game):
    db = game.db
    u = db.send("frobnicate", 1, timeout=5)
    assert not u.ok and u.err == "unknown verb frobnicate" and u.kv["verb"] == "frobnicate"
    t = db.send("throw", timeout=5)
    assert not t.ok and t.err == "exception: boom"
    n = db.send("never", 0.3, timeout=10)
    assert not n.ok and n.err == "timeout" and n.kv["timeout_s"] == "0.300"
    b = db.send_line('echo "unterminated', timeout=5)
    assert not b.ok and b.err == "bad_cmd: unterminated quote"
    assert any("ev=bad_cmd" in ln and f"id={b.id}" in ln for ln in db.lines())
    assert db.send("ping", timeout=5).ok  # still healthy


def test_e2e_data_lines(game):
    r = game.db.send("lines", 3, timeout=5)
    assert r.ok and r.kv["count"] == "3"
    assert [(d["kv"]["i"], d["kv"]["text"]) for d in r.data] == [("1", "line 1"), ("2", "line 2"), ("3", "line 3")]
    assert all(d["words"] == ["data"] and d["kv"]["id"] == r.id for d in r.data)


def test_e2e_duplicate_file_ignored(game):
    db = game.db
    r = db.send("ping", timeout=5)
    dup = game.dir / dbm.cmd_file_name(r.seq)
    dup.write_text("dupe1 ping\n")  # what Wine delete lag looks like: same seq seen again
    db.wait_for(rf"ev=cmd_dup file={dup.name} last_seq={r.seq}", timeout=5, since=r.end)
    assert db.send("ping", timeout=5).ok  # FIFO: anything queued before this has been handled
    assert not dup.exists()
    assert not any("id=dupe1" in ln for ln in db.lines())


def test_e2e_counter_behind_is_resubmitted(game):
    db = game.db
    r = db.send("ping", timeout=5)
    (game.dir / ".seq").write_text("0\n")  # simulate a lost counter
    again = db.send("echo", "retry", timeout=5)
    assert again.ok and again.kv["text"] == "retry" and again.seq == r.seq + 1
    assert any("ev=cmd_dup file=cmd-0000000001.txt" in ln for ln in db.lines(r.end))
    assert sum(f"ack id={again.id} " in ln for ln in db.lines()) == 1


def test_e2e_game_gone(game):
    killer = threading.Timer(0.3, game.proc.kill)
    killer.start()
    try:
        with pytest.raises(dbm.GameGone):
            game.db.send("never", 30, timeout=10, alive=game.alive)
    finally:
        killer.cancel()
        game.proc.wait(5)


def test_e2e_quit(game):
    r = game.db.send("quit", timeout=5, alive=game.alive)
    assert r.ok and r.kv["verb"] == "quit"
    assert game.proc.wait(5) == 0
    assert game.db.lines()[-1].endswith("ev=devbridge_shutdown")


def test_e2e_inactive_without_marker(tmp_path, host_sim):
    g = Game(tmp_path, host_sim, marker=False, frames=40)
    g.dir.mkdir(parents=True)
    (g.dir / "cmd-0000000001.txt").write_text("a ping\n")
    g.start()
    assert g.proc.wait(10) == 0
    g.close()
    assert not (g.dir / "log.txt").exists()
    assert (g.dir / "cmd-0000000001.txt").exists()


def test_e2e_cli(game, tmp_path):
    d = ["--dir", str(game.dir)]
    r = subprocess.run(CLI + d + ["send", "echo", "hi", "there", "--timeout", "5"], capture_output=True, text=True,
                       timeout=30)
    assert r.returncode == 0, r.stderr
    assert 'verb=echo text="hi there"' in r.stdout
    r = subprocess.run(CLI + d + ["send", "frobnicate"], capture_output=True, text=True, timeout=30)
    assert r.returncode == 1 and "ok=0" in r.stdout
    r = subprocess.run(CLI + d + ["wait-ready", "--timeout", "5"], capture_output=True, text=True, timeout=30)
    assert r.returncode == 0 and "ev=devbridge_ready" in r.stdout
    r = subprocess.run(CLI + d + ["wait", r"ack id=\S+ ok=0", "--timeout", "5"], capture_output=True, text=True,
                       timeout=30)
    assert r.returncode == 0 and "verb=frobnicate" in r.stdout

    cmds = tmp_path / "cmds.txt"
    cmds.write_text("# setup\n\nping\necho one two\nfrobnicate\necho after_failure\n")
    r = subprocess.run(CLI + d + ["run-file", str(cmds), "--timeout", "5"], capture_output=True, text=True, timeout=60)
    assert r.returncode == 1
    assert "text=\"one two\"" in r.stdout and "after_failure" not in r.stdout
    r = subprocess.run(CLI + d + ["run-file", str(cmds), "--keep-going"], capture_output=True, text=True, timeout=60)
    assert r.returncode == 1 and "text=after_failure" in r.stdout
    cmds.write_text("ping\nsleep_frames 2\n")
    r = subprocess.run(CLI + d + ["run-file", str(cmds)], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0 and r.stdout.count("ok=1") == 2

    off = subprocess.run(CLI + d + ["offset"], capture_output=True, text=True, timeout=30).stdout.strip()
    assert int(off) == game.db.offset()
    r = subprocess.run(CLI + d + ["--since", off, "tail"], capture_output=True, text=True, timeout=30)
    assert r.returncode == 0 and r.stdout == ""
    r = subprocess.run(CLI + d + ["tail"], capture_output=True, text=True, timeout=30)
    assert r.stdout.splitlines()[0].split(" ", 3)[3].startswith("ev=devbridge_ready")
