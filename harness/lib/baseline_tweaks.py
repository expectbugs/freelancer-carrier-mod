#!/usr/bin/env python3
"""Idempotent dev-baseline tweaks with byte verification (REQ-P0-HARNESS-3..6).

Usage (called by harness/baseline.sh; never run against the play prefix):
  baseline_tweaks.py apply  --track A|B --prefix <prefix-dev-base-X> [--fluf-tree <dir>]
  baseline_tweaks.py verify --track A|B --prefix <prefix-dev-base-X>
  baseline_tweaks.py fluf-yml --prefix <prefix-dev-base-A> --generated <FLUF.yml from first launch>
  baseline_tweaks.py note --prefix <p> --key <k> --value <json>

Writes/updates <prefix>/BASELINE.json. Every binary patch reads and compares the original bytes first.
"""
from __future__ import annotations

import argparse
import datetime as _dt
import hashlib
import json
import os
import re
import shutil
import sys
from pathlib import Path

HDE_REL = Path("drive_c/Games/Freelancer HD Edition")
ALLOWED_PREFIXES = {"/home/user/freelancer/prefix-dev-base-A", "/home/user/freelancer/prefix-dev-base-B"}
PLAY_PREFIX = Path("/home/user/freelancer/prefix")
MARK_A = "carrier-mod baseline-A"
COMMENT_TAG_A = ";carrier-mod-A; "
FLUF_FORBIDDEN_DACOM = ["jflp.dll", "DelayDisplay.dll", "MP3codec.dll", "storyfactions.dll", "FLSharp.dll"]
FLUF_MODULES = ["debugger.dll", "delay_display.dll", "story_factions.dll", "story_enhancements.dll",
                "FLUF.CrashWalker.dll"]

KEEP_RUNNING = dict(file="EXE/Freelancer.exe", offset=0x1B264C, expect=bytes.fromhex("83ff010f94c2"),
                    write=bytes.fromhex("BA0100000090"))
JFLP_ALTENTER = dict(file="EXE/jflp.dll", offset=0x1528, expect=bytes.fromhex("33"), write=bytes.fromhex("04"))


def sha256(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def now() -> str:
    return _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds")


def check_prefix(p: str) -> Path:
    rp = os.path.realpath(p)
    if rp not in ALLOWED_PREFIXES:
        sys.exit(f"baseline_tweaks: refusing prefix {p!r} (resolved {rp!r}); only prefix-dev-base-A|B")
    return Path(rp)


# ---------------------------------------------------------------- text helpers (byte-preserving, CRLF-aware)
def read_lines(p: Path) -> tuple[list[str], str]:
    raw = p.read_bytes().decode("latin-1")
    eol = "\r\n" if "\r\n" in raw else "\n"
    lines = raw.split(eol)
    return lines, eol


def write_lines(p: Path, lines: list[str], eol: str) -> None:
    p.write_bytes(eol.join(lines).encode("latin-1"))


def section_bounds(lines: list[str], name: str) -> tuple[int, int]:
    """Index of the [name] header and the index one past the section's last line."""
    start = None
    for i, ln in enumerate(lines):
        s = ln.strip()
        if start is None:
            if s.lower() == f"[{name.lower()}]":
                start = i
        elif re.match(r"^\[[^\]]+\]", s):
            return start, i
    if start is None:
        raise KeyError(name)
    return start, len(lines)


def set_key_in_section(lines: list[str], section: str, key: str, value: str) -> str:
    """Set 'key = value' (first occurrence) in a section. Returns 'changed'|'already'."""
    a, b = section_bounds(lines, section)
    pat = re.compile(rf"^\s*{re.escape(key)}\s*=", re.I)
    for i in range(a + 1, b):
        if pat.match(lines[i]):
            new = f"{key} = {value}"
            if lines[i].strip() == new:
                return "already"
            lines[i] = new
            return "changed"
    # append before trailing blank lines of the section
    j = b
    while j - 1 > a and lines[j - 1].strip() == "":
        j -= 1
    lines.insert(j, f"{key} = {value}")
    return "changed"


# ---------------------------------------------------------------- state
class Baseline:
    def __init__(self, prefix: Path, track: str):
        self.prefix = prefix
        self.track = track
        self.hde = prefix / HDE_REL
        self.json_path = prefix / "BASELINE.json"
        if self.json_path.exists():
            self.data = json.loads(self.json_path.read_text())
        else:
            self.data = {"track": track, "prefix": str(prefix), "created": now(), "tweaks": [], "files": {},
                         "notes": {}}
        self.data["track"] = track

    def record(self, tid: str, **kw) -> None:
        kw = {"id": tid, **kw, "at": now()}
        self.data["tweaks"] = [t for t in self.data["tweaks"] if t["id"] != tid] + [kw]
        print(f"TWEAK {tid} status={kw.get('status')} {kw.get('note', '')}".rstrip())

    def track_file(self, rel: str) -> None:
        self.data["files"][rel] = sha256(self.hde / rel)

    def save(self) -> None:
        self.data["updated"] = now()
        self.json_path.write_text(json.dumps(self.data, indent=2, sort_keys=False) + "\n")


def backup_orig(bl: Baseline, rel: str) -> None:
    src = bl.hde / rel
    dst = bl.hde / (rel + ".hde-orig")
    if not dst.exists():
        shutil.copy2(src, dst)


# ---------------------------------------------------------------- tweaks
def binary_patch(bl: Baseline, tid: str, spec: dict) -> None:
    p = bl.hde / spec["file"]
    off, exp, new = spec["offset"], spec["expect"], spec["write"]
    with open(p, "r+b") as f:
        f.seek(off)
        cur = f.read(len(exp))
        if cur == new:
            status = "already"
        elif cur == exp:
            f.seek(off)
            f.write(new)
            f.flush()
            os.fsync(f.fileno())
            f.seek(off)
            if f.read(len(new)) != new:
                sys.exit(f"{tid}: readback mismatch")
            status = "applied"
        else:
            print(f"TWEAK_SKIPPED {tid} bytes={cur.hex()}")
            bl.record(tid, kind="binary", file=spec["file"], offset=hex(off), expected=exp.hex(), written=None,
                      found=cur.hex(), status="skipped", note=f"bytes={cur.hex()} differ from expected")
            return
    bl.record(tid, kind="binary", file=spec["file"], offset=hex(off), expected=exp.hex(), written=new.hex(),
              status=status, verified_before_write=True)
    bl.track_file(spec["file"])


def tweak_flplusplus(bl: Baseline) -> None:
    rel = "EXE/flplusplus.ini"
    p = bl.hde / rel
    lines, eol = read_lines(p)
    r1 = set_key_in_section(lines, "flplusplus", "save_in_directory", "true")
    r2 = set_key_in_section(lines, "flplusplus", "screenshots_in_directory", "true")
    write_lines(p, lines, eol)
    bl.record("flplusplus_dirs", kind="ini", file=rel,
              keys={"save_in_directory": "true", "screenshots_in_directory": "true"},
              status="already" if (r1, r2) == ("already", "already") else "applied")
    bl.track_file(rel)


def tweak_perfoptions(bl: Baseline) -> None:
    rel = "SAVE/PerfOptions.ini"
    p = bl.hde / rel
    lines, eol = read_lines(p)
    a, b = section_bounds(lines, "Display")
    st = None
    for i in range(a + 1, b):
        if re.match(r"^\s*size\s*=", lines[i], re.I):
            old = lines[i]
            st = "already" if old.strip() == "size= 1280, 720" else "applied"
            lines[i] = "size= 1280, 720"
            break
    if st is None:
        lines.insert(a + 1, "size= 1280, 720")
        st = "applied"
    write_lines(p, lines, eol)
    bl.record("perfoptions_size", kind="ini", file=rel, keys={"[Display] size": "1280, 720"}, status=st)
    bl.track_file(rel)


def tweak_marker(bl: Baseline) -> None:
    rel = "EXE/devbridge.enabled"
    p = bl.hde / rel
    st = "already" if p.exists() else "applied"
    p.touch()
    bl.record("devbridge_marker", kind="file", file=rel, status=st)


def fluf_install_files(bl: Baseline, tree: Path) -> None:
    """Copy release EXE/fluf/* and DATA/* (new files only; never overwrite an HDE file)."""
    copied, already, conflicts = 0, 0, []
    for sub in ("EXE/fluf", "DATA"):
        src_root = tree / sub
        for src in sorted(src_root.rglob("*")):
            if not src.is_file():
                continue
            rel = src.relative_to(tree).as_posix()
            dst = bl.hde / rel
            if dst.exists():
                if sha256(dst) == sha256(src):
                    already += 1
                    continue
                conflicts.append(rel)
                continue
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
            copied += 1
    if conflicts:
        print("FLUF copy conflicts (HDE file exists, not overwritten): " + ", ".join(conflicts))
    bl.record("fluf_files", kind="copy", source=str(tree), copied=copied, already=already, conflicts=conflicts,
              status="applied" if copied else "already")
    bl.track_file("EXE/fluf/FLUF.dll")


def _is_lib_line(line: str, name: str) -> bool:
    s = line.strip()
    if not s or s.startswith(";"):
        return False
    first = re.split(r"[\s;]", s, maxsplit=1)[0]
    return first.lower() == name.lower()


def _insert_block(lines: list[str], at: int, body: list[str], tag: str) -> None:
    lines[at:at] = [f"; >>> {MARK_A} {tag}", *body, f"; <<< {MARK_A} {tag}"]


def _has_block(lines: list[str], tag: str) -> bool:
    return any(ln.strip() == f"; >>> {MARK_A} {tag}" for ln in lines)


def fluf_dacom(bl: Baseline) -> None:
    rel = "EXE/dacom.ini"
    p = bl.hde / rel
    backup_orig(bl, rel)
    lines, eol = read_lines(p)
    did = []
    if not _has_block(lines, "search_path"):
        a, b = section_bounds(lines, "DACOM")
        j = b
        while j - 1 > a and lines[j - 1].strip() == "":
            j -= 1
        _insert_block(lines, j, [r"dll_search_path = .\fluf", r"dll_search_path = .\fluf\modules"], "search_path")
        did.append("search_path")
    if not _has_block(lines, "dacom_fix"):
        a, _ = section_bounds(lines, "Libraries")
        _insert_block(lines, a + 1, ["fluf/dacom_fix.dll"], "dacom_fix")
        did.append("dacom_fix_first")
    if not _has_block(lines, "fluf_dll"):
        a, b = section_bounds(lines, "Libraries")
        idx = next((i for i in range(a + 1, b) if _is_lib_line(lines[i], "flmaterials.dll")), None)
        if idx is None:
            sys.exit("dacom.ini: flmaterials.dll not found in [Libraries]")
        _insert_block(lines, idx + 1, ["fluf/FLUF.dll"], "fluf_dll")
        did.append("fluf_after_flmaterials")
    commented = []
    a, b = section_bounds(lines, "Libraries")
    for i in range(a + 1, b):
        for name in FLUF_FORBIDDEN_DACOM:
            if _is_lib_line(lines[i], name):
                lines[i] = COMMENT_TAG_A + lines[i]
                commented.append(name)
    write_lines(p, lines, eol)
    # verify order: dacom_fix first lib, FLUF after flmaterials and before HudShift
    lines, _ = read_lines(p)
    a, b = section_bounds(lines, "Libraries")
    libs = [ln.strip().split()[0] for ln in lines[a + 1:b] if ln.strip() and not ln.strip().startswith(";")]
    order_ok = (libs[0].lower() == "fluf/dacom_fix.dll"
                and libs.index("fluf/FLUF.dll") == [x.lower() for x in libs].index("flmaterials.dll") + 1
                and libs.index("fluf/FLUF.dll") < [x.lower() for x in libs].index("hudshift.dll"))
    forbidden_left = [n for n in FLUF_FORBIDDEN_DACOM if n.lower() in [x.lower() for x in libs]]
    if not order_ok or forbidden_left:
        sys.exit(f"dacom.ini verification failed: order_ok={order_ok} forbidden_left={forbidden_left}")
    bl.record("fluf_dacom", kind="ini-marker", file=rel, actions=did, commented=commented,
              libraries_order_ok=True, status="applied" if (did or commented) else "already")
    bl.track_file(rel)


def fluf_callsign(bl: Baseline) -> None:
    rel = "EXE/freelancer.ini"
    p = bl.hde / rel
    backup_orig(bl, rel)
    lines, eol = read_lines(p)
    a, b = section_bounds(lines, "Initial SP DLLs")
    st = "already"
    found = False
    for i in range(a + 1, b):
        s = lines[i].strip()
        if re.match(r"^;carrier-mod-A;\s*DLL\s*=\s*callsign\.dll", s, re.I):
            found = True
        elif re.match(r"^DLL\s*=\s*callsign\.dll\s*,", s, re.I):
            lines[i] = COMMENT_TAG_A + lines[i]
            st, found = "applied", True
    if not found:
        bl.record("callsign_commented", kind="ini", file=rel, status="skipped", note="no callsign.dll line found")
        return
    write_lines(p, lines, eol)
    bl.record("callsign_commented", kind="ini", file=rel, status=st,
              note="commented, not deleted: a missing [Initial SP DLLs] DLL crashes vanilla without FLSharp")
    bl.track_file(rel)


def fluf_keep_running_check(bl: Baseline, src_root: Path) -> None:
    """FLUF ClientFixes::PatchScreenResolutionHandling rewrites 0x1B264C in memory at startup: keep-running bytes
    if any command-line token starts with '-w', vanilla (pausing) bytes otherwise. Our file patch would be undone."""
    f = src_root / "FLUF/Source/Client/Fixes/ScreenControl.cpp"
    evidence = None
    if f.exists():
        txt = f.read_text(errors="replace")
        if "0x1B264C" in txt and 'GetBoolSetting("-w")' in txt:
            evidence = f"{f}: SetBackGroundRunPatch(GetBoolSetting(\"-w\")) writes 0x1B264C at runtime"
    bl.record("keep_running", kind="binary", file=KEEP_RUNNING["file"], offset=hex(KEEP_RUNNING["offset"]),
              status="skipped-fluf", note="FLUF patches 0x1B264C in memory; lanes on A launch with -w",
              evidence=evidence)


def apply(args) -> None:
    prefix = check_prefix(args.prefix)
    bl = Baseline(prefix, args.track)
    tweak_flplusplus(bl)
    tweak_perfoptions(bl)
    if args.track == "B":
        binary_patch(bl, "keep_running", KEEP_RUNNING)
        binary_patch(bl, "jflp_altenter", JFLP_ALTENTER)
    else:
        fluf_keep_running_check(bl, Path("/home/user/freelancer/refs/FLUF"))
        fluf_install_files(bl, Path(args.fluf_tree))
        fluf_dacom(bl)
        fluf_callsign(bl)
    tweak_marker(bl)
    bl.data.setdefault("notes", {})
    bl.data["launch_args"] = ["-w"] if args.track == "A" else []
    bl.save()
    print(f"BASELINE.json written: {bl.json_path}")


def fluf_yml(args) -> None:
    prefix = check_prefix(args.prefix)
    bl = Baseline(prefix, "A")
    gen = Path(args.generated).read_text()
    text = set_fluf_yml(gen)
    dst = bl.hde / "EXE/fluf/FLUF.yml"
    dst.write_text(text)
    bl.record("fluf_yml", kind="yaml", file="EXE/fluf/FLUF.yml",
              keys={"logLevel": "Debug", "logSinks": ["File"], "writeSpewToLogSinks": True,
                    "clientConfig.modules": FLUF_MODULES},
              status="applied", note="edited from the FLUF.yml generated by the first launch")
    bl.track_file("EXE/fluf/FLUF.yml")
    bl.save()


def set_fluf_yml(gen: str) -> str:
    """Edit FLUF's generated YAML using PyYAML round-trip on plain data (keys are simple scalars/lists)."""
    import yaml  # from the shared venv

    data = yaml.safe_load(gen) or {}
    data["logLevel"] = "Debug"
    data["logSinks"] = ["File"]
    data["writeSpewToLogSinks"] = True
    cc = data.setdefault("clientConfig", {}) or {}
    data["clientConfig"] = cc
    cc["modules"] = list(FLUF_MODULES)
    if "setSaveDirectoryRelativeToExecutable" in data:
        data["setSaveDirectoryRelativeToExecutable"] = False
    return yaml.safe_dump(data, sort_keys=False, default_flow_style=False)


def fluf_config(args) -> None:
    """Copy FLUF's first-run generated files (EXE/fluf/config/**) from the init clone into baseline A."""
    prefix = check_prefix(args.prefix)
    bl = Baseline(prefix, "A")
    src = Path(args.src_hde) / "EXE/fluf/config"
    if not str(Path(args.src_hde).resolve()).startswith("/home/user/freelancer/prefix-dev-base-A-init/"):
        sys.exit("fluf-config: --src-hde must be the prefix-dev-base-A-init HDE dir")
    copied = []
    for f in sorted(src.rglob("*")) if src.exists() else []:
        if f.is_file():
            rel = f.relative_to(Path(args.src_hde)).as_posix()
            dst = bl.hde / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(f, dst)
            bl.track_file(rel)
            copied.append(rel)
    bl.record("fluf_first_run_config", kind="copy", files=copied, status="applied" if copied else "none",
              note="generated by FLUF on first launch (ship_classes.yml after answering OK to 'No ship classes')")
    bl.save()


def verify(args) -> int:
    prefix = check_prefix(args.prefix)
    bl = Baseline(prefix, args.track)
    if not bl.json_path.exists():
        print("FAIL no BASELINE.json")
        return 1
    fails = []
    ok = []
    for t in bl.data["tweaks"]:
        tid, st = t["id"], t["status"]
        if t["kind"] == "binary" and st in ("applied", "already"):
            p = bl.hde / t["file"]
            with open(p, "rb") as f:
                f.seek(int(t["offset"], 16))
                cur = f.read(len(bytes.fromhex(t["written"])))
            (ok if cur.hex() == t["written"].lower() else fails).append(f"{tid} bytes={cur.hex()}")
        elif tid == "flplusplus_dirs":
            lines, _ = read_lines(bl.hde / t["file"])
            txt = "\n".join(lines)
            good = all(re.search(rf"^{k} = true$", txt, re.M) for k in ("save_in_directory", "screenshots_in_directory"))
            (ok if good else fails).append(tid)
        elif tid == "perfoptions_size":
            txt = (bl.hde / t["file"]).read_bytes().decode("latin-1")
            (ok if re.search(r"^size= 1280, 720\r?$", txt, re.M) else fails).append(tid)
        elif tid == "devbridge_marker":
            (ok if (bl.hde / t["file"]).exists() else fails).append(tid)
        elif tid == "fluf_dacom":
            lines, _ = read_lines(bl.hde / t["file"])
            a, b = section_bounds(lines, "Libraries")
            libs = [ln.strip().split()[0].lower() for ln in lines[a + 1:b] if ln.strip() and not ln.strip().startswith(";")]
            good = (libs[0] == "fluf/dacom_fix.dll" and libs.index("fluf/fluf.dll") == libs.index("flmaterials.dll") + 1
                    and not [n for n in FLUF_FORBIDDEN_DACOM if n.lower() in libs])
            (ok if good else fails).append(tid)
        elif tid == "callsign_commented" and st != "skipped":
            lines, _ = read_lines(bl.hde / t["file"])
            a, b = section_bounds(lines, "Initial SP DLLs")
            live = [ln for ln in lines[a + 1:b] if re.match(r"^\s*DLL\s*=\s*callsign\.dll", ln, re.I)]
            (fails if live else ok).append(tid)
        elif tid == "fluf_yml":
            import yaml
            d = yaml.safe_load((bl.hde / t["file"]).read_text())
            good = (d.get("logLevel") == "Debug" and d.get("logSinks") == ["File"] and d.get("writeSpewToLogSinks") is True
                    and sorted(d.get("clientConfig", {}).get("modules", [])) == sorted(FLUF_MODULES))
            (ok if good else fails).append(tid)
        else:
            ok.append(f"{tid} ({st})")
    for rel, h in bl.data.get("files", {}).items():
        cur = sha256(bl.hde / rel)
        (ok if cur == h else fails).append(f"sha256 {rel}")
    if args.track == "A" and not any(t["id"] == "fluf_yml" for t in bl.data["tweaks"]):
        fails.append("fluf_yml missing (first-launch step not done)")
    pp = bl.data.get("play_prefix_sha256", {})
    for rel, h in pp.items():
        cur = sha256(PLAY_PREFIX / HDE_REL / rel)
        (ok if cur == h else fails).append(f"play-prefix-unchanged {rel}")
    for x in ok:
        print(f"OK   {x}")
    for x in fails:
        print(f"FAIL {x}")
    print(f"baseline verify {args.track}: {'PASS' if not fails else 'FAIL'} ({len(ok)} ok, {len(fails)} fail)")
    return 0 if not fails else 1


def note(args) -> None:
    prefix = check_prefix(args.prefix)
    bl = Baseline(prefix, json.loads(prefix.joinpath("BASELINE.json").read_text())["track"])
    bl.data.setdefault("notes", {})[args.key] = json.loads(args.value)
    bl.save()


def play_hashes(args) -> None:
    prefix = check_prefix(args.prefix)
    bl = Baseline(prefix, args.track)
    bl.data["play_prefix_sha256"] = {rel: sha256(PLAY_PREFIX / HDE_REL / rel)
                                     for rel in ("EXE/Freelancer.exe", "EXE/dacom.ini", "EXE/flplusplus.ini",
                                                 "EXE/freelancer.ini", "EXE/jflp.dll", "SAVE/PerfOptions.ini")}
    bl.data["source_prefix"] = str(PLAY_PREFIX)
    bl.save()


def main() -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("apply"); a.add_argument("--track", choices="AB", required=True); a.add_argument("--prefix", required=True)
    a.add_argument("--fluf-tree", default="/home/user/freelancer/refs/FLUF-release-nightly-2026-10-16/extracted")
    v = sub.add_parser("verify"); v.add_argument("--track", choices="AB", required=True); v.add_argument("--prefix", required=True)
    y = sub.add_parser("fluf-yml"); y.add_argument("--prefix", required=True); y.add_argument("--generated", required=True)
    n = sub.add_parser("note"); n.add_argument("--prefix", required=True); n.add_argument("--key", required=True); n.add_argument("--value", required=True)
    fc = sub.add_parser("fluf-config"); fc.add_argument("--prefix", required=True); fc.add_argument("--src-hde", required=True)
    h = sub.add_parser("play-hashes"); h.add_argument("--track", choices="AB", required=True); h.add_argument("--prefix", required=True)
    args = ap.parse_args()
    if args.cmd == "apply":
        apply(args)
    elif args.cmd == "verify":
        return verify(args)
    elif args.cmd == "fluf-yml":
        fluf_yml(args)
    elif args.cmd == "note":
        note(args)
    elif args.cmd == "fluf-config":
        fluf_config(args)
    elif args.cmd == "play-hashes":
        play_hashes(args)
    return 0


if __name__ == "__main__":
    sys.exit(main())
