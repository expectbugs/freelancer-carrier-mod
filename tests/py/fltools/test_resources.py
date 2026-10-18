"""fltools.peres (read) and fltools.resdll (build) -- resource DLLs and IDS."""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from fltools import peres, resdll
from fltools.install import Install

LLVM = resdll.LLVM_BIN
STRINGS = {1: "Carrier Test Name", 2: 'Osiris-class "Carrier" \\ 100%%', 17: "Block two",
           40000: "Ünïcødé – ok"}
CARDS = {100: resdll.rdl_from_text("Hello & <world>\n\nSecond paragraph.")}


def _readobj(path: Path) -> str:
    tool = LLVM / "llvm-readobj"
    if not tool.is_file():
        pytest.skip(f"{tool} not available")
    return subprocess.run([str(tool), "--file-headers", "--coff-resources", str(path)],
                          check=True, capture_output=True, text=True).stdout


def test_build_python_backend_reads_back(tmp_path):
    p = resdll.write_dll(tmp_path / "fcm_text.dll", STRINGS, CARDS)
    r = peres.ResourceDll(p)
    assert r.strings == STRINGS and r.html == CARDS
    assert r.pe.is_i386 and r.pe.is_dll and r.pe.entry_point == 0
    assert r.raw_html(100)[:2] == b"\xff\xfe"
    assert all(k[2] == resdll.LANG_EN_US for k in r.pe.resources)
    out = _readobj(p)
    assert "IMAGE_FILE_MACHINE_I386" in out
    assert "IMAGE_FILE_DLL" in out
    assert "STRINGTABLE" in out and "HTML" in out


def test_acceptance_two_strings_one_infocard(tmp_path):
    p = resdll.write_dll(tmp_path / "t.dll", {1: "one", 2: "two"},
                         {3: "<RDL><PUSH/><TEXT>card</TEXT><PARA/><POP/></RDL>"})
    r = peres.ResourceDll(p)
    assert r.strings == {1: "one", 2: "two"}
    assert r.html == {3: "<RDL><PUSH/><TEXT>card</TEXT><PARA/><POP/></RDL>"}


def test_python_backend_is_deterministic():
    assert resdll.build_dll(STRINGS, CARDS) == resdll.build_dll(STRINGS, CARDS)


@pytest.mark.skipif(not resdll.llvm_available(), reason="llvm-rc / lld-link not installed")
def test_llvm_backend_matches_python_backend(tmp_path):
    a = peres.ResourceDll(resdll.write_dll(tmp_path / "py.dll", STRINGS, CARDS))
    b = peres.ResourceDll(resdll.write_dll(tmp_path / "llvm.dll", STRINGS, CARDS, backend="llvm"))
    assert b.strings == a.strings and b.html == a.html
    assert {k: v for k, v in b.pe.resources.items()} == {k: v for k, v in a.pe.resources.items()}
    assert b.pe.is_i386 and b.pe.is_dll


def test_infocard_validation():
    with pytest.raises(ValueError):
        resdll.build_dll({}, {1: "<RDL><TEXT>unclosed</RDL>"})
    with pytest.raises(ValueError):
        resdll.build_dll({}, {1: "<HTML/>"})
    with pytest.raises(ValueError):
        resdll.build_dll({70000: "x"})
    assert "&amp; &lt;" in resdll.rdl_from_text("& <")


def test_ids_resolution_matches_r3(install, r3json):
    """IDS -> text through the [Resources] order agrees with R3's independent extraction for
    every system name, base name and faction name it recorded (values read at test time)."""
    ids = peres.IdsResolver.from_install(install)
    assert ids.names[0].lower() == "resources.dll"
    sysf = r3json("systems_full.json")["systems"]
    checked = 0
    for s in sysf.values():
        if s["strid_name"]:
            assert ids.name(s["strid_name"]) == s["name"]
            checked += 1
    for b in r3json("bases.json").values():
        if b["strid_name"]:
            assert ids.name(b["strid_name"]) == b["name"]
            checked += 1
    groups = r3json("factions.json")["groups"]
    for g in groups.values():
        if g["ids_name"] and g["ids_name"] != "0":
            assert ids.name(int(g["ids_name"])) == g["name"]
            checked += 1
    assert checked > 250
    li01 = sysf["li01"]            # the R3 §1.2 example: universe strid_name -> system name
    assert ids.name(li01["strid_name"]) == li01["name"]
    assert ids.names[li01["strid_name"] >> 16] in install.resource_dll_names()


def test_ids_out_of_range(install):
    ids = peres.IdsResolver.from_install(install)
    assert not ids.in_range(ids.count * 65536 + 1)
    assert ids.lookup(ids.count * 65536 + 1) == (None, None)


def test_detect_resource_index_hde(install):
    assert len(install.resource_dll_names()) == resdll.HDE_RESOURCE_COUNT
    assert resdll.detect_resource_index(install) == 8


def test_detect_resource_index_fails_loudly(mini_install):
    from fltools import ini
    fini = ini.ci_path(mini_install, "EXE/freelancer.ini")
    doc = ini.load(fini)
    doc.section("Resources").add("DLL", "OtherMod.dll")
    doc.dump(fini)
    with pytest.raises(resdll.ResourceIndexError, match="OtherMod.dll"):
        resdll.detect_resource_index(Install(mini_install))
    assert resdll.detect_resource_index(Install(mini_install), expected=None) == 9
    doc.section("Resources").add("DLL", "fcm_text.dll")
    doc.dump(fini)
    assert resdll.detect_resource_index(Install(mini_install), "fcm_text.dll", expected=9) == 9


def test_read_hde_dlls_counts(install, research):
    """Totals equal R3's independent dump (R3 §1.2 states them; read at test time)."""
    import re
    txt = (research / "R3-game-data.md").read_text(encoding="utf-8")
    m = re.search(r"dumps all ([\d,]+) strings \+ ([\d,]+) infocards", txt)
    if not m:
        pytest.skip("R3 string/infocard totals not found")
    ids = peres.IdsResolver.from_install(install)
    assert len(ids.all_strings()) == int(m.group(1).replace(",", ""))
    assert len(ids.all_html()) == int(m.group(2).replace(",", ""))
    assert all(h.lstrip().startswith("<RDL>") for h in list(ids.all_html().values())[:200])
