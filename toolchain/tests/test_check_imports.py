"""Tests for toolchain/check_imports.py.

Self-contained: a fake llvm-readobj prints canned output stored next to each fake binary
(<file>.imports.txt / .exports.txt / .headers.txt), and the Wine prefix is a temp dir.
Run: $FLMOD_VENV/bin/python -I -m pytest toolchain/tests -q
"""

from __future__ import annotations

import importlib.util
import sys
import textwrap
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location("check_imports", HERE.parent / "check_imports.py")
ci = importlib.util.module_from_spec(SPEC)
sys.modules["check_imports"] = ci
SPEC.loader.exec_module(ci)

FAKE_READOBJ = textwrap.dedent(
    """\
    #!/usr/bin/env python3
    import pathlib, sys
    flag, path = sys.argv[1], sys.argv[2]
    suffix = {"--coff-imports": ".imports.txt", "--coff-exports": ".exports.txt",
              "--file-headers": ".headers.txt"}[flag]
    p = pathlib.Path(path + suffix)
    sys.stdout.write(p.read_text() if p.exists() else "")
    """
)

I386 = "ImageFileHeader {\n  Machine: IMAGE_FILE_MACHINE_I386 (0x14C)\n}\n"
AMD64 = "ImageFileHeader {\n  Machine: IMAGE_FILE_MACHINE_AMD64 (0x8664)\n}\n"


def imports_text(mods: dict[str, list[str]], delay: set[str] | None = None) -> str:
    out = []
    for name, syms in mods.items():
        kind = "DelayImport" if delay and name in delay else "Import"
        out.append(f"{kind} {{\n  Name: {name}\n  ImportLookupTableRVA: 0x1000\n")
        for s in syms:
            if s.startswith("#"):
                out.append(f"  Symbol:  ({s[1:]})\n")
            else:
                out.append(f"  Symbol: {s} (7)\n")
        out.append("}\n")
    return "".join(out)


def exports_text(names: list[str], ordinals: list[int] | None = None) -> str:
    out = []
    for i, n in enumerate(names, start=1):
        out.append(f"Export {{\n  Ordinal: {i}\n  Name: {n}\n  RVA: 0x10\n}}\n")
    for o in ordinals or []:
        out.append(f"Export {{\n  Ordinal: {o}\n  Name: \n  RVA: 0x20\n}}\n")
    return "".join(out)


def make_pe(path: Path, *, headers: str = I386, imports: str = "", exports: str = "") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"MZ")
    (path.parent / (path.name + ".headers.txt")).write_text(headers)
    (path.parent / (path.name + ".imports.txt")).write_text(imports)
    (path.parent / (path.name + ".exports.txt")).write_text(exports)
    return path


@pytest.fixture()
def env(tmp_path: Path):
    readobj = tmp_path / "fake-readobj"
    readobj.write_text(FAKE_READOBJ)
    readobj.chmod(0o755)
    prefix = tmp_path / "prefix-dev-test"
    sys64 = prefix / "drive_c" / "windows" / "syswow64"
    make_pe(sys64 / "vcruntime140.dll", exports=exports_text(["_except_handler4_common", "memset"]))
    make_pe(sys64 / "msvcp140.dll", exports=exports_text(["?_Xlength_error@std@@YAXPBD@Z"], ordinals=[42]))
    make_pe(sys64 / "ucrtbase.dll", exports=exports_text(["_initterm", "fopen", "malloc"]))
    exe = prefix / "drive_c" / "Games" / "Freelancer HD Edition" / "EXE"
    make_pe(exe / "Common.dll", exports=exports_text(["?CreateID@@YAIPBD@Z"]))
    return {"tmp": tmp_path, "readobj": str(readobj), "prefix": prefix, "sys64": sys64}


def run(env, binaries, *extra) -> int:
    return ci.main([*map(str, binaries), "--prefix", str(env["prefix"]), "--readobj", env["readobj"], *extra])


def good_imports() -> dict[str, list[str]]:
    return {
        "common.dll": ["?CreateID@@YAIPBD@Z"],
        "KERNEL32.dll": ["DisableThreadLibraryCalls"],
        "VCRUNTIME140.dll": ["_except_handler4_common"],
        "MSVCP140.dll": ["?_Xlength_error@std@@YAXPBD@Z", "#42"],
        "api-ms-win-crt-runtime-l1-1-0.dll": ["_initterm"],
        "api-ms-win-crt-stdio-l1-1-0.dll": ["fopen"],
    }


def test_clean_dll_passes(env, capsys):
    dll = make_pe(env["tmp"] / "out" / "hello_b.dll", imports=imports_text(good_imports()))
    assert run(env, [dll]) == 0
    out = capsys.readouterr().out
    assert "check_imports: PASS" in out
    assert "1/1 symbols exported by drive_c/Games/Freelancer HD Edition/EXE/Common.dll" in out


def test_module_outside_allowlist_fails(env, capsys):
    mods = good_imports() | {"IMM32.dll": ["ImmGetContext"]}
    dll = make_pe(env["tmp"] / "out" / "bad.dll", imports=imports_text(mods))
    assert run(env, [dll]) == 1
    out = capsys.readouterr().out
    assert "NOT ALLOWED" in out and "IMM32.dll" in out
    assert "check_imports: FAIL" in out


def test_delay_import_outside_allowlist_fails(env, capsys):
    mods = good_imports() | {"dwmapi.dll": ["DwmEnableBlurBehindWindow"]}
    dll = make_pe(env["tmp"] / "out" / "bad.dll", imports=imports_text(mods, delay={"dwmapi.dll"}))
    assert run(env, [dll]) == 1
    assert "dwmapi.dll (delay)" in capsys.readouterr().out


def test_missing_msvcp140_symbol_fails(env, capsys):
    mods = good_imports()
    mods["MSVCP140.dll"] = ["?_Xlength_error@std@@YAXPBD@Z", "__std_brand_new_thing_1"]
    dll = make_pe(env["tmp"] / "out" / "new_stl.dll", imports=imports_text(mods))
    assert run(env, [dll]) == 1
    out = capsys.readouterr().out
    assert "MISSING new_stl.dll -> MSVCP140.dll: __std_brand_new_thing_1" in out


def test_missing_ordinal_fails(env, capsys):
    mods = good_imports()
    mods["MSVCP140.dll"] = ["#43"]
    dll = make_pe(env["tmp"] / "out" / "ord.dll", imports=imports_text(mods))
    assert run(env, [dll]) == 1
    assert "MSVCP140.dll: #43" in capsys.readouterr().out


def test_missing_required_crt_dll_fails(env, capsys):
    mods = good_imports() | {"msvcp140_atomic_wait.dll": ["__std_atomic_wait_direct"]}
    dll = make_pe(env["tmp"] / "out" / "aw.dll", imports=imports_text(mods))
    assert run(env, [dll]) == 1
    assert "reference DLL missing" in capsys.readouterr().out


def test_missing_ucrt_symbol_fails(env, capsys):
    mods = good_imports()
    mods["api-ms-win-crt-stdio-l1-1-0.dll"] = ["fopen", "_not_in_wine"]
    dll = make_pe(env["tmp"] / "out" / "crt.dll", imports=imports_text(mods))
    assert run(env, [dll]) == 1
    assert "api-ms-win-crt-stdio-l1-1-0.dll: _not_in_wine" in capsys.readouterr().out


def test_missing_game_symbol_fails(env, capsys):
    mods = good_imports()
    mods["common.dll"] = ["?CreateID@@YAIPBD@Z", "?NotInHde@@YAXXZ"]
    dll = make_pe(env["tmp"] / "out" / "game.dll", imports=imports_text(mods))
    assert run(env, [dll]) == 1
    assert "common.dll: ?NotInHde@@YAXXZ" in capsys.readouterr().out


def test_fluf_needs_flag_and_is_symbol_checked(env, capsys):
    fluf = make_pe(env["tmp"] / "fluf" / "FLUF.dll", exports=exports_text(["?GetLogger@Fluf@@SAXXZ"]))
    mods = good_imports() | {"FLUF.dll": ["?GetLogger@Fluf@@SAXXZ"]}
    dll = make_pe(env["tmp"] / "out" / "hello_a.dll", imports=imports_text(mods))
    assert run(env, [dll]) == 1
    assert "needs --allow-fluf" in capsys.readouterr().out
    assert run(env, [dll], "--allow-fluf", "--fluf-dll", str(fluf)) == 0
    mods["FLUF.dll"].append("?Missing@Fluf@@SAXXZ")
    (dll.parent / (dll.name + ".imports.txt")).write_text(imports_text(mods))
    assert run(env, [dll], "--allow-fluf", "--fluf-dll", str(fluf)) == 1


def test_non_i386_fails(env, capsys):
    dll = make_pe(env["tmp"] / "out" / "x64.dll", headers=AMD64, imports=imports_text(good_imports()))
    assert run(env, [dll]) == 1
    assert "not a PE32 i386 image" in capsys.readouterr().out


def test_bad_prefix_is_usage_error(env, tmp_path):
    dll = make_pe(env["tmp"] / "out" / "hello_b.dll", imports=imports_text(good_imports()))
    assert ci.main([str(dll), "--prefix", str(tmp_path / "nope"), "--readobj", env["readobj"]]) == 2


def test_json_report(env, tmp_path):
    dll = make_pe(env["tmp"] / "out" / "hello_b.dll", imports=imports_text(good_imports()))
    report = tmp_path / "r.json"
    assert run(env, [dll], "--json", str(report)) == 0
    import json

    data = json.loads(report.read_text())
    assert data["result"] == "PASS"
    assert data["binaries"][0]["ok"] is True


def test_parse_imports_handles_delay_and_ordinals():
    text = imports_text({"a.dll": ["f", "#3"], "b.dll": ["g"]}, delay={"b.dll"})
    mods = ci.parse_imports(text)
    assert [(m.name, m.delay, m.symbols) for m in mods] == [("a.dll", False, ["f", "#3"]), ("b.dll", True, ["g"])]
