"""triage.py tests. Run dirs and wine.log are SYNTHETIC (tmp_path). The real crash-offsets table is only
read at runtime from refs (never copied); tests that need it skip when it is absent."""
import json
import os
import subprocess
import sys

import pytest

HARNESS = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
sys.path.insert(0, HARNESS)
sys.path.insert(0, os.path.join(HARNESS, "lib"))

import triage  # noqa: E402
import verdict  # noqa: E402

TRIAGE_PY = os.path.join(HARNESS, "triage.py")
EXE = r"C:\\Games\\Freelancer HD Edition\\EXE"
SERVER_BASE = 0x06CE0000
COMMON_BASE = 0x06260000

REAL_TABLE = triage.find_offsets_file()
needs_table = pytest.mark.skipif(REAL_TABLE is None, reason="crash-offsets.json not present under refs")


def real_description(module, offset):
    with open(REAL_TABLE, encoding="utf-8") as f:
        for e in json.load(f):
            if e["moduleName"].lower() == module and int(e["offset"], 16) == offset:
                return e["description"]
    raise AssertionError("entry not in table")


def loaddll(name, base, wide=False):
    if wide:
        return r'0024:trace:loaddll:build_ntdll_module Loaded L"C:\\windows\\system32\\%s" at %016X: builtin' % (
            name, base)
    return '00f4:trace:loaddll:build_module Loaded L"%s\\\\%s" at %08X: native' % (EXE, name, base)


def av(addr, code="c0000005"):
    return ["00f4:trace:seh:dispatch_exception code=%s (EXCEPTION_ACCESS_VIOLATION) flags=0 addr=%08X" % (code, addr),
            "00f4:trace:seh:dispatch_exception  info[0]=00000000",
            "00f4:trace:seh:dispatch_exception  eip=%08X esp=0012fd00" % addr]


def mods():
    return [loaddll("ntdll.dll", 0x00006FFFFFBF0000, wide=True), loaddll("Freelancer.exe", 0x00400000),
            loaddll("common.dll", COMMON_BASE), loaddll("server.dll", SERVER_BASE)]


def mkrun(tmp_path, wine, run=None, spew=None, dev=None, name="run"):
    d = tmp_path / name
    d.mkdir()
    r = {"window_id": "0x1", "ready": True, "quit_sent": False, "exited_after_quit": False, "early_exit": True,
         "exit_code": None, "timeout": False, "cmds": [], "expects": [], "crash_windows": [], "dw15_seen": False,
         "new_dumps": [], "hang": {"detected": False}}
    r.update(run or {})
    (d / "run.json").write_text(json.dumps(r))
    (d / "wine.log").write_text("\n".join(wine) + "\n")
    if spew is not None:
        (d / "FLSpew.txt").write_text("\n".join(spew) + "\n")
    if dev is not None:
        (d / "devbridge_log.txt").write_text("\n".join(dev) + "\n")
    return str(d)


def write_table(tmp_path, entries):
    p = tmp_path / "offsets.json"
    p.write_text(json.dumps(entries))
    return str(p)


SYNTH = [
    {"moduleName": "Server.dll", "offset": "0x00014990", "author": "t", "description": "synthetic A"},
    {"moduleName": "common", "offset": "5DA50", "author": "t", "description": "synthetic B"},
    {"moduleName": "content.dll", "offset": 4096, "author": "t", "description": "synthetic C (int offset)"},
    {"moduleName": "broken.dll", "offset": "zz", "author": "t", "description": "ignored"},
    {"offset": "0x1", "description": "no module: ignored"},
]


# ------------------------------------------------------------------ acceptance (REQ-14)

@needs_table
def test_acceptance_server_dll_0x14990(tmp_path):
    wine = mods()
    for i in range(20):  # handled first-chance noise earlier in the run
        wine += av(COMMON_BASE + 0x500 + i)
    wine += av(SERVER_BASE + 0x14990)
    spew = ["spew line %d" % i for i in range(80)]
    dev = ["HARNESS t=%d.000 wall=%d ev=hb" % (i, 1760000000000 + i) for i in range(30)]
    d = mkrun(tmp_path, wine, spew=spew, dev=dev)
    r = subprocess.run([sys.executable, "-I", TRIAGE_PY, d], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    out = r.stdout
    assert "verdict: CRASH" in out
    assert "module=server.dll" in out and "rva=0x14990" in out
    assert "base=0x6ce0000" in out
    desc = real_description("server.dll", 0x14990)
    assert "likely cause: " + desc in out
    assert "TESTING hotspot: base without solar at launch" in out
    # last 50 FLSpew lines and last 20 devbridge lines
    lines = out.splitlines()
    assert "spew line 79" in lines and "spew line 30" in lines and "spew line 29" not in lines
    assert "HARNESS t=29.000 wall=1760000000029 ev=hb" in lines
    assert "HARNESS t=10.000 wall=1760000000010 ev=hb" in lines
    assert "HARNESS t=9.000 wall=1760000000009 ev=hb" not in lines
    # verdict.json gets the same fault
    v = verdict.compute_verdict(d)
    assert v["fault"]["module"] == "server.dll" and v["fault"]["rva"] == "0x14990"
    assert v["fault"]["offset_lookup"][0]["description"] == desc
    assert v["fault"]["offset_lookup"][0]["match"] == "exact"


@needs_table
def test_lookup_cli_real_table():
    desc = real_description("server.dll", 0x14990)
    for mod, off in (("server.dll", "0x14990"), ("SERVER.DLL", "14990"), ("server", "0x00014990")):
        r = subprocess.run([sys.executable, "-I", TRIAGE_PY, "--lookup", mod, off], capture_output=True, text=True,
                           timeout=60)
        assert r.returncode == 0, r.stdout + r.stderr
        assert "[exact]" in r.stdout and desc in r.stdout
    r = subprocess.run([sys.executable, "-I", TRIAGE_PY, "--lookup", "server.dll", "0x1499a"], capture_output=True,
                       text=True, timeout=60)
    assert r.returncode == 1 and "[near]" in r.stdout and desc in r.stdout
    r = subprocess.run([sys.executable, "-I", TRIAGE_PY, "--lookup", "server.dll", "0x7777777"], capture_output=True,
                       text=True, timeout=60)
    assert r.returncode == 1 and "unknown offset; see TESTING §CrashTriage hotspots" in r.stdout
    assert "server.dll 0xab670" in r.stdout and "freelancer.exe 0x14661b" in r.stdout


# ------------------------------------------------------------------ table handling (synthetic)

def test_lookup_synthetic_table_formats(tmp_path):
    table = triage.load_offsets(write_table(tmp_path, SYNTH))
    assert len(table) == 3
    hit = triage.lookup("server.dll", 0x14990, table)
    assert [h["description"] for h in hit] == ["synthetic A"] and hit[0]["match"] == "exact"
    assert triage.lookup("COMMON.DLL", 0x5DA50, table)[0]["description"] == "synthetic B"
    assert triage.lookup("content", 0x1000, table)[0]["description"] == "synthetic C (int offset)"
    near = triage.lookup("server.dll", 0x14990 + 0x10, table)
    assert near and near[0]["match"] == "near" and near[0]["delta"] == 0x10
    assert triage.lookup("server.dll", 0x14990 - 0x11, table) == []
    assert triage.lookup("other.dll", 0x14990, table) == []


def test_lookup_cli_synthetic_and_bad_input(tmp_path):
    p = write_table(tmp_path, SYNTH)
    r = subprocess.run([sys.executable, "-I", TRIAGE_PY, "--offsets", p, "--lookup", "server.dll", "0x14990"],
                       capture_output=True, text=True, timeout=60)
    assert r.returncode == 0 and "synthetic A" in r.stdout
    r = subprocess.run([sys.executable, "-I", TRIAGE_PY, "--offsets", p, "--lookup", "server.dll", "xyz"],
                       capture_output=True, text=True, timeout=60)
    assert r.returncode == 64
    r = subprocess.run([sys.executable, "-I", TRIAGE_PY, "--offsets", str(tmp_path / "none.json"), "--lookup",
                        "server.dll", "0x1"], capture_output=True, text=True, timeout=60)
    assert r.returncode == 66


# ------------------------------------------------------------------ fault location

def test_prefers_last_exception_inside_32bit_module(tmp_path):
    wine = mods() + av(COMMON_BASE + 0x100) + av(SERVER_BASE + 0x14990) + av(0x00000010)
    scan = triage.scan_wine_log(os.path.join(mkrun(tmp_path, wine), "wine.log"))
    f = triage.find_fault(scan, table=[])
    assert (f["module"], f["rva"], f["addr"]) == ("server.dll", "0x14990", "0x%x" % (SERVER_BASE + 0x14990))


def test_unknown_address_falls_back_to_last_exception(tmp_path):
    wine = mods() + av(0x00000010)
    scan = triage.scan_wine_log(os.path.join(mkrun(tmp_path, wine), "wine.log"))
    f = triage.find_fault(scan, table=[])
    assert f["addr"] == "0x10" and f["module"] is None and f["rva"] is None


def test_module_extent_and_reload(tmp_path):
    wine = mods() + [loaddll("late.dll", 0x10000000)]
    scan = triage.scan_wine_log(os.path.join(mkrun(tmp_path, wine), "wine.log"))
    m = triage.modules_at(scan)
    assert triage.find_module(m, COMMON_BASE + 0x5DA50)[0] == "common.dll"
    assert triage.find_module(m, SERVER_BASE - 1)[0] == "common.dll"  # spans until the next base
    assert triage.find_module(m, SERVER_BASE)[0] == "server.dll"
    assert triage.find_module(m, SERVER_BASE + (64 << 20)) is None  # 64 MiB cap
    assert triage.find_module(m, 0x1000) is None
    assert triage.find_module(m, 0x00006FFFFFBF0010)[0] == "ntdll.dll"
    # server.dll reloaded at another base after an unload: the later base applies to later faults only
    wine2 = mods() + av(SERVER_BASE + 0x20) + [
        r'00f4:trace:loaddll:free_modref Unloaded module L"%s\\server.dll" : native' % EXE,
        loaddll("server.dll", 0x20000000)] + av(0x20000000 + 0x14990)
    scan2 = triage.scan_wine_log(os.path.join(mkrun(tmp_path, wine2, name="r2"), "wine.log"))
    assert triage.find_module(triage.modules_at(scan2), SERVER_BASE + 0x20)[0] != "server.dll"
    assert triage.find_module(triage.modules_at(scan2, scan2["exceptions"][0]["line"]), SERVER_BASE + 0x20)[0] == \
        "server.dll"
    f = triage.find_fault(scan2, table=[])
    assert (f["module"], f["rva"]) == ("server.dll", "0x14990")


def test_scan_counts_and_ignores_cpp_exceptions(tmp_path):
    wine = mods() + av(COMMON_BASE + 1) + av(COMMON_BASE + 2) + av(COMMON_BASE + 3, code="e06d7363") + [
        "0024:err:module:import_dll Library MSVCP140.dll (which is needed by L\"C:\\\\x\\\\a.dll\") not found"]
    scan = triage.scan_wine_log(os.path.join(mkrun(tmp_path, wine), "wine.log"))
    assert triage.first_chance_count(scan) == 2
    assert len(scan["import_errors"]) == 1 and scan["definite"] == []
    assert triage.last_system_exception(scan)["addr"] == COMMON_BASE + 2


def test_unknown_offset_prints_hotspots(tmp_path):
    wine = mods() + av(SERVER_BASE + 0x777)
    d = mkrun(tmp_path, wine)
    r = subprocess.run([sys.executable, "-I", TRIAGE_PY, "--offsets", write_table(tmp_path, SYNTH), d],
                       capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    assert "rva=0x777" in r.stdout
    assert "likely cause: unknown offset; see TESTING §CrashTriage hotspots" in r.stdout
    assert "common.dll 0x5da50" in r.stdout and "server.dll 0x1b221" in r.stdout
    assert "missing" in r.stdout  # FLSpew/devbridge absent: reported, not fatal


def test_triage_survives_empty_run_dir(tmp_path):
    d = tmp_path / "empty"
    d.mkdir()
    out = triage.triage_report(str(d))
    assert "wine.log: missing" in out and "fault: no exception address" in out
