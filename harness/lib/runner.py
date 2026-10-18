#!/usr/bin/env python3
"""Game run driver behind harness/run.sh (REQ-P0-HARNESS-11). See run.sh for the CLI.

Launches Freelancer.exe on a held lane (through the wine guard), finds and places its window, waits for readiness,
loads a save, feeds devbridge commands, checks expectations, collects evidence, quits and tears the lane's wineserver
down. Writes <rundir>/run.json + liveness.tsv and calls harness/verdict.py. Never touches anything outside the lane.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import time
from pathlib import Path

LIB = Path(__file__).resolve().parent
HARNESS = LIB.parent
sys.path.insert(0, str(HARNESS))
sys.path.insert(0, str(LIB))

FLMOD_LOCKS = Path(os.environ.get("FLMOD_LOCKS", "/home/user/freelancer/carrier-mod/local/locks"))
FLMOD_TESTRUNS = Path(os.environ.get("FLMOD_TESTRUNS", "/home/user/freelancer/carrier-mod/local/testruns"))
SPEW_REL = "drive_c/users/steamuser/AppData/Local/Freelancer/FLSpew.txt"
MYGAMES_REL = "drive_c/users/steamuser/Documents/My Games/Freelancer"
MENU_SPEW = "Starting single player game"
CRASH_TITLES = r"Fatal Crash|Freelancer has encountered|has encountered a problem|Unhandled exception"
CRASH_TEXT = re.compile(r"Unhandled exception|starting debugger|wine: Unhandled|page fault on")


def now_ms() -> int:
    return int(time.time() * 1000)


def read_config() -> dict:
    cfg = {}
    for line in (HARNESS / "config.sh").read_text().splitlines():
        m = re.match(r'^([A-Z_][A-Z0-9_]*)=(.*)$', line.strip())
        if not m:
            continue
        k, v = m.group(1), m.group(2)
        if not v.startswith(('"', "'")):
            v = re.sub(r"\s+#.*$", "", v)   # trailing shell comment
        m2 = re.match(r'^\$\{' + k + r':-(.*)\}$', v)
        if m2:
            v = os.environ.get(k, m2.group(1))
        v = v.strip('"').strip("'")
        cfg[k] = v
    return cfg


CFG = read_config()


def load_lane(n: int) -> dict:
    envf = FLMOD_LOCKS / f"lane-{n}.env"
    owner = FLMOD_LOCKS / f"lane-{n}.owner"
    if not envf.exists() or not owner.exists():
        sys.exit(f"run: lane {n} is not held (harness/lane.sh acquire --lane {n})")
    env = {}
    for line in envf.read_text().splitlines():
        m = re.match(r"^export ([A-Z_]+)=(.*)$", line)
        if m:
            env[m.group(1)] = shlex.split(m.group(2))[0] if m.group(2) else ""
    own = dict(l.split("=", 1) for l in owner.read_text().splitlines() if "=" in l)
    hp = own.get("holder_pid", "")
    if not hp or not Path(f"/proc/{hp}").exists():
        sys.exit(f"run: lane {n} lock holder {hp} is dead; re-acquire the lane")
    env["_owner"] = own
    return env


def prefix_pids(prefix: str) -> list[int]:
    key = f"WINEPREFIX={os.path.realpath(prefix)}".encode()
    out = []
    for d in os.listdir("/proc"):
        if not d.isdigit():
            continue
        try:
            with open(f"/proc/{d}/environ", "rb") as f:
                if key in f.read().split(b"\0"):
                    out.append(int(d))
        except OSError:
            pass
    return out


def comm(pid: int) -> str:
    try:
        return Path(f"/proc/{pid}/comm").read_text().strip()
    except OSError:
        return ""


def cmdline(pid: int) -> str:
    try:
        return Path(f"/proc/{pid}/cmdline").read_bytes().replace(b"\0", b" ").decode(errors="replace")
    except OSError:
        return ""


def xdo(*args: str, timeout: float = 10, display: str | None = None) -> str:
    env = dict(os.environ, DISPLAY=display) if display else None
    try:
        r = subprocess.run(["xdotool", *args], capture_output=True, text=True, timeout=timeout, env=env)
        return r.stdout.strip()
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return ""


CLK_TCK = os.sysconf("SC_CLK_TCK") if hasattr(os, "sysconf") else 100

def cpu_ticks(pid: int | None) -> int:
    """utime + stime of a process in clock ticks (all threads), 0 if unknown."""
    if not pid:
        return 0
    try:
        f = Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()
        return int(f[11]) + int(f[12])   # fields 14 and 15 of stat (after pid and comm)
    except (OSError, IndexError, ValueError):
        return 0


def proc_start(pid: int) -> str:
    """Start time of a process (field 22 of /proc/<pid>/stat, clock ticks since boot); '' if unknown."""
    try:
        return Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()[19]
    except (OSError, IndexError):
        return ""


def command_budget(line: str) -> tuple[str, float | None]:
    """Runner-side budget of one --cmds line (D111). `[timeout_s=N] <cmd>` sets it explicitly (the prefix is not
    sent); `perf <s>` gets s + 30 (the verb's own budget). Returns (line to send, budget or None)."""
    m = re.match(r"^\[timeout_s=([0-9.]+)\]\s*(.*)$", line)
    if m:
        return m.group(2), float(m.group(1))
    m = re.match(r"^perf\s+([0-9.]+)\b", line)
    if m:
        return line, float(m.group(1)) + 30.0
    return line, None


def fsize(p: Path) -> int:
    try:
        return p.stat().st_size
    except OSError:
        return 0


class Run:
    def __init__(self, a):
        self.a = a
        self.lane = load_lane(a.lane)
        self.n = a.lane
        self.prefix = self.lane["WINEPREFIX"]
        self.hde = Path(self.lane["HDE"])
        self.track = self.lane.get("LANE_TRACK", "B")
        self.spew = Path(self.prefix) / SPEW_REL
        self.dbdir = Path(self.lane["FL_DEVBRIDGE_DIR"])
        self.dblog = self.dbdir / "log.txt"
        stamp = time.strftime("%Y%m%d-%H%M%S", time.gmtime())
        self.dir = FLMOD_TESTRUNS / f"{stamp}-lane{self.n}-{a.name}"
        self.dir.mkdir(parents=True, exist_ok=False)
        (self.dir / "shots").mkdir()
        self.r = {
            "name": a.name, "lane": self.n, "track": self.track, "prefix": self.prefix, "hde": str(self.hde),
            "args": [], "start_ms": None, "end_ms": None, "game_pid": None, "window_id": None,
            "window_method": CFG.get("WINDOW_METHOD", "pid"), "ready": False, "ready_marker": None, "ready_ms": None,
            "loaded": None, "loaded_marker": None, "load_method": None, "quit_sent": False, "quit_ms": None,
            "exited_after_quit": False, "process_exit_ms": None, "exit_code": None, "early_exit": False,
            "timeout": False, "hang": {"detected": False, "at_ms": None, "idle_s": None, "minidump": None},
            "cmds": [], "expects": [], "crash_windows": [], "dw15_seen": False, "new_dumps": [], "spew_allow": None,
            "devbridge": False, "shots": [], "notes": [], "lane_owner": self.lane["_owner"].get("owner"),
        }
        self.launcher = None
        self.gpid = None
        self.seen_game = False
        self.wid = None
        self.pending = False
        self.waiting = False
        self.last_growth = time.time()
        self.last_sizes = (0, 0)
        self.last_wine = 0
        self.last_wine_growth = time.time()
        self.hb = False            # the devbridge emits ev=hb heartbeats (selftest DLL, W1-CORE)
        self._hb_checked = 0.0
        self._holder_checked = 0.0
        self.lane_lost = False
        self.liv = open(self.dir / "liveness.tsv", "w")
        # cpu_ticks is diagnostic only; progress = log growth (spew/devbridge; wine.log too during start-up)
        self.liv.write("ms\talive\tspew_bytes\tdevbridge_bytes\tpending\tcpu_ticks\tphase\twine_bytes\thb\n")
        self.last_tick = 0.0
        self.windows_log = open(self.dir / "windows.txt", "w")
        self.db = None
        self.quitting = False
        # Lanes run on X :0 only. gamescope (nested/headless) was evaluated and is banned on this host (D103: its
        # Xwayland triggered the 05:28Z GPU fault, NOTES.md N8); environment_error() refuses any other mode.
        self.display = self.lane.get("LANE_DISPLAY") or ("headless" if self.lane.get("LANE_HEADLESS") == "1" else "x11")
        self.r["display"] = self.display
        # x11: the launcher is `wine Freelancer.exe`, so its exit code is the game's; vdesk: it is explorer's
        self.r["exit_code_is_game"] = self.display != "vdesk"
        self.r["killed_by_harness"] = False

    # ------------------------------------------------------------------ monitoring
    def log(self, msg: str) -> None:
        line = f"[run] {time.strftime('%H:%M:%S')} {msg}"
        print(line, file=sys.stderr, flush=True)
        with open(self.dir / "runner.log", "a") as f:
            f.write(line + "\n")

    def alive(self) -> bool:
        return self.gpid is not None and Path(f"/proc/{self.gpid}").exists() and comm(self.gpid) == "Freelancer.exe"

    def tick(self, force: bool = False) -> None:
        t = time.time()
        if not force and t - self.last_tick < 0.9:
            return
        self.last_tick = t
        pids = prefix_pids(self.prefix)
        if self.gpid is None or not self.alive():
            g = next((p for p in pids if comm(p) == "Freelancer.exe"), None)
            if g is not None:
                if self.gpid is None:
                    self.log(f"game pid {g}")
                self.gpid = g
                self.r["game_pid"] = g
                self.gpid_start = proc_start(g)
                self.seen_game = True
        for p in pids:
            if "dw15" in comm(p).lower() or "dw15.exe" in cmdline(p).lower():
                if not self.r["dw15_seen"]:
                    self.log(f"dw15.exe seen (pid {p}) -> crash")
                self.r["dw15_seen"] = True
        if self.seen_game and not self.alive() and not self.quitting and not self.r["early_exit"]:
            self.r["early_exit"] = True
            self.r["process_exit_ms"] = now_ms()
            self.log("game process exited before quit")
        if self.seen_game and not self.alive() and self.r["process_exit_ms"] is None:
            self.r["process_exit_ms"] = now_ms()
        # crash windows belonging to this lane
        found = xdo("search", "--name", CRASH_TITLES)
        for w in found.split():
            pid = xdo("getwindowpid", w)
            if pid.isdigit() and int(pid) in pids:
                title = xdo("getwindowname", w)
                if not any(c["wid"] == w for c in self.r["crash_windows"]):
                    self.r["crash_windows"].append({"wid": w, "title": title, "pid": int(pid)})
                    self.log(f"crash window {w} '{title}'")
        if self.wid is not None and self.alive() and t - getattr(self, "_last_wcheck", 0) >= 2:
            self._last_wcheck = t
            if not self.window_valid():
                self.log(f"window {self.wid} gone, not viewable or not ours any more; searching again")
                self.windows_log.write(f"{now_ms()} invalid wid={self.wid}\n")
                self.find_window()
            elif not (self.r.get("window_placed") or {}).get("ok") and getattr(self, "_place_tries", 0) < 5:
                self.place()
        if self.wid is None and self.alive():
            self.find_window()
        sizes = (fsize(self.spew), fsize(self.dblog))
        wbytes = fsize(self.dir / "wine.log")
        cpu = cpu_ticks(self.gpid) if self.alive() else 0
        if sizes != self.last_sizes:
            self.last_sizes = sizes
            self.last_growth = t
        if wbytes != self.last_wine:
            self.last_wine = wbytes
            self.last_wine_growth = t
        if t - getattr(self, "_last_xprobe", 0) >= 10:
            self._last_xprobe = t
            self.x_alive()
        if not self.hb and t - self._hb_checked >= 5:
            self._hb_checked = t
            try:
                self.hb = "ev=hb" in self.dblog.read_text(errors="replace")
            except OSError:
                pass
            if self.hb:
                self.r["heartbeat"] = True
        if t - self._holder_checked >= 5:
            self._holder_checked = t
            self.check_holder()
        busy = self.pending or self.waiting
        phase = "run" if self.r["ready"] else "startup"
        self.liv.write(f"{now_ms()}\t{int(self.alive())}\t{sizes[0]}\t{sizes[1]}\t{int(busy)}\t{cpu}\t{phase}"
                       f"\t{wbytes}\t{int(self.hb)}\n")
        self.liv.flush()
        if not self.alive() or self.r["hang"]["detected"] or self.quitting:
            return
        hang_s = float(self.a.hang_s)
        idle = t - self.last_growth
        if idle < hang_s:
            return
        if phase == "startup":
            # start-up: module loads and exceptions in wine.log also count as progress (NOTES.md N14, review r1 m3)
            prog_idle = t - max(self.last_growth, self.last_wine_growth)
            if busy and prog_idle >= hang_s:
                self.on_hang(prog_idle, kind="startup_stall")
        elif busy:
            self.on_hang(idle)                       # a command or wait pending, nothing written (D111 keep-alives count)
        elif self.hb:
            self.on_hang(idle, kind="no_heartbeat")  # idle, but a heartbeat-capable devbridge went silent

    def check_holder(self) -> None:
        """The lane's lock holder must outlive the run (review r1 m9): if its lease expired or it was killed, another
        acquirer may recreate this prefix under the running game. Abort the run."""
        own = self.lane["_owner"]
        hp, start = own.get("holder_pid", ""), own.get("holder_start", "")
        alive = bool(hp) and Path(f"/proc/{hp}").exists() and comm(int(hp)) == "sleep"
        if alive and start:
            alive = proc_start(int(hp)) == start
        if not alive and not self.lane_lost:
            self.lane_lost = True
            self.r["lane_lost"] = {"ms": now_ms(), "holder_pid": hp}
            self.log(f"LANE LOST: lock holder {hp} is gone (lease expired or killed); aborting the run")

    @staticmethod
    def pid_windows(pids: set[int], name_re: str) -> list[str]:
        """Visible windows titled name_re whose _NET_WM_PID is in pids, checked window by window. Never trust
        `xdotool search --pid P --name N`: it ORs the two (every lane's "Freelancer" window comes back), which once
        made concurrent runners share one window id (NOTES.md N13)."""
        out = []
        for w in xdo("search", "--onlyvisible", "--name", name_re).split():
            p = xdo("getwindowpid", w)
            if p.isdigit() and int(p) in pids:
                out.append(w)
        return out

    @staticmethod
    def area(wid: str) -> int:
        g = dict(kv.split("=", 1) for kv in xdo("getwindowgeometry", "--shell", wid).split() if "=" in kv)
        try:
            return int(g.get("WIDTH", 0)) * int(g.get("HEIGHT", 0))
        except ValueError:
            return 0

    def window_valid(self) -> bool:
        """The tracked window still exists, is viewable and still belongs to this lane."""
        if self.wid is None:
            return False
        if self.display == "vdesk":
            return self.wid in self.pid_windows(set(prefix_pids(self.prefix)), f"^lane{self.n} - Wine Desktop$")
        return self.wid in self.pid_windows({self.gpid}, "^Freelancer$")   # --onlyvisible = viewable

    def find_window(self) -> None:
        if self.gpid is None:
            return
        if self.display == "vdesk":
            method = "vdesk-title"   # "lane<N> - Wine Desktop", owned by the lane's explorer.exe
            ws = self.pid_windows(set(prefix_pids(self.prefix)), f"^lane{self.n} - Wine Desktop$")
            self.game_wid = (self.pid_windows({self.gpid}, "^Freelancer$") or [None])[0]
        else:
            method = "pid"   # _NET_WM_PID = the lane's Freelancer.exe unix pid, checked per window (REQ-8)
            ws = self.pid_windows({self.gpid}, "^Freelancer$")
            # FL may show a short-lived early window before the real one: prefer the largest
            ws.sort(key=self.area, reverse=True)
            self.game_wid = ws[0] if ws else None
        if not ws:
            return
        if self.wid is not None and self.wid != ws[0]:
            self.r.setdefault("window_changes", []).append({"ms": now_ms(), "old": self.wid, "new": ws[0]})
        self.wid = ws[0]
        self.r["window_id"] = self.wid
        self.r["window_method"] = method
        desk, cur = xdo("get_desktop_for_window", self.wid), xdo("get_desktop")
        self.r["window_desktop"] = {"window": desk, "current": cur, "ms": now_ms()}
        self.windows_log.write(f"{now_ms()} wid={self.wid} pid={self.gpid} method={method} desktop={desk} "
                               f"current_desktop={cur} all={ws}\n")
        self.windows_log.flush()
        self.log(f"window {self.wid} (pid {self.gpid}, {method})")
        self._place_tries = 0
        self.place()

    def place(self) -> None:
        """Move/size the lane window to its slot and record whether it got there. A window that is still being set
        up (e.g. the vdesk desktop briefly full-screen) is re-placed from tick(), up to 5 times."""
        self._place_tries = getattr(self, "_place_tries", 0) + 1
        x, y = self.lane.get("LANE_X", "0"), self.lane.get("LANE_Y", "0")
        if self._place_tries > 1:
            # a window manager state (maximized / fullscreen) makes it ignore move/size requests: record and clear it
            try:
                st = subprocess.run(["xprop", "-id", str(self.wid), "_NET_WM_STATE"], capture_output=True, text=True,
                                    timeout=5).stdout.strip()
            except subprocess.TimeoutExpired:
                st = "?"
            self.windows_log.write(f"{now_ms()} wm_state wid={self.wid} {st}\n")
            if any(s in st for s in ("MAXIMIZED", "FULLSCREEN")):
                xdo("windowstate", "--remove", "MAXIMIZED_VERT", self.wid)
                xdo("windowstate", "--remove", "MAXIMIZED_HORZ", self.wid)
                xdo("windowstate", "--remove", "FULLSCREEN", self.wid)
        xdo("windowmove", self.wid, x, y)
        xdo("windowsize", self.wid, CFG.get("LANE_W", "1280"), CFG.get("LANE_H", "720"))
        geo = xdo("getwindowgeometry", "--shell", self.wid).replace("\n", " ")
        g = dict(kv.split("=", 1) for kv in geo.split() if "=" in kv)
        # the window manager keeps decorated windows (the vdesk) below the top panel: allow a small y offset
        ok = g.get("X") == str(x) and g.get("Y", "").isdigit() and 0 <= int(g["Y"]) - int(y) <= 80 \
            and g.get("WIDTH") == CFG.get("LANE_W", "1280") and g.get("HEIGHT") == CFG.get("LANE_H", "720")
        self.r["window_placed"] = {"geometry": geo, "slot": [int(x), int(y)], "ok": ok, "tries": self._place_tries}
        self.windows_log.write(f"{now_ms()} placed {geo} slot={x},{y} ok={int(ok)} try={self._place_tries}\n")
        self.windows_log.flush()
        if not ok:
            self.log(f"window {self.wid} not at its slot ({x},{y}) yet: {geo}")

    def lane_windows(self, tag: str, shoot: bool = True) -> list[dict]:
        """Record every visible window owned by a lane process (titles reveal modal dialogs); screenshot dialogs."""
        pids = set(prefix_pids(self.prefix))
        out = []
        for w in xdo("search", "--onlyvisible", "--name", ".*").split():
            pid = xdo("getwindowpid", w)
            if not pid.isdigit() or int(pid) not in pids:
                continue
            title = xdo("getwindowname", w)
            geo = xdo("getwindowgeometry", "--shell", w).replace("\n", " ")
            out.append({"wid": w, "pid": int(pid), "title": title, "geometry": geo})
        self.windows_log.write(f"{now_ms()} [{tag}] lane windows: {json.dumps(out)}\n")
        self.windows_log.flush()
        if shoot:
            for d in out:
                if d["title"] not in ("Freelancer", "Default IME", "", f"lane{self.n} - Wine Desktop") \
                        and "WIDTH=1 " not in d["geometry"]:
                    self.r.setdefault("dialogs", []).append({**d, "tag": tag})
                    self.shot_wid(d["wid"], f"dialog_{tag}_{d['wid']}")
        return out

    def shot_wid(self, wid: str, name: str) -> None:
        out = self.dir / "shots" / f"{name}.png"
        try:
            subprocess.run(["timeout", "-s", "KILL", "10", "import", "-silent", "-window", wid, str(out)],
                           capture_output=True, timeout=20)
        except subprocess.TimeoutExpired:
            pass

    def x_alive(self, limit: float = 3.0) -> bool:
        """Probe the X server with a fresh connection (a stuck grab makes new connections block)."""
        t0 = time.time()
        try:
            subprocess.run(["xdotool", "getdisplaygeometry"], capture_output=True, timeout=limit)
            ok = True
        except subprocess.TimeoutExpired:
            ok = False
        dt = time.time() - t0
        if not ok or dt > 1.0:
            self.r.setdefault("x_stalls", []).append({"ms": now_ms(), "probe_s": round(dt, 2), "ok": ok})
        return ok

    def on_hang(self, idle: float, kind: str = "hang") -> None:
        """Hang: record windows, screenshot, dump (bounded, see capture_dump), kill the lane."""
        self.log(f"HANG ({kind}): no progress for {idle:.0f}s; dumping")
        self.lane_windows("hang")
        if self.wid:
            self.shot("hang")
        h = self.r["hang"]
        h.update(detected=True, at_ms=now_ms(), idle_s=round(idle, 1), kind=kind)
        # crash texts after this wine.log line come from the dump/kill below (winedbg attaching to the WoW64 game
        # crashed it once, NOTES.md N14); verdict.py reports them as info, not as a CRASH
        try:
            with open(self.dir / "wine.log", "rb") as f:
                h["wine_log_lines"] = sum(1 for _ in f)
        except OSError:
            pass
        h.update(self.capture_dump("hang"))
        self.kill_lane(gentle=False)
        self.x_alive()

    def capture_dump(self, tag: str) -> dict:
        """Bounded minidump of the lane's Freelancer.exe plus a text backtrace (`winedbg --command "bt all"`), with the
        reason recorded whenever either fails (review r1 m6). The dump suspends the game's threads; if one of them holds
        an X grab the display would block (NOTES.md N1/N6), so X is probed throughout and the dump is abandoned the
        moment X stops answering; nothing runs longer than HANG_DUMP_S."""
        out: dict = {"minidump": None, "dump_reasons": [], "backtrace": None}
        env = dict(os.environ, WINEPREFIX=self.prefix)
        limit = float(CFG.get("HANG_DUMP_S", "30"))
        why = out["dump_reasons"]
        try:
            if not self.x_alive():
                why.append("X server not responding before the dump: skipped")
                return out
            info = subprocess.run(["winedbg", "--command", "info proc"], env=env, capture_output=True,
                                  text=True, timeout=30)
            (self.dir / f"winedbg_info_proc_{tag}.txt").write_text(info.stdout + info.stderr)
            m = re.search(r"([0-9a-fA-F]{8})\s+\d+\s+.*'Freelancer\.exe'", info.stdout)
            if not m:
                why.append(f"info proc: no Freelancer.exe in the process list (rc={info.returncode})")
                return out
            wpid = f"0x{m.group(1)}"
            # 1. text backtrace first: cheaper, and it survives if the dump attach kills the game (N14)
            bt = self.dir / f"backtrace_{tag}.txt"
            try:
                r = subprocess.run(["winedbg", "--command", "bt all"], env=env, capture_output=True, text=True,
                                   timeout=limit)
                bt.write_text(r.stdout + ("\n--- stderr ---\n" + r.stderr if r.stderr else ""))
                if "Backtrace" in r.stdout or "=>" in r.stdout:
                    out["backtrace"] = str(bt)
                else:
                    why.append(f"bt all: no backtrace in the output (rc={r.returncode}, {len(r.stdout)} bytes)")
            except subprocess.TimeoutExpired:
                why.append(f"bt all: timeout {limit:.0f}s")
            if not self.alive():
                why.append("game gone after the backtrace: no minidump")
                return out
            # 2. minidump
            dump = self.dir / f"{tag}.mdmp"
            log = open(self.dir / f"winedbg_minidump_{tag}.txt", "w")
            dbg = subprocess.Popen(["winedbg", "--minidump", str(dump), wpid], env=env, stdout=log,
                                   stderr=subprocess.STDOUT)
            end = time.time() + limit
            while dbg.poll() is None and time.time() < end:
                if not self.x_alive(2.0):
                    why.append("minidump: X stopped answering during the dump; abandoned")
                    break
                time.sleep(1)
            if dbg.poll() is None:
                dbg.kill()
                why.append(f"minidump: still running after {limit:.0f}s; killed")
            elif dbg.returncode:
                why.append(f"minidump: winedbg exited rc={dbg.returncode}")
            log.close()
            if dump.exists() and dump.stat().st_size > 0:
                out["minidump"] = str(dump)
            else:
                why.append("minidump: no file written (see winedbg_minidump_%s.txt)" % tag)
                if not self.alive():
                    why.append("game exited during the dump attach")
        except (subprocess.TimeoutExpired, OSError) as e:
            self.log(f"dump failed: {e}")
            why.append(f"error: {type(e).__name__}: {e}")
        return out

    def sleep(self, s: float) -> None:
        end = time.time() + s
        while time.time() < end and not self.lane_lost:
            self.tick()
            time.sleep(min(0.5, max(0.0, end - time.time())))

    def wait_until(self, pred, timeout: float, what: str) -> bool:
        end = time.time() + timeout
        self.waiting = True
        try:
            while time.time() < end:
                self.tick()
                if self.r["early_exit"] or self.r["hang"]["detected"] or self.r["crash_windows"] or self.r["dw15_seen"] \
                        or self.lane_lost:
                    return False
                v = pred()
                if v:
                    return True
                time.sleep(0.5)
            self.log(f"timeout waiting for {what}")
            return False
        finally:
            self.waiting = False

    # ------------------------------------------------------------------ text sources
    def fluf_log(self) -> Path | None:
        for p in (self.hde / "SAVE" / "fluf.log", Path(self.prefix) / MYGAMES_REL / "fluf.log"):
            if p.exists():
                return p
        return None

    def text_sources(self) -> dict[str, str]:
        out = {}
        for name, p in (("devbridge", self.dblog), ("spew", self.spew), ("fluf", self.fluf_log())):
            if p is not None and p.exists():
                try:
                    out[name] = p.read_text(errors="replace")
                except OSError:
                    pass
        return out

    def spew_has(self, s: str) -> bool:
        try:
            return s in self.spew.read_text(errors="replace")
        except OSError:
            return False

    # ------------------------------------------------------------------ devbridge
    def db_ready(self) -> bool:
        try:
            return "ev=devbridge_ready" in self.dblog.read_text(errors="replace")
        except OSError:
            return False

    def db_send(self, line: str, timeout: float = 30, expect_fail: bool = False, record: bool = True) -> dict:
        import devbridge  # harness/devbridge.py

        if self.db is None:
            self.db = devbridge.Devbridge(str(self.dbdir))
        parts = shlex.split(line)
        rec = {"line": line, "id": None, "sent_ms": now_ms(), "ack": False, "ok": None, "err": None,
               "expect_fail": expect_fail, "kv": {}}
        self.pending = True
        try:
            resp = self.db.send(parts[0], *parts[1:], timeout=timeout, alive=self._alive_cb)
            rec.update(id=resp.id, ack=True, ok=1 if resp.ok else 0, err=resp.err, kv=resp.kv)
        except Exception as e:  # AckTimeout / GameGone / IO
            rec["err"] = f"{type(e).__name__}: {e}"
        finally:
            self.pending = False
        if record:
            self.r["cmds"].append(rec)
            self.log(f"cmd '{line}' -> ack={rec['ack']} ok={rec['ok']} err={rec['err']}")
        else:
            self.r["polls"] = self.r.get("polls", 0) + 1
        return rec

    def _alive_cb(self) -> bool:
        self.tick()
        if self.r["hang"]["detected"]:
            return False
        return self.alive()

    def db_state(self, record: bool = False) -> dict:
        """Poll `state`. Polls are counted (`run.json polls`), not listed in `cmds`; the --cmds file's own `state`
        lines are recorded as usual."""
        rec = self.db_send("state", timeout=15, record=record)
        return rec.get("kv") or {}

    # ------------------------------------------------------------------ input (gated, lib/xinput.py)
    def xin(self, *args: str, timeout: float = 120) -> tuple[int, str]:
        """Guarded synthetic input through harness/lib/xinput.py (input lock, active-window and cover checks)."""
        if self.lane.get("LANE_INPUT") != "1":
            raise RuntimeError("synthetic input requires a lane acquired with --input")
        cmd = [sys.executable, "-I", str(LIB / "xinput.py"), "--lane", str(self.n), "--wid", str(self.wid), *args]
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        out = (r.stdout + r.stderr).strip()
        self.r.setdefault("input", []).append({"args": list(args), "rc": r.returncode, "out": out, "ms": now_ms()})
        self.log(f"input {' '.join(args)} -> rc={r.returncode} {out}")
        return r.returncode, out

    # ------------------------------------------------------------------ evidence
    def shot(self, name: str) -> str | None:
        if self.wid is None:
            return None
        out = self.dir / "shots" / f"{name}.png"
        desk, cur = xdo("get_desktop_for_window", self.wid), xdo("get_desktop")
        if desk not in (cur, "-1", "4294967295"):
            # windows on another XFCE workspace are unmapped: no capture possible (and we never switch desktops)
            info = f"window on workspace {desk}, current {cur}: not captured"
            self.log(f"shot {name}: {info}")
            self.r["shots"].append({"name": name, "path": str(out), "rc": 1, "info": info})
            return None
        try:
            r = subprocess.run([str(HARNESS / "shot.sh"), self.wid, str(out)], capture_output=True, text=True, timeout=60)
        except subprocess.TimeoutExpired:
            self.log(f"shot {name}: timed out")
            self.r["shots"].append({"name": name, "path": str(out), "rc": -1, "info": "timeout"})
            return None
        self.log(f"shot {name}: {r.stdout.strip()} rc={r.returncode}")
        # rc 0 = the window's own pixels, non-uniform (proof of rendering); rc 2 = root-crop fallback of an uncovered
        # window (evidence only, never proof); rc 1 = failed / covered / uniform (shot.sh)
        self.r["shots"].append({"name": name, "path": str(out), "rc": r.returncode, "info": r.stdout.strip(),
                                "proof": r.returncode == 0})
        return str(out) if out.exists() else None

    def collect(self) -> None:
        for src, dst in ((self.spew, "FLSpew.txt"), (self.dblog, "devbridge_log.txt"),
                         (self.hde / "DEPLOY_MANIFEST.json", "deploy_manifest.json")):
            if src.exists():
                shutil.copy2(src, self.dir / dst)
        try:   # deploy.sh's dacom libraries: verdict.py checks each one really loaded (D107 "DLL loaded")
            self.r["dacom_libraries"] = json.loads((self.dir / "deploy_manifest.json").read_text()).get(
                "dacom_libraries", [])
        except (OSError, ValueError):
            self.r["dacom_libraries"] = []
        fl = self.fluf_log()
        if fl:
            shutil.copy2(fl, self.dir / "fluf.log")
            self.r["notes"].append(f"fluf.log found at {fl}")
        new = [p for p in self.dump_files() if str(p) not in self.pre_dumps]
        if new:
            (self.dir / "dumps").mkdir(exist_ok=True)
            for p in new:
                shutil.copy2(p, self.dir / "dumps" / p.name)
            self.r["new_dumps"] = [str(p) for p in new]
        wl = self.dir / "wine.log"
        if wl.exists():
            lines = [l for l in wl.read_text(errors="replace").splitlines() if CRASH_TEXT.search(l)]
            (self.dir / "crash_lines.txt").write_text("\n".join(lines[-200:]) + ("\n" if lines else ""))

    def dump_files(self) -> list[Path]:
        roots = [self.hde / "SAVE", self.hde / "EXE", Path(self.prefix) / MYGAMES_REL]
        out = []
        for r in roots:
            if r.exists():
                for pat in ("*.dmp", "*.mdmp"):
                    out += list(r.rglob(pat))
        return out

    # ------------------------------------------------------------------ lifecycle
    def kill_lane(self, gentle: bool = True) -> None:
        """Let the game exit first where possible (a graceful window close), then the scoped wineserver kill.
        Killing a process in the middle of GPU submission is a suspect in the 05:28Z GPU fault (NOTES.md N8)."""
        self.quitting = True
        if self.lane_lost:
            # the lane is no longer ours: another acquirer may already run a game in this prefix, so no
            # wineserver -k; only our own game process (pid + start time) is killed
            if self.alive() and proc_start(self.gpid) == getattr(self, "gpid_start", None):
                self.r["killed_by_harness"] = True
                try:
                    os.kill(self.gpid, 9)
                except OSError:
                    pass
            return
        target = getattr(self, "game_wid", None) or self.wid
        if gentle and self.alive() and target:
            xdo("windowquit", str(target))   # the game's own window (never the vdesk desktop window)
            end = time.time() + 10
            while time.time() < end and self.alive():
                time.sleep(0.5)
            self.r["gentle_close"] = not self.alive()
            if self.alive():
                self.log("game did not exit after a graceful window close; killing the lane")
            elif self.r["process_exit_ms"] is None:
                self.r["process_exit_ms"] = now_ms()
        if self.alive():
            self.r["killed_by_harness"] = True   # the exit code then says nothing about the game
        env = dict(os.environ, WINEPREFIX=self.prefix)
        subprocess.run(["wineserver", "-k"], env=env, capture_output=True, timeout=60)
        try:
            subprocess.run(["wineserver", "-w"], env=env, capture_output=True, timeout=60)
        except subprocess.TimeoutExpired:
            self.log("wineserver -w timed out")

    def prepare(self) -> None:
        self.dbdir.mkdir(parents=True, exist_ok=True)
        for p in list(self.dbdir.glob("cmd-*.txt")) + list(self.dbdir.glob(".tmp-cmd-*")):
            p.unlink(missing_ok=True)
        for p in (self.dblog, self.dbdir / ".seq"):
            p.unlink(missing_ok=True)
        self.pre_dumps = {str(p) for p in self.dump_files()}
        (self.dir / "FLSpew.pre_size").write_text(str(fsize(self.spew)))
        # The lane's FLSpew/fluf.log come from the cloned play prefix (or a previous run) and already contain the
        # menu marker; FL truncates FLSpew only once it starts, so remove both to avoid a stale-marker race.
        for p in (self.spew, self.hde / "SAVE" / "fluf.log", Path(self.prefix) / MYGAMES_REL / "fluf.log"):
            p.unlink(missing_ok=True)

    def launch(self) -> None:
        a = self.a
        args = []
        if self.track == "A":
            args.append("-w")   # FLUF re-applies the keep-running-unfocused patch only when an arg starts with -w
        if a.save and self.load_method == "fluf":
            args.append(f"--save-file={a.save}")
        args += a.launch_arg or []
        self.r["args"] = args
        env = dict(os.environ)
        env.update(WINEPREFIX=self.prefix, WINEDEBUG=CFG.get("RUN_WINEDEBUG", "fixme-all,+seh,+loaddll"),
                   DXVK_LOG_LEVEL=CFG.get("RUN_DXVK_LOG_LEVEL", "warn"),
                   # the 60 fps cap lives in DXVK_CONFIG (d3d9.maxFrameRate): DXVK 3.1.1 ignores DXVK_FRAME_RATE (N17)
                   DXVK_CONFIG=CFG.get("RUN_DXVK_CONFIG", "d3d9.presentInterval = 0; d3d9.maxFrameRate = 60"),
                   FLCOPILOT_PORT=self.lane.get("FLCOPILOT_PORT", ""),
                   FLCOPILOT_FORCE_TEST_PROFILE="1")   # lanes never run the sidecar's live profile (P0-SIDECAR)
        if CFG.get("RUN_DXVK_HUD"):
            env["DXVK_HUD"] = CFG["RUN_DXVK_HUD"]
        if self.renderer in ("wined3d", "wined3d-sw"):
            # Wine's builtin d3d8/d3d9 (wined3d on OpenGL) instead of HDE's chain EXE/d3d8.dll (dxwrapper stub,
            # d3d8to9) -> EXE/d3d9.dll (ReShade) -> syswow64 d3d9 (DXVK). d3d9=b alone still let dxwrapper load
            # DXVK's d3d8 (Vulkan), so both are builtin. Lane environment only; no HDE file is touched.
            ov = CFG.get("RENDERER_WINED3D_OVERRIDES", "d3d8=b;d3d9=b")
            env["WINEDLLOVERRIDES"] = ";".join(x for x in (env.get("WINEDLLOVERRIDES"), ov) if x)
        if self.renderer == "wined3d-sw":
            # Mesa llvmpipe through GLVND: no GPU use at all (the degraded GPU refuses new GL/Vulkan channels, N8)
            env.update(__GLX_VENDOR_LIBRARY_NAME="mesa", LIBGL_ALWAYS_SOFTWARE="1", GALLIUM_DRIVER="llvmpipe")
        self.r["env"] = {k: env.get(k) for k in ("WINEDEBUG", "WINEDLLOVERRIDES", "DXVK_CONFIG", "DXVK_HUD",
                                                 "__GLX_VENDOR_LIBRARY_NAME", "LIBGL_ALWAYS_SOFTWARE")}
        cmd = ["wine", "Freelancer.exe", *args]
        if self.display == "vdesk":
            # per-lane Wine virtual desktop: unique window title, and the game sees a 1280x720 desktop (FLUF sizes
            # the game to the desktop, N2). Full path: explorer does not resolve a bare exe name against the cwd.
            w, h = CFG.get("LANE_W", "1280"), CFG.get("LANE_H", "720")
            exe = r"C:\Games\Freelancer HD Edition\EXE\Freelancer.exe"
            cmd = ["wine", "explorer", f"/desktop=lane{self.n},{w}x{h}", exe, *args]
        self.log(f"launch: {' '.join(cmd)} renderer={self.renderer} (cwd {self.hde / 'EXE'})")
        self.r["start_ms"] = now_ms()
        self.launcher = subprocess.Popen(cmd, cwd=self.hde / "EXE", env=env, stdin=subprocess.DEVNULL,
                                         stdout=open(self.dir / "wine.log", "wb"), stderr=subprocess.STDOUT,
                                         start_new_session=True)

    def choose_load_method(self) -> str:
        m = self.a.load_method
        if m != "auto":
            return m
        if not self.a.save:
            return "none"
        return "fluf" if self.track == "A" else "devbridge"

    def is_loaded_state(self, kv: dict) -> bool:
        return kv.get("state") in ("docked", "space")

    def environment_error(self) -> str | None:
        """Refuse to launch on a broken host: DXVK needs a Vulkan device (NOTES.md N8), and X must answer."""
        if not self.x_alive(5.0):
            return "X server :0 not answering"
        if self.display not in ("x11", "vdesk"):
            return f"display mode '{self.display}' needs gamescope, which is banned on this host (D103)"
        if self.renderer == "dxvk":
            ok, why = vulkan_ok()
            if not ok:
                return f"renderer dxvk requested but Vulkan device creation fails ({why}); see harness/NOTES.md N8"
        return None

    def run(self) -> int:
        a = self.a
        # --renderer, else $FLMOD_RENDERER, else what lane.sh acquire resolved (LANE_RENDERER), else config default
        self.renderer = resolve_renderer(a.renderer or os.environ.get("FLMOD_RENDERER") or self.lane.get("LANE_RENDERER"))
        self.r["renderer"] = self.renderer
        self.load_method = self.choose_load_method()
        self.r["load_method"] = self.load_method
        err = self.environment_error()
        if err:
            self.log(f"ENVIRONMENT ERROR: {err}; not launching")
            self.r["notes"].append(f"environment error: {err}")
            self.r["end_ms"] = now_ms()
            self.liv.close()
            self.windows_log.close()
            (self.dir / "run.json").write_text(json.dumps(self.r, indent=2) + "\n")
            (self.dir / "verdict.json").write_text(json.dumps(
                {"verdict": "ERROR", "reasons": [f"harness/environment: {err}"], "run": str(self.dir)}, indent=2) + "\n")
            print(f"rundir={self.dir}")
            print("verdict=ERROR")
            return 2
        self.prepare()
        try:
            self.launch()
            # window
            if not self.wait_until(lambda: self.wid is not None, a.window_timeout, "game window"):
                self.log("no window")
                self.lane_windows("no_window")
                return self.finish()
            # menu readiness
            ok = self.wait_until(lambda: self.spew_has(MENU_SPEW) or self.db_ready(), a.timeout, "main menu")
            if not ok:
                self.r["timeout"] = not (self.r["early_exit"] or self.r["hang"]["detected"] or self.lane_lost)
                if self.r["timeout"] and self.alive():
                    # start-up never finished: keep the evidence (review r1 m3)
                    self.r["startup_dump"] = self.capture_dump("startup_timeout")
                return self.finish()
            self.r["devbridge"] = self.db_ready()
            self.r["ready"] = True
            self.r["ready_marker"] = "devbridge_ready" if self.r["devbridge"] else MENU_SPEW
            self.r["ready_ms"] = now_ms()
            if self.r["devbridge"]:
                # the core is up; wait for the menu proper
                self.wait_until(lambda: self.spew_has(MENU_SPEW), 60, "menu spew")
            for s in a.shot_at_ready or []:
                self.shot(s)
            # load
            if a.save:
                if not self.do_load():
                    return self.finish()
            if a.launch_in_space:
                self.do_launch()
            # commands
            if a.cmds:
                for line in Path(a.cmds).read_text().splitlines():
                    line = line.strip()
                    if not line or line.startswith("#"):
                        continue
                    if line.startswith("@"):
                        if not self.harness_step(line[1:].strip()):
                            break
                        if self.r["early_exit"] or self.r["hang"]["detected"]:
                            break
                        continue
                    xf = line.startswith("!")
                    line, budget = command_budget(line.lstrip("!").strip())
                    rec = self.db_send(line, timeout=max(a.cmd_timeout, budget + 15) if budget else a.cmd_timeout,
                                       expect_fail=xf)
                    rec["timeout_s"] = budget
                    if self.lane_lost:
                        break
                    if self.r["early_exit"] or self.r["hang"]["detected"]:
                        break
                    if not rec["ack"] and not self.alive():
                        break
            # expectations
            exps = [{"regex": e, "matched": False, "where": None} for e in (a.expect or [])]
            self.r["expects"] = exps
            if exps:
                def all_matched() -> bool:
                    src = self.text_sources()
                    for e in exps:
                        if not e["matched"]:
                            for k, txt in src.items():
                                if re.search(e["regex"], txt, re.M):
                                    e.update(matched=True, where=k)
                                    break
                    return all(e["matched"] for e in exps)
                if not self.wait_until(all_matched, a.timeout, "expectations"):
                    if not (self.r["early_exit"] or self.r["hang"]["detected"] or self.lane_lost):
                        self.r["timeout"] = True
            if a.hold_s:
                self.sleep(a.hold_s)
            if self.alive():
                self.shot("final")
            if a.dump_before_quit and self.alive():
                self.r["manual_dump"] = self.capture_dump("manual")
            for s in a.shot or []:
                self.shot(s)
            return self.finish()
        except Exception as e:
            self.log(f"runner exception: {type(e).__name__}: {e}")
            self.r["notes"].append(f"runner exception: {type(e).__name__}: {e}")
            self.r["runner_error"] = f"{type(e).__name__}: {e}"
            return self.finish()

    def harness_step(self, step: str) -> bool:
        """Runner-side steps in a --cmds file (lines starting with '@'):
          @sleep <s>                               keep monitoring for s seconds
          @shot <name>                             screenshot of the lane window
          @key <keysym> [--hold-ms N]              one gated XTEST key (lane acquired with --input)
          @console <text>                          adoxa console chat command (Return, text, Return), gated
          @click <x> <y>                           gated click at window point (x, y); FL cursor dead reckoning, NOTES.md N5
          @wait_state <k>=<v>[,<v2>...] [timeout_s]  poll devbridge `state` until key k has one of the values
        A failed step is recorded in run.json `steps` (ok=false) and ends the command list."""
        parts = shlex.split(step)
        rec = {"step": step, "ms": now_ms(), "ok": False, "info": None}
        self.r.setdefault("steps", []).append(rec)
        try:
            verb, args = parts[0], parts[1:]
            if verb == "sleep":
                self.sleep(float(args[0]))
                rec["ok"] = True
            elif verb == "shot":
                rec["ok"] = self.shot(args[0]) is not None
            elif verb in ("key", "console", "click"):
                rc, out = self.xin(verb, *args)
                rec.update(ok=rc == 0, info=out)
            elif verb == "wait_state":
                k, vals = args[0].split("=", 1)
                want = set(vals.split(","))
                timeout = float(args[1]) if len(args) > 1 else 60.0
                last: dict = {}

                def match() -> bool:
                    last.clear()
                    last.update(self.db_state())
                    if last.get(k) in want:
                        return True
                    time.sleep(1.0)
                    return False
                rec["ok"] = self.wait_until(match, timeout, f"state {k} in {sorted(want)}")
                rec["info"] = {kk: last.get(kk) for kk in ("state", "base_id", "system_id", k)}
            else:
                rec["info"] = f"unknown step '{verb}'"
        except (IndexError, ValueError, RuntimeError, subprocess.TimeoutExpired) as e:
            rec["info"] = f"{type(e).__name__}: {e}"
        self.log(f"step @{step} -> ok={rec['ok']} {rec['info'] or ''}")
        return rec["ok"]

    def do_load(self) -> bool:
        a = self.a
        m = self.load_method
        self.log(f"loading '{a.save}' via {m}")
        if m == "fluf":
            pass  # FLUF debugger presses the menu buttons itself
        elif m == "devbridge":
            rec = self.db_send(f"load {fixture_file(a.save)}", timeout=60)
            if not rec["ok"]:
                # no menu-click fallback: FL's software cursor makes clicks unreliable (NOTES.md N5)
                self.r["notes"].append("devbridge load failed")
                return False
        # loaded?
        def loaded() -> bool:
            if self.r["devbridge"]:
                kv = self.db_state()
                if self.is_loaded_state(kv):
                    self.r["loaded_marker"] = f"devbridge state={kv.get('state')}"
                    return True
                time.sleep(1.5)
                return False
            for rx in LOADED_SPEW:
                try:
                    if re.search(rx, self.spew.read_text(errors="replace"), re.M):
                        self.r["loaded_marker"] = f"spew /{rx}/"
                        return True
                except OSError:
                    pass
            return False
        ok = self.wait_until(loaded, a.load_timeout, "save loaded")
        self.r["loaded"] = ok
        if ok:
            self.sleep(a.settle_s)
            self.shot("loaded")
        elif not (self.r["early_exit"] or self.r["hang"]["detected"] or self.lane_lost):
            self.r["timeout"] = True
        return ok

    def do_launch(self) -> bool:
        launched = False
        if self.r["devbridge"]:
            rec = self.db_send("launch", timeout=60, expect_fail=True)
            launched = bool(rec["ok"])
        if not launched:
            # adoxa console.dll is loaded on both tracks: chat command "launch" (keyboard only; clicks are unreliable
            # because FL's software cursor integrates relative deltas, harness/NOTES.md N5)
            self.log("launch via adoxa console 'launch' (keyboard, input lock)")
            rc, out = self.xin("console", "launch")
            if rc != 0:
                raise RuntimeError(f"console launch refused: {out}")
        ok = True
        if self.r["devbridge"]:
            def in_space() -> bool:
                kv = self.db_state()
                if kv.get("state") == "space":
                    return True
                time.sleep(1.5)
                return False
            ok = self.wait_until(in_space, 60, "state=space after launch")
            self.r["launched"] = ok
            if not ok and not (self.r["early_exit"] or self.r["hang"]["detected"] or self.lane_lost):
                self.r["timeout"] = True
        self.sleep(self.a.settle_s)
        self.shot("launched")
        return ok

    def finish(self) -> int:
        a = self.a
        try:
            self.tick(force=True)
            if self.alive():
                self.lane_windows("finish")
            if self.alive() and not a.no_quit and self.r["devbridge"] and not self.lane_lost:
                self.quitting = True
                self.r["quit_sent"] = True
                self.r["quit_ms"] = now_ms()
                q = self.db_send("quit", timeout=15)
                self.r["quit_acked"] = bool(q["ack"] and q["ok"])
                end = time.time() + 30
                while time.time() < end and self.alive():
                    self.tick()          # dw15.exe, crash windows and X state stay watched during the exit
                    time.sleep(0.5)
                self.tick(force=True)
                self.r["exited_after_quit"] = not self.alive()
                if self.r["exited_after_quit"]:
                    self.r["process_exit_ms"] = self.r["process_exit_ms"] or now_ms()
                else:
                    self.log("quit acked but the game did not exit within 30 s")
            self.quitting = True
            if not a.keep_running:
                self.kill_lane()
            if self.launcher is not None:
                try:
                    self.r["exit_code"] = self.launcher.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    self.r["exit_code"] = None
            self.collect()
        finally:
            self.r["end_ms"] = now_ms()
            self.liv.close()
            self.windows_log.close()
            allow = HARNESS / "baseline" / f"spew_allow_{self.track}_{self.renderer}.txt"
            self.r["spew_allow"] = str(allow) if allow.exists() else None
            (self.dir / "run.json").write_text(json.dumps(self.r, indent=2) + "\n")
        verdict = "UNKNOWN"
        vp = HARNESS / "verdict.py"
        if vp.exists():
            cmd = [sys.executable, "-I", str(vp), str(self.dir), "--track", self.track]
            if self.r["spew_allow"]:
                cmd += ["--allow", self.r["spew_allow"]]
            else:
                # no allow-list for this track/renderer yet: report spew, don't fail on it
                cmd += ["--allow", str(HARNESS / "baseline" / f"__missing_{self.track}_{self.renderer}.txt")]
            if a.spew_check:
                cmd += ["--spew-check", a.spew_check]
            subprocess.run(cmd, timeout=120)
            try:
                vj = json.loads((self.dir / "verdict.json").read_text())
                verdict = vj["verdict"]
                vj["renderer"] = self.renderer
                vj["display"] = self.display
                (self.dir / "verdict.json").write_text(json.dumps(vj, indent=2) + "\n")
            except (OSError, ValueError, KeyError):
                verdict = "ERROR"
        print(f"rundir={self.dir}")
        print(f"renderer={self.renderer}")
        print(f"verdict={verdict}")
        return 0 if verdict == "PASS" else 1


_VK_CACHE: tuple[bool, str] | None = None


def vulkan_ok() -> tuple[bool, str]:
    """Quick Vulkan device probe: `vulkaninfo --summary` exits 0 and reports no vkCreateDevice failure."""
    global _VK_CACHE
    if _VK_CACHE is not None:
        return _VK_CACHE
    if not shutil.which("vulkaninfo"):
        _VK_CACHE = (False, "vulkaninfo not installed")
        return _VK_CACHE
    try:
        r = subprocess.run(["vulkaninfo", "--summary"], capture_output=True, text=True, timeout=30)
        out = r.stdout + r.stderr
        bad = r.returncode != 0 or "vkCreateDevice failed" in out or "ERROR_INITIALIZATION_FAILED" in out
        _VK_CACHE = (not bad, out.strip().splitlines()[-1][:200] if bad and out.strip() else "ok")
    except subprocess.TimeoutExpired:
        _VK_CACHE = (False, "vulkaninfo timed out")
    return _VK_CACHE


def resolve_renderer(req: str | None) -> str:
    """FLMOD_RENDERER=auto|dxvk|wined3d|wined3d-sw (D103). auto = dxvk if a Vulkan device can be created; otherwise
    the GPU is degraded (it refuses new GPFIFO channels for GL too, NOTES.md N10), so wined3d on Mesa llvmpipe."""
    req = (req or os.environ.get("FLMOD_RENDERER") or CFG.get("RENDERER_DEFAULT", "auto")).lower()
    if req not in ("auto", "dxvk", "wined3d", "wined3d-sw"):
        sys.exit(f"run: unknown renderer {req!r} (auto|dxvk|wined3d|wined3d-sw)")
    if req == "auto":
        return "dxvk" if vulkan_ok()[0] else CFG.get("RENDERER_FALLBACK", "wined3d-sw")
    return req


def fixture_file(save: str) -> str:
    """Save file name for a description (FL/console rule `%x.fl` of CreateID(description)); pass *.fl through."""
    if save.lower().endswith(".fl"):
        return save
    sys.path.insert(0, str(HARNESS / "fixtures"))
    from flhash import create_id  # harness/fixtures/flhash.py

    return "%x.fl" % create_id(save)


# FLSpew markers that show a save finished loading (no devbridge). Filled from observed runs (harness/NOTES.md).
LOADED_SPEW: list[str] = []


def main() -> int:
    ap = argparse.ArgumentParser(prog="run.sh")
    ap.add_argument("--lane", type=int, required=True)
    ap.add_argument("--save")
    ap.add_argument("--timeout", type=float, default=180, help="per-phase wall timeout (menu, expectations)")
    ap.add_argument("--window-timeout", type=float, default=90)
    ap.add_argument("--load-timeout", type=float, default=120)
    ap.add_argument("--cmd-timeout", type=float, default=60)
    ap.add_argument("--cmds")
    ap.add_argument("--name", default="run")
    ap.add_argument("--expect", action="append")
    ap.add_argument("--load-method", default="auto", choices=["auto", "fluf", "devbridge", "none"])
    ap.add_argument("--launch-in-space", action="store_true")
    ap.add_argument("--launch-arg", action="append", help="extra Freelancer.exe argument")
    ap.add_argument("--no-quit", action="store_true")
    ap.add_argument("--keep-running", action="store_true", help="do not kill the lane at the end (debugging)")
    ap.add_argument("--dump-before-quit", action="store_true",
                    help="debugging: capture a backtrace + minidump of the live game before quitting (may kill it, N14)")
    ap.add_argument("--hang-s", type=float, default=float(CFG.get("HANG_S", "60")))
    ap.add_argument("--hold-s", type=float, default=0, help="stay in game this long before the final screenshot")
    ap.add_argument("--settle-s", type=float, default=5)
    ap.add_argument("--spew-check", choices=["strict", "report"])
    ap.add_argument("--renderer", choices=["auto", "dxvk", "wined3d", "wined3d-sw"],
                    help="default: $FLMOD_RENDERER, else the lane's LANE_RENDERER, else config RENDERER_DEFAULT (auto)")
    ap.add_argument("--shot", action="append", help="extra screenshot names taken at the end")
    ap.add_argument("--shot-at-ready", action="append")
    a = ap.parse_args()
    return Run(a).run()


if __name__ == "__main__":
    sys.exit(main())
