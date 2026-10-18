"""deploy.py's dacom.ini [Libraries] entry as the fltools patch unit `harness.dacom` (D107, review r1 m11).

Synthetic dacom.ini only (our own minimal text, no game file). Checks: apply, idempotent re-apply, byte-exact
removal, the legacy pre-D107 block is dropped, and a gen overlay redeploy (fltools.patch.apply_overlay_patches)
keeps the harness unit.
"""
import os
import sys
from pathlib import Path

HARNESS = Path(__file__).resolve().parents[1]
REPO = HARNESS.parent
sys.path.insert(0, str(HARNESS / "lib"))
sys.path.insert(0, str(REPO / "tools"))

import deploy  # noqa: E402
from fltools import patch as flpatch  # noqa: E402

DACOM = (
    "[DACOM]\r\n"
    "IgnoreDACOMEnv = true\r\n"
    "\r\n"
    "[Libraries]\r\n"
    "ReadFile.dll\r\n"
    "x86math.dll\r\n"
    "EngBase.dll\r\n"
    "\r\n"
)


def mk(tmp_path, text=DACOM):
    hde = tmp_path / "hde"
    (hde / "EXE").mkdir(parents=True)
    (hde / "EXE" / "dacom.ini").write_bytes(text.encode("latin-1"))
    return hde


def test_apply_reapply_remove(tmp_path):
    hde = mk(tmp_path)
    p = hde / "EXE" / "dacom.ini"
    deploy.dacom_block(hde, ["devbridge_selftest.dll"], REPO)
    t1 = p.read_bytes()
    s = t1.decode("latin-1")
    assert "; >>> carrier-mod harness.dacom v1" in s and "; <<< carrier-mod harness.dacom" in s
    assert deploy.dacom_listed(hde, ["devbridge_selftest.dll"]) == []
    # the entry sits inside [Libraries], after the existing entries and before the blank line that ends it
    lines = s.split("\r\n")
    i = lines.index("devbridge_selftest.dll")
    assert lines.index("EngBase.dll") < i and lines.index("[Libraries]") < i
    deploy.dacom_block(hde, ["devbridge_selftest.dll"], REPO)  # idempotent
    assert p.read_bytes() == t1
    deploy.dacom_block(hde, [], REPO)  # removal restores the original bytes and drops the patch state
    assert p.read_bytes() == DACOM.encode("latin-1")
    assert not (hde / flpatch.STATE_NAME).exists()
    assert deploy.dacom_listed(hde, ["devbridge_selftest.dll"]) == ["devbridge_selftest.dll"]


def test_legacy_block_is_dropped(tmp_path):
    legacy = DACOM.replace("EngBase.dll\r\n", "EngBase.dll\r\n; >>> carrier-mod\r\nold.dll\r\n; <<< carrier-mod\r\n")
    hde = mk(tmp_path, legacy)
    deploy.dacom_block(hde, ["new.dll"], REPO)
    s = (hde / "EXE" / "dacom.ini").read_text(encoding="latin-1")
    assert "old.dll" not in s and "new.dll" in s
    assert deploy.dacom_listed(hde, ["old.dll", "new.dll"]) == ["old.dll"]


def test_gen_overlay_redeploy_keeps_the_harness_unit(tmp_path):
    hde = mk(tmp_path)
    deploy.dacom_block(hde, ["devbridge_selftest.dll"], REPO)
    gen_unit = {"file": "EXE/dacom.ini", "id": "gen.test", "version": 1,
                "ops": [{"op": "append", "section": "DACOM", "lines": ["; gen was here"]}]}
    flpatch.apply_overlay_patches(hde, [gen_unit], log=lambda *_: None)
    s = (hde / "EXE" / "dacom.ini").read_text(encoding="latin-1")
    assert "; gen was here" in s and "devbridge_selftest.dll" in s
    flpatch.apply_overlay_patches(hde, [], log=lambda *_: None)  # gen undeploys its own unit only
    assert deploy.dacom_listed(hde, ["devbridge_selftest.dll"]) == []
    assert "; gen was here" not in (hde / "EXE" / "dacom.ini").read_text(encoding="latin-1")
