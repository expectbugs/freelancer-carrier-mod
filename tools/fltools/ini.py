"""Lossless reader/writer for Freelancer text INI files.

Grammar (follows the retail ``INI_Reader`` text mode; reference: see NOTES.md §6; VERIFIED here
by byte-exact round trip of every HDE DATA INI):

- Line endings ``\\r\\n``, ``\\n\\r``, ``\\r`` or ``\\n``; every line keeps its own terminator.
- Only space and tab are "blank" (trimmed). ``str.strip()`` is never used on data because it
  would also eat ``\\xa0`` and friends from the latin-1 decoded text.
- A section header is a line whose first non-blank char is ``[``; the name runs to the first
  ``]``. A name starting with ``;`` (``[;Houses]``) is a commented-out section: kept in the
  document, flagged ``disabled``, and skipped by lookups unless asked for.
- ``key = params``: the key runs to the first ``=`` or ``;``; params run from ``=`` to the first
  ``;``. A line without ``=`` is a key with empty params. ``;`` starts a comment.
- Params are comma separated; each field is blank-trimmed.
- Lines before the first section (the preamble) are kept but ignored, as the game does.
- Duplicate sections and duplicate keys are normal and preserved in order.
- Bytes are decoded/encoded as latin-1, so every byte round-trips.

Lookups of section names and keys are case-insensitive. Unmodified lines are written back
verbatim, so ``dumps(loads(b)) == b`` for any input.
"""
from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Iterable, Iterator, Sequence

ENCODING = "latin-1"
BLANKS = " \t"
_EOL_RE = re.compile(r"\r\n|\n\r|\r|\n")
_KEY_END_RE = re.compile(r"[=;]")

__all__ = [
    "Document", "Section", "Entry", "Line", "load", "loads", "dump", "split_lines",
    "format_value", "CIResolver", "ci_path", "split_params",
]


def split_lines(text: str) -> list[tuple[str, str]]:
    """Split ``text`` into ``(content, terminator)`` pairs. The last pair may have ``''``."""
    out: list[tuple[str, str]] = []
    pos = 0
    for m in _EOL_RE.finditer(text):
        out.append((text[pos:m.start()], m.group()))
        pos = m.end()
    if pos < len(text):
        out.append((text[pos:], ""))
    return out


def split_params(params: str) -> list[str]:
    """Split a parameter string into blank-trimmed comma fields (``''`` -> ``[]``)."""
    if params == "":
        return []
    return [f.strip(BLANKS) for f in params.split(",")]


def format_value(value) -> str:
    """Render a Python value as an INI parameter string."""
    if isinstance(value, str):
        return value
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        r = repr(value)
        if r.endswith(".0"):
            r = r[:-2]
        return r
    if isinstance(value, (list, tuple)):
        return ", ".join(format_value(v) for v in value)
    return str(value)


class Line:
    """A raw line: blank, comment, or anything that is not a key/value entry."""

    __slots__ = ("text", "eol")

    def __init__(self, text: str, eol: str = "\r\n"):
        self.text = text
        self.eol = eol

    def render(self) -> str:
        return self.text + self.eol

    @property
    def is_entry(self) -> bool:
        return False

    def __repr__(self) -> str:
        return f"Line({self.text!r})"


class Entry(Line):
    """A ``key = params`` line."""

    __slots__ = ("key", "params", "comment", "_values")

    def __init__(self, text: str, eol: str, key: str, params: str, comment: str):
        super().__init__(text, eol)
        self.key = key
        self.params = params
        self.comment = comment
        self._values: list[str] | None = None

    @classmethod
    def parse(cls, text: str, eol: str) -> "Entry | None":
        s = text.lstrip(BLANKS)
        if not s or s[0] == ";":
            return None
        m = _KEY_END_RE.search(s)
        if m is None:
            return cls(text, eol, s.rstrip(BLANKS), "", "")
        key = s[:m.start()].rstrip(BLANKS)
        if m.group() == ";":
            return cls(text, eol, key, "", s[m.start():])
        rest = s[m.end():]
        c = rest.find(";")
        if c < 0:
            return cls(text, eol, key, rest.strip(BLANKS), "")
        return cls(text, eol, key, rest[:c].strip(BLANKS), rest[c:])

    @classmethod
    def make(cls, key: str, value, eol: str = "\r\n", comment: str = "") -> "Entry":
        params = format_value(value)
        text = f"{key} = {params}" if params != "" else f"{key} ="
        if comment:
            text += " " + comment
        return cls(text, eol, key, params, comment)

    @property
    def is_entry(self) -> bool:
        return True

    @property
    def lkey(self) -> str:
        return self.key.lower()

    @property
    def values(self) -> list[str]:
        if self._values is None:
            self._values = split_params(self.params)
        return self._values

    def value(self, index: int = 0, default=None):
        v = self.values
        return v[index] if index < len(v) else default

    def set_value(self, value) -> None:
        """Replace the params; the line is re-rendered (indent and comment kept)."""
        params = format_value(value)
        indent = self.text[: len(self.text) - len(self.text.lstrip(BLANKS))]
        text = f"{indent}{self.key} = {params}" if params != "" else f"{indent}{self.key} ="
        if self.comment:
            text += " " + self.comment
        self.text = text
        self.params = params
        self._values = None

    def __repr__(self) -> str:
        return f"Entry({self.key!r} = {self.params!r})"


class Section:
    """A ``[Name]`` section with its lines (entries and trivia) in file order."""

    __slots__ = ("header", "name", "lines", "disabled")

    def __init__(self, header: Line, name: str, lines: list[Line] | None = None):
        self.header = header
        self.name = name
        self.lines: list[Line] = lines if lines is not None else []
        self.disabled = name.startswith(";")

    @classmethod
    def make(cls, name: str, items: Iterable = (), eol: str = "\r\n") -> "Section":
        sec = cls(Line(f"[{name}]", eol), name)
        for item in items:
            if isinstance(item, Line):
                sec.lines.append(item)
            else:
                k, v = item
                sec.lines.append(Entry.make(k, v, eol))
        return sec

    @property
    def lname(self) -> str:
        return self.name.lower()

    # -- reading ---------------------------------------------------------------------------
    def entries(self, key: str | None = None) -> list[Entry]:
        if key is None:
            return [ln for ln in self.lines if ln.is_entry]
        lk = key.lower()
        return [ln for ln in self.lines if ln.is_entry and ln.key.lower() == lk]

    def __iter__(self) -> Iterator[Entry]:
        return iter(self.entries())

    def has(self, key: str) -> bool:
        lk = key.lower()
        return any(ln.is_entry and ln.key.lower() == lk for ln in self.lines)

    def entry(self, key: str, index: int = 0) -> Entry | None:
        es = self.entries(key)
        return es[index] if index < len(es) else None

    def get(self, key: str, default=None):
        """Params string of the first ``key`` (or ``default``)."""
        e = self.entry(key)
        return e.params if e is not None else default

    def get1(self, key: str, default=None):
        """First field of the first ``key`` (or ``default`` when missing or empty)."""
        e = self.entry(key)
        if e is None or not e.values:
            return default
        return e.values[0]

    def getv(self, key: str, default=None):
        """Field list of the first ``key``."""
        e = self.entry(key)
        return list(e.values) if e is not None else default

    def getall(self, key: str) -> list[str]:
        """Params strings of every ``key``, in order."""
        return [e.params for e in self.entries(key)]

    def getallv(self, key: str) -> list[list[str]]:
        """Field lists of every ``key``, in order."""
        return [list(e.values) for e in self.entries(key)]

    @property
    def nickname(self) -> str | None:
        return self.get1("nickname")

    # -- writing ---------------------------------------------------------------------------
    def _eol(self) -> str:
        return self.header.eol or "\r\n"

    def _insert_index(self) -> int:
        """Index just after the last entry (new keys go before trailing blank/comment lines)."""
        for i in range(len(self.lines) - 1, -1, -1):
            if self.lines[i].is_entry:
                return i + 1
        # no entries: right after the header, but after leading comments that hug it
        return 0

    def set(self, key: str, value, index: int = 0) -> Entry:
        """Set the ``index``-th occurrence of ``key``; appends when ``index`` == count."""
        es = self.entries(key)
        if index < len(es):
            es[index].set_value(value)
            return es[index]
        if index == len(es):
            return self.add(key, value)
        raise IndexError(f"[{self.name}] has {len(es)} '{key}' entries; cannot set index {index}")

    def add(self, key: str, value, index: int | None = None) -> Entry:
        """Add a new ``key = value`` line after the last entry (or at line ``index``)."""
        e = Entry.make(key, value, self._eol())
        if index is None:
            index = self._insert_index()
        self.lines.insert(index, e)
        return e

    def remove(self, key: str, index: int | None = None) -> int:
        """Remove every (or the ``index``-th) ``key`` line. Returns the number removed."""
        es = self.entries(key)
        if index is not None:
            es = es[index:index + 1]
        ids = {id(e) for e in es}
        self.lines = [ln for ln in self.lines if id(ln) not in ids]
        return len(es)

    def render(self) -> str:
        return self.header.render() + "".join(ln.render() for ln in self.lines)

    def __repr__(self) -> str:
        return f"Section([{self.name}], {len(self.entries())} entries)"


def _match(sec: Section, match: dict | None) -> bool:
    if not match:
        return True
    for k, want in match.items():
        got = sec.get1(k)
        if got is None or got.lower() != str(want).lower():
            return False
    return True


class Document:
    """A parsed INI file. ``dumps()`` reproduces the input exactly when nothing was changed."""

    def __init__(self, preamble: list[Line] | None = None, sections: list[Section] | None = None,
                 path: str | os.PathLike | None = None, source_format: str = "text"):
        self.preamble: list[Line] = preamble if preamble is not None else []
        self._sections: list[Section] = sections if sections is not None else []
        self.path = Path(path) if path is not None else None
        self.source_format = source_format

    # -- parsing ---------------------------------------------------------------------------
    @classmethod
    def parse(cls, text: str, path=None) -> "Document":
        doc = cls(path=path)
        cur_lines = doc.preamble
        for content, eol in split_lines(text):
            s = content.lstrip(BLANKS)
            if s.startswith("["):
                end = s.find("]", 1)
                name = (s[1:end] if end >= 0 else s[1:]).strip(BLANKS)
                sec = Section(Line(content, eol), name)
                doc._sections.append(sec)
                cur_lines = sec.lines
                continue
            if cur_lines is doc.preamble:
                cur_lines.append(Line(content, eol))
                continue
            e = Entry.parse(content, eol)
            cur_lines.append(e if e is not None else Line(content, eol))
        return doc

    # -- queries ---------------------------------------------------------------------------
    @property
    def all_sections(self) -> list[Section]:
        """Every section including disabled (``[;Name]``) ones, in file order."""
        return self._sections

    def sections(self, name: str | None = None, include_disabled: bool = False,
                 **match) -> list[Section]:
        """Sections named ``name`` (case-insensitive; all when None), optionally filtered by
        ``key=value`` field-0 matches, e.g. ``doc.sections('Ship', nickname='li_cruiser')``."""
        ln = name.lower() if name is not None else None
        out = []
        for s in self._sections:
            if s.disabled and not include_disabled:
                continue
            if ln is not None and s.name.lower() != ln:
                continue
            if match and not _match(s, match):
                continue
            out.append(s)
        return out

    def section(self, name: str, **match) -> Section | None:
        ss = self.sections(name, **match)
        return ss[0] if ss else None

    def __iter__(self) -> Iterator[Section]:
        return iter(self.sections())

    @property
    def eol(self) -> str:
        """The dominant line terminator (``\\r\\n`` if the file has none)."""
        counts: dict[str, int] = {}
        for ln in self._all_lines():
            if ln.eol:
                counts[ln.eol] = counts.get(ln.eol, 0) + 1
        if not counts:
            return "\r\n"
        return max(counts.items(), key=lambda kv: kv[1])[0]

    def _all_lines(self) -> Iterator[Line]:
        yield from self.preamble
        for s in self._sections:
            yield s.header
            yield from s.lines

    # -- editing ---------------------------------------------------------------------------
    def add_section(self, name: str, items: Iterable = (), index: int | None = None) -> Section:
        eol = self.eol
        self._ensure_trailing_eol()
        sec = Section.make(name, items, eol)
        if index is None:
            self._sections.append(sec)
        else:
            self._sections.insert(index, sec)
        return sec

    def remove_section(self, sec: Section) -> None:
        self._sections = [s for s in self._sections if s is not sec]

    def _ensure_trailing_eol(self) -> None:
        last = None
        for last in self._all_lines():
            pass
        if last is not None and last.eol == "":
            last.eol = self.eol

    # -- output ----------------------------------------------------------------------------
    def dumps(self) -> str:
        parts = [ln.render() for ln in self.preamble]
        parts.extend(s.render() for s in self._sections)
        return "".join(parts)

    def to_bytes(self) -> bytes:
        return self.dumps().encode(ENCODING)

    def dump(self, path: str | os.PathLike | None = None) -> None:
        target = Path(path) if path is not None else self.path
        if target is None:
            raise ValueError("no path given")
        if self.source_format != "text":
            raise ValueError("refusing to write a document parsed from BINI as text over its source"
                             if target == self.path else "BINI-sourced document: write explicitly")
        from .safety import refuse_play_prefix
        refuse_play_prefix(target)
        target.write_bytes(self.to_bytes())

    def __repr__(self) -> str:
        return f"Document({self.path}, {len(self._sections)} sections)"


def loads(data: bytes | str, path=None) -> Document:
    """Parse INI ``data`` (bytes are decoded latin-1; BINI bytes are decoded via fltools.bini)."""
    if isinstance(data, bytes):
        if data[:4] == b"BINI":
            from . import bini
            return bini.to_document(data, path=path)
        data = data.decode(ENCODING)
    return Document.parse(data, path=path)


def load(path: str | os.PathLike) -> Document:
    p = Path(path)
    return loads(p.read_bytes(), path=p)


def dump(doc: Document, path: str | os.PathLike) -> None:
    doc.dump(path)


class CIResolver:
    """Case-insensitive path resolver with a directory-listing cache.

    FL paths are case-insensitive and use backslashes; the Linux filesystem is case-sensitive
    and HDE mixes case (``DATA/UNIVERSE/universe.ini`` vs ``Universe\\Systems\\...``). An exact
    match wins; otherwise the first case-insensitive match in sorted order (deterministic).
    """

    def __init__(self):
        self._listing: dict[str, dict[str, str]] = {}

    def _list(self, d: str) -> dict[str, str] | None:
        got = self._listing.get(d)
        if got is None:
            try:
                names = sorted(os.listdir(d))
            except (FileNotFoundError, NotADirectoryError, PermissionError):
                return None
            got = {}
            for n in names:
                got.setdefault(n.lower(), n)
            self._listing[d] = got
        return got

    def invalidate(self, d: str | os.PathLike | None = None) -> None:
        if d is None:
            self._listing.clear()
        else:
            self._listing.pop(str(d), None)

    def resolve(self, base: str | os.PathLike, rel: str = "") -> Path | None:
        """Resolve ``rel`` (FL-style, ``\\`` or ``/``) under ``base``; None when missing."""
        cur = str(base)
        if not os.path.exists(cur):
            return None
        parts = [p for p in rel.replace("\\", "/").split("/") if p not in ("", ".")]
        for p in parts:
            if p == "..":
                cur = os.path.dirname(cur.rstrip("/")) or "/"
                continue
            cand = os.path.join(cur, p)
            if os.path.exists(cand):
                cur = cand
                continue
            listing = self._list(cur)
            if listing is None:
                return None
            hit = listing.get(p.lower())
            if hit is None:
                return None
            cur = os.path.join(cur, hit)
        return Path(cur)


_DEFAULT_RESOLVER = CIResolver()


def ci_path(base: str | os.PathLike, rel: str = "") -> Path | None:
    """Module-level convenience around a shared :class:`CIResolver`."""
    return _DEFAULT_RESOLVER.resolve(base, rel)


def iter_ini_files(root: str | os.PathLike) -> Iterator[Path]:
    """Every ``*.ini`` (any case) under ``root``, in sorted, deterministic order."""
    for dp, dns, fns in os.walk(root):
        dns.sort()
        for fn in sorted(fns):
            if fn.lower().endswith(".ini"):
                yield Path(dp) / fn


def nickname_index(docs: Sequence[Document], section: str) -> dict[str, Section]:
    """``{nickname.lower(): first Section}`` for every ``[section]`` in ``docs``."""
    out: dict[str, Section] = {}
    for d in docs:
        for s in d.sections(section):
            n = s.nickname
            if n:
                out.setdefault(n.lower(), s)
    return out
