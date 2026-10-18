"""Build a resource-only x86 PE DLL holding Freelancer strings and infocards.

Two backends produce equivalent resource trees (the tests read both back with
:mod:`fltools.peres`):

- ``python`` (default, stdlib only, no Windows toolchain): writes the PE32 image directly.
  The header shape copies HDE's own ``Controls.dll`` (a resource-only DLL the game already
  loads on this host via ``LoadLibraryA``): i386, characteristics ``0x210E`` (DLL, 32-bit,
  executable, stripped), entry point 0, one ``.rsrc`` section, file alignment 0x200, section
  alignment 0x1000, subsystem GUI, no DllCharacteristics, not RELOCS_STRIPPED (the image needs
  no fixups, so the loader may rebase it). TimeDateStamp is 0 so output is deterministic.
- ``llvm``: the recipe VERIFIED in R4 §A2.4 -- a ``.rc`` with ``#pragma code_page(65001)``,
  ``LANGUAGE 0x09, 0x01``, a STRINGTABLE and ``<id> HTML "<file>.xml"``, compiled with
  ``llvm-rc`` and linked with ``lld-link /dll /noentry /machine:x86 /Brepro``.

Strings go to RT_STRING (blocks of 16, block id = (local >> 4) + 1), infocards to RT_HTML
(type 23) as ``FF FE`` + UTF-16LE ``<RDL>...</RDL>``; language 1033 (en-US), like vanilla.

``detect_resource_index(install)`` predicts the index the DLL gets once appended to
``[Resources]`` (HDE: 8, so IDS = 524288 + local id; R3 §1.2, R4 §0.1 #9) and fails loudly when
the install's list is not what we expect.
"""
from __future__ import annotations

import os
import shutil
import struct
import subprocess
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path
from xml.sax.saxutils import escape as _xml_escape

from .peres import RT_HTML, RT_STRING

LANG_EN_US = 1033
DEFAULT_IMAGE_BASE = 0x07100000  # free in HDE's layout (controls.dll ends at 0x070E6000)
LLVM_BIN = Path(os.environ.get("FLTOOLS_LLVM_BIN", "/usr/lib/llvm/22/bin"))
HDE_RESOURCE_COUNT = 7  # InfoCards .. Controls (R3 §1.2)

__all__ = [
    "build_dll", "write_dll", "rdl_from_text", "encode_infocard", "check_infocard",
    "detect_resource_index", "ResourceIndexError", "llvm_available",
]


class ResourceIndexError(RuntimeError):
    pass


# ---------------------------------------------------------------------------------------------
# infocard helpers

def rdl_from_text(text: str) -> str:
    """Plain text -> RDL infocard XML. Blank lines separate paragraphs; XML is escaped."""
    paras = [p.strip() for p in text.replace("\r\n", "\n").split("\n\n")]
    paras = [" ".join(p.split("\n")) for p in paras if p]
    body = "</TEXT><PARA/><TEXT>".join(_xml_escape(p) for p in paras)
    return f"<RDL><PUSH/><TEXT>{body}</TEXT><PARA/><POP/></RDL>"


def check_infocard(xml: str) -> None:
    """Raise ValueError unless ``xml`` is a well-formed ``<RDL>`` document."""
    try:
        root = ET.fromstring(xml)
    except ET.ParseError as e:
        raise ValueError(f"infocard is not well-formed XML: {e}") from None
    if root.tag != "RDL":
        raise ValueError(f"infocard root element is <{root.tag}>, expected <RDL>")


def encode_infocard(xml: str) -> bytes:
    return b"\xff\xfe" + xml.encode("utf-16-le")


# ---------------------------------------------------------------------------------------------
# resource section (pure python)

def _align(n: int, a: int) -> int:
    return (n + a - 1) // a * a


def _string_blocks(strings: dict[int, str]) -> dict[int, bytes]:
    blocks: dict[int, list[str | None]] = {}
    for local, text in strings.items():
        if not 0 <= local <= 0xFFFF:
            raise ValueError(f"string id {local} outside 0..65535")
        b = (local >> 4) + 1
        blocks.setdefault(b, [None] * 16)[local & 15] = text
    out = {}
    for b, slots in blocks.items():
        parts = []
        for s in slots:
            if s is None:
                parts.append(b"\0\0")
            else:
                enc = s.encode("utf-16-le")
                if len(enc) // 2 > 0xFFFF:
                    raise ValueError("string longer than 65535 UTF-16 units")
                parts.append(struct.pack("<H", len(enc) // 2) + enc)
        out[b] = b"".join(parts)
    return out


def build_rsrc(strings: dict[int, str], infocards: dict[int, str], section_rva: int,
               lang: int = LANG_EN_US) -> bytes:
    """The ``.rsrc`` section bytes (resource directory + data) for the given content."""
    types: dict[int, dict[int, bytes]] = {}
    if strings:
        types[RT_STRING] = _string_blocks(strings)
    if infocards:
        html = {}
        for local, xml in infocards.items():
            if not 0 <= local <= 0xFFFF:
                raise ValueError(f"infocard id {local} outside 0..65535")
            check_infocard(xml)
            html[local] = encode_infocard(xml)
        types[RT_HTML] = html

    type_ids = sorted(types)
    root_size = 16 + 8 * len(type_ids)
    type_dir_off = {}
    off = root_size
    for t in type_ids:
        type_dir_off[t] = off
        off += 16 + 8 * len(types[t])
    name_dir_off = {}
    for t in type_ids:
        for rid in sorted(types[t]):
            name_dir_off[(t, rid)] = off
            off += 16 + 8
    data_entry_off = {}
    for t in type_ids:
        for rid in sorted(types[t]):
            data_entry_off[(t, rid)] = off
            off += 16
    data_off = {}
    off = _align(off, 8)
    for t in type_ids:
        for rid in sorted(types[t]):
            data_off[(t, rid)] = off
            off = _align(off + len(types[t][rid]), 8)
    buf = bytearray(off)

    def dir_header(at: int, n_ids: int) -> None:
        struct.pack_into("<IIHHHH", buf, at, 0, 0, 0, 0, 0, n_ids)

    dir_header(0, len(type_ids))
    for i, t in enumerate(type_ids):
        struct.pack_into("<II", buf, 16 + 8 * i, t, 0x80000000 | type_dir_off[t])
    for t in type_ids:
        rids = sorted(types[t])
        dir_header(type_dir_off[t], len(rids))
        for i, rid in enumerate(rids):
            struct.pack_into("<II", buf, type_dir_off[t] + 16 + 8 * i, rid,
                             0x80000000 | name_dir_off[(t, rid)])
            nd = name_dir_off[(t, rid)]
            dir_header(nd, 1)
            struct.pack_into("<II", buf, nd + 16, lang, data_entry_off[(t, rid)])
            blob = types[t][rid]
            struct.pack_into("<IIII", buf, data_entry_off[(t, rid)],
                             section_rva + data_off[(t, rid)], len(blob), 0, 0)
            buf[data_off[(t, rid)]:data_off[(t, rid)] + len(blob)] = blob
    return bytes(buf)


_DOS_STUB = bytes.fromhex(
    "0e1fba0e00b409cd21b8014ccd21") + b"This program cannot be run in DOS mode.\r\r\n$" + b"\0" * 7


def _pe_checksum(data: bytearray, checksum_off: int) -> int:
    total = 0
    n = len(data)
    padded = data + (b"\0" if n % 2 else b"")
    for i in range(0, len(padded), 2):
        if i == checksum_off or i == checksum_off + 2:
            continue
        total += padded[i] | (padded[i + 1] << 8)
        total = (total & 0xFFFF) + (total >> 16)
    total = (total & 0xFFFF) + (total >> 16)
    return (total + n) & 0xFFFFFFFF


def _build_python(strings: dict[int, str], infocards: dict[int, str], image_base: int) -> bytes:
    sect_align, file_align = 0x1000, 0x200
    rsrc_rva = 0x1000
    rsrc = build_rsrc(strings, infocards, rsrc_rva)
    e_lfanew = 0x80
    headers_end = e_lfanew + 4 + 20 + 224 + 40
    size_of_headers = _align(headers_end, file_align)
    raw_size = _align(len(rsrc), file_align)
    size_of_image = _align(rsrc_rva + len(rsrc), sect_align)
    out = bytearray(size_of_headers + raw_size)

    # DOS header + stub
    struct.pack_into("<2sHHHHHHHHHHHHHH", out, 0, b"MZ", 0x90, 3, 0, 4, 0, 0xFFFF, 0, 0xB8,
                     0, 0, 0, 0x40, 0, 0)
    struct.pack_into("<I", out, 0x3C, e_lfanew)
    out[0x40:0x40 + len(_DOS_STUB)] = _DOS_STUB
    # PE signature + COFF file header
    o = e_lfanew
    out[o:o + 4] = b"PE\0\0"
    struct.pack_into("<HHIIIHH", out, o + 4, 0x014C, 1, 0, 0, 0, 224, 0x210E)
    # optional header (PE32)
    opt = o + 24
    struct.pack_into("<HBBIIIIII", out, opt, 0x10B, 6, 0, 0, raw_size, 0, 0, 0x1000, 0x1000)
    struct.pack_into("<IIIHHHHHHIIIIHHIIIIII", out, opt + 28, image_base, sect_align, file_align,
                     4, 0, 0, 0, 4, 0, 0, size_of_image, size_of_headers, 0, 2, 0,
                     0x100000, 0x1000, 0x100000, 0x1000, 0, 16)
    dd = opt + 96
    struct.pack_into("<II", out, dd + 2 * 8, rsrc_rva, len(rsrc))
    # section table
    sh = opt + 224
    struct.pack_into("<8sIIIIIIHHI", out, sh, b".rsrc", len(rsrc), rsrc_rva, raw_size,
                     size_of_headers, 0, 0, 0, 0, 0x40000040)
    out[size_of_headers:size_of_headers + len(rsrc)] = rsrc
    struct.pack_into("<I", out, opt + 64, _pe_checksum(out, opt + 64))
    return bytes(out)


# ---------------------------------------------------------------------------------------------
# llvm backend

def llvm_available(bin_dir: Path | None = None) -> bool:
    b = Path(bin_dir or LLVM_BIN)
    return (b / "llvm-rc").is_file() and (b / "lld-link").is_file()


def _rc_escape(s: str) -> str:
    return s.replace("\\", "\\\\").replace('"', '""').replace("\n", "\\n").replace("\t", "\\t")


def _build_llvm(strings: dict[int, str], infocards: dict[int, str], image_base: int,
                bin_dir: Path | None = None) -> bytes:
    b = Path(bin_dir or LLVM_BIN)
    if not llvm_available(b):
        raise FileNotFoundError(f"llvm-rc/lld-link not found in {b}")
    with tempfile.TemporaryDirectory(prefix="fltools-resdll-") as td:
        tdp = Path(td)
        lines = ["#pragma code_page(65001)", "LANGUAGE 0x09, 0x01"]
        if strings:
            lines += ["STRINGTABLE", "BEGIN"]
            lines += [f'  {k} "{_rc_escape(strings[k])}"' for k in sorted(strings)]
            lines += ["END"]
        for k in sorted(infocards):
            check_infocard(infocards[k])
            (tdp / f"card{k}.xml").write_bytes(encode_infocard(infocards[k]))
            lines.append(f'{k} HTML "card{k}.xml"')
        (tdp / "mod.rc").write_text("\n".join(lines) + "\n", encoding="utf-8")
        subprocess.run([str(b / "llvm-rc"), "/nologo", "/C", "65001", "/l", "0x409", "/fo", "mod.res",
                        "mod.rc"],
                       cwd=td, check=True, capture_output=True)
        subprocess.run([str(b / "lld-link"), "/nologo", "/dll", "/noentry", "/machine:x86",
                        "/Brepro", f"/base:0x{image_base:x}", "/out:mod.dll", "mod.res"],
                       cwd=td, check=True, capture_output=True)
        return (tdp / "mod.dll").read_bytes()


# ---------------------------------------------------------------------------------------------
# public API

def build_dll(strings: dict[int, str] | None = None, infocards: dict[int, str] | None = None, *,
              backend: str = "python", image_base: int = DEFAULT_IMAGE_BASE) -> bytes:
    """Build the DLL image from ``{local_id: text}`` and ``{local_id: rdl_xml}``."""
    strings = dict(strings or {})
    infocards = dict(infocards or {})
    if not strings and not infocards:
        raise ValueError("nothing to put in the DLL")
    if backend == "python":
        return _build_python(strings, infocards, image_base)
    if backend == "llvm":
        return _build_llvm(strings, infocards, image_base)
    raise ValueError(f"unknown backend {backend!r}")


def write_dll(path: str | os.PathLike, strings=None, infocards=None, **kw) -> Path:
    from .safety import refuse_play_prefix
    p = Path(path)
    refuse_play_prefix(p)
    data = build_dll(strings, infocards, **kw)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(p.name + ".tmp")
    tmp.write_bytes(data)
    os.replace(tmp, p)
    return p


def detect_resource_index(install, dll_name: str | None = None,
                          expected: int | None = HDE_RESOURCE_COUNT + 1) -> int:
    """Index our DLL has (if already listed) or will get when appended to ``[Resources]``.

    ``install`` is an :class:`fltools.install.Install` or a path to the install root.
    Raises :class:`ResourceIndexError` when the answer differs from ``expected`` (HDE: 8),
    e.g. because another mod appended its own DLL. Pass ``expected=None`` to skip the check.
    """
    from .install import Install
    inst = install if isinstance(install, Install) else Install(install)
    names = inst.resource_dll_names()
    if dll_name:
        for i, n in enumerate(names):
            if n.lower() == dll_name.lower():
                idx = i + 1
                break
        else:
            idx = len(names) + 1
    else:
        idx = len(names) + 1
    if expected is not None and idx != expected:
        raise ResourceIndexError(
            f"[Resources] in {inst.exe_dir}/freelancer.ini lists {len(names)} DLLs "
            f"({', '.join(names)}); our DLL would get index {idx}, expected {expected}. "
            "Another mod probably appended a resource DLL: refusing to guess IDS numbers.")
    return idx


def copy_dll(src: str | os.PathLike, dst: str | os.PathLike) -> None:
    shutil.copyfile(src, dst)


def main(argv: list[str] | None = None) -> int:
    """``flresdll spec.json out.dll``: spec = {"strings": {id: text}, "infocards": {id: rdl}}."""
    import argparse
    import json
    ap = argparse.ArgumentParser(prog="flresdll", description="build a resource-only DLL")
    ap.add_argument("spec")
    ap.add_argument("out")
    ap.add_argument("--backend", choices=("python", "llvm"), default="python")
    a = ap.parse_args(argv)
    from .safety import PlayPrefixError
    try:
        spec = json.loads(Path(a.spec).read_text(encoding="utf-8"))
        strings = {int(k): v for k, v in spec.get("strings", {}).items()}
        cards = {int(k): v for k, v in spec.get("infocards", {}).items()}
        write_dll(a.out, strings, cards, backend=a.backend)
    except (PlayPrefixError, OSError, ValueError, AttributeError, RuntimeError) as e:
        import sys
        print(f"ERROR: {' '.join(str(e).split())}", file=sys.stderr)
        return 1
    print(f"wrote {a.out}: {len(strings)} strings, {len(cards)} infocards")
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
