"""PE resource reader for Freelancer resource DLLs, and global IDS resolution.

- RT_STRING (type 6): blocks of 16 strings; block resource id ``b`` holds local ids
  ``(b-1)*16 .. (b-1)*16+15``; each entry is ``u16 length`` + UTF-16LE text.
- RT_HTML (type 23): one infocard per resource id; UTF-16LE ``<RDL>`` XML, normally with a
  ``FF FE`` BOM (stripped here).
- Global IDS = ``dll_index * 65536 + local_id``. ``resources.dll`` (EXE dir) is the implicit
  index 0; ``[Resources] DLL =`` lines of ``EXE/freelancer.ini`` are indexes 1..N in order
  (VERIFIED R3 §1.2: a universe ``strid_name`` of ``3 * 65536 + n`` is local id ``n`` of the
  third listed DLL; see ``test_ids_resolution_matches_r3``).

The HDE installer keeps ``*_vanilla.dll`` copies; always read the names ``[Resources]`` lists.
"""
from __future__ import annotations

import os
import struct
from dataclasses import dataclass, field
from pathlib import Path

RT_STRING = 6
RT_HTML = 23
IMAGE_FILE_MACHINE_I386 = 0x014C
IMAGE_FILE_DLL = 0x2000

__all__ = ["PEInfo", "ResourceDll", "IdsResolver", "read_pe", "RT_STRING", "RT_HTML"]


def _u16(b: bytes, o: int) -> int:
    return struct.unpack_from("<H", b, o)[0]


def _u32(b: bytes, o: int) -> int:
    return struct.unpack_from("<I", b, o)[0]


@dataclass
class PEInfo:
    machine: int
    characteristics: int
    magic: int
    entry_point: int
    image_base: int
    sections: list[tuple[str, int, int, int, int]]  # name, vaddr, vsize, raw_off, raw_size
    resources: dict[tuple, bytes] = field(default_factory=dict)  # (type, id, lang) -> data

    @property
    def is_dll(self) -> bool:
        return bool(self.characteristics & IMAGE_FILE_DLL)

    @property
    def is_i386(self) -> bool:
        return self.machine == IMAGE_FILE_MACHINE_I386


def read_pe(data: bytes) -> PEInfo:
    """Parse a PE image's headers and its whole resource tree."""
    if data[:2] != b"MZ":
        raise ValueError("not an MZ image")
    pe = _u32(data, 0x3C)
    if data[pe:pe + 4] != b"PE\0\0":
        raise ValueError("no PE signature")
    machine = _u16(data, pe + 4)
    nsec = _u16(data, pe + 6)
    optsz = _u16(data, pe + 20)
    chars = _u16(data, pe + 22)
    opt = pe + 24
    magic = _u16(data, opt)
    if magic == 0x10B:
        entry = _u32(data, opt + 16)
        image_base = _u32(data, opt + 28)
        dd = opt + 96
    elif magic == 0x20B:
        entry = _u32(data, opt + 16)
        image_base = struct.unpack_from("<Q", data, opt + 24)[0]
        dd = opt + 112
    else:
        raise ValueError(f"unknown optional header magic 0x{magic:x}")
    rsrc_rva, rsrc_size = struct.unpack_from("<II", data, dd + 2 * 8)
    secs = []
    so = opt + optsz
    for _ in range(nsec):
        name = data[so:so + 8].rstrip(b"\0").decode("ascii", "replace")
        vs, va, rs, rp = struct.unpack_from("<IIII", data, so + 8)
        secs.append((name, va, vs, rp, rs))
        so += 40
    info = PEInfo(machine, chars, magic, entry, image_base, secs)
    if rsrc_rva == 0 or rsrc_size == 0:
        return info

    def rva2off(rva: int) -> int:
        for _n, va, vs, rp, rs in secs:
            if va <= rva < va + max(vs, rs):
                return rva - va + rp
        raise ValueError(f"RVA 0x{rva:x} outside every section")

    base = rva2off(rsrc_rva)

    def name_of(raw: int):
        if raw & 0x80000000:
            o = base + (raw & 0x7FFFFFFF)
            n = _u16(data, o)
            return data[o + 2:o + 2 + 2 * n].decode("utf-16-le", "replace")
        return raw

    def readdir(off: int):
        nn = _u16(data, base + off + 12)
        ni = _u16(data, base + off + 14)
        for i in range(nn + ni):
            eo = base + off + 16 + i * 8
            yield name_of(_u32(data, eo)), _u32(data, eo + 4)

    for tid, tod in readdir(0):
        if not tod & 0x80000000:
            continue
        for rid, rod in readdir(tod & 0x7FFFFFFF):
            if not rod & 0x80000000:
                continue
            for lid, lod in readdir(rod & 0x7FFFFFFF):
                if lod & 0x80000000:
                    continue
                drva, dsz = struct.unpack_from("<II", data, base + lod)
                o = rva2off(drva)
                info.resources[(tid, rid, lid)] = data[o:o + dsz]
    return info


def decode_string_block(block_id: int, data: bytes) -> dict[int, str]:
    out: dict[int, str] = {}
    first = (block_id - 1) * 16
    o = 0
    for i in range(16):
        if o + 2 > len(data):
            break
        n = _u16(data, o)
        o += 2
        if n:
            out[first + i] = data[o:o + 2 * n].decode("utf-16-le", "replace")
        o += 2 * n
    return out


def decode_html(data: bytes) -> str:
    if data[:2] == b"\xff\xfe":
        data = data[2:]
    return data.decode("utf-16-le", "replace")


class ResourceDll:
    """Strings and infocards of one resource DLL (local ids)."""

    def __init__(self, path: str | os.PathLike):
        self.path = Path(path)
        self.pe = read_pe(self.path.read_bytes())
        self.strings: dict[int, str] = {}
        self.html: dict[int, str] = {}
        seen_str: set[int] = set()
        seen_html: set[int] = set()
        for (t, rid, _lang), blob in sorted(self.pe.resources.items(), key=lambda kv: str(kv[0])):
            if t == RT_STRING and isinstance(rid, int) and rid not in seen_str:
                seen_str.add(rid)
                self.strings.update(decode_string_block(rid, blob))
            elif t == RT_HTML and isinstance(rid, int) and rid not in seen_html:
                seen_html.add(rid)
                self.html[rid] = decode_html(blob)

    def raw_html(self, local_id: int) -> bytes | None:
        for (t, rid, _lang), blob in self.pe.resources.items():
            if t == RT_HTML and rid == local_id:
                return blob
        return None


class IdsResolver:
    """Resolve global IDS against an ordered DLL list (index 0 = resources.dll)."""

    def __init__(self, dll_paths: list[Path | None], names: list[str] | None = None):
        self.dll_paths = list(dll_paths)
        self.names = names or [p.name if p else "?" for p in dll_paths]
        self._dlls: dict[int, ResourceDll | None] = {}

    @classmethod
    def from_install(cls, install, extra: list[tuple[str, Path]] | None = None) -> "IdsResolver":
        """From an :class:`fltools.install.Install`; ``extra`` appends (name, path) DLLs."""
        names = ["resources.dll"] + install.resource_dll_names()
        paths = [install.exe_path(n) for n in names]
        for n, p in extra or []:
            names.append(n)
            paths.append(Path(p))
        return cls(paths, names)

    @property
    def count(self) -> int:
        return len(self.dll_paths)

    def dll(self, index: int) -> ResourceDll | None:
        if index not in self._dlls:
            p = self.dll_paths[index] if 0 <= index < len(self.dll_paths) else None
            self._dlls[index] = ResourceDll(p) if p is not None and p.exists() else None
        return self._dlls[index]

    @staticmethod
    def split(ids: int) -> tuple[int, int]:
        return ids >> 16, ids & 0xFFFF

    def in_range(self, ids: int) -> bool:
        return 0 <= (ids >> 16) < self.count

    def name(self, ids: int) -> str | None:
        idx, local = self.split(ids)
        d = self.dll(idx) if self.in_range(ids) else None
        return d.strings.get(local) if d else None

    def infocard(self, ids: int) -> str | None:
        idx, local = self.split(ids)
        d = self.dll(idx) if self.in_range(ids) else None
        return d.html.get(local) if d else None

    def lookup(self, ids: int):
        """``("string", text)``, ``("html", xml)`` or ``(None, None)``."""
        s = self.name(ids)
        if s is not None:
            return "string", s
        h = self.infocard(ids)
        if h is not None:
            return "html", h
        return None, None

    def all_strings(self) -> dict[int, str]:
        out = {}
        for i in range(self.count):
            d = self.dll(i)
            if d:
                for k, v in d.strings.items():
                    out[i * 65536 + k] = v
        return out

    def all_html(self) -> dict[int, str]:
        out = {}
        for i in range(self.count):
            d = self.dll(i)
            if d:
                for k, v in d.html.items():
                    out[i * 65536 + k] = v
        return out


def main(argv: list[str] | None = None) -> int:
    """``flids <ids>...``: resolve global IDS against an install's [Resources] list."""
    import argparse
    from .install import Install, default_hde_root
    ap = argparse.ArgumentParser(prog="flids", description="resolve Freelancer IDS numbers")
    ap.add_argument("ids", nargs="*", type=int)
    ap.add_argument("--install", default=str(default_hde_root()))
    ap.add_argument("--overlay")
    ap.add_argument("--dll", help="dump every string/infocard of this DLL file instead")
    a = ap.parse_args(argv)
    if a.dll:
        d = ResourceDll(a.dll)
        for k, v in sorted(d.strings.items()):
            print(f"S {k}\t{v}")
        for k, v in sorted(d.html.items()):
            print(f"H {k}\t{v}")
        return 0
    r = IdsResolver.from_install(Install(a.install, a.overlay))
    missing = False
    for i in a.ids:
        kind, text = r.lookup(i)
        idx, local = r.split(i)
        dll = r.names[idx] if r.in_range(i) else "(no such DLL)"
        print(f"{i}\t{dll}:{local}\t{kind or 'MISSING'}\t{text if text is not None else ''}")
        missing |= kind is None
    return 1 if missing else 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
