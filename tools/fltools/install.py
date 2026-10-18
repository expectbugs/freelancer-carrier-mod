"""A Freelancer install, optionally combined with a candidate overlay, as one data tree.

An *overlay* (produced by ``gen/run.py build``) is a directory::

    <overlay>/MANIFEST.json
    <overlay>/files/<install-relative path>     new files, e.g. files/DATA/EQUIPMENT/fcm_x.ini
    <overlay>/patches.json                      {"units": [ fltools.patch units ]}

Reading through :class:`Install` with an overlay gives the *combined* view the game would see
after deploy: overlay files shadow/add to the install, and patch units are applied in memory.
The install itself is only read.

Paths: FL paths are case-insensitive with backslashes. ``data_path('Universe\\universe.ini')``
resolves under the data dir (``[Freelancer] data path`` of ``EXE/freelancer.ini``, i.e.
``..\\DATA``), ``exe_path(...)`` under ``EXE``.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from . import ini as _ini
from . import patch as _patch

__all__ = ["Install", "default_hde_root"]

# Content.dll hard-codes these (relative to DATA; R3 §1.1, VERIFIED by string scan).
CONTENT_HARDCODED = [
    r"missions\npcships.ini", r"missions\faction_prop.ini", r"missions\mBases.ini",
    r"missions\lootprops.ini", r"missions\pilots_population.ini", r"missions\pilots_story.ini",
    r"missions\shipclasses.ini", r"missions\formations.ini", r"missions\voice_properties.ini",
    r"missions\empathy.ini", r"missions\specific_npc.ini", r"missions\news.ini",
    r"missions\RankDiff.ini", r"missions\PTough.ini", r"equipment\commodities_per_faction.ini",
    r"Universe\systems_shortest_path.ini", r"Universe\shortest_legal_path.ini",
    r"Universe\shortest_illegal_path.ini",
]


def default_hde_root() -> Path:
    """``$FLMOD_HDE`` or the play install's HDE dir (read-only use only)."""
    env = os.environ.get("FLMOD_HDE")
    if env:
        return Path(env)
    return Path("/home/user/freelancer/prefix/drive_c/Games/Freelancer HD Edition")


def _norm(rel: str) -> str:
    return "/".join(p for p in rel.replace("\\", "/").lower().split("/") if p not in ("", "."))


DEPLOY_STATE = "carrier-mod.deploy.json"


class Install:
    """``pristine=True`` reads the install as it was before any carrier-mod deploy: every
    carrier-mod marker region is stripped on read and files a previous deploy copied in
    (``<root>/carrier-mod.deploy.json``) are hidden. Builds use it so their output never
    depends on whether the install was deployed before."""

    def __init__(self, root: str | os.PathLike, overlay: str | os.PathLike | None = None,
                 extra_units: list[dict] | None = None, pristine: bool = False):
        self.root = Path(root)
        if not self.root.is_dir():
            raise FileNotFoundError(f"install root {self.root} does not exist")
        self.resolver = _ini.CIResolver()
        self.overlay = Path(overlay) if overlay else None
        self.pristine = pristine
        self._hidden: set[str] = set()
        if pristine:
            ds = self.root / DEPLOY_STATE
            if ds.is_file():
                try:
                    files = json.loads(ds.read_text(encoding="utf-8")).get("files", {})
                except (OSError, ValueError, AttributeError) as e:
                    raise ValueError(f"deploy state {ds} is unreadable or corrupt: {e}") from None
                self._hidden = {_norm(k) for k in files}
        exe = self.resolver.resolve(self.root, "EXE")
        if exe is None:
            raise FileNotFoundError(f"no EXE dir under {self.root}")
        self.exe_dir = exe
        self._docs: dict[str, _ini.Document] = {}
        self._units_by_file: dict[str, list[dict]] = {}
        units = []
        if self.overlay is not None:
            pj = self.overlay / "patches.json"
            if pj.is_file():
                units = json.loads(pj.read_text(encoding="utf-8")).get("units", [])
        units += list(extra_units or [])
        for u in units:
            self._units_by_file.setdefault(_norm(u["file"]), []).append(u)
        fini = self.freelancer_ini()
        sec = fini.section("Freelancer")
        dp = (sec.get1("data path") if sec else None) or r"..\DATA"
        d = self.resolver.resolve(self.exe_dir, dp)
        if d is None:
            raise FileNotFoundError(f"data path {dp!r} from freelancer.ini not found")
        self.data_dir = d
        self._data_rel = _norm(os.path.relpath(self.data_dir, self.root))

    # -- paths -----------------------------------------------------------------------------
    def rel_from_root(self, path: Path) -> str:
        return os.path.relpath(path, self.root).replace(os.sep, "/")

    def _overlay_file(self, root_rel: str) -> Path | None:
        if self.overlay is None:
            return None
        p = self.resolver.resolve(self.overlay / "files", root_rel)
        return p if p is not None and p.is_file() else None

    def path(self, root_rel: str) -> Path | None:
        """Resolve an install-root-relative path (overlay first)."""
        p = self._overlay_file(root_rel)
        if p is not None:
            return p
        if self._hidden and _norm(root_rel) in self._hidden:
            return None
        return self.resolver.resolve(self.root, root_rel)

    def data_rel(self, rel: str) -> str:
        return self._data_rel + "/" + _norm(rel)

    def exe_rel(self, rel: str) -> str:
        return _norm(os.path.relpath(self.exe_dir, self.root)) + "/" + _norm(rel)

    def data_path(self, rel: str) -> Path | None:
        return self.path(self.data_rel(rel))

    def exe_path(self, rel: str) -> Path | None:
        return self.path(self.exe_rel(rel))

    def exists_data(self, rel: str) -> bool:
        p = self.data_path(rel)
        return p is not None and p.is_file()

    # -- reading ---------------------------------------------------------------------------
    def read_bytes_rel(self, root_rel: str) -> bytes | None:
        p = self.path(root_rel)
        if p is None or not p.is_file():
            return None
        raw = p.read_bytes()
        units = self._units_by_file.get(_norm(root_rel))
        if units or (self.pristine and _patch.MARK_OPEN.encode() in raw):
            txt, _ = _patch.strip(raw.decode("latin-1"))
            raw = (_patch.apply_units(txt, units) if units else txt).encode("latin-1")
        return raw

    def ini_rel(self, root_rel: str) -> _ini.Document | None:
        k = _norm(root_rel)
        if k in self._docs:
            return self._docs[k]
        raw = self.read_bytes_rel(root_rel)
        doc = _ini.loads(raw, path=self.path(root_rel)) if raw is not None else None
        self._docs[k] = doc
        return doc

    def data_ini(self, rel: str) -> _ini.Document | None:
        return self.ini_rel(self.data_rel(rel))

    def exe_ini(self, rel: str) -> _ini.Document | None:
        return self.ini_rel(self.exe_rel(rel))

    def freelancer_ini(self) -> _ini.Document:
        d = self.exe_ini("freelancer.ini")
        if d is None:
            raise FileNotFoundError(f"no freelancer.ini in {self.exe_dir}")
        return d

    # -- freelancer.ini --------------------------------------------------------------------
    def data_entries(self) -> list[tuple[str, str]]:
        """``[(key_lower, data-relative path), ...]`` from every ``[Data]`` section, in order.
        Keys without a value (``bases``) are skipped."""
        out = []
        for sec in self.freelancer_ini().sections("Data"):
            for e in sec.entries():
                if e.values and e.values[0]:
                    out.append((e.key.lower(), e.values[0]))
        return out

    def data_files(self, key: str) -> list[str]:
        k = key.lower()
        return [p for kk, p in self.data_entries() if kk == k]

    def resource_dll_names(self) -> list[str]:
        """``[Resources] DLL =`` names in order (index 1..N; resources.dll is index 0)."""
        out = []
        for sec in self.freelancer_ini().sections("Resources"):
            for e in sec.entries("DLL"):
                if e.values:
                    out.append(e.values[0])
        return out

    def iter_data_inis(self) -> list[str]:
        """Data-relative paths of every ``*.ini`` under DATA (install + overlay), sorted."""
        seen: dict[str, str] = {}
        for base in [self.data_dir] + ([self._overlay_data_dir()] if self.overlay else []):
            if base is None or not base.is_dir():
                continue
            for p in _ini.iter_ini_files(base):
                rel = os.path.relpath(p, base).replace(os.sep, "/")
                if base == self.data_dir and self._hidden and self.data_rel(rel) in self._hidden:
                    continue
                seen.setdefault(rel.lower(), rel)
        return [seen[k] for k in sorted(seen)]

    def _overlay_data_dir(self) -> Path | None:
        if self.overlay is None:
            return None
        return self.resolver.resolve(self.overlay / "files", self._data_rel)

    def overlay_files(self) -> list[str]:
        """Install-root-relative paths of every overlay file."""
        if self.overlay is None or not (self.overlay / "files").is_dir():
            return []
        base = self.overlay / "files"
        out = []
        for dp, dns, fns in os.walk(base):
            dns.sort()
            for fn in sorted(fns):
                out.append(os.path.relpath(os.path.join(dp, fn), base).replace(os.sep, "/"))
        return out

    def manifest(self) -> dict:
        if self.overlay is None:
            return {}
        mp = self.overlay / "MANIFEST.json"
        return json.loads(mp.read_text(encoding="utf-8")) if mp.is_file() else {}
