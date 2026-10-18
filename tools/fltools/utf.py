"""UTF ("Universal Tree Format") container reader/writer: ``.cmp``, ``.3db``, ``.mat``, ``.txm``.

Format (studied from Librelancer ``LibreLancer/Utf/*`` and flint ``formats/utf.py``;
reimplemented, not copied; every claim below is VERIFIED by the round-trip tests on HDE
models):

- 56-byte header: ``"UTF "``, version 0x101, tree offset, tree size, (unused), entry size (44),
  names offset, names allocated, names used, data offset, (unused) x2, FILETIME lo/hi.
- The tree is an array of 44-byte entries: next-sibling offset, name offset, flags
  (0x10 intermediate, 0x80 leaf), sharing, child-or-data offset, allocated size, used size,
  uncompressed size, three timestamps. Offsets of siblings/children are relative to the tree,
  name offsets to the name block (NUL-terminated ASCII, deduplicated), data offsets to the
  data block. Entry 0 is the root ``\\``.
- HDE ship models lay the file out as header | tree | names | data, contiguously; leaf
  allocations are ``max(8, align4(size))``.

Two writers:

- ``layout="preserve"`` (default): every original entry, name and data byte keeps its offset;
  new nodes, names and data are appended to the end of their block (standard layout only;
  otherwise growth falls back to compact). An unmodified tree is rewritten byte-identically,
  whatever the source layout. Removed nodes leave unreferenced entries behind, as some HDE
  ``.3db`` files already do.
- ``layout="compact"``: a fresh, canonical layout (pre-order entries, deduplicated names in
  first-use order, 4-aligned data). Valid and re-readable; not byte-identical to the source.

Hardpoints live in every part node (the ``*.3db`` children of the root in a ``.cmp``, or the
root of a ``.3db``) under ``Hardpoints/Fixed`` and ``Hardpoints/Revolute``. Each hardpoint is
an intermediate node with ``Orientation`` (3x3 float32, row-major), ``Position`` (3 float32);
revolute ones also ``Axis`` (3 float32), ``Min`` and ``Max`` (float32 radians). In-game proof
of hardpoints added this way is S-LOADOUT's job (UNVERIFIED in game).
"""
from __future__ import annotations

import os
import struct
from dataclasses import dataclass
from pathlib import Path

MAGIC = b"UTF "
VERSION = 0x101
ENTRY_SIZE = 44
HEADER_SIZE = 56
FLAG_INTERMEDIATE = 0x10
FLAG_LEAF = 0x80

__all__ = ["Node", "UtfFile", "load", "loads", "Hardpoint", "list_hardpoints",
           "add_hardpoint", "parts", "UtfError"]


class UtfError(ValueError):
    pass


def _align(n: int, a: int) -> int:
    return (n + a - 1) // a * a


def _leaf_alloc(n: int) -> int:
    return max(8, _align(n, 4))


class Node:
    """A tree node: intermediate (``children`` list) or leaf (``data`` bytes)."""

    __slots__ = ("name", "children", "_data", "_orig", "_dirty")

    def __init__(self, name: str, children: list["Node"] | None = None, data: bytes | None = None):
        if (children is None) == (data is None):
            raise UtfError("a node is either intermediate (children) or a leaf (data)")
        self.name = name
        self.children = children
        self._data = data
        self._orig: dict | None = None   # layout memory from the source file
        self._dirty = False

    @property
    def is_leaf(self) -> bool:
        return self.children is None

    @property
    def data(self) -> bytes | None:
        return self._data

    @data.setter
    def data(self, value: bytes) -> None:
        if self.children is not None:
            raise UtfError(f"{self.name!r} is an intermediate node")
        self._data = bytes(value)
        self._dirty = True

    def child(self, name: str) -> "Node | None":
        """First child named ``name`` (case-insensitive)."""
        if self.children is None:
            return None
        ln = name.lower()
        for c in self.children:
            if c.name.lower() == ln:
                return c
        return None

    def find(self, path: str) -> "Node | None":
        """``a/b/c`` path lookup (case-insensitive)."""
        cur: Node | None = self
        for part in [p for p in path.replace("\\", "/").split("/") if p]:
            cur = cur.child(part) if cur is not None else None
        return cur

    def add(self, node: "Node", sort: bool = True) -> "Node":
        if self.children is None:
            raise UtfError(f"{self.name!r} is a leaf")
        if sort:
            k = node.name.lower()
            for i, c in enumerate(self.children):
                if c.name.lower() > k:
                    self.children.insert(i, node)
                    return node
        self.children.append(node)
        return node

    def walk(self, prefix: str = ""):
        """Yield ``(path, node)`` pre-order."""
        path = f"{prefix}/{self.name}" if prefix else self.name
        yield path, self
        for c in self.children or []:
            yield from c.walk(path)

    # typed leaf helpers
    def floats(self) -> tuple[float, ...]:
        d = self._data or b""
        return struct.unpack(f"<{len(d) // 4}f", d[: len(d) // 4 * 4])

    def string(self) -> str:
        d = self._data or b""
        return d.split(b"\0", 1)[0].decode("ascii", "replace")

    def int32(self) -> int:
        return struct.unpack_from("<i", self._data or b"\0\0\0\0")[0]

    def __repr__(self) -> str:
        if self.is_leaf:
            return f"Node({self.name!r}, {len(self._data)}B)"
        return f"Node({self.name!r}/, {len(self.children)} children)"


class UtfFile:
    def __init__(self, root: Node, source: bytes | None = None, header: dict | None = None):
        self.root = root
        self._source = source
        self._header = header or {}

    # -- parse -----------------------------------------------------------------------------
    @classmethod
    def parse(cls, b: bytes) -> "UtfFile":
        if len(b) < HEADER_SIZE or b[:4] != MAGIC:
            raise UtfError("not a UTF file")
        (_sig, ver, tree_off, tree_size, u0, esz, names_off, names_alloc, names_used,
         data_off, u1, u2, ft_lo, ft_hi) = struct.unpack_from("<4s13I", b, 0)
        if ver != VERSION:
            raise UtfError(f"UTF version 0x{ver:x} unsupported")
        if esz != ENTRY_SIZE:
            raise UtfError(f"entry size {esz} unsupported")
        if tree_off + tree_size > len(b) or names_off + names_used > len(b) or data_off > len(b):
            raise UtfError("block out of range")
        names = b[names_off:names_off + names_alloc]
        tree = b[tree_off:tree_off + tree_size]
        data = b[data_off:]
        n_entries = tree_size // ENTRY_SIZE

        def name_at(o: int) -> str:
            end = names.find(b"\0", o)
            return names[o:end if end >= 0 else len(names)].decode("ascii", "replace")

        seen: set[int] = set()

        def build(off: int) -> Node:
            if off in seen:
                raise UtfError(f"entry 0x{off:x} reached twice (cyclic or shared tree)")
            if off % ENTRY_SIZE or off >= tree_size:
                raise UtfError(f"bad entry offset 0x{off:x}")
            seen.add(off)
            (peer, name_off, flags, sharing, child, alloc, used, uncomp, t1, t2, t3) = \
                struct.unpack_from("<11I", tree, off)
            name = name_at(name_off)
            orig = {"entry": off, "name_off": name_off, "flags": flags, "sharing": sharing,
                    "child": child, "alloc": alloc, "used": used, "uncomp": uncomp,
                    "ts": (t1, t2, t3), "name": name}
            if flags & FLAG_INTERMEDIATE:
                kids: list[Node] = []
                c = child
                while c:
                    kn, nxt = build(c), struct.unpack_from("<I", tree, c)[0]
                    kids.append(kn)
                    c = nxt
                node = Node(name, children=kids)
            else:
                if child + used > len(data):
                    raise UtfError(f"leaf {name!r} data out of range")
                node = Node(name, data=data[child:child + used])
            node._orig = orig
            return node

        root = build(0)
        header = {"tree_off": tree_off, "tree_size": tree_size, "u0": u0, "names_off": names_off,
                  "names_alloc": names_alloc, "names_used": names_used, "data_off": data_off,
                  "u1": u1, "u2": u2, "ft": (ft_lo, ft_hi), "n_entries": n_entries,
                  "n_reached": len(seen)}
        return cls(root, source=b, header=header)

    # -- serialize -------------------------------------------------------------------------
    def dumps(self, layout: str = "preserve") -> bytes:
        if layout == "compact" or self._source is None:
            return self._dump_compact()
        if layout != "preserve":
            raise ValueError(f"unknown layout {layout!r}")
        return self._dump_preserve()

    def dump(self, path: str | os.PathLike, layout: str = "preserve") -> None:
        from .safety import refuse_play_prefix
        p = Path(path)
        refuse_play_prefix(p)
        data = self.dumps(layout)
        tmp = p.with_name(p.name + ".tmp")
        tmp.write_bytes(data)
        os.replace(tmp, p)

    def _nodes_preorder(self) -> list[Node]:
        out: list[Node] = []

        def rec(n: Node):
            out.append(n)
            for c in n.children or []:
                rec(c)
        rec(self.root)
        return out

    def _dump_preserve(self) -> bytes:
        """Keep every original byte where it was; grow blocks only when needed.

        No growth (same nodes or fewer, no new names, changed leaves fit their allocation):
        the original file is copied and only tree entries / changed leaf bytes are rewritten in
        place, whatever the source block layout (some HDE .ale/.sph/.utf files put the tree
        after a gap; some .3db files carry unreachable garbage entries -- both kept as-is).
        Growth on the standard layout (header | tree | names | data): new entries go after the
        old tree, new names after the old names, new data after the old data. Growth on any
        other layout falls back to the compact writer.
        """
        h = self._header
        src = self._source
        nodes = self._nodes_preorder()

        # entries: original nodes keep their slot (a node object reached twice gets a new one)
        entry_of: dict[int, int] = {}
        used_slots: set[int] = set()
        next_entry = h["tree_size"]
        for n in nodes:
            o = n._orig
            if o is not None and o["entry"] not in used_slots:
                entry_of[id(n)] = o["entry"]
                used_slots.add(o["entry"])
            else:
                entry_of[id(n)] = next_entry
                next_entry += ENTRY_SIZE
        tree_size = next_entry

        # names
        names = bytearray(src[h["names_off"]:h["names_off"] + h["names_used"]])
        name_index: dict[str, int] = {}
        o = 0
        while o < len(names):
            end = names.find(b"\0", o)
            if end < 0:
                break
            name_index.setdefault(names[o:end].decode("ascii", "replace"), o)
            o = end + 1
        name_off: dict[int, int] = {}
        for n in nodes:
            if n._orig is not None and n.name == n._orig["name"]:
                name_off[id(n)] = n._orig["name_off"]
                continue
            off = name_index.get(n.name)
            if off is None:
                off = len(names)
                names += n.name.encode("ascii") + b"\0"
                name_index[n.name] = off
            name_off[id(n)] = off
        names_grew = len(names) > h["names_used"]

        # data
        data = bytearray(src[h["data_off"]:])
        orig_data_len = len(data)
        leaf_pos: dict[int, tuple[int, int]] = {}
        for n in nodes:
            if not n.is_leaf:
                continue
            o = n._orig
            if o is not None and not n._dirty and entry_of[id(n)] == o["entry"]:
                leaf_pos[id(n)] = (o["child"], o["alloc"])
                continue
            d = n.data
            if o is not None and entry_of[id(n)] == o["entry"] and len(d) <= o["alloc"]:
                start = o["child"]
                data[start:start + o["alloc"]] = d + b"\0" * (o["alloc"] - len(d))
                leaf_pos[id(n)] = (start, o["alloc"])
                continue
            start = len(data)
            alloc = _leaf_alloc(len(d))
            data += d + b"\0" * (alloc - len(d))
            leaf_pos[id(n)] = (start, alloc)
        data_grew = len(data) > orig_data_len
        grows = tree_size > h["tree_size"] or names_grew or data_grew

        standard = (h["tree_off"] == HEADER_SIZE
                    and h["names_off"] == h["tree_off"] + h["tree_size"]
                    and h["data_off"] == h["names_off"] + h["names_alloc"])
        if grows and not standard:
            return self._dump_compact()

        tree = bytearray(src[h["tree_off"]:h["tree_off"] + h["tree_size"]])
        tree += b"\0" * (tree_size - len(tree))

        def rec(n: Node, peer: int, ts):
            e = entry_of[id(n)]
            o = n._orig if (n._orig is not None and n._orig["entry"] == e) else None
            my_ts = o["ts"] if o is not None else ts
            if n.is_leaf:
                off, alloc = leaf_pos[id(n)]
                used = len(n.data)
                flags = o["flags"] if o is not None else FLAG_LEAF
                sharing = o["sharing"] if o is not None else 0
                uncomp = o["uncomp"] if (o is not None and not n._dirty) else used
                struct.pack_into("<11I", tree, e, peer, name_off[id(n)], flags, sharing, off,
                                 alloc, used, uncomp, *my_ts)
                return
            kids = n.children
            first = entry_of[id(kids[0])] if kids else 0
            flags = o["flags"] if o is not None else FLAG_INTERMEDIATE
            sharing = o["sharing"] if o is not None else 0
            alloc, used, uncomp = ((o["alloc"], o["used"], o["uncomp"]) if o is not None
                                   else (0, 0, 0))
            struct.pack_into("<11I", tree, e, peer, name_off[id(n)], flags, sharing, first,
                             alloc, used, uncomp, *my_ts)
            for i, c in enumerate(kids):
                nxt = entry_of[id(kids[i + 1])] if i + 1 < len(kids) else 0
                rec(c, nxt, my_ts)

        root_ts = self.root._orig["ts"] if self.root._orig else (0, 0, 0)
        rec(self.root, 0, root_ts)

        if not grows:
            out = bytearray(src)
            out[h["tree_off"]:h["tree_off"] + h["tree_size"]] = tree
            out[h["data_off"]:] = data
            return bytes(out)

        if names_grew:
            names_used = len(names)
            names_alloc = _align(names_used, 4)
            names_block = bytes(names) + b"\0" * (names_alloc - names_used)
        else:
            names_used, names_alloc = h["names_used"], h["names_alloc"]
            names_block = src[h["names_off"]:h["names_off"] + names_alloc]
        names_off = HEADER_SIZE + tree_size
        data_off = names_off + names_alloc
        hdr = struct.pack("<4s13I", MAGIC, VERSION, HEADER_SIZE, tree_size, h["u0"], ENTRY_SIZE,
                          names_off, names_alloc, names_used, data_off, h["u1"], h["u2"], *h["ft"])
        return hdr + bytes(tree) + names_block + bytes(data)

    def _dump_compact(self) -> bytes:
        nodes = self._nodes_preorder()
        entry_of = {id(n): i * ENTRY_SIZE for i, n in enumerate(nodes)}
        names = bytearray(b"\0")
        name_index: dict[str, int] = {"": 0}
        name_off = {}
        for n in nodes:
            off = name_index.get(n.name)
            if off is None:
                off = len(names)
                names += n.name.encode("ascii") + b"\0"
                name_index[n.name] = off
            name_off[id(n)] = off
        names_used = len(names)
        names_alloc = _align(names_used, 4)
        data = bytearray()
        leaf_pos = {}
        for n in nodes:
            if n.is_leaf:
                alloc = _leaf_alloc(len(n.data))
                leaf_pos[id(n)] = (len(data), alloc)
                data += n.data + b"\0" * (alloc - len(n.data))
        tree = bytearray(len(nodes) * ENTRY_SIZE)

        def rec(n: Node, peer: int):
            o = n._orig
            ts = o["ts"] if o is not None else (0, 0, 0)
            e = entry_of[id(n)]
            if n.is_leaf:
                off, alloc = leaf_pos[id(n)]
                sharing = o["sharing"] if o is not None else 0
                struct.pack_into("<11I", tree, e, peer, name_off[id(n)], FLAG_LEAF, sharing, off,
                                 alloc, len(n.data), len(n.data), *ts)
                return
            kids = n.children
            first = entry_of[id(kids[0])] if kids else 0
            struct.pack_into("<11I", tree, e, peer, name_off[id(n)], FLAG_INTERMEDIATE, 0, first,
                             0, 0, 0, *ts)
            for i, c in enumerate(kids):
                rec(c, entry_of[id(kids[i + 1])] if i + 1 < len(kids) else 0)

        rec(self.root, 0)
        h = self._header
        names_off = HEADER_SIZE + len(tree)
        data_off = names_off + names_alloc
        hdr = struct.pack("<4s13I", MAGIC, VERSION, HEADER_SIZE, len(tree), h.get("u0", 0),
                          ENTRY_SIZE, names_off, names_alloc, names_used, data_off,
                          h.get("u1", 0), h.get("u2", 0), *h.get("ft", (0, 0)))
        return hdr + bytes(tree) + bytes(names) + b"\0" * (names_alloc - names_used) + bytes(data)


def loads(b: bytes) -> UtfFile:
    return UtfFile.parse(b)


def load(path: str | os.PathLike) -> UtfFile:
    return UtfFile.parse(Path(path).read_bytes())


# ---------------------------------------------------------------------------------------------
# hardpoints

IDENTITY = (1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0)


@dataclass
class Hardpoint:
    part: str            # part object name ("Root", ...) or the part node name for a .3db
    part_node: str       # the part's node name ("<model>_lod1....3db" or "\\")
    name: str
    kind: str            # "fixed" | "revolute"
    position: tuple[float, float, float]
    orientation: tuple[float, ...]   # 9 floats, row-major
    axis: tuple[float, float, float] | None = None
    min: float | None = None
    max: float | None = None


def parts(utf: UtfFile) -> list[tuple[str, Node]]:
    """``[(part_name, part_node)]``: for a ``.cmp`` every root child that is referenced by
    ``Cmpnd/*/File name`` (named by its ``Object name``) or holds ``Hardpoints``; for a
    ``.3db`` the root itself (named ``\\``)."""
    root = utf.root
    cmpnd = root.child("Cmpnd")
    out: list[tuple[str, Node]] = []
    if cmpnd is None:
        return [(root.name, root)]
    file_to_obj: dict[str, str] = {}
    for c in cmpnd.children or []:
        fn, on = c.child("File name"), c.child("Object name")
        if fn is not None and on is not None and fn.is_leaf and on.is_leaf:
            file_to_obj[fn.string().lower()] = on.string()
    for c in root.children or []:
        if c.is_leaf:
            continue
        obj = file_to_obj.get(c.name.lower())
        if obj is not None or c.child("Hardpoints") is not None:
            out.append((obj or c.name, c))
    return out


def _f3(n: Node | None):
    if n is None or not n.is_leaf or len(n.data) < 12:
        return None
    return tuple(n.floats()[:3])


def _f1(n: Node | None):
    if n is None or not n.is_leaf or len(n.data) < 4:
        return None
    return n.floats()[0]


def list_hardpoints(utf: UtfFile) -> list[Hardpoint]:
    out = []
    for pname, pnode in parts(utf):
        hps = pnode.child("Hardpoints")
        if hps is None or hps.is_leaf:
            continue
        for grp in hps.children:
            kind = grp.name.lower()
            if kind not in ("fixed", "revolute") or grp.is_leaf:
                continue
            for hp in grp.children:
                if hp.is_leaf:
                    continue
                ori = hp.child("Orientation")
                out.append(Hardpoint(
                    part=pname, part_node=pnode.name, name=hp.name, kind=kind,
                    position=_f3(hp.child("Position")) or (0.0, 0.0, 0.0),
                    orientation=tuple(ori.floats()[:9]) if ori is not None and ori.is_leaf
                    else IDENTITY,
                    axis=_f3(hp.child("Axis")) if kind == "revolute" else None,
                    min=_f1(hp.child("Min")) if kind == "revolute" else None,
                    max=_f1(hp.child("Max")) if kind == "revolute" else None))
    return out


def _pack_floats(vals, n: int) -> bytes:
    flat = []
    for v in vals:
        if isinstance(v, (list, tuple)):
            flat.extend(float(x) for x in v)
        else:
            flat.append(float(v))
    if len(flat) != n:
        raise UtfError(f"expected {n} floats, got {len(flat)}")
    return struct.pack(f"<{n}f", *flat)


def add_hardpoint(utf: UtfFile, part: str | None, name: str, kind: str, position,
                  orientation=IDENTITY, axis=None, min: float | None = None,
                  max: float | None = None) -> Node:
    """Add hardpoint ``name`` to ``part`` (object name like ``Root``, or the part node name;
    None = the ``Root`` part, else the first part). Refuses a name that already exists anywhere
    in the model (case-insensitive)."""
    kind_l = kind.lower()
    if kind_l not in ("fixed", "revolute"):
        raise UtfError("kind must be 'fixed' or 'revolute'")
    try:
        name.encode("ascii")
    except UnicodeEncodeError:
        raise UtfError("hardpoint names must be ASCII") from None
    if any(h.name.lower() == name.lower() for h in list_hardpoints(utf)):
        raise UtfError(f"hardpoint {name!r} already exists")
    ps = parts(utf)
    if not ps:
        raise UtfError("model has no parts")
    if part is None:
        roots = [n for pn, n in ps if pn.lower() == "root"]
        pnode = roots[0] if roots else ps[0][1]
    else:
        pl = part.lower()
        hits = [n for pn, n in ps if pn.lower() == pl or n.name.lower() == pl]
        if not hits:
            raise UtfError(f"no part {part!r}; parts: {[pn for pn, _ in ps]}")
        pnode = hits[0]
    hps = pnode.child("Hardpoints")
    if hps is None:
        hps = pnode.add(Node("Hardpoints", children=[]))
    grp_name = "Fixed" if kind_l == "fixed" else "Revolute"
    grp = hps.child(grp_name)
    if grp is None:
        grp = hps.add(Node(grp_name, children=[]))
    leaves = []
    if kind_l == "revolute":
        leaves.append(Node("Axis", data=_pack_floats(axis if axis is not None else (0, 1, 0), 3)))
        leaves.append(Node("Max", data=_pack_floats([max if max is not None else 0.0], 1)))
        leaves.append(Node("Min", data=_pack_floats([min if min is not None else 0.0], 1)))
    leaves.append(Node("Orientation", data=_pack_floats(orientation, 9)))
    leaves.append(Node("Position", data=_pack_floats(position, 3)))
    return grp.add(Node(name, children=leaves))


def main(argv: list[str] | None = None) -> int:
    import argparse
    ap = argparse.ArgumentParser(prog="flutf", description="UTF tree dump / hardpoint list")
    ap.add_argument("file")
    ap.add_argument("--hardpoints", action="store_true")
    a = ap.parse_args(argv)
    u = load(a.file)
    if a.hardpoints:
        for hp in list_hardpoints(u):
            print(f"{hp.part}\t{hp.kind}\t{hp.name}\t"
                  f"{', '.join('%g' % v for v in hp.position)}")
    else:
        for path, n in u.root.walk():
            print(path + ("" if n.is_leaf else "/"), f"{len(n.data)}B" if n.is_leaf else "")
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
