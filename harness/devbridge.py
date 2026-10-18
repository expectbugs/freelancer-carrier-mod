#!/usr/bin/env python3
"""Devbridge client library + CLI (wire protocol v1, harness/devbridge/PROTOCOL.md).

Library:
    db = Devbridge("/path/to/HDE/SAVE/devbridge")
    db.wait_ready(60)
    r = db.send("echo", "hello world", timeout=30)   # -> Response(ok, id, kv, err, data, line)

CLI (exit 0 ok, 1 ok=0/failed, 2 timeout, 3 game gone, 64 usage):
    devbridge.py (--dir D | --lane N) [--since N|end] send <verb> [args...] [--timeout S] [--id ID] [--pid P]
    devbridge.py ... wait-ready [--timeout S]
    devbridge.py ... wait <regex> [--timeout S]
    devbridge.py ... run-file <cmds.txt> [--timeout S] [--keep-going] [--pid P]
    devbridge.py ... tail [--follow]
    devbridge.py ... offset
Without --dir/--lane, $FL_DEVBRIDGE_DIR is used. `--since` (default 0) is the log byte offset
that wait/wait-ready/tail start from; pass `--since $(devbridge.py ... offset)` captured before
launching the game, or delete log.txt before launch, so a ready line from an earlier run is not
matched.

Stdlib only. Run with `python -I`.
"""
from __future__ import annotations

import argparse
import dataclasses
import fcntl
import os
import re
import shlex
import sys
import time
from typing import Callable, Iterator, Optional, Pattern, Union

PROTOCOL_VERSION = 1
SEQ_WIDTH = 10
CMD_RE = re.compile(r"^cmd-(\d{1,19})\.txt$")
TMP_RE = re.compile(r"^\.tmp-cmd-(\d{1,19})$")
ID_RE = re.compile(r"^[A-Za-z0-9_.:-]{1,64}$")
MARKER_RE = re.compile(r"(?:^|\s)HARNESS(?=\s|$)")
DEFAULT_LOCKS = "/home/user/freelancer/carrier-mod/local/locks"
LOG_NAME = "log.txt"
SEQ_NAME = ".seq"
SEQ_LOCK_NAME = ".seq.lock"

EXIT_OK, EXIT_FAIL, EXIT_TIMEOUT, EXIT_GONE, EXIT_USAGE = 0, 1, 2, 3, 64


class DevbridgeError(Exception):
    """Base class for client errors."""


class DevbridgeTimeout(DevbridgeError, TimeoutError):
    """A wait ran out of time."""


class AckTimeout(DevbridgeTimeout):
    """No ack arrived for a command in time."""

    def __init__(self, cmd_id: str, seq: int, timeout: float, picked_up: bool):
        self.id, self.seq, self.timeout, self.picked_up = cmd_id, seq, timeout, picked_up
        state = "game took the file" if picked_up else "file was never picked up (withdrawn)"
        super().__init__(f"no ack for id={cmd_id} seq={seq} within {timeout:g}s ({state})")


class WaitTimeout(DevbridgeTimeout):
    """wait_for() did not see a matching line in time."""


class GameGone(DevbridgeError):
    """The alive() callback reported that the game process is gone."""


class CommandIgnored(DevbridgeError):
    """The game logged ev=cmd_dup for our file: its seq was <= the game's last_seq (never executed)."""

    def __init__(self, cmd_id: str, seq: int, last_seq: int):
        self.id, self.seq, self.last_seq = cmd_id, seq, last_seq
        super().__init__(f"id={cmd_id} seq={seq} ignored as duplicate (game last_seq={last_seq}); .seq counter was behind")


# ---- line format ---------------------------------------------------------------------------

_WS = " \t\r\n\v\f"


def _scan(s: str, strict: bool) -> list[tuple[str, int]]:
    """Shell-like split. Returns (token, eq) pairs; eq = index of the first unquoted '=' or -1.

    Quotes may appear anywhere in a token; inside quotes \\" -> " and \\\\ -> \\, any other
    backslash is literal. Outside quotes backslashes are literal.
    """
    out: list[tuple[str, int]] = []
    i, n = 0, len(s)
    while True:
        while i < n and s[i] in _WS:
            i += 1
        if i >= n:
            break
        buf: list[str] = []
        inq = False
        eq = -1
        while i < n:
            c = s[i]
            if inq:
                if c == "\\" and i + 1 < n and s[i + 1] in '"\\':
                    buf.append(s[i + 1])
                    i += 2
                    continue
                if c == '"':
                    inq = False
                    i += 1
                    continue
                buf.append(c)
                i += 1
            else:
                if c in _WS:
                    break
                if c == '"':
                    inq = True
                    i += 1
                    continue
                if c == "=" and eq < 0:
                    eq = len(buf)
                buf.append(c)
                i += 1
        if inq and strict:
            raise ValueError("unterminated quote")
        out.append(("".join(buf), eq))
    return out


def tokenize(s: str) -> list[str]:
    """Split a command line the way the game does (raises ValueError on an unterminated quote)."""
    return [t for t, _ in _scan(s, strict=True)]


def _sanitize(v: object) -> str:
    return "".join(" " if (ord(c) < 0x20 or ord(c) == 0x7F) else c for c in str(v))


def _quoted(s: str) -> str:
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'


def quote(v: object) -> str:
    """Quote a log value exactly like DevbridgeQuote (C++): empty, space, '"' or '=' -> quoted."""
    s = _sanitize(v)
    if s == "" or any(c in ' "=' for c in s):
        return _quoted(s)
    return s


def quote_arg(v: object) -> str:
    """Quote a command argument: only empty, whitespace or '"' need quotes (so k=v stays bare)."""
    s = _sanitize(v)
    if s == "" or any(c in ' "' for c in s):
        return _quoted(s)
    return s


def parse_line(s: str) -> Optional[dict]:
    """Parse a HARNESS line -> {"t", "wall", "words", "kv"}; None if it has no HARNESS marker.

    The marker may be preceded by other text (e.g. a logger prefix in FLSpew).
    """
    s = s.rstrip("\r\n")
    m = MARKER_RE.search(s)
    if not m:
        return None
    t: Optional[float] = None
    wall: Optional[int] = None
    words: list[str] = []
    kv: dict[str, str] = {}
    for idx, (tok, eq) in enumerate(_scan(s[m.end():], strict=False)):
        if eq > 0:
            k, v = tok[:eq], tok[eq + 1:]
            if idx == 0 and k == "t":
                try:
                    t = float(v)
                except ValueError:
                    t = None
                continue
            if idx == 1 and k == "wall" and wall is None:
                try:
                    wall = int(v)
                except ValueError:
                    wall = None
                continue
            kv[k] = v
        else:
            words.append(tok)
    return {"t": t, "wall": wall, "words": words, "kv": kv}


def cmd_file_name(seq: int) -> str:
    return f"cmd-{seq:0{SEQ_WIDTH}d}.txt"


def tmp_file_name(seq: int) -> str:
    return f".tmp-cmd-{seq:0{SEQ_WIDTH}d}"


# ---- client --------------------------------------------------------------------------------


@dataclasses.dataclass
class Response:
    ok: bool
    id: str
    kv: dict
    err: Optional[str]
    data: list  # parsed data lines (dicts from parse_line, plus "line")
    line: str  # the raw ack line
    seq: int = 0
    end: int = 0  # log offset just after the ack line (use as since= for follow-up waits)


class Devbridge:
    """Client for one devbridge directory (<HDE>/SAVE/devbridge)."""

    def __init__(self, dir: Union[str, os.PathLike], since: Union[int, str] = 0, poll_s: float = 0.02):
        self.dir = os.fspath(dir)
        self.log_path = os.path.join(self.dir, LOG_NAME)
        self.poll_s = poll_s
        self.base = self.offset() if since == "end" else int(since)

    # -- log reading --

    def offset(self) -> int:
        """Current size of log.txt in bytes (0 if it does not exist yet)."""
        try:
            return os.path.getsize(self.log_path)
        except OSError:
            return 0

    def _read_complete(self, off: int) -> tuple[list[tuple[str, int]], int]:
        """Complete lines from byte offset off -> ([(line, end_offset)], new_offset)."""
        try:
            with open(self.log_path, "rb") as f:
                size = os.fstat(f.fileno()).st_size
                if size < off:  # truncated or recreated
                    off = 0
                f.seek(off)
                chunk = f.read()
        except OSError:
            return [], off
        out: list[tuple[str, int]] = []
        pos = 0
        while True:
            nl = chunk.find(b"\n", pos)
            if nl < 0:
                break
            raw = chunk[pos:nl]
            pos = nl + 1
            out.append((raw.decode("utf-8", "replace").rstrip("\r"), off + pos))
        return out, off + pos

    def lines(self, since: int = 0) -> list[str]:
        """All complete lines from byte offset since."""
        return [line for line, _ in self._read_complete(since)[0]]

    def _follow(self, since: int, timeout: float, alive: Optional[Callable[[], bool]]) -> Iterator[tuple[str, int]]:
        """Yield (line, end) as lines arrive; raises DevbridgeTimeout / GameGone."""
        deadline = time.monotonic() + timeout
        off = since
        while True:
            batch, off = self._read_complete(off)
            yield from batch
            if alive is not None and not alive():
                batch, off = self._read_complete(off)  # last chance for lines written before exit
                yield from batch
                raise GameGone("game process is gone")
            if time.monotonic() >= deadline:
                raise DevbridgeTimeout(f"timeout after {timeout:g}s")
            time.sleep(self.poll_s)

    # -- commands --

    def _next_seq_locked(self) -> int:
        counter = 0
        try:
            with open(os.path.join(self.dir, SEQ_NAME), encoding="ascii") as f:
                counter = int(f.read().strip() or 0)
        except (OSError, ValueError):
            counter = 0
        top = 0
        try:
            names = os.listdir(self.dir)
        except OSError:
            names = []
        for n in names:
            m = CMD_RE.match(n) or TMP_RE.match(n)
            if m:
                top = max(top, int(m.group(1)))
        return max(counter, top) + 1

    def bump_seq(self, floor: int) -> None:
        """Raise the .seq counter to at least floor (e.g. the game's last_seq)."""
        os.makedirs(self.dir, exist_ok=True)
        with open(os.path.join(self.dir, SEQ_LOCK_NAME), "a+") as lock:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
            try:
                if self._next_seq_locked() - 1 < floor:
                    self._write_counter(floor)
            finally:
                fcntl.flock(lock.fileno(), fcntl.LOCK_UN)

    def _write_counter(self, value: int) -> None:
        seq_path = os.path.join(self.dir, SEQ_NAME)
        with open(seq_path + ".tmp", "w", encoding="ascii") as f:
            f.write(f"{value}\n")
        os.replace(seq_path + ".tmp", seq_path)

    def submit(self, text: str, id: Optional[str] = None) -> tuple[int, str, int]:
        """Write one command file atomically; returns (seq, id, log offset taken before writing).

        text is "<verb> [args...]" exactly as it should appear after the id (not re-quoted).
        Allocation, the temp write and the rename all happen under an flock on .seq.lock, so files
        from concurrent clients appear in seq order.
        """
        text = text.strip()
        if not text or "\n" in text or "\r" in text:
            raise ValueError("command text must be one non-empty line")
        if id is not None and not ID_RE.match(id):
            raise ValueError(f"bad id {id!r}: must match {ID_RE.pattern}")
        os.makedirs(self.dir, exist_ok=True)
        start = self.offset()
        with open(os.path.join(self.dir, SEQ_LOCK_NAME), "a+") as lock:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
            try:
                seq = self._next_seq_locked()
                cmd_id = id or f"h{seq}"
                self._write_counter(seq)
                tmp = os.path.join(self.dir, tmp_file_name(seq))
                with open(tmp, "w", encoding="utf-8", newline="\n") as f:
                    f.write(f"{cmd_id} {text}\n")
                    f.flush()
                    os.fsync(f.fileno())
                os.replace(tmp, os.path.join(self.dir, cmd_file_name(seq)))
            finally:
                fcntl.flock(lock.fileno(), fcntl.LOCK_UN)
        return seq, cmd_id, start

    def wait_ack(self, cmd_id: str, since: int, timeout: float = 30.0, seq: int = 0,
                 alive: Optional[Callable[[], bool]] = None) -> Response:
        """Collect data lines for cmd_id and return at its ack line.

        Raises AckTimeout (the file is withdrawn if the game never took it), GameGone, or
        CommandIgnored if the game reports our file (seq) as a duplicate.
        """
        data: list[dict] = []
        dup_name = cmd_file_name(seq) if seq else None
        try:
            for line, end in self._follow(since, timeout, alive):
                p = parse_line(line)
                if not p:
                    continue
                if dup_name and p["kv"].get("ev") == "cmd_dup" and p["kv"].get("file") == dup_name:
                    try:
                        last = int(p["kv"].get("last_seq", "0"))
                    except ValueError:
                        last = 0
                    raise CommandIgnored(cmd_id, seq, last)
                if not p["words"] or p["kv"].get("id") != cmd_id:
                    continue
                if p["words"][0] == "data":
                    data.append(dict(p, line=line))
                elif p["words"][0] == "ack":
                    kv = p["kv"]
                    return Response(ok=kv.get("ok") == "1", id=cmd_id, kv=kv, err=kv.get("err"), data=data,
                                    line=line, seq=seq, end=end)
        except DevbridgeTimeout:
            picked_up = True
            if seq:
                try:
                    os.remove(os.path.join(self.dir, cmd_file_name(seq)))
                    picked_up = False
                except FileNotFoundError:
                    picked_up = True
                except OSError:
                    picked_up = True
            raise AckTimeout(cmd_id, seq, timeout, picked_up) from None
        raise AssertionError("unreachable")

    def send_line(self, text: str, timeout: float = 30.0, id: Optional[str] = None,
                  alive: Optional[Callable[[], bool]] = None) -> Response:
        """Send "<verb> [args...]" verbatim and wait for its ack.

        If the game ignores the file as a duplicate (our .seq counter was behind its last_seq),
        the counter is raised and the command is resubmitted once; the ignored copy never ran.
        """
        seq, cmd_id, start = self.submit(text, id=id)
        try:
            return self.wait_ack(cmd_id, start, timeout=timeout, seq=seq, alive=alive)
        except CommandIgnored as e:
            self.bump_seq(e.last_seq)
            seq, cmd_id, start = self.submit(text, id=id)
            return self.wait_ack(cmd_id, start, timeout=timeout, seq=seq, alive=alive)

    def send(self, verb: str, *args: object, timeout: float = 30.0, id: Optional[str] = None,
             alive: Optional[Callable[[], bool]] = None) -> Response:
        """Send verb with args (each quoted as needed) and wait for its ack."""
        if not verb or any(c in _WS + '"' for c in verb):
            raise ValueError(f"bad verb {verb!r}")
        text = " ".join([verb] + [quote_arg(a) for a in args])
        return self.send_line(text, timeout=timeout, id=id, alive=alive)

    # -- waiting --

    def wait_for(self, pattern: Union[str, Pattern, Callable[[dict], bool]], timeout: float = 30.0,
                 since: Optional[int] = None, alive: Optional[Callable[[], bool]] = None) -> dict:
        """Wait for a line: a regex (searched in the raw line) or a predicate(parsed dict).

        Returns the parsed dict (empty fields for non-HARNESS lines) plus "line" and "end".
        """
        start = self.base if since is None else since
        if callable(pattern) and not isinstance(pattern, (str, re.Pattern)):
            pred = pattern

            def match(line: str, p: Optional[dict]) -> bool:
                return p is not None and bool(pred(p))
        else:
            rx = re.compile(pattern) if isinstance(pattern, str) else pattern

            def match(line: str, p: Optional[dict]) -> bool:
                return rx.search(line) is not None
        try:
            for line, end in self._follow(start, timeout, alive):
                p = parse_line(line)
                if match(line, p):
                    base = p if p is not None else {"t": None, "wall": None, "words": [], "kv": {}}
                    return dict(base, line=line, end=end)
        except DevbridgeTimeout:
            raise WaitTimeout(f"no line matching {pattern!r} within {timeout:g}s") from None
        raise AssertionError("unreachable")

    def wait_ready(self, timeout: float = 60.0, since: Optional[int] = None,
                   alive: Optional[Callable[[], bool]] = None) -> dict:
        """Wait for ev=devbridge_ready (from offset since, default self.base).

        Also raises the .seq counter to the game's reported last_seq, so new commands are never
        mistaken for stale ones.
        """
        ready = self.wait_for(lambda p: p["kv"].get("ev") == "devbridge_ready", timeout=timeout, since=since,
                              alive=alive)
        try:
            self.bump_seq(int(ready["kv"].get("last_seq", "0")))
        except ValueError:
            pass
        return ready


# ---- CLI -----------------------------------------------------------------------------------


class _Parser(argparse.ArgumentParser):
    def error(self, message):  # usage errors must not collide with exit 2 (timeout)
        self.print_usage(sys.stderr)
        sys.stderr.write(f"{self.prog}: error: {message}\n")
        sys.exit(EXIT_USAGE)


def lane_dir(lane: Union[int, str], locks: Optional[str] = None) -> str:
    """FL_DEVBRIDGE_DIR from <locks>/lane-<N>.env (export lines written by harness/lane.sh)."""
    locks = locks or os.environ.get("FLMOD_LOCKS") or DEFAULT_LOCKS
    path = os.path.join(locks, f"lane-{lane}.env")
    with open(path, encoding="utf-8") as f:
        for raw in f:
            toks = shlex.split(raw, comments=True)
            if toks and toks[0] == "export":
                toks = toks[1:]
            for tok in toks:
                if tok.startswith("FL_DEVBRIDGE_DIR="):
                    return tok.split("=", 1)[1]
    raise DevbridgeError(f"FL_DEVBRIDGE_DIR not found in {path}")


def _alive_pid(pid: Optional[int]) -> Optional[Callable[[], bool]]:
    if not pid:
        return None

    def alive() -> bool:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return False
        except PermissionError:
            return True
        return True
    return alive


def _print_response(r: Response) -> None:
    for d in r.data:
        print(d["line"])
    print(r.line)
    sys.stdout.flush()


def _split_send_args(words: list[str]) -> tuple[list[str], dict]:
    """Pull --timeout/--id/--pid out of send's words (anywhere before a literal --)."""
    opts: dict = {}
    pos: list[str] = []
    i = 0
    while i < len(words):
        w = words[i]
        if w == "--":
            pos.extend(words[i + 1:])
            break
        name, eq, val = w.partition("=")
        if name in ("--timeout", "--id", "--pid"):
            if not eq:
                if i + 1 >= len(words):
                    raise ValueError(f"{name} needs a value")
                val = words[i + 1]
                i += 1
            opts[name[2:]] = val
        else:
            pos.append(w)
        i += 1
    return pos, opts


def main(argv: Optional[list[str]] = None) -> int:
    ap = _Parser(prog="devbridge.py", description="Devbridge client (protocol v1).")
    where = ap.add_mutually_exclusive_group()
    where.add_argument("--dir", help="devbridge directory (<HDE>/SAVE/devbridge)")
    where.add_argument("--lane", help="lane number: read FL_DEVBRIDGE_DIR from the lane env file")
    ap.add_argument("--since", default="0", help="log byte offset for wait/wait-ready/tail, or 'end' (default 0)")
    sub = ap.add_subparsers(dest="cmd", required=True, parser_class=_Parser)
    sp = sub.add_parser("send", help="send one command and print its data + ack lines")
    sp.add_argument("--timeout", type=float, default=None)
    sp.add_argument("--id", default=None)
    sp.add_argument("--pid", type=int, default=None)
    sp.add_argument("words", nargs=argparse.REMAINDER, help="<verb> [args...] [--timeout S] [--id ID] [--pid P]")
    wr = sub.add_parser("wait-ready", help="wait for ev=devbridge_ready")
    wr.add_argument("--timeout", type=float, default=60.0)
    wr.add_argument("--pid", type=int)
    wt = sub.add_parser("wait", help="wait for a log line matching a regex")
    wt.add_argument("regex")
    wt.add_argument("--timeout", type=float, default=30.0)
    wt.add_argument("--pid", type=int)
    rf = sub.add_parser("run-file", help="send each command of a file, waiting for each ack")
    rf.add_argument("file")
    rf.add_argument("--timeout", type=float, default=30.0, help="per command")
    rf.add_argument("--keep-going", action="store_true")
    rf.add_argument("--pid", type=int)
    tl = sub.add_parser("tail", help="print log lines")
    tl.add_argument("--follow", "-f", action="store_true")
    sub.add_parser("offset", help="print the current log size (use as --since later)")
    a = ap.parse_args(argv)

    try:
        if a.dir:
            d = a.dir
        elif a.lane:
            d = lane_dir(a.lane)
        elif os.environ.get("FL_DEVBRIDGE_DIR"):
            d = os.environ["FL_DEVBRIDGE_DIR"]
        else:
            ap.error("need --dir, --lane or $FL_DEVBRIDGE_DIR")
        if a.since != "end":
            try:
                int(a.since)
            except ValueError:
                ap.error("--since must be an integer offset or 'end'")
        db = Devbridge(d, since=a.since)

        if a.cmd == "send":
            try:
                words, opts = _split_send_args(a.words)
                for k in ("timeout", "id", "pid"):
                    if getattr(a, k) is not None:
                        opts.setdefault(k, getattr(a, k))
                timeout = float(opts.get("timeout", 30.0))
                pid = int(opts["pid"]) if "pid" in opts else None
            except ValueError as e:
                ap.error(str(e))
            if not words:
                ap.error("send needs a verb")
            r = db.send(words[0], *words[1:], timeout=timeout, id=opts.get("id"), alive=_alive_pid(pid))
            _print_response(r)
            return EXIT_OK if r.ok else EXIT_FAIL

        if a.cmd == "wait-ready":
            print(db.wait_ready(a.timeout, alive=_alive_pid(a.pid))["line"])
            return EXIT_OK

        if a.cmd == "wait":
            print(db.wait_for(a.regex, a.timeout, alive=_alive_pid(a.pid))["line"])
            return EXIT_OK

        if a.cmd == "run-file":
            failed = False
            with open(a.file, encoding="utf-8") as f:
                cmds = [ln.strip() for ln in f]
            for text in cmds:
                if not text or text.startswith("#"):
                    continue
                r = db.send_line(text, timeout=a.timeout, alive=_alive_pid(a.pid))
                _print_response(r)
                if not r.ok:
                    failed = True
                    if not a.keep_going:
                        break
            return EXIT_FAIL if failed else EXIT_OK

        if a.cmd == "tail":
            off = db.base
            while True:
                batch, off = db._read_complete(off)
                for line, _ in batch:
                    print(line)
                sys.stdout.flush()
                if not a.follow:
                    return EXIT_OK
                time.sleep(0.2)

        if a.cmd == "offset":
            print(db.offset())
            return EXIT_OK
    except DevbridgeTimeout as e:
        print(f"devbridge: {e}", file=sys.stderr)
        return EXIT_TIMEOUT
    except GameGone as e:
        print(f"devbridge: {e}", file=sys.stderr)
        return EXIT_GONE
    except KeyboardInterrupt:
        return EXIT_OK
    except (DevbridgeError, OSError, ValueError) as e:
        print(f"devbridge: {e}", file=sys.stderr)
        return EXIT_FAIL
    return EXIT_USAGE


if __name__ == "__main__":
    sys.exit(main())
