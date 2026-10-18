#!/usr/bin/env python3
"""Run verdict (REQ-P0-HARNESS-13, TESTING §CrashTriage).

  verdict.py <rundir> [--allow <spew_allow file>] [--track A|B] [--spew-check strict|report]
             [--hang-s N] [--offsets <crash-offsets.json>] [--no-write]

Writes <rundir>/verdict.json, prints one `verdict=... key=value` summary line and exits 0 iff PASS
(FAIL 1, CRASH 2, HANG 3, NO_WINDOW 4, EXITED_EARLY 5, TIMEOUT 6, usage/IO error 64+).
Precedence: CRASH > HANG > NO_WINDOW > EXITED_EARLY > TIMEOUT > FAIL > PASS. The runner may also write
`"verdict": "ERROR"` itself when its environment check refuses to launch (X not answering, Vulkan device creation
failing for --renderer dxvk, a banned display mode): no game ran, run.sh exits 2, and this tool is not called.

First-chance exceptions are normal (a healthy run has dozens of handled c0000005, and clean quits end with a handled
access violation near the end of wine.log, harness/NOTES.md N18): a wine.log exception
counts as a crash only through wine's definite crash text, or as a trailing exception of a process that exited
before quit (early_exit). After quit the game's own exit code decides: nonzero -> CRASH (x11 lanes, where the
launcher is the game; not when the harness killed it). A quit that is answered but never exits -> HANG.
The spew check fails closed: without an allow-list file for the track and renderer, only the built-in benign
patterns are allowed (`--spew-check report` is the explicit opt-out).
"""
from __future__ import annotations

import argparse
import json
import os
import sys

HERE = os.path.dirname(os.path.realpath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "lib"))

import triage  # noqa: E402
import spew_allow  # noqa: E402

PRECEDENCE = ("CRASH", "HANG", "NO_WINDOW", "EXITED_EARLY", "TIMEOUT", "FAIL", "PASS")
EXIT_CODES = {"PASS": 0, "FAIL": 1, "CRASH": 2, "HANG": 3, "NO_WINDOW": 4, "EXITED_EARLY": 5, "TIMEOUT": 6}
DEFAULT_HANG_S = 60.0
MAX_NEW_SPEW = 200  # verdict.json keeps at most this many new spew lines (the count is in reasons)


def _b(v) -> bool:
    if isinstance(v, bool):
        return v
    if isinstance(v, (int, float)):
        return v != 0
    if isinstance(v, str):
        return v.strip().lower() in ("1", "true", "yes", "on")
    return False


def _i(v):
    if v is None or isinstance(v, bool):
        return None
    try:
        return int(str(v).strip(), 0) if isinstance(v, str) else int(v)
    except (TypeError, ValueError):
        return None


def load_run(rundir):
    try:
        with open(os.path.join(rundir, "run.json"), "r", encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else None
    except (OSError, ValueError):
        return None


def liveness_hang(path, hang_s):
    """Longest stall >= hang_s in liveness.tsv (the runner's rule, applied offline). A stall is: the game alive and
    no progress, where progress = FLSpew or devbridge log growth, plus wine.log growth in the start-up phase.
    It counts when something is pending (command, wait) or, for a heartbeat-capable devbridge (hb=1), always.

    Returns {"start_ms", "end_ms", "idle_s", "why"} or None. Rows that do not parse are skipped. Older files without
    the phase/wine_bytes/hb columns use the pending rule only.
    """
    if not os.path.isfile(path):
        return None
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        rows = [l.rstrip("\r\n").split("\t") for l in f if l.strip()]
    if not rows:
        return None
    hdr = [h.strip() for h in rows[0]]
    need = ("ms", "alive", "spew_bytes", "devbridge_bytes", "pending")
    if not all(k in hdr for k in need):
        return None
    ix = {k: hdr.index(k) for k in need}
    opt = {k: hdr.index(k) for k in ("phase", "wine_bytes", "hb") if k in hdr}
    best = None
    start = ref = None
    why = ""
    for r in rows[1:]:
        try:
            ms, alive, sb, db, pend = (int(float(r[ix[k]])) for k in need)
            phase = r[opt["phase"]].strip() if "phase" in opt else ""
            wb = int(r[opt["wine_bytes"]]) if "wine_bytes" in opt else 0
            hb = int(r[opt["hb"]]) if "hb" in opt else 0
        except (ValueError, IndexError):
            continue
        watch = alive and (pend or hb)
        if not watch:
            start = ref = None
            continue
        key = (sb, db, wb if phase == "startup" else None)
        if start is None or key != ref:
            start, ref = ms, key
            why = "start-up wait" if phase == "startup" else ("command pending" if pend else "heartbeat silent")
            continue
        idle = (ms - start) / 1000.0
        if idle >= hang_s and (best is None or idle > best["idle_s"]):
            best = {"start_ms": start, "end_ms": ms, "idle_s": idle, "why": why}
    return best


REQUIRED_RUN_KEYS = ("ready", "window_id", "cmds", "end_ms")


def _resolve_allow(allow, run, track, reasons):
    """Path of the spew allow file (--allow > run.json spew_allow > baseline/spew_allow_<track>.txt) or None."""
    if allow:
        if os.path.isfile(allow):
            return allow
        reasons.append("info: allow file %s not found; strict check against the built-in patterns only" % allow)
        return None
    rec = run.get("spew_allow") if run else None
    if isinstance(rec, str) and rec and os.path.isfile(rec):
        return rec
    if track in ("A", "B"):
        p = os.path.join(HERE, "baseline", "spew_allow_%s.txt" % track)
        if os.path.isfile(p):
            return p
    return None


def compute_verdict(rundir, allow=None, track=None, spew_check=None, hang_s=None, offsets=None, meta=None) -> dict:
    """verdict.json dict (exact schema keys). `meta`, if a dict, receives spew_mode/allow/hang_s."""
    rundir = os.path.abspath(rundir)
    if hang_s is None:
        try:
            hang_s = float(os.environ.get("HANG_S") or DEFAULT_HANG_S)
        except ValueError:
            hang_s = DEFAULT_HANG_S
    run = load_run(rundir)
    r = run or {}
    track = track or (r.get("track") if r.get("track") in ("A", "B") else None)
    sigs = []      # every detected signature
    cats = {k: [] for k in PRECEDENCE}  # verdict category -> human reasons
    info = []

    def sig(cat, kind, detail):
        sigs.append({"kind": kind, "detail": detail})
        cats[cat].append("%s: %s" % (kind, detail))

    if run is None:
        sig("FAIL", "no_run_json", "run.json missing or unreadable")
    else:
        # a runner that died early leaves a partial run.json: never a PASS (review r1 m5)
        missing = [k for k in REQUIRED_RUN_KEYS if k not in r]
        if missing:
            sig("FAIL", "incomplete_run_json", "run.json lacks %s" % ", ".join(missing))
        elif not _b(r.get("ready")):
            sig("FAIL", "not_ready", "the game never reached the main menu (ready=false)")
        if r.get("lane_lost"):
            sig("FAIL", "lane_lost", "the lane's lock holder died during the run: %s" % r.get("lane_lost"))

    # ---- crash
    scan = triage.scan_wine_log(os.path.join(rundir, "wine.log"))
    extra = triage.scan_crash_lines(os.path.join(rundir, "crash_lines.txt"))
    if not scan["exists"]:
        info.append("info: wine.log missing")
    hang0 = r.get("hang") if isinstance(r.get("hang"), dict) else {}
    cut = _i(hang0.get("wine_log_lines")) if _b(hang0.get("detected")) else None
    definite = scan["definite"] + extra
    if cut is not None:
        # after a detected hang the harness dumps and kills the game: crash texts past that point are its doing
        late = [d for d in scan["definite"] if d.get("line", 0) > cut]
        definite = [d for d in scan["definite"] if d.get("line", 0) <= cut]
        for d in late[:3]:
            info.append("info: crash text after the hang was detected (wine.log line %s > %d; attributed to the "
                        "hang dump/kill): %s" % (d.get("line"), cut, d["text"]))
    for d in definite[:3]:
        sig("CRASH", "wine_crash_text", d["text"])
    if _b(r.get("dw15_seen")):
        sig("CRASH", "dw15", "dw15.exe (Freelancer's Watson) process seen")
    # the lane window must have reached its slot: elsewhere it overlaps other lanes or the user's desktop
    wp = r.get("window_placed")
    if isinstance(wp, dict) and wp.get("ok") is False:
        sig("FAIL", "window_not_at_slot", "window never reached slot %s after %s tries: %s" % (
            wp.get("slot"), wp.get("tries"), wp.get("geometry")))
    # every dacom library deploy.sh listed (harness.dacom unit, D107) must really have loaded
    if _b(r.get("ready")) and scan["exists"]:
        loaded = {l[2].lower() for l in scan["loads"] if l[1] == "load"}
        for lib in r.get("dacom_libraries") or []:
            if str(lib).replace("\\", "/").split("/")[-1].lower() not in loaded:
                sig("FAIL", "dll_not_loaded", "%s is listed in dacom.ini [Libraries] but never loaded "
                    "(wine.log +loaddll)" % lib)
    dw15 = [l for l in scan["loads"] if l[1] == "load" and l[2].lower() == "dw15.exe"]
    if dw15:
        sig("CRASH", "dw15_loaded", "dw15.exe loaded at wine.log line %d (Freelancer's Watson)" % dw15[0][0])
    for w in r.get("crash_windows") or []:
        title = w.get("title") if isinstance(w, dict) else str(w)
        sig("CRASH", "crash_window", "window %r" % title)
    for d in r.get("new_dumps") or []:
        sig("CRASH", "new_dump", str(d))
    early = _b(r.get("early_exit"))
    exit_code = _i(r.get("exit_code"))
    if early:
        if exit_code is None:
            sig("CRASH", "early_exit", "process exited before the run finished (exit code unknown)")
        elif exit_code != 0:
            sig("CRASH", "early_exit", "process exited before the run finished (exit_code=%d)" % exit_code)
        last = triage.last_system_exception(scan)
        if triage.is_trailing(scan, last):
            sig("CRASH", "trailing_exception", "code=%08x addr=%s at wine.log line %d of %d, then early exit" % (
                last["code"], "0x%x" % last["addr"] if last["addr"] is not None else "?", last["line"], scan["lines"]))
        if exit_code == 0 and not cats["CRASH"]:
            sig("EXITED_EARLY", "early_exit_clean", "process exited with code 0 before quit")
    # the game exited by itself after quit (or a window close): its exit code decides (review r1 M1)
    by_itself = _b(r.get("exited_after_quit")) or (_b(r.get("gentle_close")) and not _b(r.get("quit_sent")))
    if not early and by_itself and r.get("exit_code_is_game", True) is not False \
            and not _b(r.get("killed_by_harness")) and exit_code not in (None, 0):
        last = triage.last_system_exception(scan)
        tail = ""
        if triage.is_trailing(scan, last):
            tail = "; trailing code=%08x addr=%s at wine.log line %d" % (
                last["code"], "0x%x" % last["addr"] if last["addr"] is not None else "?", last["line"])
        sig("CRASH", "exit_code", "game exited with code %d (0x%x) after %s%s" % (
            exit_code, exit_code & 0xFFFFFFFF, "quit" if _b(r.get("quit_sent")) else "a window close", tail))
    if not early and _b(r.get("quit_sent")) and not _b(r.get("exited_after_quit")) \
            and not _b((r.get("hang") or {}).get("detected") if isinstance(r.get("hang"), dict) else False):
        sig("HANG", "quit_no_exit", "quit %s but the game did not exit within 30 s (the harness killed it)" % (
            "acked" if _b(r.get("quit_acked")) else "sent (no ack)"))

    # ---- hang
    hang = r.get("hang") if isinstance(r.get("hang"), dict) else {}
    if _b(hang.get("detected")):
        sig("HANG", "hang", "harness detected a hang at_ms=%s idle_s=%s minidump=%s" % (
            hang.get("at_ms"), hang.get("idle_s"), hang.get("minidump")))
    lh = liveness_hang(os.path.join(rundir, "liveness.tsv"), hang_s)
    if lh:
        sig("HANG", "hang_liveness", "alive, %s, no progress for %.0fs (ms %d..%d)" % (
            lh["why"], lh["idle_s"], lh["start_ms"], lh["end_ms"]))

    # ---- window / timeout
    if run is not None and "window_id" in r and r.get("window_id") in (None, "") and not early:
        sig("NO_WINDOW", "no_window", "no game window found (method=%s)" % r.get("window_method"))
    if _b(r.get("timeout")):
        sig("TIMEOUT", "timeout", "ready=%s ready_marker=%r; ready or expectations not reached in time" % (
            _b(r.get("ready")), r.get("ready_marker")))

    # ---- cmds / expects
    cmds = [c for c in (r.get("cmds") or []) if isinstance(c, dict)]
    n_ack = n_fail = 0
    for c in cmds:
        ack = _b(c.get("ack"))
        ok = _i(c.get("ok"))
        n_ack += ack
        if not _b(c.get("expect_fail")) and (not ack or ok == 0):
            n_fail += 1
            sig("FAIL", "cmd_failed", "%r id=%s ack=%s ok=%s err=%s" % (
                c.get("line"), c.get("id"), int(ack), ok, c.get("err")))
    if r.get("runner_error"):           # the runner gave up on a step (e.g. a refused input): never a PASS
        sig("FAIL", "runner_error", str(r.get("runner_error")))
    for s in (r.get("steps") or []):   # runner-side @steps of a --cmds file (key, console, wait_state, ...)
        if isinstance(s, dict) and not _b(s.get("ok")):
            sig("FAIL", "step_failed", "@%s info=%s" % (s.get("step"), s.get("info")))
    exps = [e for e in (r.get("expects") or []) if isinstance(e, dict)]
    n_match = 0
    for e in exps:
        if _b(e.get("matched")):
            n_match += 1
        else:
            sig("FAIL", "expect_unmatched", "regex %r never matched" % e.get("regex"))

    # ---- spew
    allow_path = _resolve_allow(allow, run, track, info)
    mode = spew_check or "strict"   # fail closed (review r1 m4); `--spew-check report` is the explicit opt-out
    bad = []
    pats = spew_allow.load_allow(allow_path, bad)
    info += ["info: %s" % b for b in bad]
    spew_path = os.path.join(rundir, "FLSpew.txt")
    if not os.path.isfile(spew_path):
        info.append("info: FLSpew.txt missing")
    new_spew = spew_allow.new_errors(spew_path, pats)
    if new_spew:
        if mode == "strict":
            sig("FAIL", "new_spew_errors", "%d ERROR/WARNING line(s) not in %s; first: %s" % (
                len(new_spew), allow_path or "(no allow file)", new_spew[0]))
        else:
            info.append("info: %d new spew ERROR/WARNING line(s) (report mode, allow=%s)" % (
                len(new_spew), allow_path))

    # ---- fault
    verdict = next(k for k in PRECEDENCE if k == "PASS" or cats[k])
    fault = {"module": None, "rva": None, "addr": None, "offset_lookup": []}
    if verdict == "CRASH":
        table = triage.load_offsets(offsets)
        if not table:
            info.append("info: crash-offsets table not found")
        f = triage.find_fault(scan, extra, table)
        fault = {k: f[k] for k in ("module", "rva", "addr", "offset_lookup")}
        if f["addr"]:
            exact = [h for h in f["offset_lookup"] if h.get("match") == "exact"]
            info.insert(0, "fault: %s+%s addr=%s (%s)%s" % (
                f["module"] or "?", f["rva"] or "?", f["addr"], f["source"],
                "; known: " + exact[0].get("description", "?") if exact else ""))

    clean_quit = _b(r.get("quit_sent")) and _b(r.get("exited_after_quit"))
    if _b(r.get("quit_sent")) and not _b(r.get("exited_after_quit")) and not early:
        info.append("info: quit sent but the process did not exit by itself")
    reasons = []
    for k in PRECEDENCE:
        reasons += cats[k]
    reasons += info
    if isinstance(meta, dict):
        meta.update(spew_mode=mode, allow=allow_path, hang_s=hang_s, track=track)
    return {
        "verdict": verdict,
        "reasons": reasons,
        "signatures": sigs,
        "fault": fault,
        "new_spew_errors": new_spew[:MAX_NEW_SPEW],
        "first_chance_exceptions": triage.first_chance_count(scan),
        "cmds": {"sent": len(cmds), "acked": n_ack, "failed": n_fail},
        "expects": {"total": len(exps), "matched": n_match},
        "ready": _b(r.get("ready")),
        "clean_quit": clean_quit,
        "run": rundir,
    }


def summary_line(v, meta=None) -> str:
    f = v["fault"]
    fault = "%s+%s" % (f["module"], f["rva"]) if f["module"] else (f["addr"] or "-")
    first = v["reasons"][0] if v["reasons"] else ""
    return ('verdict=%s fault=%s cmds=%d/%d/%d expects=%d/%d new_spew=%d spew_check=%s first_chance=%d '
            'ready=%d clean_quit=%d reason="%s" run=%s') % (
        v["verdict"], fault, v["cmds"]["sent"], v["cmds"]["acked"], v["cmds"]["failed"],
        v["expects"]["matched"], v["expects"]["total"], len(v["new_spew_errors"]), (meta or {}).get("spew_mode", "?"),
        v["first_chance_exceptions"], v["ready"], v["clean_quit"], first.replace('"', "'")[:160], v["run"])


def write_verdict(v) -> str:
    path = os.path.join(v["run"], "verdict.json")
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(v, fh, indent=2)
        fh.write("\n")
    os.replace(tmp, path)
    return path


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="verdict.py", description="Compute a harness run verdict")
    ap.add_argument("rundir")
    ap.add_argument("--allow", help="spew allow-list (default: harness/baseline/spew_allow_<track>.txt)")
    ap.add_argument("--track", choices=("A", "B"))
    ap.add_argument("--spew-check", choices=("strict", "report"))
    ap.add_argument("--hang-s", type=float, default=None, help="offline hang threshold (default $HANG_S or 60)")
    ap.add_argument("--offsets", help="crash-offsets.json (default: refs copy)")
    ap.add_argument("--no-write", action="store_true", help="do not write verdict.json")
    a = ap.parse_args(argv)
    if not os.path.isdir(a.rundir):
        print("verdict: no such run dir: %s" % a.rundir, file=sys.stderr)
        return 66
    meta = {}
    v = compute_verdict(a.rundir, a.allow, a.track, a.spew_check, a.hang_s, a.offsets, meta)
    if not a.no_write:
        try:
            write_verdict(v)
        except OSError as e:
            print("verdict: cannot write verdict.json: %s" % e, file=sys.stderr)
            return 70
    print(summary_line(v, meta))
    return EXIT_CODES[v["verdict"]]


if __name__ == "__main__":
    sys.exit(main())
