#!/usr/bin/env python3
"""check_imports.py: prove that built DLLs only import what Wine-proton 11 + Freelancer provide.

Usage (run with python3 -I):
    toolchain/check_imports.py <dll|exe>... --prefix <wineprefix> [--allow-fluf] [--json out.json]

Checks, per binary:
  1. It is a PE32 i386 image.
  2. Every imported module (normal and delay-load) is on the allowlist:
       Freelancer's DLLs  common server dalib dacom remoteclient rp8 (+ FLUF.dll with --allow-fluf)
       MSVC runtime       msvcp140*.dll vcruntime140*.dll api-ms-win-crt-*.dll
       Win32              kernel32 user32 gdi32 advapi32 ws2_32 d3d9 dsound ole32 oleaut32 shell32
                          winmm version psapi dbghelp
  3. Every imported msvcp140*/vcruntime140* DLL (msvcp140, vcruntime140, msvcp140_atomic_wait, msvcp140_1, ...)
     exists in <prefix>/drive_c/windows/syswow64/ (the Wine builtins), and every symbol imported from it is in
     that DLL's export table. A missing DLL (e.g. msvcp140d.dll) is a failure.
  4. api-ms-win-crt-* imports are checked against syswow64/ucrtbase.dll, which Wine's apisetschema
     maps the whole api-ms-win-crt-* set to.
  5. Imports from Freelancer's DLLs are checked against the game's own EXE dir (found under the
     prefix, or --game-exe-dir), and FLUF.dll imports against --fluf-dll (default: the pinned FLUF
     release in $FLMOD_VENDOR). Skipped with a note if the reference DLL is not found.

Exit status: 0 PASS, 1 FAIL, 2 usage or tool error. Prints a summary table.
Read-only: it never writes to the prefix.
"""

from __future__ import annotations

import argparse
import fnmatch
import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_READOBJ = "/usr/lib/llvm/22/bin/llvm-readobj"
DEFAULT_VENDOR = "/home/user/freelancer/carrier-mod/vendor"

FREELANCER_DLLS = {"common.dll", "server.dll", "dalib.dll", "dacom.dll", "remoteclient.dll", "rp8.dll"}
FLUF_DLLS = {"fluf.dll"}
SYSTEM_DLLS = {
    f"{n}.dll"
    for n in (
        "kernel32", "user32", "gdi32", "advapi32", "ws2_32", "d3d9", "dsound", "ole32", "oleaut32",
        "shell32", "winmm", "version", "psapi", "dbghelp",
    )
}
CRT_PATTERNS = ("msvcp140*.dll", "vcruntime140*.dll", "api-ms-win-crt-*.dll")


@dataclass
class ImportedModule:
    name: str
    delay: bool = False
    symbols: list[str] = field(default_factory=list)  # names; ordinal-only imports as "#<n>"


@dataclass
class ModuleResult:
    module: str
    category: str
    count: int
    status: str  # OK | FAIL | NOTE
    detail: str = ""
    missing: list[str] = field(default_factory=list)


@dataclass
class BinaryResult:
    path: str
    ok: bool = True
    machine: str = ""
    errors: list[str] = field(default_factory=list)
    modules: list[ModuleResult] = field(default_factory=list)


class ToolError(Exception):
    pass


def run_readobj(readobj: str, args: list[str]) -> str:
    try:
        proc = subprocess.run([readobj, *args], capture_output=True, text=True, check=False)
    except FileNotFoundError as e:
        raise ToolError(f"llvm-readobj not found: {readobj}") from e
    if proc.returncode != 0:
        raise ToolError(f"{readobj} {' '.join(args)} failed: {proc.stderr.strip()}")
    return proc.stdout


_SYMBOL_RE = re.compile(r"^\s*Symbol:\s*(.*?)\s*\((\d+)\)\s*$")


def parse_imports(text: str) -> list[ImportedModule]:
    """Parse `llvm-readobj --coff-imports` output.

    Normal imports are flat `Import { Name: …  Symbol: … }` blocks. llvm-readobj 22 prints each delay-loaded module
    as `DelayImport { Name: … Import { Symbol: … Address: … } Import { … } }`: one nested `Import {}` per symbol.
    """
    mods: list[ImportedModule] = []
    stack: list[str] = []          # open block kinds, outermost first
    cur: ImportedModule | None = None
    for line in text.splitlines():
        s = line.strip()
        if s.endswith("{"):
            kind = s[:-1].strip()
            if not stack and kind in ("Import", "DelayImport"):
                cur = ImportedModule(name="", delay=(kind == "DelayImport"))
                mods.append(cur)
            stack.append(kind)
            continue
        if s == "}":
            if stack:
                stack.pop()
            if not stack:
                cur = None
            continue
        if cur is None:
            continue
        if s.startswith("Name:") and len(stack) == 1 and not cur.name:
            cur.name = s.split(":", 1)[1].strip()
            continue
        m = _SYMBOL_RE.match(line)
        if m:
            name, hint_or_ordinal = m.group(1), m.group(2)
            cur.symbols.append(name if name else f"#{hint_or_ordinal}")
    return [m for m in mods if m.name]


def parse_exports(text: str) -> tuple[set[str], set[str]]:
    """Parse `llvm-readobj --coff-exports` output into (names, '#ordinal' strings)."""
    names: set[str] = set()
    ordinals: set[str] = set()
    for line in text.splitlines():
        s = line.strip()
        if s.startswith("Name:"):
            v = s.split(":", 1)[1].strip()
            if v:
                names.add(v)
        elif s.startswith("Ordinal:"):
            v = s.split(":", 1)[1].strip()
            if v:
                ordinals.add(f"#{v}")
    return names, ordinals


def parse_machine(text: str) -> str:
    for line in text.splitlines():
        s = line.strip()
        if s.startswith("Machine:"):
            return s.split(":", 1)[1].strip()
    return ""


def categorize(module: str, allow_fluf: bool) -> str | None:
    m = module.lower()
    if m in FREELANCER_DLLS:
        return "freelancer"
    if m in FLUF_DLLS:
        return "fluf" if allow_fluf else None
    if m in SYSTEM_DLLS:
        return "system"
    if any(fnmatch.fnmatch(m, p) for p in CRT_PATTERNS):
        return "crt"
    return None


def find_case_insensitive(directory: Path, filename: str) -> Path | None:
    if not directory.is_dir():
        return None
    p = directory / filename
    if p.is_file():
        return p
    want = filename.lower()
    for child in directory.iterdir():
        if child.name.lower() == want and child.is_file():
            return child
    return None


def find_game_exe_dir(prefix: Path) -> Path | None:
    drive_c = prefix / "drive_c"
    candidates: list[Path] = []
    for pattern in ("Games/*/EXE", "Program Files*/*/EXE", "Program Files*/*/*/EXE"):
        candidates.extend(sorted(drive_c.glob(pattern)))
    for c in candidates:
        if find_case_insensitive(c, "common.dll"):
            return c
    return None


class ExportCache:
    def __init__(self, readobj: str):
        self.readobj = readobj
        self._cache: dict[Path, tuple[set[str], set[str]]] = {}

    def get(self, dll: Path) -> tuple[set[str], set[str]]:
        dll = dll.resolve()
        if dll not in self._cache:
            self._cache[dll] = parse_exports(run_readobj(self.readobj, ["--coff-exports", str(dll)]))
        return self._cache[dll]


def check_symbols(symbols: list[str], exports: tuple[set[str], set[str]]) -> list[str]:
    names, ordinals = exports
    return [s for s in symbols if (s not in ordinals if s.startswith("#") else s not in names)]


def check_binary(path: Path, args: argparse.Namespace, exports: ExportCache, syswow64: Path,
                 game_exe_dir: Path | None, fluf_dll: Path | None) -> BinaryResult:
    res = BinaryResult(path=str(path))
    if not path.is_file():
        res.ok = False
        res.errors.append("file not found")
        return res

    res.machine = parse_machine(run_readobj(args.readobj, ["--file-headers", str(path)]))
    if "I386" not in res.machine:
        res.ok = False
        res.errors.append(f"not a PE32 i386 image (Machine: {res.machine or 'unknown'})")

    imported = parse_imports(run_readobj(args.readobj, ["--coff-imports", str(path)]))
    # Merge normal and delay imports of the same module for reporting.
    merged: dict[str, ImportedModule] = {}
    for mod in imported:
        key = mod.name.lower()
        if key in merged:
            merged[key].symbols.extend(mod.symbols)
            merged[key].delay = merged[key].delay or mod.delay
        else:
            merged[key] = ImportedModule(name=mod.name, delay=mod.delay, symbols=list(mod.symbols))

    for key, mod in sorted(merged.items()):
        cat = categorize(key, args.allow_fluf)
        label = mod.name + (" (delay)" if mod.delay else "")
        n = len(mod.symbols)
        if cat is None:
            hint = " (FLUF.dll needs --allow-fluf)" if key in FLUF_DLLS else ""
            res.modules.append(ModuleResult(label, "NOT ALLOWED", n, "FAIL", f"module not on the allowlist{hint}"))
            res.ok = False
            continue

        ref: Path | None = None
        required = False
        if cat == "crt":
            if key.startswith("api-ms-win-crt-"):
                ref = find_case_insensitive(syswow64, "ucrtbase.dll")
                required = True
            else:
                # Any msvcp140*/vcruntime140* DLL must exist as a Wine builtin, or the load fails.
                ref = find_case_insensitive(syswow64, key)
                required = True
        elif cat == "freelancer":
            ref = find_case_insensitive(game_exe_dir, key) if game_exe_dir else None
        elif cat == "fluf":
            ref = fluf_dll if fluf_dll and fluf_dll.is_file() else None
        elif cat == "system":
            ref = None  # Wine builtins; the symbol check is out of scope for system DLLs.

        if ref is None:
            if required:
                res.modules.append(ModuleResult(label, cat, n, "FAIL", f"reference DLL missing in {syswow64}"))
                res.ok = False
            elif cat in ("freelancer", "fluf"):
                res.modules.append(ModuleResult(label, cat, n, "NOTE", "allowed; reference DLL not found, symbols not checked"))
            else:
                res.modules.append(ModuleResult(label, cat, n, "OK", "allowed"))
            continue

        missing = check_symbols(mod.symbols, exports.get(ref))
        found = n - len(missing)
        where = os.path.relpath(ref, args.prefix) if str(ref).startswith(str(args.prefix)) else str(ref)
        if missing:
            res.modules.append(ModuleResult(label, cat, n, "FAIL", f"{found}/{n} symbols exported by {where}", missing))
            res.ok = False
        else:
            res.modules.append(ModuleResult(label, cat, n, "OK", f"{found}/{n} symbols exported by {where}"))
    return res


def print_table(results: list[BinaryResult]) -> None:
    rows = [("BINARY", "IMPORTED MODULE", "CATEGORY", "SYMS", "STATUS", "DETAIL")]
    for r in results:
        name = Path(r.path).name
        for e in r.errors:
            rows.append((name, "-", "-", "-", "FAIL", e))
        for m in r.modules:
            rows.append((name, m.module, m.category, str(m.count), m.status, m.detail))
        if not r.errors and not r.modules:
            rows.append((name, "(no imports)", "-", "0", "OK", ""))
    widths = [max(len(row[i]) for row in rows) for i in range(5)]
    for row in rows:
        print("  ".join(row[i].ljust(widths[i]) for i in range(5)) + "  " + row[5])
    for r in results:
        for m in r.modules:
            for s in m.missing:
                print(f"MISSING {Path(r.path).name} -> {m.module}: {s}")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Check DLL imports against Wine-proton 11 and Freelancer.")
    ap.add_argument("binaries", nargs="+", type=Path, help="DLLs/EXEs to check")
    ap.add_argument("--prefix", required=True, type=Path, help="Wine prefix (read-only) with drive_c/windows/syswow64")
    ap.add_argument("--allow-fluf", action="store_true", help="allow FLUF.dll imports (Track A modules)")
    ap.add_argument("--fluf-dll", type=Path, default=None,
                    help="FLUF.dll to check FLUF imports against (default: $FLMOD_VENDOR/FLUF/EXE/fluf/FLUF.dll)")
    ap.add_argument("--game-exe-dir", type=Path, default=None,
                    help="Freelancer EXE dir to check Common.dll etc. imports against (default: found under the prefix)")
    ap.add_argument("--readobj", default=os.environ.get("FLMOD_READOBJ", DEFAULT_READOBJ))
    ap.add_argument("--json", type=Path, default=None, help="also write the results as JSON")
    args = ap.parse_args(argv)

    args.prefix = args.prefix.resolve()
    syswow64 = args.prefix / "drive_c" / "windows" / "syswow64"
    if not syswow64.is_dir():
        print(f"check_imports: {syswow64} does not exist (is --prefix a Wine prefix?)", file=sys.stderr)
        return 2
    game_exe_dir = args.game_exe_dir.resolve() if args.game_exe_dir else find_game_exe_dir(args.prefix)
    fluf_dll = args.fluf_dll
    if fluf_dll is None and args.allow_fluf:
        fluf_dll = Path(os.environ.get("FLMOD_VENDOR", DEFAULT_VENDOR)) / "FLUF" / "EXE" / "fluf" / "FLUF.dll"

    exports = ExportCache(args.readobj)
    try:
        results = [check_binary(b, args, exports, syswow64, game_exe_dir, fluf_dll) for b in args.binaries]
    except ToolError as e:
        print(f"check_imports: {e}", file=sys.stderr)
        return 2

    print(f"check_imports: prefix={args.prefix} syswow64={syswow64}")
    print(f"check_imports: game EXE dir={game_exe_dir or 'not found'}; FLUF.dll={'allowed: ' + str(fluf_dll) if args.allow_fluf else 'not allowed'}")
    print_table(results)
    ok = all(r.ok for r in results)
    print(f"check_imports: {'PASS' if ok else 'FAIL'} ({sum(r.ok for r in results)}/{len(results)} binaries clean)")

    if args.json:
        payload = {
            "prefix": str(args.prefix),
            "game_exe_dir": str(game_exe_dir) if game_exe_dir else None,
            "allow_fluf": args.allow_fluf,
            "result": "PASS" if ok else "FAIL",
            "binaries": [
                {
                    "path": r.path, "ok": r.ok, "machine": r.machine, "errors": r.errors,
                    "modules": [m.__dict__ for m in r.modules],
                }
                for r in results
            ],
        }
        args.json.write_text(json.dumps(payload, indent=2) + "\n")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
