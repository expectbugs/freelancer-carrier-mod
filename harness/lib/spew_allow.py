#!/usr/bin/env python3
"""FLSpew allow-lists (REQ-P0-HARNESS-15). Format: harness/baseline/README.md.

Library:
  normalize(line)          strip CR/LF, the flplusplus `[YYYY-MM-DD HH:MM:SS] ` prefix and trailing blanks
  is_error_line(nline)     True for ERROR/WARNING/FATAL/ASSERT lines (`: ERROR:General:`, `*** WARNING: ...`)
  line_to_pattern(nline)   short anchored regex for one normalized line
  build_allow(files)       patterns for every ERROR/WARNING line in the given FLSpew files (deduped, ordered)
  load_allow(path)         compiled patterns from an allow file (bad regexes are reported, not fatal)
  new_errors(spew, pats)   normalized ERROR/WARNING lines of a spew file that no pattern matches

CLI:
  spew_allow.py build --out <file> [--merge] <FLSpew files...>
  spew_allow.py check --allow <file> <FLSpew files...>    (exit 1 if any line is not allowed)
"""
from __future__ import annotations

import argparse
import datetime
import os
import re
import sys

# `[2026-10-17 23:23:08] ` added by flplusplus (log.cpp fdump_timestamped); optional fraction for safety.
# flplusplus prefix `[YYYY-MM-DD HH:MM:SS] `; with FLUF (Track A) FLSpew lines get a second, outer prefix
# `[YYYY/MM/DD - HH:MM:SS] ` (observed 2026-10-18). Both are stripped (any order, up to 3 times).
_TS_RE = re.compile(r"^\[\d{4}[-/]\d{2}[-/]\d{2}(?: - | )\d{2}:\d{2}:\d{2}(?:[.,]\d+)?\]\s?")
# `<src path>(<line>) : ` source location; the first such separator in the line.
_LOC_RE = re.compile(r"^(?P<loc>.*?)\((?P<ln>\d+)\) : ")
_FILE_OK_RE = re.compile(r"^[\w.\- ]+$")
_SEV_START_RE = re.compile(r"^(?:\*{3}\s*)?(?:ERROR|WARNING|FATAL|ASSERT)\b")
_SEV_ANY_RE = re.compile(r"\*{3}\s*(?:ERROR|WARNING|FATAL|ASSERT)\b")
# Volatile tokens: hex pointers (0x... or 8+ hex digits) first, then standalone decimal numbers.
_TOKEN_RE = re.compile(
    r"(?P<hex>(?<![0-9A-Za-z_])(?:0[xX][0-9A-Fa-f]+|[0-9A-Fa-f]{8,})(?![0-9A-Za-z_]))"
    r"|(?P<dec>(?<![0-9A-Za-z_])-?\d+(?:\.\d+)*)"
)
_HEX_PAT = r"[0-9A-Fa-fx]+"
_REGEX_SPECIAL = set("\\.^$*+?{}[]|()")
MAX_REST = 120  # source characters of the message kept before the pattern is truncated (no `$` then)

# Always allowed, whatever the allow file says: VERIFIED benign on this install (R4 §B8).
BUILTIN_ALLOW = (r"StreamingSound: missing MP3 codec\?$",)


def normalize(line: str) -> str:
    """Strip line ending, the flplusplus timestamp prefix and trailing whitespace."""
    s = line.rstrip("\r\n")
    for _ in range(3):
        s2 = _TS_RE.sub("", s, count=1)
        if s2 == s:
            break
        s = s2
    return s.rstrip()


def _split_loc(nline: str):
    """Return (source file basename or None, rest of line after `(<n>) : `)."""
    m = _LOC_RE.match(nline)
    if m:
        loc = m.group("loc")
        fname = re.split(r"[\\/]+", loc)[-1].strip()
        if fname and " : " not in loc and not loc.lstrip().startswith("*") and _FILE_OK_RE.match(fname):
            return fname, nline[m.end():]
    return None, nline


def is_error_line(nline: str) -> bool:
    _, rest = _split_loc(nline)
    return bool(_SEV_START_RE.match(rest) or _SEV_ANY_RE.search(nline))


def _escape(s: str) -> str:
    return "".join("\\" + c if c in _REGEX_SPECIAL else c for c in s)


def _rest_pattern(rest: str) -> str:
    out = []
    used = 0  # source characters consumed
    pos = 0
    truncated = False
    for m in _TOKEN_RE.finditer(rest):
        lit = rest[pos:m.start()]
        if used + len(lit) > MAX_REST:
            out.append(_escape(lit[: max(0, MAX_REST - used)].rstrip()))
            truncated = True
            break
        out.append(_escape(lit))
        used += len(lit)
        tok = m.group(0)
        if m.group("hex"):
            out.append(_HEX_PAT)
        else:
            out.append(("-?" if tok.startswith("-") else "") + (r"[\d.]+" if "." in tok else r"\d+"))
        used += len(tok)
        pos = m.end()
        if used > MAX_REST:
            truncated = pos < len(rest)
            break
    else:
        lit = rest[pos:]
        if used + len(lit) > MAX_REST:
            out.append(_escape(lit[: max(0, MAX_REST - used)].rstrip()))
            truncated = True
        else:
            out.append(_escape(lit))
    pat = "".join(out)
    return pat if truncated else pat + "$"


def line_to_pattern(nline: str) -> str:
    """Short anchored regex for a normalized spew line (matched with re.search)."""
    fname, rest = _split_loc(nline)
    head = "^.*" + _escape(fname) + r"\(\d+\) : " if fname else "^"
    return head + _rest_pattern(rest)


def _read_lines(path):
    with open(path, "r", encoding="utf-8", errors="replace", newline="") as f:
        for line in f:
            yield line


def iter_error_lines(path):
    """Yield normalized ERROR/WARNING lines of one spew file (missing file -> nothing)."""
    if not path or not os.path.isfile(path):
        return
    for raw in _read_lines(path):
        n = normalize(raw)
        if n and is_error_line(n):
            yield n


def build_allow(files) -> list:
    """Patterns for all ERROR/WARNING lines found in `files` (list of paths), deduped, first-seen order."""
    seen = set()
    pats = []
    for path in files:
        for n in iter_error_lines(path):
            p = line_to_pattern(n)
            if p not in seen:
                seen.add(p)
                pats.append(p)
    return pats


def read_allow_lines(path) -> list:
    """(lineno, pattern text) for every non-blank, non-comment line of an allow file."""
    out = []
    for i, raw in enumerate(_read_lines(path), 1):
        s = raw.strip()
        if s and not s.startswith("#"):
            out.append((i, s))
    return out


def load_allow(path, errors=None, builtin=True) -> list:
    """Compiled patterns from an allow file (plus BUILTIN_ALLOW). Bad regexes are appended to `errors`."""
    pats = [re.compile(p) for p in BUILTIN_ALLOW] if builtin else []
    if path and os.path.isfile(path):
        for ln, s in read_allow_lines(path):
            try:
                pats.append(re.compile(s))
            except re.error as e:
                if errors is not None:
                    errors.append(f"{path}:{ln}: bad regex ({e}): {s}")
    return pats


def is_allowed(nline: str, patterns) -> bool:
    return any(p.search(nline) for p in patterns)


def new_errors(spew_path, patterns) -> list:
    """Unique normalized ERROR/WARNING lines of `spew_path` not matched by any pattern (first-seen order)."""
    seen = set()
    out = []
    for n in iter_error_lines(spew_path):
        if n not in seen:
            seen.add(n)
            if not is_allowed(n, patterns):
                out.append(n)
    return out


def _cmd_build(a) -> int:
    pats = build_allow(a.spew)
    kept = []
    if a.merge and os.path.isfile(a.out):
        kept = [s for _, s in read_allow_lines(a.out)]
    allp = list(dict.fromkeys(kept + pats))
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    nfiles = sum(1 for p in a.spew if os.path.isfile(p))
    header = [
        "# FLSpew allow-list: one Python regex per line, re.search against the normalized line.",
        "# Format and regeneration: harness/baseline/README.md",
        f"# generated {stamp} by harness/lib/spew_allow.py build from {nfiles} spew file(s)"
        + (f"; merged with {len(kept)} existing pattern(s)" if a.merge else ""),
    ]
    tmp = a.out + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(header + allp) + "\n")
    os.replace(tmp, a.out)
    print(f"spew_allow: wrote {len(allp)} pattern(s) ({len(pats)} from spew) to {a.out}")
    return 0


def _cmd_check(a) -> int:
    errs = []
    pats = load_allow(a.allow, errs)
    for e in errs:
        print(f"spew_allow: {e}", file=sys.stderr)
    bad = 0
    for path in a.spew:
        for n in new_errors(path, pats):
            print(f"{path}: {n}")
            bad += 1
    print(f"spew_allow: {bad} line(s) not allowed")
    return 1 if bad else 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="spew_allow.py", description="FLSpew allow-list tool")
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build", help="derive patterns from FLSpew files")
    b.add_argument("--out", required=True)
    b.add_argument("--merge", action="store_true", help="keep the patterns already in --out")
    b.add_argument("spew", nargs="+")
    c = sub.add_parser("check", help="list ERROR/WARNING lines not matched by an allow file")
    c.add_argument("--allow", required=True)
    c.add_argument("spew", nargs="+")
    a = ap.parse_args(argv)
    return _cmd_build(a) if a.cmd == "build" else _cmd_check(a)


if __name__ == "__main__":
    sys.exit(main())
