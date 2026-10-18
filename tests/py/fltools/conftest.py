"""Shared fixtures for the fltools / generator-framework tests.

Game data is never committed: tests that need the local HDE install, the research extracts or
golden files skip with a reason when they are absent (GitHub Actions has none of them).

The ``hde`` fixture is a READ-ONLY VIEW, never the play install itself: once per session the
files the tests read (EXE INIs, ``.fl`` and DLLs; DATA INIs and ``.cmp/.3db/.sph`` models) are
cloned into a session temp dir (reflink via ``FICLONE`` on XFS, so it costs no data blocks) and
chmod'ed read-only. A test that writes must copy what it needs into ``tmp_path`` first; a stray
write into the view fails with PermissionError instead of touching Adam's install.
"""
from __future__ import annotations

import fcntl
import json
import os
import shutil
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
for _p in (str(REPO / "tools"), str(REPO)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

FLMOD_LOCAL = Path(os.environ.get("FLMOD_LOCAL", "/home/user/freelancer/carrier-mod/local"))
RESEARCH = Path(os.environ.get("FLMOD_RESEARCH", str(FLMOD_LOCAL / "research")))
HDE_SOURCE = Path(os.environ.get(
    "FLMOD_HDE", "/home/user/freelancer/prefix/drive_c/Games/Freelancer HD Edition"))
VIEW_EXTS = {"EXE": (".ini", ".fl", ".dll"), "DATA": (".ini", ".cmp", ".3db", ".sph")}
FICLONE = 0x40049409


def _clone(src: Path, dst: Path) -> None:
    """Reflink ``src`` to ``dst`` (read-only open of the source); plain copy if unsupported."""
    with open(src, "rb") as fs, open(dst, "wb") as fd:
        try:
            fcntl.ioctl(fd.fileno(), FICLONE, fs.fileno())
            return
        except OSError:
            pass
    shutil.copyfile(src, dst)


def _set_tree_writable(root: Path, writable: bool) -> None:
    for dp, dns, fns in os.walk(root):
        for fn in fns:
            os.chmod(os.path.join(dp, fn), 0o644 if writable else 0o444)
        os.chmod(dp, 0o755 if writable else 0o555)


def _build_view(src: Path, view: Path) -> None:
    for top, exts in VIEW_EXTS.items():
        base = next((src / n for n in os.listdir(src) if n.upper() == top), None)
        if base is None:
            continue
        for dp, _dns, fns in os.walk(base):
            for fn in fns:
                if fn.lower().endswith(exts):
                    s = Path(dp) / fn
                    d = view / s.relative_to(src)
                    d.parent.mkdir(parents=True, exist_ok=True)
                    _clone(s, d)
            if top == "EXE":
                break           # EXE: top level only


@pytest.fixture(scope="session", autouse=True)
def _private_locks(tmp_path_factory):
    """Deploy/undeploy and the text-id map take flocks under ``$FLMOD_LOCKS``; tests (and the
    subprocesses they start, which inherit os.environ) use a private dir, never the shared
    one."""
    with pytest.MonkeyPatch.context() as mp:
        mp.setenv("FLMOD_LOCKS", str(tmp_path_factory.mktemp("locks")))
        yield


@pytest.fixture(scope="session")
def hde(tmp_path_factory) -> Path:
    if not (HDE_SOURCE / "EXE" / "freelancer.ini").is_file():
        pytest.skip(f"local HDE install not found at {HDE_SOURCE} (set FLMOD_HDE)")
    view = tmp_path_factory.mktemp("hde-ro") / HDE_SOURCE.name
    _build_view(HDE_SOURCE, view)
    _set_tree_writable(view, False)
    yield view
    _set_tree_writable(view, True)      # let pytest clean its temp dirs


@pytest.fixture(scope="session")
def install(hde):
    from fltools.install import Install
    return Install(hde)


@pytest.fixture(scope="session")
def r3() -> Path:
    d = RESEARCH / "R3-data"
    if not (d / "system_graph.json").is_file():
        pytest.skip(f"R3 research extracts not found under {d}")
    return d


@pytest.fixture(scope="session")
def r3json(r3):
    cache = {}

    def load(name):
        if name not in cache:
            cache[name] = json.loads((r3 / name).read_text(encoding="utf-8"))
        return cache[name]
    return load


@pytest.fixture(scope="session")
def research() -> Path:
    if not RESEARCH.is_dir():
        pytest.skip(f"research dir not found at {RESEARCH}")
    return RESEARCH


@pytest.fixture(scope="session")
def world(install):
    from fltools import worldexport
    return worldexport.export(install)


def copy_tree_files(src_root: Path, rels: list[str], dst_root: Path) -> None:
    for rel in rels:
        s = src_root / rel
        d = dst_root / rel
        d.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(s, d)


@pytest.fixture
def mini_install(hde, tmp_path) -> Path:
    """A tiny writable install: copies of EXE/freelancer.ini, EXE/dacom.ini and a few DATA
    INIs (the real ones, copied into tmp_path), plus an empty DATA tree otherwise."""
    from fltools.ini import ci_path
    root = tmp_path / "hde"
    rels = []
    for rel in ("EXE/freelancer.ini", "EXE/dacom.ini", "EXE/newplayer.fl",
                "DATA/EQUIPMENT/market_ships.ini", "DATA/MISSIONS/npcships.ini",
                "DATA/UNIVERSE/universe.ini"):
        p = ci_path(hde, rel)
        if p is not None:
            rels.append(os.path.relpath(p, hde))
    copy_tree_files(hde, rels, root)
    (root / "DATA").mkdir(exist_ok=True)
    return root


# --- synthetic install (no game data; our own placeholder text) -------------------------------
SYNTH_FREELANCER_INI = (
    "[Freelancer]\r\n"
    "data path = ..\\DATA\r\n"
    "\r\n"
    "[Resources]\r\n"
    + "".join(f"DLL = synth_res{i}.dll\r\n" for i in range(1, 8))      # 7 like HDE -> index 8
    + "\r\n"
    "[Data]\r\n"
    "equipment = equipment\\synth_equip.ini\r\n"
    "goods = equipment\\synth_goods.ini\r\n"
    "markets = equipment\\market_synth.ini\r\n"
)
SYNTH_FILES = {
    "EXE/freelancer.ini": SYNTH_FREELANCER_INI,
    "DATA/EQUIPMENT/synth_equip.ini": "[Engine]\r\nnickname = synth_engine\r\n",
    "DATA/EQUIPMENT/synth_goods.ini": "[Good]\r\nnickname = synth_engine\r\n",
    "DATA/EQUIPMENT/market_synth.ini": ("[BaseGood]\r\nbase = synth_base\r\n"
                                        "marketgood = synth_engine, 0, -1, 1, 1, 0, 1\r\n"),
}


def make_synth_install(root: Path) -> Path:
    """A minimal install tree the generator framework can build and deploy against."""
    for rel, text in SYNTH_FILES.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(text.encode("latin-1"))
    return root


@pytest.fixture
def synth_install(tmp_path) -> Path:
    return make_synth_install(tmp_path / "synth")


@pytest.fixture
def make_synth():
    """``make_synth(root)`` builds another synthetic install (tests never import conftest)."""
    return make_synth_install


@pytest.fixture
def snap():
    """``snap(root)``: :func:`tree_state` as a fixture."""
    return tree_state


def tree_state(root: Path) -> dict[str, bytes | None]:
    """Every path under ``root``: file -> bytes, directory -> None (so new dirs show too)."""
    out: dict[str, bytes | None] = {}
    for p in sorted(Path(root).rglob("*")):
        rel = p.relative_to(root).as_posix()
        out[rel] = p.read_bytes() if p.is_file() and not p.is_symlink() else None
    return out
