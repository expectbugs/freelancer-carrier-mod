"""verdict.py + lib/spew_allow.py tests. Every run dir is SYNTHETIC (tmp_path); no game files are read."""
import json
import os
import re
import subprocess
import sys

import pytest

HARNESS = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
sys.path.insert(0, HARNESS)
sys.path.insert(0, os.path.join(HARNESS, "lib"))

import spew_allow  # noqa: E402
import verdict  # noqa: E402

VERDICT_PY = os.path.join(HARNESS, "verdict.py")
SPEW_ALLOW_PY = os.path.join(HARNESS, "lib", "spew_allow.py")
KEYS = {"verdict", "reasons", "signatures", "fault", "new_spew_errors", "first_chance_exceptions", "cmds",
        "expects", "ready", "clean_quit", "run"}

EXE = r"C:\\Games\\Freelancer HD Edition\\EXE"
SERVER_BASE = 0x06CE0000
COMMON_BASE = 0x06260000


def loaddll(name, base, wide=False, kind="native"):
    b = "%016X" % base if wide else "%08X" % base
    path = r"C:\\windows\\system32\\" + name if wide else EXE + "\\\\" + name
    return '00f4:trace:loaddll:build_module Loaded L"%s" at %s: %s' % (path, b, kind)


def av(addr, wide=False, tid="00f4"):
    a = "%016X" % addr if wide else "%08X" % addr
    return [
        "%s:trace:seh:dispatch_exception code=c0000005 (EXCEPTION_ACCESS_VIOLATION) flags=0 addr=%s" % (tid, a),
        "%s:trace:seh:dispatch_exception  info[0]=00000000" % tid,
        "%s:trace:seh:dispatch_exception  info[1]=00000010" % tid,
        "%s:trace:seh:dispatch_exception  eax=00000000 ebx=00000001 ecx=0012fe00 eip=%s" % (tid, a[-8:]),
        "%s:warn:seh:dispatch_exception backtrace: --- Exception 0xc0000005." % tid,
    ]


def modules():
    return [
        loaddll("ntdll.dll", 0x00006FFFFFBF0000, wide=True, kind="builtin"),
        loaddll("Freelancer.exe", 0x00400000),
        loaddll("common.dll", COMMON_BASE),
        loaddll("server.dll", SERVER_BASE),
        r'00f4:trace:loaddll:build_module Loaded L"C:\\Games\\Freelancer HD Edition\\EXE\\fluf\\FLUF.dll" at E6BA0000: native',
    ]


def healthy_run(**over):
    run = {
        "name": "t", "lane": 1, "track": None, "prefix": "/nonexistent/prefix-lane-1", "hde": "/nonexistent/hde",
        "args": [], "start_ms": 1000, "end_ms": 200000, "game_pid": 4242, "window_id": "0x3a00007",
        "window_method": "pid", "ready": True, "ready_marker": "ev=devbridge_ready", "quit_sent": True,
        "quit_ms": 190000, "exited_after_quit": True, "process_exit_ms": 191000, "exit_code": 0,
        "early_exit": False, "timeout": False,
        "hang": {"detected": False, "at_ms": None, "idle_s": None, "minidump": None},
        "cmds": [{"line": "state", "id": "h1", "sent_ms": 5000, "ack": True, "ok": 1, "err": None,
                  "expect_fail": False}],
        "expects": [{"regex": "state=menu", "matched": True, "where": "devbridge_log.txt"}],
        "crash_windows": [], "dw15_seen": False, "new_dumps": [], "spew_allow": None,
    }
    run.update(over)
    return run


HEALTHY_SPEW = [
    r"C:\src\lib\x\Loader.cpp(618) : NOTICE:General:Loader: DLL 'C:\Games\x\EXE\plugin.dll' [1.1.2]",
    r"[2026-10-17 15:03:54] C:\src\x\Sound\Stream.cpp(50) : ERROR:General:StreamingSound: missing MP3 codec?",
    r"[2026-10-17 15:03:57] E:\src\Client\Session.cpp(351) : NOTICE:General:Starting game.",
]


def mk(tmp_path, run="healthy", wine=None, spew=None, liveness=None, devbridge=None, name="run"):
    d = tmp_path / name
    d.mkdir()
    if run == "healthy":
        run = healthy_run()
    if run is not None:
        (d / "run.json").write_text(json.dumps(run))
    (d / "wine.log").write_text("\n".join(modules() + (wine or [])) + "\n")
    (d / "FLSpew.txt").write_text("\n".join(HEALTHY_SPEW if spew is None else spew) + "\n")
    if liveness is not None:
        (d / "liveness.tsv").write_text("ms\talive\tspew_bytes\tdevbridge_bytes\tpending\n" + "".join(
            "%d\t%d\t%d\t%d\t%d\n" % r for r in liveness))
    (d / "devbridge_log.txt").write_text("\n".join(devbridge or [
        "HARNESS t=1.000 wall=1760000000000 ev=devbridge_ready ver=1",
        "HARNESS t=2.000 wall=1760000001000 ack id=h1 ok=1 verb=state state=menu"]) + "\n")
    return str(d)


def V(rundir, **kw):
    v = verdict.compute_verdict(rundir, **kw)
    assert set(v) == KEYS
    return v


def kinds(v):
    return [s["kind"] for s in v["signatures"]]


# ------------------------------------------------------------------ PASS / CRASH

def test_pass_despite_many_first_chance_av(tmp_path):
    wine = []
    for i in range(40):
        wine += av(COMMON_BASE + 0x1000 + i)
    v = V(mk(tmp_path, wine=wine))
    assert v["verdict"] == "PASS", v["reasons"]
    assert v["first_chance_exceptions"] == 40
    assert v["clean_quit"] is True and v["ready"] is True
    assert v["fault"] == {"module": None, "rva": None, "addr": None, "offset_lookup": []}
    assert v["cmds"] == {"sent": 1, "acked": 1, "failed": 0}
    assert v["expects"] == {"total": 1, "matched": 1}


def test_crash_trailing_av_then_early_exit(tmp_path):
    wine = []
    for i in range(10):
        wine += av(COMMON_BASE + 0x2000 + i)
    wine += av(SERVER_BASE + 0x14990)
    run = healthy_run(early_exit=True, exit_code=0, quit_sent=False, exited_after_quit=False)
    v = V(mk(tmp_path, run=run, wine=wine))
    assert v["verdict"] == "CRASH", v["reasons"]
    assert "trailing_exception" in kinds(v)
    assert v["fault"]["module"] == "server.dll"
    assert v["fault"]["rva"] == "0x14990"
    assert v["fault"]["addr"] == "0x%x" % (SERVER_BASE + 0x14990)


def test_crash_early_exit_nonzero_code_64bit_addr_form(tmp_path):
    wine = av(SERVER_BASE + 0x14990, wide=True)
    run = healthy_run(early_exit=True, exit_code=5, quit_sent=False, exited_after_quit=False)
    v = V(mk(tmp_path, run=run, wine=wine))
    assert v["verdict"] == "CRASH"
    assert "early_exit" in kinds(v)
    assert (v["fault"]["module"], v["fault"]["rva"]) == ("server.dll", "0x14990")


def test_crash_missing_process_unknown_exit_code(tmp_path):
    run = healthy_run(early_exit=True, exit_code=None, window_id=None, quit_sent=False, exited_after_quit=False)
    d = mk(tmp_path, run=run)
    os.remove(os.path.join(d, "wine.log"))
    v = V(d)
    assert v["verdict"] == "CRASH"  # not NO_WINDOW: the process vanished
    assert "early_exit" in kinds(v)
    assert "no_window" not in kinds(v)


def test_crash_dw15(tmp_path):
    v = V(mk(tmp_path, run=healthy_run(dw15_seen=True)))
    assert v["verdict"] == "CRASH" and "dw15" in kinds(v)


def test_crash_window(tmp_path):
    run = healthy_run(crash_windows=[{"wid": "0x4400001", "title": "Fatal Crash. Unknown Error Code", "pid": 4242}])
    v = V(mk(tmp_path, run=run))
    assert v["verdict"] == "CRASH" and "crash_window" in kinds(v)
    assert any("Fatal Crash" in s["detail"] for s in v["signatures"])


def test_crash_new_dump(tmp_path):
    v = V(mk(tmp_path, run=healthy_run(new_dumps=["/tmp/x/crash.dmp"])))
    assert v["verdict"] == "CRASH" and "new_dump" in kinds(v)


def test_crash_definite_wine_text_even_after_quit(tmp_path):
    wine = av(COMMON_BASE + 0x10) + [
        "wine: Unhandled page fault on read access to 00000010 at address %08X (thread 00f4), starting debugger..."
        % (SERVER_BASE + 0xAB670)]
    v = V(mk(tmp_path, wine=wine))
    assert v["verdict"] == "CRASH" and "wine_crash_text" in kinds(v)
    assert (v["fault"]["module"], v["fault"]["rva"]) == ("server.dll", "0xab670")


def test_early_exit_with_old_av_is_exited_early_not_crash(tmp_path):
    wine = av(COMMON_BASE + 0x10) + ["00f4:trace:loaddll:noise line %d" % i for i in range(400)]
    run = healthy_run(early_exit=True, exit_code=0, quit_sent=False, exited_after_quit=False)
    v = V(mk(tmp_path, run=run, wine=wine))
    assert v["verdict"] == "EXITED_EARLY", v["reasons"]
    assert v["first_chance_exceptions"] == 1


def test_exited_early(tmp_path):
    run = healthy_run(early_exit=True, exit_code=0, quit_sent=False, exited_after_quit=False, window_id=None)
    v = V(mk(tmp_path, run=run))
    assert v["verdict"] == "EXITED_EARLY"
    assert kinds(v) == ["early_exit_clean"]
    assert v["clean_quit"] is False


# ------------------------------------------------------------------ HANG

def test_hang_from_run_json(tmp_path):
    run = healthy_run(hang={"detected": True, "at_ms": 90000, "idle_s": 61.0, "minidump": "hang.mdmp"},
                      quit_sent=False, exited_after_quit=False)
    v = V(mk(tmp_path, run=run))
    assert v["verdict"] == "HANG" and "hang" in kinds(v)


def test_crash_text_after_detected_hang_is_hang_not_crash(tmp_path):
    # NOTES.md N14: winedbg attaching to the hung WoW64 game made a new thread fault; that is the dump's doing
    lines = modules()
    run = healthy_run(hang={"detected": True, "at_ms": 90000, "idle_s": 61.0, "minidump": None,
                            "wine_log_lines": len(lines)},
                      quit_sent=False, exited_after_quit=False)
    wine = av(0xFFF40E50, tid="01d0") + [
        "wine: Unhandled page fault on read access to FFF40E50 at address FFF40E50 (thread 01d0), starting debugger..."]
    v = V(mk(tmp_path, run=run, wine=wine))
    assert v["verdict"] == "HANG", v["reasons"]
    assert "wine_crash_text" not in kinds(v)
    assert any("attributed to the hang dump" in r for r in v["reasons"])


def test_crash_text_before_detected_hang_still_crash(tmp_path):
    wine = ["wine: Unhandled page fault on read access to 00000010 at address 06D8B670 (thread 00f4), starting debugger..."]
    run = healthy_run(hang={"detected": True, "at_ms": 90000, "idle_s": 61.0, "minidump": None,
                            "wine_log_lines": len(modules()) + 5},
                      quit_sent=False, exited_after_quit=False)
    v = V(mk(tmp_path, run=run, wine=wine))
    assert v["verdict"] == "CRASH", v["reasons"]


def _liv7(tmp_path, name, rows):
    p = tmp_path / name
    p.write_text("ms\talive\tspew_bytes\tdevbridge_bytes\tpending\tcpu_ticks\tphase\twine_bytes\thb\n" +
                 "".join("\t".join(str(x) for x in r) + "\n" for r in rows))
    return str(p)


def test_liveness_progress_signals_and_heartbeat(tmp_path):
    # start-up: wine.log growth (module loads) is progress; nothing growing is a stall; CPU use is not progress
    loading = [(1000 + s * 1000, 1, 500, 0, 1, s * 100, "startup", 1000 + s * 50, 0) for s in range(90)]
    assert verdict.liveness_hang(_liv7(tmp_path, "a.tsv", loading), 60) is None
    spin = [(1000 + s * 1000, 1, 500, 0, 1, s * 100, "startup", 1000, 0) for s in range(90)]
    assert verdict.liveness_hang(_liv7(tmp_path, "b.tsv", spin), 60)["why"] == "start-up wait"
    # after start-up wine.log growth does not count: a pending command with only wine.log growth is a stall
    run = [(1000 + s * 1000, 1, 500, 20, 1, s * 100, "run", 1000 + s * 50, 0) for s in range(90)]
    assert verdict.liveness_hang(_liv7(tmp_path, "c.tsv", run), 60)["why"] == "command pending"
    # idle (nothing pending) with a heartbeat-capable devbridge that went silent: frozen game (review probe 5)
    frozen = [(1000 + s * 1000, 1, 500, 300, 0, s * 100, "run", 1000, 1) for s in range(300)]
    assert verdict.liveness_hang(_liv7(tmp_path, "d.tsv", frozen), 60)["why"] == "heartbeat silent"
    # idle, no heartbeat (Track A: nothing writes while the menu sits there): not a hang
    quiet = [(1000 + s * 1000, 1, 500, 0, 0, s * 100, "run", 1000, 0) for s in range(300)]
    assert verdict.liveness_hang(_liv7(tmp_path, "e.tsv", quiet), 60) is None
    # D111 keep-alives make a long command grow the devbridge log: no stall
    longcmd = [(1000 + s * 1000, 1, 500, 300 + (s // 5) * 60, 1, s * 100, "run", 1000, 1) for s in range(90)]
    assert verdict.liveness_hang(_liv7(tmp_path, "f.tsv", longcmd), 60) is None


# ---- review r1 probes (MAJOR 1, MINOR 5): crash/hang during or after quit, partial run.json ---------------

NOISE = ["00f4:trace:loaddll:noise %d" % i for i in range(20)]


def test_r1_crash_on_quit_nonzero_exit_codes(tmp_path):
    for code, name in ((0xC0000005, "av"), (1, "one")):
        v = V(mk(tmp_path, run=healthy_run(exit_code=code), wine=NOISE + av(COMMON_BASE + 0x5DA50), name=name))
        assert v["verdict"] == "CRASH" and "exit_code" in kinds(v), v["reasons"]
    # killed by the harness, or a vdesk lane (exit code is explorer's): the code says nothing about the game
    v = V(mk(tmp_path, run=healthy_run(exit_code=1, killed_by_harness=True), name="killed"))
    assert "exit_code" not in kinds(v)
    v = V(mk(tmp_path, run=healthy_run(exit_code=1, exit_code_is_game=False), name="vdesk"))
    assert "exit_code" not in kinds(v)


def test_r1_clean_quit_with_trailing_handled_av_is_pass(tmp_path):
    # every real clean quit ends with a handled AV at dacom.dll+0x3de4 and exit code 0 (NOTES.md N18)
    v = V(mk(tmp_path, run=healthy_run(exit_code=0), wine=NOISE + av(COMMON_BASE + 0x3DE4)))
    assert v["verdict"] == "PASS", v["reasons"]


def test_r1_dw15_loaded_only_in_wine_log(tmp_path):
    dw = '00f4:trace:loaddll:build_module Loaded L"%s\\\\dw15.exe" at 00400000: native' % EXE
    v = V(mk(tmp_path, run=healthy_run(exit_code=0), wine=NOISE + [dw]))
    assert v["verdict"] == "CRASH" and "dw15_loaded" in kinds(v), v["reasons"]


def test_r1_quit_acked_but_no_exit_is_hang(tmp_path):
    run = healthy_run(exited_after_quit=False, process_exit_ms=None, exit_code=None, quit_acked=True,
                      killed_by_harness=True)
    v = V(mk(tmp_path, run=run))
    assert v["verdict"] == "HANG" and "quit_no_exit" in kinds(v), v["reasons"]


def test_r1_minimal_or_unready_run_json_is_not_pass(tmp_path):
    v = V(mk(tmp_path, run={"name": "x"}, name="min"))
    assert v["verdict"] == "FAIL" and "incomplete_run_json" in kinds(v)
    v = V(mk(tmp_path, run=healthy_run(ready=False), name="unready"))
    assert v["verdict"] == "FAIL" and "not_ready" in kinds(v)
    v = V(mk(tmp_path, run=healthy_run(lane_lost={"ms": 1, "holder_pid": "9"}), name="lost"))
    assert v["verdict"] == "FAIL" and "lane_lost" in kinds(v)


def test_d107_listed_dacom_library_must_load(tmp_path):
    loaded = '00f4:trace:loaddll:build_module Loaded L"%s\\\\\\\\devbridge_selftest.dll" at 10000000: native' % EXE
    v = V(mk(tmp_path, run=healthy_run(dacom_libraries=["devbridge_selftest.dll"]), wine=[loaded], name="ok"))
    assert v["verdict"] == "PASS", v["reasons"]
    v = V(mk(tmp_path, run=healthy_run(dacom_libraries=["devbridge_selftest.dll"]), name="missing"))
    assert v["verdict"] == "FAIL" and "dll_not_loaded" in kinds(v), v["reasons"]


def test_window_not_at_slot_is_fail(tmp_path):
    wp = {"geometry": "WINDOW=1 X=0 Y=0 WIDTH=3744 HEIGHT=2106", "slot": [0, 0], "ok": False, "tries": 5}
    v = V(mk(tmp_path, run=healthy_run(window_placed=wp), name="bad"))
    assert v["verdict"] == "FAIL" and "window_not_at_slot" in kinds(v)
    v = V(mk(tmp_path, run=healthy_run(window_placed=dict(wp, ok=True)), name="good"))
    assert v["verdict"] == "PASS", v["reasons"]


def test_r1_frozen_while_idle_with_heartbeat_is_hang(tmp_path):
    rows = [(1000 + i * 1000, 1, 5000, 300, 0, 100 + i * 100, "run", 9000, 1) for i in range(300)]
    d = mk(tmp_path, run=healthy_run())
    with open(os.path.join(d, "liveness.tsv"), "w") as f:
        f.write("ms\talive\tspew_bytes\tdevbridge_bytes\tpending\tcpu_ticks\tphase\twine_bytes\thb\n")
        f.writelines("\t".join(str(x) for x in r) + "\n" for r in rows)
    v = V(d)
    assert v["verdict"] == "HANG" and "hang_liveness" in kinds(v), v["reasons"]


def test_runner_error_and_failed_step_are_fail(tmp_path):
    v = V(mk(tmp_path, run=healthy_run(runner_error="RuntimeError: console launch refused"), name="a"))
    assert v["verdict"] == "FAIL" and "runner_error" in kinds(v)
    run = healthy_run(steps=[{"step": "key F3", "ok": True, "info": "ok"},
                             {"step": "wait_state system_id=1 60", "ok": False, "info": {"system_id": "2"}}])
    v = V(mk(tmp_path, run=run, name="b"))
    assert v["verdict"] == "FAIL" and kinds(v) == ["step_failed"]
    v = V(mk(tmp_path, run=healthy_run(steps=[{"step": "sleep 1", "ok": True, "info": None}]), name="c"))
    assert v["verdict"] == "PASS", v["reasons"]


def _live(n, stall_from, pending_from=0, alive=1, grow_until=None):
    rows = []
    for s in range(n):
        grow = s < stall_from if grow_until is None else s < grow_until
        b = s * 100 if grow else stall_from * 100
        rows.append((1000 + s * 1000, alive, b, b // 2, 1 if s >= pending_from else 0))
    return rows


def test_hang_offline_from_liveness(tmp_path):
    v = V(mk(tmp_path, liveness=_live(100, stall_from=10, pending_from=5)))
    assert v["verdict"] == "HANG", v["reasons"]
    assert "hang_liveness" in kinds(v)


def test_no_hang_short_stall_or_nothing_pending(tmp_path):
    assert V(mk(tmp_path, liveness=_live(40, stall_from=10), name="short"))["verdict"] == "PASS"
    assert V(mk(tmp_path, liveness=_live(100, stall_from=10, pending_from=1000), name="idle"))["verdict"] == "PASS"
    assert V(mk(tmp_path, liveness=_live(100, stall_from=10, alive=0), name="dead"))["verdict"] == "PASS"
    # 59 s stall is under the threshold; --hang-s lowers it
    d = mk(tmp_path, liveness=_live(70, stall_from=10), name="edge")
    assert V(d)["verdict"] == "PASS"
    assert V(d, hang_s=30)["verdict"] == "HANG"


def test_hang_growth_resets_stall(tmp_path):
    rows = []
    for s in range(200):  # one byte of spew every 50 s: never a 60 s stall
        b = s // 50
        rows.append((s * 1000, 1, b, 7, 1))
    assert V(mk(tmp_path, liveness=rows))["verdict"] == "PASS"


# ------------------------------------------------------------------ NO_WINDOW / TIMEOUT / FAIL

def test_no_window(tmp_path):
    v = V(mk(tmp_path, run=healthy_run(window_id=None)))
    assert v["verdict"] == "NO_WINDOW" and kinds(v) == ["no_window"]


def test_timeout(tmp_path):
    v = V(mk(tmp_path, run=healthy_run(timeout=True, ready=False)))
    assert v["verdict"] == "TIMEOUT" and v["ready"] is False


def test_fail_cmd_ok0_and_noack(tmp_path):
    cmds = [{"line": "load x", "id": "h1", "sent_ms": 1, "ack": True, "ok": 0, "err": "no such save",
             "expect_fail": False}]
    v = V(mk(tmp_path, run=healthy_run(cmds=cmds), name="ok0"))
    assert v["verdict"] == "FAIL" and v["cmds"] == {"sent": 1, "acked": 1, "failed": 1}
    cmds = [{"line": "state", "id": "h1", "sent_ms": 1, "ack": False, "ok": None, "err": None, "expect_fail": False}]
    v = V(mk(tmp_path, run=healthy_run(cmds=cmds), name="noack"))
    assert v["verdict"] == "FAIL" and v["cmds"] == {"sent": 1, "acked": 0, "failed": 1}


def test_expected_failure_is_not_fail(tmp_path):
    cmds = [{"line": "load nope", "id": "h1", "sent_ms": 1, "ack": True, "ok": 0, "err": "not found",
             "expect_fail": True}]
    v = V(mk(tmp_path, run=healthy_run(cmds=cmds)))
    assert v["verdict"] == "PASS" and v["cmds"]["failed"] == 0


def test_fail_unmatched_expect(tmp_path):
    exps = [{"regex": "state=space", "matched": False, "where": None},
            {"regex": "state=menu", "matched": True, "where": "devbridge_log.txt"}]
    v = V(mk(tmp_path, run=healthy_run(expects=exps)))
    assert v["verdict"] == "FAIL" and v["expects"] == {"total": 2, "matched": 1}
    assert "expect_unmatched" in kinds(v)


def test_missing_run_json_is_fail(tmp_path):
    v = V(mk(tmp_path, run=None))
    assert v["verdict"] == "FAIL" and "no_run_json" in kinds(v)


def test_precedence(tmp_path):
    hang = {"detected": True, "at_ms": 1, "idle_s": 61, "minidump": None}
    run = healthy_run(dw15_seen=True, hang=hang, timeout=True, window_id=None)
    assert V(mk(tmp_path, run=run, name="a"))["verdict"] == "CRASH"
    run = healthy_run(hang=hang, timeout=True, window_id=None)
    assert V(mk(tmp_path, run=run, name="b"))["verdict"] == "HANG"
    run = healthy_run(timeout=True, window_id=None)
    assert V(mk(tmp_path, run=run, name="c"))["verdict"] == "NO_WINDOW"
    run = healthy_run(timeout=True, early_exit=True, exit_code=0, window_id=None)
    assert V(mk(tmp_path, run=run, name="d"))["verdict"] == "EXITED_EARLY"
    run = healthy_run(timeout=True, expects=[{"regex": "x", "matched": False, "where": None}])
    assert V(mk(tmp_path, run=run, name="e"))["verdict"] == "TIMEOUT"


# ------------------------------------------------------------------ spew allow-list

BASE_SPEW = [
    r"C:\src\lib\x\Loader.cpp(618) : NOTICE:General:Loader: DLL 'C:\Games\x\plugin.dll' [1.1.2]",
    r"[2026-10-17 15:03:54] C:\src\x\Sound\Stream.cpp(50) : ERROR:General:StreamingSound: missing MP3 codec?",
    r"[2026-10-17 15:03:55] C:\src\x\Render\render_dx8.cpp(4819) : WARNING:General:set_mode() called outside of begin_frame/end_frame",
    r"[2026-10-17 15:03:56] E:\src\Common\Thing.cpp(77) : *** WARNING: object 0x0ABCDEF0 has 3 parts at 12.5 m",
    r"[2026-10-17 15:03:56] E:\src\Common\Thing.cpp(77) : *** WARNING: object 0x0BBBBBB0 has 4 parts at 1.25 m",
    r"[2026-10-17 15:03:57] E:\src\Client\Session.cpp(351) : NOTICE:General:Starting game.",
]
NEW_SPEW = [
    r"C:\src\lib\x\Loader.cpp(618) : NOTICE:General:Loader: DLL 'C:\Games\x\plugin.dll' [1.1.2]",
    r"[2026-10-18 01:02:03] C:\src\x\Sound\Stream.cpp(50) : ERROR:General:StreamingSound: missing MP3 codec?",
    r"[2026-10-18 01:02:04] C:\src\x\Render\render_dx8.cpp(4820) : WARNING:General:set_mode() called outside of begin_frame/end_frame",
    r"[2026-10-18 01:02:05] E:\src\Common\Thing.cpp(78) : *** WARNING: object 0x12345678 has 17 parts at 3.75 m",
    r"[2026-10-18 01:02:06] E:\src\Common\Shiparch.cpp(901) : *** ERROR: fcm_test_ship has no engine",
    r"[2026-10-18 01:02:07] E:\src\Client\Session.cpp(351) : NOTICE:General:Starting game.",
]
NEW_ERR = r"E:\src\Common\Shiparch.cpp(901) : *** ERROR: fcm_test_ship has no engine"


def test_normalize_and_classify():
    ts = r"[2026-10-17 15:03:54] C:\x\Stream.cpp(50) : ERROR:General:StreamingSound: missing MP3 codec?" + "\r\n"
    assert spew_allow.normalize(ts) == r"C:\x\Stream.cpp(50) : ERROR:General:StreamingSound: missing MP3 codec?"
    assert spew_allow.normalize("no timestamp here  \n") == "no timestamp here"
    assert spew_allow.is_error_line(spew_allow.normalize(ts))
    assert spew_allow.is_error_line(r"C:\x\Thing.cpp(1) : *** WARNING: x")
    assert spew_allow.is_error_line("*** ERROR: synthetic failure x")
    assert not spew_allow.is_error_line(r"C:\x\Session.cpp(351) : NOTICE:General:Starting game.")
    assert not spew_allow.is_error_line(r"C:\x\a.cpp(1) : NOTICE:General:text mentions ERROR: inside a notice")


def test_spew_allow_build_round_trip(tmp_path):
    base = tmp_path / "base.txt"
    base.write_text("\n".join(BASE_SPEW) + "\n")
    pats = spew_allow.build_allow([str(base)])
    assert len(pats) == 3  # MP3, render, Thing (two pointer variants dedupe to one)
    comp = [re.compile(p) for p in pats]
    for line in BASE_SPEW:
        n = spew_allow.normalize(line)
        if spew_allow.is_error_line(n):
            assert any(c.search(n) for c in comp), (n, pats)
    unrelated = r"E:\src\Common\Thing.cpp(77) : *** ERROR: object 0x0ABCDEF0 has 3 parts at 12.5 m"
    assert not any(c.search(unrelated) for c in comp)
    assert not any(c.search("C:\\x\\Other.cpp(5) : ERROR:General:something else") for c in comp)
    for p in pats:  # short: the long source path prefix is gone
        assert "src" not in p and len(p) < 200, p
        assert p.startswith("^.*") and p.endswith("$")
    assert r"[0-9A-Fa-fx]+" in pats[2] and r"\d+" in pats[2]


def test_spew_allow_cli_build_and_check(tmp_path):
    base = tmp_path / "base.txt"
    base.write_text("\n".join(BASE_SPEW) + "\n")
    out = tmp_path / "allow.txt"
    r = subprocess.run([sys.executable, "-I", SPEW_ALLOW_PY, "build", "--out", str(out), str(base)],
                       capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    lines = out.read_text().splitlines()
    assert lines[0].startswith("#")
    assert len(spew_allow.read_allow_lines(str(out))) == 3
    # --merge keeps a hand-written pattern
    with open(out, "a") as f:
        f.write("\n# hand-written\nhand pattern$\n")
    r = subprocess.run([sys.executable, "-I", SPEW_ALLOW_PY, "build", "--merge", "--out", str(out), str(base)],
                       capture_output=True, text=True, timeout=60)
    assert r.returncode == 0 and "hand pattern$" in [s for _, s in spew_allow.read_allow_lines(str(out))]
    new = tmp_path / "new.txt"
    new.write_text("\n".join(NEW_SPEW) + "\n")
    r = subprocess.run([sys.executable, "-I", SPEW_ALLOW_PY, "check", "--allow", str(out), str(new)],
                       capture_output=True, text=True, timeout=60)
    assert r.returncode == 1 and NEW_ERR in r.stdout and "1 line(s) not allowed" in r.stdout


def test_new_spew_errors_with_allow_list(tmp_path):
    base = tmp_path / "base.txt"
    base.write_text("\n".join(BASE_SPEW) + "\n")
    allow = tmp_path / "spew_allow_B.txt"
    allow.write_text("# test allow-list\n\n" + "\n".join(
        p for p in spew_allow.build_allow([str(base)]) if "MP3" not in p) + "\n")
    d = mk(tmp_path, spew=NEW_SPEW)
    v = V(d, allow=str(allow))  # allow given -> strict
    assert v["verdict"] == "FAIL", v["reasons"]
    assert v["new_spew_errors"] == [NEW_ERR]  # MP3 (builtin) allowed; timestamps/pointers/line numbers normalized
    assert "new_spew_errors" in kinds(v)
    v = V(d, allow=str(allow), spew_check="report")
    assert v["verdict"] == "PASS" and v["new_spew_errors"] == [NEW_ERR]
    meta = {}
    v = V(d, meta=meta)  # no allow file, no track -> still strict: fails closed (review r1 m4)
    assert v["verdict"] == "FAIL" and meta["spew_mode"] == "strict"
    assert NEW_ERR in v["new_spew_errors"] and len(v["new_spew_errors"]) == 3
    v = V(d, allow=str(tmp_path / "__missing_B_wined3d.txt"))  # the runner's path for a renderer without a list
    assert v["verdict"] == "FAIL" and any("built-in patterns only" in r for r in v["reasons"])
    v = V(d, spew_check="strict")  # strict with no allow file: only builtin-allowed lines pass
    assert v["verdict"] == "FAIL" and len(v["new_spew_errors"]) == 3
    # run.json spew_allow is honoured when --allow is not given
    d2 = mk(tmp_path, run=healthy_run(spew_allow=str(allow)), spew=NEW_SPEW, name="rec")
    assert V(d2)["new_spew_errors"] == [NEW_ERR]


def test_bad_regex_in_allow_file_is_reported(tmp_path):
    allow = tmp_path / "allow.txt"
    allow.write_text("([unclosed\n")
    v = V(mk(tmp_path), allow=str(allow))
    assert v["verdict"] == "PASS"
    assert any("bad regex" in r for r in v["reasons"])


# ------------------------------------------------------------------ CLI

def test_cli_writes_verdict_json_and_exit_codes(tmp_path):
    d = mk(tmp_path, name="ok")
    r = subprocess.run([sys.executable, "-I", VERDICT_PY, d, "--spew-check", "report"],
                       capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stdout + r.stderr
    assert r.stdout.startswith("verdict=PASS ") and len(r.stdout.strip().splitlines()) == 1
    with open(os.path.join(d, "verdict.json")) as f:
        assert set(json.load(f)) == KEYS
    d = mk(tmp_path, run=healthy_run(dw15_seen=True), name="crash")
    r = subprocess.run([sys.executable, "-I", VERDICT_PY, d], capture_output=True, text=True, timeout=60)
    assert r.returncode == verdict.EXIT_CODES["CRASH"] and r.stdout.startswith("verdict=CRASH ")
    with open(os.path.join(d, "verdict.json")) as f:
        assert json.load(f)["verdict"] == "CRASH"
    r = subprocess.run([sys.executable, "-I", VERDICT_PY, str(tmp_path / "nope")], capture_output=True, text=True,
                       timeout=60)
    assert r.returncode != 0
