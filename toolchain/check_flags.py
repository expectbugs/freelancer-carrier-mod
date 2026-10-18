#!/usr/bin/env python3
"""Static check of the win32 compile flags in compile_commands.json (CI stage 10; review r2 F2).

usage: python3 -I toolchain/check_flags.py <compile_commands.json>... [--json out.json]

Every clang-cl translation unit (C and C++; resource-compiler entries are ignored) must have:
  - /clang:-mstackrealign (or -mstackrealign) with no later -mno-stackrealign     (toolchain/ABI.md §6.3)
  - the release DLL runtime: the last of /MD /MDd /MT /MTd is /MD                 (ABI.md §1)
  - -D_ITERATOR_DEBUG_LEVEL=0 as the last _ITERATOR_DEBUG_LEVEL definition          (ABI.md §1, FLUF must-match)
and every C++ TU (-TP, or a C++ extension without -TC) must have /EHa as its last /EH flag (ABI.md §6.1, §6.2).
Flags may be spelled with '/' or '-'. Exit: 0 all TUs clean, 1 a violation (or no clang-cl TU at all), 2 usage.
No Wine, no build: it only reads the JSON CMake wrote.
"""

from __future__ import annotations

import argparse
import json
import shlex
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path

CXX_EXTS = {".cpp", ".cc", ".cxx", ".c++", ".cp"}
C_EXTS = {".c"}


@dataclass
class Unit:
    file: str
    lang: str
    problems: list[str] = field(default_factory=list)


def tokens_of(entry: dict) -> list[str]:
    if "arguments" in entry:
        return list(entry["arguments"])
    return shlex.split(entry["command"])


def norm(tok: str) -> str:
    """'/EHa' and '-EHa' -> '-EHa'; '/clang:-mfoo' -> '-mfoo'."""
    if tok.startswith("/clang:"):
        return tok[len("/clang:"):]
    if tok.startswith("-clang:"):
        return tok[len("-clang:"):]
    if tok.startswith("/"):
        return "-" + tok[1:]
    return tok


def is_clang_cl(toks: list[str]) -> bool:
    return bool(toks) and Path(toks[0]).name.lower() in ("clang-cl", "clang-cl.exe")


def language(toks: list[str], filename: str) -> str:
    lang = None
    for t in map(norm, toks):
        if t == "-TP":
            lang = "c++"
        elif t == "-TC":
            lang = "c"
    if lang:
        return lang
    ext = Path(filename).suffix.lower()
    if ext in C_EXTS:
        return "c"
    return "c++" if ext in CXX_EXTS else "unknown"


def last(toks: list[str], choices: set[str]) -> str | None:
    found = None
    for t in toks:
        if t in choices:
            found = t
    return found


def check_unit(entry: dict) -> Unit | None:
    toks = tokens_of(entry)
    if not is_clang_cl(toks):
        return None
    n = [norm(t) for t in toks[1:]]
    u = Unit(file=entry.get("file", "?"), lang=language(toks[1:], entry.get("file", "")))
    if last(n, {"-mstackrealign", "-mno-stackrealign"}) != "-mstackrealign":
        u.problems.append("missing /clang:-mstackrealign (or overridden by -mno-stackrealign)")
    rt = last(n, {"-MD", "-MDd", "-MT", "-MTd"})
    if rt != "-MD":
        u.problems.append(f"runtime flag is {rt or 'absent'}, want /MD")
    idl = [t for t in n if t.startswith("-D_ITERATOR_DEBUG_LEVEL")]
    if not idl or idl[-1] != "-D_ITERATOR_DEBUG_LEVEL=0":
        u.problems.append(f"_ITERATOR_DEBUG_LEVEL is {idl[-1] if idl else 'not defined'}, want -D_ITERATOR_DEBUG_LEVEL=0")
    if u.lang == "c++":
        eh = [t for t in n if t.startswith("-EH")]
        if not eh or eh[-1] != "-EHa":
            u.problems.append(f"last /EH flag is {eh[-1] if eh else 'absent'}, want /EHa")
    elif u.lang == "unknown":
        u.problems.append("cannot tell whether this TU is C or C++")
    return u


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("compile_commands", nargs="+", type=Path)
    ap.add_argument("--json", type=Path, default=None, help="also write the per-TU results as JSON")
    args = ap.parse_args(argv)

    ok = True
    report: dict[str, list[dict]] = {}
    for cc in args.compile_commands:
        try:
            entries = json.loads(cc.read_text())
        except (OSError, ValueError) as e:
            print(f"check_flags: cannot read {cc}: {e}", file=sys.stderr)
            return 2
        units = [u for u in (check_unit(e) for e in entries) if u is not None]
        bad = [u for u in units if u.problems]
        n_cxx = sum(1 for u in units if u.lang == "c++")
        report[str(cc)] = [asdict(u) for u in units]
        if not units:
            print(f"check_flags: {cc}: FAIL: no clang-cl translation units found")
            ok = False
            continue
        for u in bad:
            for p in u.problems:
                print(f"check_flags: {cc}: {u.file}: {p}")
        status = "FAIL" if bad else "OK"
        print(f"check_flags: {cc}: {status}: {len(units)} clang-cl TUs ({n_cxx} C++, {len(units) - n_cxx} C), "
              f"{len(bad)} with problems")
        ok = ok and not bad
    if args.json:
        args.json.write_text(json.dumps(report, indent=1))
    print(f"check_flags: {'PASS' if ok else 'FAIL'}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
