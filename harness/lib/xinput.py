#!/usr/bin/env python3
"""Gated synthetic input for a lane's game window (CONVENTIONS §7: XTEST to the focused window, input lock only).

  xinput.py --lane N [--wid W] click X Y [--hold-ms 120]   window-relative client coordinates
  xinput.py --lane N [--wid W] key <keysym> [--hold-ms 80]
  xinput.py --lane N [--wid W] move X Y
  xinput.py --lane N [--wid W] type <text>                  XTEST typing, one gated keystroke at a time
  xinput.py --lane N [--wid W] console <command>            adoxa console.dll chat command (e.g. "launch")
  xinput.py --lane N [--wid W] check [X Y]                  run the gate only; print ok or the refusal
  (--prefix P instead of --lane N: only prefix-dev-base-A|B(-init), for baseline.sh's first-launch dialog; the
   caller (or an ancestor, e.g. `flock input.lock xinput.py ...`) must hold input.lock, checked in /proc/locks)

THE GATE (orchestrator requirement after input reached Adam's Steam window, 2026-10-18; NOTES.md N9). Before
every input step (each key, each typed character, each batch of pointer motion, each button event):
  1. the lane holds the input lock (lane-N.owner input=1, holder alive, and /proc/locks shows input.lock held by
     that holder; in --prefix mode by this process or an ancestor);
  2. the target window's _NET_WM_PID is the lane's own Freelancer.exe (x11 lanes), or, for a vdesk lane
     (LANE_DISPLAY=vdesk), the target is exactly the window titled `lane<N> - Wine Desktop` whose _NET_WM_PID is the
     lane's own explorer.exe (the game's Win32 window lives inside that desktop window and gets the keyboard focus
     from it). _NET_WM_PID is only a property any client can set, so the X server's own record of the window's
     creator (X-Resource extension, XResQueryClientIds LocalClientPID) must agree (review r1 m1);
  3. the window is on the CURRENT XFCE workspace (_NET_WM_DESKTOP == current desktop; we never switch desktops
     and never move windows between them);
  4. after `windowactivate --sync` the current desktop did not change and the ACTIVE window is the target (its
     _NET_WM_PID is the lane's game process; for vdesk the active window must be the lane's desktop window itself);
  5. for pointer actions: the X pointer is inside the game window and no other top-level window covers the point.
Any failure aborts the step and prints `HARNESS input_refused reason=<r> active=<wid/name>`; nothing is sent and
there is no fallback. Never uses `xdotool key --window` (XSendEvent is invisible to the game).
"""
from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
import time
from pathlib import Path

FLMOD_LOCKS = Path(os.environ.get("FLMOD_LOCKS", "/home/user/freelancer/carrier-mod/local/locks"))
CURSOR_GAIN = float(os.environ.get("FL_CURSOR_GAIN", "1.034"))  # measured 2026-10-18, NOTES.md N5


class Refused(Exception):
    def __init__(self, reason: str, active: str = "-"):
        super().__init__(reason)
        self.reason, self.active = reason, active


def xdo(*args: str, timeout: float = 10) -> str:
    try:
        return subprocess.run(["xdotool", *args], capture_output=True, text=True, timeout=timeout).stdout.strip()
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return ""


def geom(wid: str) -> dict:
    return {k: int(v) for k, v in (kv.split("=", 1) for kv in xdo("getwindowgeometry", "--shell", wid).split()
                                   if "=" in kv) if v.lstrip("-").isdigit()}


def xres_pid(wid) -> int | None:
    """Unix pid of the X client that created window `wid`, from the X server (X-Resource LocalClientPID). None if
    the extension or python-xlib is unavailable or the lookup fails (callers refuse then: fail closed)."""
    try:
        from Xlib import display
        from Xlib.ext import res
    except ImportError:
        return None
    try:
        d = display.Display()
    except Exception:  # noqa: BLE001 (any connection failure)
        return None
    try:
        if not d.has_extension("X-Resource"):
            return None
        r = d.res_query_client_ids([{"client": int(wid), "mask": res.LocalClientPIDMask}])
        for cid in r.ids:
            if cid.spec.mask & res.LocalClientPIDMask and cid.value:
                return int(cid.value[0])
        return None
    except Exception:  # noqa: BLE001 (BadWindow etc.)
        return None
    finally:
        d.close()


def has_open(pid: int, path: Path) -> bool:
    """Does process `pid` have `path` open (an fd linking to it)?"""
    want = os.path.realpath(path)
    try:
        for fd in os.listdir(f"/proc/{pid}/fd"):
            try:
                if os.readlink(f"/proc/{pid}/fd/{fd}") == want:
                    return True
            except OSError:
                pass
    except OSError:
        pass
    return False


def lock_held_by(path: Path, pids) -> bool:
    """`path` is flock()ed (it has an entry in /proc/locks) and one of `pids` has it open. /proc/locks names the
    process that took the lock, which for flock(1) on an inherited fd is a short-lived child, so the open fd is
    what identifies the holder (lock_holder.sh's `sleep`, or the `flock file cmd` ancestor)."""
    return bool(flock_holders(path)) and any(has_open(p, path) for p in pids)


def flock_holders(path: Path) -> set[int]:
    """Pids recorded for FLOCK entries on `path` in /proc/locks (device major:minor:inode match)."""
    try:
        st = path.stat()
    except OSError:
        return set()
    want = (os.major(st.st_dev), os.minor(st.st_dev), st.st_ino)
    out = set()
    try:
        for line in Path("/proc/locks").read_text().splitlines():
            f = line.split()
            if len(f) >= 6 and f[1] == "FLOCK":
                try:
                    maj, mnr, ino = f[5].split(":")
                    if (int(maj, 16), int(mnr, 16), int(ino)) == want:
                        out.add(int(f[4]))
                except ValueError:
                    pass
    except OSError:
        pass
    return out


def ancestors(pid: int) -> list[int]:
    chain = []
    while pid > 1 and len(chain) < 64:
        chain.append(pid)
        try:
            pid = int(re.search(r"^PPid:\s+(\d+)", Path(f"/proc/{pid}/status").read_text(), re.M).group(1))
        except (OSError, AttributeError, ValueError):
            break
    return chain


def lane_env(n: int) -> dict:
    own = FLMOD_LOCKS / f"lane-{n}.owner"
    envf = FLMOD_LOCKS / f"lane-{n}.env"
    if not own.exists() or not envf.exists():
        raise Refused(f"lane_{n}_not_held")
    o = dict(l.split("=", 1) for l in own.read_text().splitlines() if "=" in l)
    if o.get("input") != "1":
        raise Refused("no_input_lock")
    if not Path(f"/proc/{o.get('holder_pid', 'x')}").exists():
        raise Refused("lock_holder_dead")
    if not lock_held_by(FLMOD_LOCKS / "input.lock", [int(o.get("holder_pid", "0") or 0)]):
        raise Refused("input_lock_not_held_by_lane")
    e = {}
    for l in envf.read_text().splitlines():
        m = re.match(r"^export ([A-Z_]+)='?(.*?)'?$", l)
        if m:
            e[m.group(1)] = m.group(2)
    return e


def prefix_pid(prefix: str, comm: str) -> int | None:
    key = f"WINEPREFIX={os.path.realpath(prefix)}".encode()
    for d in os.listdir("/proc"):
        if not d.isdigit():
            continue
        try:
            if key in Path(f"/proc/{d}/environ").read_bytes().split(b"\0") and \
                    Path(f"/proc/{d}/comm").read_text().strip() == comm:
                return int(d)
        except OSError:
            pass
    return None


def game_pid(prefix: str) -> int:
    pid = prefix_pid(prefix, "Freelancer.exe")
    if pid is None:
        raise Refused("no_game_process")
    return pid


def vdesk_window(prefix: str, lane: int) -> tuple[str, int]:
    """The lane's Wine virtual desktop window: title exactly `lane<N> - Wine Desktop`, owned by the lane's explorer.exe."""
    epid = prefix_pid(prefix, "explorer.exe")
    if epid is None:
        raise Refused("no_vdesk_explorer")
    ws = [w for w in xdo("search", "--onlyvisible", "--name", f"^lane{lane} - Wine Desktop$").split()
          if xdo("getwindowpid", w) == str(epid)]
    if len(ws) != 1:
        raise Refused(f"vdesk_window_count={len(ws)}")
    return ws[0], epid


class Gate:
    def __init__(self, prefix: str, wid: str | None, lane: int | None, display: str = "x11"):
        self.lane = lane
        self.gpid = game_pid(prefix)
        self.display = display
        # accept_pid: the _NET_WM_PID the target (and, after activation, the active) window must carry
        if display == "vdesk":
            if lane is None:
                raise Refused("vdesk_needs_lane")
            vwid, self.accept_pid = vdesk_window(prefix, lane)
            if wid is not None and wid != vwid:
                raise Refused(f"target_not_lane_vdesk wid={wid} vdesk={vwid}")
            wid = vwid
        else:
            self.accept_pid = self.gpid
            if wid is None:
                # pid checked per window: xdotool search ORs --pid with --name (NOTES.md N13)
                ws = [w for w in xdo("search", "--onlyvisible", "--name", "^Freelancer$").split()
                      if xdo("getwindowpid", w) == str(self.gpid)]
                if not ws:
                    raise Refused("no_game_window")
                wid = ws[0]
        self.wid = wid
        self.recheck_lock = (lambda: lane_env(lane)) if lane is not None else (lambda: None)

    def active_desc(self) -> str:
        a = xdo("getactivewindow")
        return f"{a}/{xdo('getwindowname', a)!r}" if a else "-"

    def check(self, activate: bool = True) -> None:
        self.recheck_lock()
        wpid = xdo("getwindowpid", self.wid)
        if wpid != str(self.accept_pid):
            raise Refused("target_not_game_window", self.active_desc())
        xp = xres_pid(self.wid)
        if xp is None:
            raise Refused("xres_lookup_failed", self.active_desc())
        if xp != self.accept_pid:
            raise Refused(f"target_creator_mismatch net_wm_pid={wpid} xres_pid={xp}", self.active_desc())
        if self.display == "vdesk" and xdo("getwindowname", self.wid) != f"lane{self.lane} - Wine Desktop":
            raise Refused("target_not_lane_vdesk", self.active_desc())
        cur, wdesk = xdo("get_desktop"), xdo("get_desktop_for_window", self.wid)
        if not cur or wdesk not in (cur, "-1", "4294967295"):   # -1 / 0xFFFFFFFF = sticky (all desktops)
            raise Refused(f"workspace_mismatch window_desktop={wdesk or '?'} current={cur or '?'}", self.active_desc())
        if activate:
            xdo("windowactivate", "--sync", self.wid, timeout=10)
            time.sleep(0.15)
            if xdo("get_desktop") != cur:
                raise Refused("desktop_changed_by_activation", self.active_desc())
        active = xdo("getactivewindow")
        if not active or xdo("getwindowpid", active) != str(self.accept_pid) or xres_pid(active) != self.accept_pid:
            raise Refused("focus_mismatch", self.active_desc())
        if self.display == "vdesk" and active != self.wid:
            raise Refused("focus_mismatch_vdesk", self.active_desc())

    def check_point(self, x: int | None = None, y: int | None = None) -> None:
        """Pointer must be inside the game window and the point not covered by another top-level window."""
        g = geom(self.wid)
        if not g:
            raise Refused("no_geometry", self.active_desc())
        if x is None:
            loc = dict(kv.split("=", 1) for kv in xdo("getmouselocation", "--shell").split() if "=" in kv)
            x, y = int(loc.get("X", -1)) - g["X"], int(loc.get("Y", -1)) - g["Y"]
        if not (0 <= x < g["WIDTH"] and 0 <= y < g["HEIGHT"]):
            raise Refused(f"pointer_outside_game_window x={x} y={y}", self.active_desc())
        sx, sy = g["X"] + x, g["Y"] + y
        try:
            out = subprocess.run(["xprop", "-root", "_NET_CLIENT_LIST_STACKING"], capture_output=True, text=True,
                                 timeout=10).stdout
        except subprocess.TimeoutExpired:
            raise Refused("xprop_timeout", self.active_desc())
        stack = [int(w, 16) for w in re.findall(r"0x[0-9a-fA-F]+", out)]
        me = int(self.wid)
        if me not in stack:
            raise Refused("game_window_not_managed", self.active_desc())
        for w in stack[stack.index(me) + 1:]:
            h = geom(str(w))
            if h and h["X"] <= sx < h["X"] + h["WIDTH"] and h["Y"] <= sy < h["Y"] + h["HEIGHT"]:
                raise Refused(f"covered_by window={w}/{xdo('getwindowname', str(w))!r}", self.active_desc())

    # ---------------------------------------------------------------- gated primitives
    def key(self, keysym: str, hold_ms: int = 80) -> None:
        self.check()
        xdo("keydown", keysym)
        time.sleep(hold_ms / 1000)
        xdo("keyup", keysym)

    def type_text(self, text: str, delay_ms: int = 60) -> None:
        for ch in text:
            self.check(activate=False)          # focus must still be ours before every character
            xdo("type", "--delay", "0", "--", ch)
            time.sleep(delay_ms / 1000)

    def rel_steps(self, dx: int, dy: int, step: int = 40) -> None:
        n = max(1, int(max(abs(dx), abs(dy)) / step + 0.999))
        done_x = done_y = 0
        for i in range(1, n + 1):
            if i % 8 == 1:
                self.check(activate=False)
            tx, ty = round(dx * i / n), round(dy * i / n)
            xdo("mousemove_relative", "--", str(tx - done_x), str(ty - done_y))
            done_x, done_y = tx, ty
            time.sleep(0.02)

    def point(self, x: int, y: int, warp: bool = False) -> None:
        """Put Freelancer's own cursor on window point (x, y). FL draws a software cursor integrated from relative
        deltas (gain ~1.034), so absolute warps don't land where expected (N5): park the X pointer at the window's
        bottom-right, sweep to the top-left (FL's cursor clamps at 0,0), then move by target/gain."""
        self.check()
        g = geom(self.wid)
        if warp:
            xdo("mousemove", "--window", self.wid, str(x), str(y))
            time.sleep(0.25)
            return
        xdo("mousemove", "--window", self.wid, str(g["WIDTH"] - 1), str(g["HEIGHT"] - 1))
        time.sleep(0.15)
        self.rel_steps(-(g["WIDTH"] - 1), -(g["HEIGHT"] - 1))
        time.sleep(0.15)
        self.rel_steps(round(x / CURSOR_GAIN), round(y / CURSOR_GAIN))
        time.sleep(0.3)

    def click(self, x: int, y: int, hold_ms: int = 120, button: str = "1", warp: bool = False) -> None:
        self.point(x, y, warp)
        self.check(activate=False)
        self.check_point()          # where the X pointer actually is now (the game may warp it)
        xdo("mousedown", button)
        time.sleep(hold_ms / 1000)
        xdo("mouseup", button)


def main() -> int:
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--lane", type=int)
    g.add_argument("--prefix", help="build prefix (prefix-dev*) when there is no lane; caller holds input.lock")
    ap.add_argument("--wid")
    ap.add_argument("--warp", action="store_true", help="absolute X warp instead of FL cursor dead reckoning")
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("click"); c.add_argument("x", type=int); c.add_argument("y", type=int)
    c.add_argument("--hold-ms", type=int, default=120); c.add_argument("--button", default="1")
    k = sub.add_parser("key"); k.add_argument("keysym"); k.add_argument("--hold-ms", type=int, default=80)
    m = sub.add_parser("move"); m.add_argument("x", type=int); m.add_argument("y", type=int)
    t = sub.add_parser("type"); t.add_argument("text"); t.add_argument("--delay-ms", type=int, default=60)
    co = sub.add_parser("console", help="adoxa console.dll command via chat (Return, text, Return)")
    co.add_argument("text")
    ch = sub.add_parser("check"); ch.add_argument("x", type=int, nargs="?"); ch.add_argument("y", type=int, nargs="?")
    a = ap.parse_args()
    try:
        display = "x11"
        if a.lane is not None:
            env = lane_env(a.lane)
            prefix = env["WINEPREFIX"]
            display = env.get("LANE_DISPLAY") or "x11"
        else:
            prefix = os.path.realpath(a.prefix)
            if not re.fullmatch(r"/home/user/freelancer/prefix-dev-base-[AB](-init)?", prefix):
                raise Refused("prefix_not_a_baseline_prefix")
            if not lock_held_by(FLMOD_LOCKS / "input.lock", ancestors(os.getpid())):
                raise Refused("input_lock_not_held_by_caller")
        gate = Gate(prefix, a.wid, a.lane, display)
        if a.cmd == "check":
            gate.check(activate=False)
            if a.x is not None:
                gate.check_point(a.x, a.y)
        elif a.cmd == "click":
            gate.click(a.x, a.y, a.hold_ms, a.button, a.warp)
        elif a.cmd == "move":
            gate.point(a.x, a.y, a.warp)
        elif a.cmd == "key":
            gate.key(a.keysym, a.hold_ms)
        elif a.cmd == "type":
            gate.check()
            gate.type_text(a.text, a.delay_ms)
        elif a.cmd == "console":
            gate.key("Return")
            time.sleep(0.6)
            gate.type_text(a.text)
            time.sleep(0.3)
            gate.key("Return")
    except Refused as r:
        print(f"HARNESS input_refused reason={r.reason} active={r.active}")
        return 3
    print(f"xinput {a.cmd} ok wid={gate.wid} pid={gate.gpid} display={gate.display}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
