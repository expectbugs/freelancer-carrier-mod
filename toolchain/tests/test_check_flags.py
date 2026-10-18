"""Tests for toolchain/check_flags.py (static compile_commands.json check, CI stage 10).

Run: $FLMOD_VENV/bin/python -I -m pytest toolchain/tests -q
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location("check_flags", HERE.parent / "check_flags.py")
cf = importlib.util.module_from_spec(SPEC)
sys.modules["check_flags"] = cf
SPEC.loader.exec_module(cf)

CL = "/usr/lib/llvm/22/bin/clang-cl --target=i686-pc-windows-msvc /nologo"
GOOD_COMMON = '/winsysroot "/x w/xwin" -gdwarf /utf-8 -D_ITERATOR_DEBUG_LEVEL=0 /clang:-mstackrealign -MD'


def entry(file: str, flags: str, compiler: str = CL) -> dict:
    return {"directory": "/b", "file": file, "command": f"{compiler} {flags} /Fo{file}.obj -c {file}"}


def run(tmp_path: Path, entries: list[dict], capsys) -> tuple[int, str]:
    p = tmp_path / "compile_commands.json"
    p.write_text(json.dumps(entries))
    rc = cf.main([str(p)])
    return rc, capsys.readouterr().out


def test_good_cxx_and_c_pass(tmp_path, capsys):
    rc, out = run(tmp_path, [entry("a.cpp", f"-TP {GOOD_COMMON} /EHa"), entry("b.c", GOOD_COMMON)], capsys)
    assert rc == 0, out
    assert "2 clang-cl TUs (1 C++, 1 C)" in out


def test_missing_stackrealign_fails(tmp_path, capsys):
    flags = GOOD_COMMON.replace("/clang:-mstackrealign", "")
    rc, out = run(tmp_path, [entry("a.cpp", f"-TP {flags} /EHa")], capsys)
    assert rc == 1
    assert "a.cpp: missing /clang:-mstackrealign" in out


def test_later_mno_stackrealign_fails(tmp_path, capsys):
    rc, out = run(tmp_path, [entry("a.cpp", f"-TP {GOOD_COMMON} /EHa /clang:-mno-stackrealign")], capsys)
    assert rc == 1
    assert "overridden" in out


def test_cxx_with_later_ehsc_fails(tmp_path, capsys):
    rc, out = run(tmp_path, [entry("a.cpp", f"-TP {GOOD_COMMON} /EHa /EHsc")], capsys)
    assert rc == 1
    assert "last /EH flag is -EHsc" in out


def test_cxx_without_eh_fails_but_c_without_eh_passes(tmp_path, capsys):
    rc, out = run(tmp_path, [entry("a.cpp", f"-TP {GOOD_COMMON}"), entry("b.c", GOOD_COMMON)], capsys)
    assert rc == 1
    assert "a.cpp: last /EH flag is absent" in out
    assert "b.c:" not in out


def test_c_file_compiled_as_cxx_needs_eha(tmp_path, capsys):
    rc, out = run(tmp_path, [entry("yyjson.c", f"-TP {GOOD_COMMON}")], capsys)
    assert rc == 1
    assert "yyjson.c: last /EH flag is absent" in out


def test_debug_runtime_and_iterator_level_fail(tmp_path, capsys):
    flags = GOOD_COMMON.replace("-MD", "-MDd").replace("_ITERATOR_DEBUG_LEVEL=0", "_ITERATOR_DEBUG_LEVEL=2")
    rc, out = run(tmp_path, [entry("a.cpp", f"-TP {flags} /EHa")], capsys)
    assert rc == 1
    assert "runtime flag is -MDd" in out
    assert "_ITERATOR_DEBUG_LEVEL is -D_ITERATOR_DEBUG_LEVEL=2" in out


def test_resource_compiler_entries_are_ignored(tmp_path, capsys):
    rc_entry = {"directory": "/b", "file": "x.rc", "command": "/usr/bin/cmake -E cmake_llvm_rc x.rc x.res"}
    rc, out = run(tmp_path, [entry("a.cpp", f"-TP {GOOD_COMMON} /EHa"), rc_entry], capsys)
    assert rc == 0, out
    assert "1 clang-cl TUs" in out


def test_no_clang_cl_units_fails(tmp_path, capsys):
    host = {"directory": "/b", "file": "a.cpp", "command": "/usr/lib/llvm/22/bin/clang++ -c a.cpp"}
    rc, out = run(tmp_path, [host], capsys)
    assert rc == 1
    assert "no clang-cl translation units" in out


def test_arguments_form_is_supported(tmp_path, capsys):
    e = {"directory": "/b", "file": "a.cpp",
         "arguments": ["/usr/lib/llvm/22/bin/clang-cl", "-TP", "-MD", "-D_ITERATOR_DEBUG_LEVEL=0",
                       "/clang:-mstackrealign", "/EHa", "-c", "a.cpp"]}
    rc, out = run(tmp_path, [e], capsys)
    assert rc == 0, out


def test_unreadable_file_is_usage_error(tmp_path):
    assert cf.main([str(tmp_path / "missing.json")]) == 2
