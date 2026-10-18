#!/usr/bin/env python3
"""Crash triage for a harness run dir (REQ-P0-HARNESS-14, TESTING §CrashTriage).

  triage.py <rundir> [--offsets <crash-offsets.json>] [--spew-lines 50] [--devbridge-lines 20]
  triage.py --lookup <module> <hex offset> [--offsets <crash-offsets.json>]

Fault location: `+loaddll` lines in wine.log give module bases; the fault address comes from wine's
"Unhandled ..." message if present, else from the last first-chance system exception (`+seh`
dispatch_exception) before the end of the log, preferring one inside a loaded 32-bit module.
RVA = addr - base; it is looked up in the Starport crash-offsets table, loaded at runtime from refs
(never copied into this repo). Module extents are unknown from the log: a module is assumed to span
until the next higher base, capped at 64 MiB.

Importable: scan_wine_log, scan_crash_lines, modules_at, find_module, find_fault, load_offsets,
lookup, likely_cause, tail_lines, triage_report.
"""
from __future__ import annotations

import argparse
import bisect
import collections
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.realpath(__file__))

_REFS = os.environ.get("FLMOD_REFS") or "/home/user/freelancer/refs"
CRASH_OFFSETS_PATHS = (
    os.path.join(_REFS, "StarportKnowledgeBase", "static", "payloads", "crash-offsets.json"),
    os.path.join(_REFS, "starport-kb-payload", "crash-offsets.json"),
)
MODULE_CAP = 64 << 20
NEAR = 0x10
EXC_WINDOW = 10        # how many of the final exceptions are searched for one inside a 32-bit module
TRAILING_LINES = 300   # an exception this close to the end of wine.log is "trailing" (UNVERIFIED tuning)

# TESTING §CrashTriage "known hotspots" (our own notes; descriptions of the table live in refs).
HOTSPOTS = (
    ("server.dll", 0xAB670, "base without solar at launch"),
    ("server.dll", 0x14990, "base without solar at launch"),
    ("common.dll", 0x5DA50, "capital death fuses"),
    ("common.dll", 0x5E010, "capital death fuses"),
    ("common.dll", 0xC22FE, "loading a save with unknown nicknames"),
    ("common.dll", 0x91F38, "loading a save with unknown nicknames"),
    ("server.dll", 0x1B221, "per-system >10 jump objects"),
    ("freelancer.exe", 0x14661B, "destroying a just-spawned scripted NPC (SP-only)"),
)

RE_LOADED = re.compile(r'Loaded L"(?P<path>[^"]*)" at (?:0x)?(?P<base>[0-9A-Fa-f]+)(?::\s*(?P<kind>\w+))?')
RE_UNLOADED = re.compile(r'Unloaded module L"(?P<path>[^"]*)"')
RE_DISPATCH_CODE = re.compile(r"\bcode=(?:0x)?(?P<code>[0-9A-Fa-f]{1,8})\b(?:\s*\((?P<name>[^)]*)\))?")
RE_DISPATCH_ADDR = re.compile(r"\b(?:addr|ip)=(?:0x)?(?P<addr>[0-9A-Fa-f]+)\b")
RE_EXC_WARN = re.compile(r"--- Exception 0x(?P<code>[0-9A-Fa-f]+)")
RE_DEFINITE = re.compile(
    r"wine: Unhandled|Unhandled exception|Unhandled page fault|Unhandled stack overflow"
    r"|starting debugger|unimplemented function .*aborting|virtual_setup_exception stack overflow"
)
RE_DEFINITE_ADDR = re.compile(r"(?:at address|\baddr)[ =](?:0x)?(?P<addr>[0-9A-Fa-f]+)\b")
RE_IMPORT_ERR = re.compile(r"err:module:import_dll .*not found")


# --------------------------------------------------------------------------- wine.log

def _basename(path: str) -> str:
    return re.split(r"[\\/]+", path)[-1].lower()


def is_system_error(code: int) -> bool:
    """NTSTATUS severity=error, customer bit clear (c0000005 etc.; excludes C++ e06d7363 and debug prints)."""
    return (code & 0xE0000000) == 0xC0000000


def _empty_scan(path, exists=False):
    return {"path": path, "exists": exists, "lines": 0, "loads": [], "exceptions": [],
            "warn_exceptions": 0, "definite": [], "import_errors": []}


def scan_wine_log(path) -> dict:
    """One pass over wine.log. Missing file -> empty scan with exists=False."""
    scan = _empty_scan(path)
    if not path or not os.path.isfile(path):
        return scan
    scan["exists"] = True
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        for ln, line in enumerate(f, 1):
            scan["lines"] = ln
            if "Loaded L\"" in line:
                m = RE_LOADED.search(line)
                if m:
                    p = m.group("path").replace("\\\\", "\\")
                    scan["loads"].append((ln, "load", _basename(p), p, int(m.group("base"), 16), m.group("kind")))
                    continue
            if "Unloaded module" in line:
                m = RE_UNLOADED.search(line)
                if m:
                    p = m.group("path").replace("\\\\", "\\")
                    scan["loads"].append((ln, "unload", _basename(p), p, None, None))
                    continue
            if "dispatch_exception" in line:
                mc = RE_DISPATCH_CODE.search(line)
                if mc:
                    ma = RE_DISPATCH_ADDR.search(line, mc.end())
                    scan["exceptions"].append({
                        "line": ln, "code": int(mc.group("code"), 16), "name": mc.group("name"),
                        "addr": int(ma.group("addr"), 16) if ma else None})
                    continue
                if RE_EXC_WARN.search(line):
                    scan["warn_exceptions"] += 1
                    continue
            if RE_DEFINITE.search(line):
                ma = RE_DEFINITE_ADDR.search(line)
                scan["definite"].append({"line": ln, "text": line.strip()[:300],
                                         "addr": int(ma.group("addr"), 16) if ma else None})
            elif "import_dll" in line and RE_IMPORT_ERR.search(line):
                scan["import_errors"].append(line.strip()[:300])
    return scan


def scan_crash_lines(path) -> list:
    """Definite crash texts from crash_lines.txt (harness extract); same patterns as wine.log."""
    out = []
    if path and os.path.isfile(path):
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            for ln, line in enumerate(f, 1):
                if RE_DEFINITE.search(line):
                    ma = RE_DEFINITE_ADDR.search(line)
                    out.append({"line": ln, "text": line.strip()[:300],
                                "addr": int(ma.group("addr"), 16) if ma else None})
    return out


def first_chance_count(scan) -> int:
    n = sum(1 for e in scan["exceptions"] if is_system_error(e["code"]))
    return n if scan["exceptions"] else scan["warn_exceptions"]


def modules_at(scan, line_no=None) -> dict:
    """{base: (name, path)} for loads at or before `line_no` (later loads replace earlier ones)."""
    by_base = {}
    by_path = {}
    for ln, op, name, path, base, _kind in scan["loads"]:
        if line_no is not None and ln > line_no:
            break
        key = path.lower()
        if op == "load":
            old = by_path.get(key)
            if old is not None and old != base:
                by_base.pop(old, None)
            prev = by_base.get(base)
            if prev is not None and prev[1].lower() != key:
                by_path.pop(prev[1].lower(), None)
            by_base[base] = (name, path)
            by_path[key] = base
        else:
            old = by_path.pop(key, None)
            if old is not None:
                by_base.pop(old, None)
    return by_base


def find_module(mods: dict, addr: int):
    """(name, base, path) of the module containing addr, or None."""
    if addr is None or not mods:
        return None
    bases = sorted(mods)
    i = bisect.bisect_right(bases, addr) - 1
    if i < 0:
        return None
    base = bases[i]
    limit = base + MODULE_CAP
    if i + 1 < len(bases):
        limit = min(limit, bases[i + 1])
    if addr >= limit:
        return None
    name, path = mods[base]
    return name, base, path


def _in_32bit_module(scan, exc):
    if exc["addr"] is None or exc["addr"] > 0xFFFFFFFF:
        return None
    hit = find_module(modules_at(scan, exc["line"]), exc["addr"])
    if hit and hit[1] <= 0xFFFFFFFF:
        return hit
    return None


def last_system_exception(scan, before_line=None):
    excs = [e for e in scan["exceptions"] if is_system_error(e["code"])
            and (before_line is None or e["line"] < before_line)]
    return excs[-1] if excs else None


def is_trailing(scan, exc) -> bool:
    return exc is not None and scan["lines"] - exc["line"] <= TRAILING_LINES


def find_fault(scan, definite_extra=(), table=None) -> dict:
    """Fault dict: module, rva, addr, offset_lookup (verdict.json keys) plus base, path, code, line, source."""
    fault = {"module": None, "rva": None, "addr": None, "offset_lookup": [],
             "base": None, "path": None, "code": None, "line": None, "source": None}
    definite = list(scan["definite"]) + list(definite_extra)
    chosen = None
    # wine's own "Unhandled ... at address X" wins; crash_lines.txt entries resolve against all loads.
    for src, items in (("wine.log", scan["definite"]), ("crash_lines.txt", definite_extra)):
        for d in items:
            if d["addr"] is not None:
                chosen = {"line": d["line"] if src == "wine.log" else None, "addr": d["addr"], "code": None}
                fault["source"] = "unhandled-exception message (%s line %d)" % (src, d["line"])
                break
        if chosen:
            break
    if chosen is None:
        before = scan["definite"][0]["line"] if scan["definite"] else None
        excs = [e for e in scan["exceptions"] if is_system_error(e["code"]) and e["addr"] is not None
                and (before is None or e["line"] < before)]
        if excs:
            pick = None
            for e in reversed(excs[-EXC_WINDOW:]):
                if _in_32bit_module(scan, e):
                    pick = e
                    break
            pick = pick or excs[-1]
            chosen = pick
            fault["source"] = "last first-chance exception code=%08x (wine.log line %d)" % (pick["code"], pick["line"])
    if chosen is None:
        if definite:
            fault["source"] = "crash text without an address"
        return fault
    fault["addr"] = "0x%x" % chosen["addr"]
    fault["line"] = chosen["line"]
    if chosen.get("code") is not None:
        fault["code"] = "0x%08x" % chosen["code"]
    hit = find_module(modules_at(scan, chosen["line"]), chosen["addr"])
    if hit:
        name, base, path = hit
        rva = chosen["addr"] - base
        fault.update(module=name, base="0x%x" % base, path=path, rva="0x%x" % rva)
        if table is not None:
            fault["offset_lookup"] = lookup(name, rva, table)
    return fault


# --------------------------------------------------------------------------- crash-offsets table

def _modkey(name: str) -> str:
    n = _basename(str(name).strip())
    for ext in (".dll", ".exe"):
        if n.endswith(ext):
            return n[: -len(ext)]
    return n


def _parse_offset(v):
    if isinstance(v, bool):
        return None
    if isinstance(v, int):
        return v
    if isinstance(v, str):
        s = v.strip().lower()
        if s.startswith("0x"):
            s = s[2:]
        try:
            return int(s, 16)
        except ValueError:
            return None
    return None


def find_offsets_file(path=None):
    cands = [path] if path else [os.environ.get("CRASH_OFFSETS_JSON"), os.environ.get("CRASH_OFFSETS_JSON_ALT"),
                                 *CRASH_OFFSETS_PATHS]
    for c in cands:
        if c and os.path.isfile(c):
            return c
    return None


def load_offsets(path=None) -> list:
    """Normalized table: [{"_mod": key, "_off": int, "entry": original dict}]. Missing/invalid -> []."""
    p = find_offsets_file(path)
    if not p:
        return []
    try:
        with open(p, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return []
    if isinstance(data, dict):  # tolerate {"entries":[...]} or {"<module>": [...]} shapes
        data = data.get("entries") or data.get("offsets") or [
            dict(e, moduleName=k) for k, v in data.items() if isinstance(v, list) for e in v if isinstance(e, dict)]
    out = []
    for e in data if isinstance(data, list) else []:
        if not isinstance(e, dict):
            continue
        mod = e.get("moduleName", e.get("module", e.get("Module")))
        off = _parse_offset(e.get("offset", e.get("Offset")))
        if mod is None or off is None:
            continue
        out.append({"_mod": _modkey(mod), "_off": off, "entry": e})
    return out


def lookup(module: str, offset: int, table, near=NEAR) -> list:
    """Entries for module (case-insensitive, .dll/.exe optional) at offset: exact first, then near (±near)."""
    key = _modkey(module)
    res = []
    for t in table:
        if t["_mod"] != key:
            continue
        delta = offset - t["_off"]
        if abs(delta) <= near:
            r = dict(t["entry"])
            r["match"] = "exact" if delta == 0 else "near"
            r["delta"] = delta
            res.append(r)
    res.sort(key=lambda r: (r["match"] != "exact", abs(r["delta"])))
    return res


def hotspot_lines() -> list:
    return ["  %s 0x%x: %s" % (m, o, why) for m, o, why in HOTSPOTS]


def likely_cause(fault) -> list:
    """Human lines: table description(s) if found, else the hotspot list."""
    hits = fault.get("offset_lookup") or []
    exact = [h for h in hits if h.get("match") == "exact"]
    if exact:
        return ["likely cause: %s (%s)" % (h.get("description", "?"), h.get("author", "?")) for h in exact] + [
            "near match: %+#x %s" % (h["delta"], h.get("description", "?")) for h in hits if h.get("match") == "near"]
    out = []
    if hits:
        out += ["likely cause (near match, delta %+#x): %s (%s)" % (h["delta"], h.get("description", "?"),
                                                                   h.get("author", "?")) for h in hits]
    else:
        out.append("likely cause: unknown offset; see TESTING §CrashTriage hotspots")
    out += hotspot_lines()
    return out


# --------------------------------------------------------------------------- report

def tail_lines(path, n) -> list:
    if not path or not os.path.isfile(path) or n <= 0:
        return []
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        return [l.rstrip("\r\n") for l in collections.deque(f, maxlen=n)]


def _load_json(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else None
    except (OSError, ValueError):
        return None


def triage_report(rundir, offsets_path=None, spew_n=50, dev_n=20) -> str:
    rundir = os.path.abspath(rundir)
    out = ["triage: %s" % rundir]
    v = None
    try:
        sys.path.insert(0, HERE)
        import verdict as _verdict  # lazy: verdict imports this module
        v = _verdict.compute_verdict(rundir, offsets=offsets_path)
    except Exception as e:  # triage must still print the logs
        out.append("verdict: (not computed: %s)" % e)
    if v:
        out.append("verdict: %s" % v["verdict"])
        out += ["  reason: %s" % r for r in v["reasons"]]
    run = _load_json(os.path.join(rundir, "run.json")) or {}
    scan = scan_wine_log(os.path.join(rundir, "wine.log"))
    extra = scan_crash_lines(os.path.join(rundir, "crash_lines.txt"))
    table = load_offsets(offsets_path)
    tfile = find_offsets_file(offsets_path)
    out.append("crash-offsets: %s (%d entries)" % (tfile or "NOT FOUND", len(table)))
    if not scan["exists"]:
        out.append("wine.log: missing")
    else:
        out.append("wine.log: %d lines, %d module loads, %d first-chance system exceptions"
                   % (scan["lines"], sum(1 for l in scan["loads"] if l[1] == "load"), first_chance_count(scan)))
    for d in (scan["definite"] + extra)[:5]:
        out.append("  crash text (line %d): %s" % (d["line"], d["text"]))
    for t in run.get("crash_windows") or []:
        out.append("  crash window: %s" % (t.get("title") if isinstance(t, dict) else t))
    if run.get("dw15_seen"):
        out.append("  dw15.exe seen")
    for d in run.get("new_dumps") or []:
        out.append("  new dump: %s" % d)
    fault = find_fault(scan, extra, table)
    crashed = v is not None and v["verdict"] == "CRASH"
    if fault["addr"] is None:
        out.append("fault: no exception address found in wine.log")
    else:
        if not crashed:
            out.append("note: no crash signature; showing the last first-chance exception for reference")
        out.append("fault: module=%s base=%s addr=%s rva=%s code=%s" % (
            fault["module"] or "?", fault["base"] or "?", fault["addr"], fault["rva"] or "?", fault["code"] or "-"))
        out.append("  from: %s" % fault["source"])
        if fault["path"]:
            out.append("  path: %s" % fault["path"])
        if fault["module"]:
            for h in fault["offset_lookup"]:
                out.append("  offset table [%s]: %s 0x%08x %s: %s" % (
                    h["match"], h.get("moduleName"), _parse_offset(h.get("offset")) or 0,
                    h.get("author", "?"), h.get("description", "?")))
            out += likely_cause(fault)
            for m, o, why in HOTSPOTS:
                if _modkey(m) == _modkey(fault["module"]) and int(fault["rva"], 16) == o:
                    out.append("  TESTING hotspot: %s" % why)
        else:
            out.append("likely cause: address is not inside any module loaded before the fault line")
            out += hotspot_lines()
    if scan["import_errors"]:
        out.append("wine import errors:")
        out += ["  %s" % e for e in scan["import_errors"][:10]]
    for label, name, n in (("FLSpew", "FLSpew.txt", spew_n), ("devbridge", "devbridge_log.txt", dev_n),
                           ("fluf.log", "fluf.log", dev_n)):
        p = os.path.join(rundir, name)
        if name == "fluf.log" and not os.path.isfile(p):
            continue
        lines = tail_lines(p, n)
        out.append("--- last %d %s lines (%s) ---" % (n, label, "missing" if not os.path.isfile(p) else len(lines)))
        out += lines
    return "\n".join(out)


def _lookup_cli(module, off_text, offsets_path) -> int:
    off = _parse_offset(off_text)
    if off is None:
        print("triage: bad offset %r (want hex, e.g. 0x14990)" % off_text, file=sys.stderr)
        return 64
    table = load_offsets(offsets_path)
    if not table:
        print("triage: crash-offsets table not found or empty", file=sys.stderr)
        return 66
    fault = {"module": module, "rva": "0x%x" % off, "offset_lookup": lookup(module, off, table)}
    print("lookup: %s 0x%x" % (module, off))
    for h in fault["offset_lookup"]:
        print("  [%s] %s %s %s: %s" % (h["match"], h.get("moduleName"), h.get("offset"), h.get("author", "?"),
                                      h.get("description", "?")))
    print("\n".join(likely_cause(fault)))
    return 0 if any(h["match"] == "exact" for h in fault["offset_lookup"]) else 1


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="triage.py", description="Crash triage for a harness run dir")
    ap.add_argument("rundir", nargs="?")
    ap.add_argument("--lookup", nargs=2, metavar=("MODULE", "HEXOFFSET"))
    ap.add_argument("--offsets", help="crash-offsets.json (default: refs copy)")
    ap.add_argument("--spew-lines", type=int, default=50)
    ap.add_argument("--devbridge-lines", type=int, default=20)
    a = ap.parse_args(argv)
    if a.lookup:
        return _lookup_cli(a.lookup[0], a.lookup[1], a.offsets)
    if not a.rundir:
        ap.error("rundir or --lookup required")
    if not os.path.isdir(a.rundir):
        print("triage: no such run dir: %s" % a.rundir, file=sys.stderr)
        return 66
    print(triage_report(a.rundir, a.offsets, a.spew_lines, a.devbridge_lines))
    return 0


if __name__ == "__main__":
    sys.exit(main())
