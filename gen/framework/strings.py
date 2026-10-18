"""Strings registry: stable text keys -> local ids in our resource DLL -> global IDS.

Rules (provisional until ARCH-0 writes ``docs/spec/text_ids.md``; then that file wins):

- Local ids start at 1 (0 means "none"); names (RT_STRING) and infocards (RT_HTML) share one
  id space so a number never means two things.
- A key keeps its id forever once allocated; the mapping is persisted to
  ``$FLMOD_LOCAL/gen/text_ids.json``. Ids of keys that disappear stay reserved (never reused).
- New keys get the next free id above the highest one ever used, in registration order. YAML
  keys are registered first, sorted by key; generator registrations follow in generator order.
  Same inputs (YAML + generators + mapping file) -> same ids.
- A YAML entry may pin ``id: N``; a pin that clashes with another key's id is an error.
- Global IDS = dll_index * 65536 + local id; the index is detected at build time
  (``fltools.resdll.detect_resource_index``: 8 on HDE).

YAML (``data/**/strings*.yaml``)::

    strings:                       # names (RT_STRING)
      carrier.name.fleet: Fleet Carrier
    infocards:                     # RT_HTML; plain text (blank line = new paragraph) ...
      carrier.info.fleet: |
        A big ship.
    entries:                       # ... or the long form, any kind
      carrier.info.raw: {kind: infocard, rdl: "<RDL><PUSH/><TEXT>x</TEXT><POP/></RDL>", id: 40}
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from fltools import resdll
from fltools.safety import refuse_play_prefix

KINDS = ("name", "infocard")


class StringsError(ValueError):
    pass


class StringsRegistry:
    def __init__(self, ids_path: Path | None, dll_index: int):
        self.ids_path = Path(ids_path) if ids_path else None
        self.dll_index = dll_index
        self.mapping: dict[str, int] = {}
        self.entries: dict[str, dict] = {}   # key -> {kind, text|rdl, source}
        if self.ids_path and self.ids_path.is_file():
            data = json.loads(self.ids_path.read_text(encoding="utf-8"))
            self.mapping = {k: int(v["local"]) for k, v in data.get("ids", {}).items()}
        self._used = set(self.mapping.values())
        self._next = max(self._used, default=0) + 1

    # ---------------------------------------------------------------------------------------
    def _alloc(self, key: str, pin: int | None) -> int:
        if key in self.mapping:
            if pin is not None and pin != self.mapping[key]:
                raise StringsError(f"{key}: pinned id {pin} but already allocated "
                                   f"{self.mapping[key]} (ids never move)")
            return self.mapping[key]
        if pin is not None:
            if not 1 <= pin <= 0xFFFF:
                raise StringsError(f"{key}: pinned id {pin} outside 1..65535")
            if pin in self._used:
                raise StringsError(f"{key}: pinned id {pin} already belongs to another key")
            local = pin
        else:
            while self._next in self._used:
                self._next += 1
            local = self._next
        if local > 0xFFFF:
            raise StringsError("resource DLL id space exhausted (65535)")
        self.mapping[key] = local
        self._used.add(local)
        return local

    def register(self, key: str, text: str | None = None, kind: str = "name", *,
                 rdl: str | None = None, id: int | None = None, source: str = "code") -> int:
        """Register ``key``; returns its global IDS."""
        if kind not in KINDS:
            raise StringsError(f"{key}: kind must be one of {KINDS}")
        if kind == "name":
            if text is None or rdl is not None:
                raise StringsError(f"{key}: a name needs plain text (no rdl)")
        elif (text is None) == (rdl is None):
            raise StringsError(f"{key}: an infocard needs exactly one of text / rdl")
        if rdl is not None:
            try:
                resdll.check_infocard(rdl)
            except ValueError as e:
                raise StringsError(f"{key}: {e}") from None
        prev = self.entries.get(key)
        new = {"kind": kind, "text": text, "rdl": rdl, "source": source}
        if prev is not None and (prev["kind"], prev["text"], prev["rdl"]) != \
                (kind, text, rdl):
            raise StringsError(f"{key}: registered twice with different content "
                               f"({prev['source']} and {source})")
        self.entries[key] = new
        return self.dll_index * 65536 + self._alloc(key, id)

    def ids(self, key: str) -> int:
        if key not in self.mapping or key not in self.entries:
            raise KeyError(key)
        return self.dll_index * 65536 + self.mapping[key]

    # ---------------------------------------------------------------------------------------
    def load_yaml_tree(self, data_dir: Path) -> list[Path]:
        """Register every ``strings*.yaml`` under ``data_dir`` (sorted keys first)."""
        files = sorted(p for p in Path(data_dir).rglob("strings*.yaml")) if Path(data_dir).is_dir() \
            else []
        if not files:
            return []
        try:
            import yaml  # PyYAML from the shared venv
        except ImportError as e:  # pragma: no cover
            raise StringsError("PyYAML is needed to read data/**/strings*.yaml") from e
        items: dict[str, tuple[dict, str]] = {}
        for f in files:
            try:
                doc = yaml.safe_load(f.read_text(encoding="utf-8")) or {}
            except (yaml.YAMLError, UnicodeDecodeError) as e:
                one = " ".join(str(e).split())          # one line for the CLI
                raise StringsError(f"{f}: invalid YAML: {one}") from None
            if not isinstance(doc, dict):
                raise StringsError(f"{f}: top level must be a mapping")
            for section, kind in (("strings", "name"), ("infocards", "infocard"),
                                  ("entries", None)):
                for k, v in (doc.get(section) or {}).items():
                    if isinstance(v, str):
                        spec = {"kind": kind or "name", "text": v}
                    elif isinstance(v, dict):
                        spec = dict(v)
                        spec.setdefault("kind", kind or "name")
                    else:
                        raise StringsError(f"{f}: {k}: value must be text or a mapping")
                    if k in items:
                        raise StringsError(f"{k}: defined in {items[k][1]} and {f}")
                    items[str(k)] = (spec, str(f))
            unknown = set(doc) - {"strings", "infocards", "entries", "version"}
            if unknown:
                raise StringsError(f"{f}: unknown top-level keys {sorted(unknown)}")
        for k in sorted(items):
            spec, src = items[k]
            self.register(k, spec.get("text"), spec.get("kind", "name"), rdl=spec.get("rdl"),
                          id=spec.get("id"), source=src)
        return files

    # ---------------------------------------------------------------------------------------
    def tables(self) -> tuple[dict[int, str], dict[int, str]]:
        strings, cards = {}, {}
        for k, e in self.entries.items():
            local = self.mapping[k]
            if e["kind"] == "name":
                strings[local] = e["text"]
            else:
                cards[local] = e["rdl"] if e["rdl"] is not None else resdll.rdl_from_text(e["text"])
        return strings, cards

    def build_dll(self, path: Path, backend: str = "python") -> Path | None:
        strings, cards = self.tables()
        if not strings and not cards:
            return None
        return resdll.write_dll(path, strings, cards, backend=backend)

    def save(self) -> None:
        if not self.ids_path:
            return
        data = {"version": 1, "note": "local ids of our resource DLL; never renumber shipped ids",
                "dll_index": self.dll_index,
                "ids": {k: {"local": v, "ids": self.dll_index * 65536 + v,
                            "kind": self.entries.get(k, {}).get("kind"),
                            "active": k in self.entries}
                        for k, v in sorted(self.mapping.items(), key=lambda kv: kv[1])}}
        refuse_play_prefix(self.ids_path)
        self.ids_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.ids_path.with_name(self.ids_path.name + ".tmp")
        tmp.write_text(json.dumps(data, indent=1) + "\n", encoding="utf-8")
        os.replace(tmp, self.ids_path)

    def manifest(self) -> dict[str, int]:
        return {k: self.ids(k) for k in sorted(self.entries)}
