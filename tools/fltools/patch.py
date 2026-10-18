"""Idempotent, reversible marker-block patches for existing Freelancer INI files.

We never replace an HDE file wholesale (R4 §0.1 #10). Every change lives in a marked region::

    ; >>> carrier-mod <region-id> v<N>[ noeol]
    ; carrier-mod-disabled: <original line, verbatim>      (only for replaced lines)
    <new lines>
    ; <<< carrier-mod <region-id>

Stripping a region removes the marker and new lines and restores each disabled line exactly
(text and line terminator), so ``unpatch(patch(f)) == f`` byte for byte. ``noeol`` records that
the file's last line had no terminator before we touched it.

A *unit* is ``{"file": "<install-relative path>", "id": "<block id>", "version": N,
"ops": [...]}``. One unit can produce several regions; they are named ``<id>`` (exactly one)
or ``<id>#1``, ``<id>#2``, ... in file order.

Applying is a rebuild: strip every carrier-mod region (giving the pristine text), check its
sha256 against the recorded baseline, apply all wanted units in order, and write only if the
result differs. That makes it idempotent and order-stable. ``force`` re-baselines a file whose
pristine text changed (e.g. the HDE installer rewrote it) and logs it.

Ops (all targets are computed on the pristine text; matching is case-insensitive):

``{"op": "append", "section": S, "match": {k: v}|"*"|None, "nth": 0|"all"|"last", "lines": [..],
   "after_key": K|None}``
    insert the lines after the last entry of the matched section(s), or, with ``after_key``,
    right after the last ``K`` line (falling back to the end). ``[Data]`` additions use
    ``after_key`` so a new file loads right after the existing files of the same key (load
    order matters: ``solar`` before ``universe``; R3 §1.1).
``{"op": "add_section", "lines": ["[Name]", "k = v", ...], "after": {"section":..}|None}``
    insert new section(s) at end of file, or after the matched section's last line.
``{"op": "set", "section": S, "match":.., "nth":.., "key": K, "value": V, "field": i|None,
   "occurrence": 0|"all", "where": {"field": i, "value": v}|None, "add_missing": bool}``
    replace a key's value (or one field of it); the original line is kept disabled.
``{"op": "comment_out", "section": S, "match":.., "nth":.., "key": K, "occurrence":..,
   "where":..}``
    disable key lines without replacement.

``state`` is a JSON file (by default ``<root>/carrier-mod.patchstate.json``) recording per file
the pristine sha256, the patched sha256 and the applied unit specs.
"""
from __future__ import annotations

import datetime as _dt
import hashlib
import json
import os
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

from .ini import BLANKS, Document, Entry, Line, Section, split_params
from .safety import UnsafePathError, contained_rel, refuse_play_prefix

MARK_OPEN = "; >>> carrier-mod "
MARK_CLOSE = "; <<< carrier-mod "
DISABLED = "; carrier-mod-disabled: "
STATE_NAME = "carrier-mod.patchstate.json"
# D107: unit ids in these namespaces belong to the test harness (harness/lib/deploy.py), not to
# the generator overlay. Overlay reconciliation (plan/apply_overlay_patches, so gen deploy and
# undeploy) keeps them in place and never applies, drops or re-orders them; only an explicit
# patch_file / unpatch_file with their ids changes them. See README "Reserved unit namespace".
PRESERVED_PREFIXES = ("harness.",)
_ID_RE = re.compile(r"^[A-Za-z0-9_.:-]+$")
_OPEN_RE = re.compile(r"^; >>> carrier-mod ([A-Za-z0-9_.:#-]+) v(\d+)( noeol)?$")
_CLOSE_RE = re.compile(r"^; <<< carrier-mod ([A-Za-z0-9_.:#-]+)$")

__all__ = ["PatchError", "strip", "apply_units", "PatchState", "patch_file", "unpatch_file",
           "is_preserved", "PRESERVED_PREFIXES",
           "sha256", "region_ids"]


class PatchError(RuntimeError):
    pass


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


# ---------------------------------------------------------------------------------------------
# line model (flat list of (text, eol))

def _lines(text: str) -> list[list[str]]:
    from .ini import split_lines
    return [[t, e] for t, e in split_lines(text)]


def _render(lines: list[list[str]]) -> str:
    return "".join(t + e for t, e in lines)


def _dominant_eol(lines) -> str:
    counts: dict[str, int] = {}
    for _t, e in lines:
        if e:
            counts[e] = counts.get(e, 0) + 1
    return max(counts.items(), key=lambda kv: kv[1])[0] if counts else "\r\n"


def strip(text: str, ids: set[str] | None = None) -> tuple[str, list[str]]:
    """Remove carrier-mod regions (all, or those whose unit id is in ``ids``).

    Returns ``(text, removed_region_ids)``. Raises PatchError on unbalanced markers.
    """
    lines = _lines(text)
    out: list[list[str]] = []
    removed: list[str] = []
    i = 0
    n = len(lines)
    while i < n:
        t, e = lines[i]
        m = _OPEN_RE.match(t)
        if not m:
            if _CLOSE_RE.match(t):
                raise PatchError(f"close marker without open: {t!r}")
            out.append([t, e])
            i += 1
            continue
        rid = m.group(1)
        unit = rid.split("#", 1)[0]
        noeol = bool(m.group(3))
        j = i + 1
        while j < n:
            cm = _CLOSE_RE.match(lines[j][0])
            if cm:
                if cm.group(1) != rid:
                    raise PatchError(f"region {rid!r} closed by {cm.group(1)!r}")
                break
            if _OPEN_RE.match(lines[j][0]):
                raise PatchError(f"nested region inside {rid!r}")
            j += 1
        else:
            raise PatchError(f"region {rid!r} is not closed")
        if ids is not None and unit not in ids:
            out.extend([list(x) for x in lines[i:j + 1]])
            i = j + 1
            continue
        restored = []
        for bt, be in lines[i + 1:j]:
            if bt.startswith(DISABLED):
                restored.append([bt[len(DISABLED):], be])
        if noeol:
            if restored:
                restored[-1][1] = ""
            elif out:
                out[-1][1] = ""
        out.extend(restored)
        removed.append(rid)
        i = j + 1
    return _render(out), removed


def region_ids(text: str) -> list[tuple[str, int]]:
    """``[(region_id, version), ...]`` present in ``text``."""
    out = []
    for t, _e in _lines(text):
        m = _OPEN_RE.match(t)
        if m:
            out.append((m.group(1), int(m.group(2))))
    return out


# ---------------------------------------------------------------------------------------------
# op targeting

@dataclass
class _Edit:
    kind: str                 # "insert" (before index) | "replace" (line index)
    index: int
    new: list[str] = field(default_factory=list)   # new line texts
    unit: int = 0             # unit order
    seq: int = 0              # op order inside the unit


class _Index:
    """Map Document objects to flat line indexes."""

    def __init__(self, text: str):
        self.doc = Document.parse(text)
        self.flat: list[Line] = list(self.doc._all_lines())
        self.pos = {id(ln): i for i, ln in enumerate(self.flat)}

    def sections(self, spec: dict) -> list[Section]:
        name = spec.get("section")
        if not name:
            raise PatchError(f"op needs 'section': {spec}")
        match = spec.get("match")
        if match == "*" or match is None:
            secs = self.doc.sections(name)
        else:
            secs = self.doc.sections(name, **match)
        nth = spec.get("nth", 0)
        if not secs:
            raise PatchError(f"no [{name}] section matches {match!r}")
        if nth == "all":
            return secs
        if nth == "last":
            return [secs[-1]]
        if not isinstance(nth, int) or nth >= len(secs):
            raise PatchError(f"[{name}] match {match!r}: nth={nth!r} but {len(secs)} match")
        return [secs[nth]]

    def end_of_entries(self, sec: Section) -> int:
        idx = sec._insert_index()
        if idx == 0:
            return self.pos[id(sec.header)] + 1
        return self.pos[id(sec.lines[idx - 1])] + 1

    def end_of_section(self, sec: Section) -> int:
        last = sec.lines[-1] if sec.lines else sec.header
        return self.pos[id(last)] + 1


def _where_ok(e: Entry, where: dict | None) -> bool:
    if not where:
        return True
    f = int(where.get("field", 0))
    v = e.values[f] if f < len(e.values) else None
    return v is not None and v.lower() == str(where["value"]).lower()


def _target_entries(sec: Section, spec: dict) -> list[Entry]:
    es = [e for e in sec.entries(spec["key"]) if _where_ok(e, spec.get("where"))]
    occ = spec.get("occurrence", 0)
    if occ == "all":
        return es
    if not isinstance(occ, int):
        raise PatchError(f"bad occurrence {occ!r}")
    return es[occ:occ + 1]


def _new_line_for(e: Entry, spec: dict) -> str | None:
    if spec.get("field") is None:
        params = str(spec["value"])
    else:
        f = int(spec["field"])
        vals = list(e.values)
        while len(vals) <= f:
            vals.append("")
        vals[f] = str(spec["value"])
        params = ", ".join(vals)
    if params == e.params:
        return None
    indent = e.text[: len(e.text) - len(e.text.lstrip(BLANKS))]
    return f"{indent}{e.key} = {params}"


def _edits_for_op(ix: _Index, op: dict, unit: int, seq: int) -> list[_Edit]:
    kind = op.get("op")
    edits: list[_Edit] = []
    if kind == "append":
        lines = [str(x) for x in op.get("lines", [])]
        if not lines:
            raise PatchError("append needs 'lines'")
        for sec in ix.sections(op):
            after = op.get("after_key")
            same = sec.entries(after) if after else []
            at = ix.pos[id(same[-1])] + 1 if same else ix.end_of_entries(sec)
            edits.append(_Edit("insert", at, lines, unit, seq))
    elif kind == "add_section":
        lines = [str(x) for x in op.get("lines", [])]
        if not lines or not lines[0].lstrip(BLANKS).startswith("["):
            raise PatchError("add_section 'lines' must start with a [Section] header")
        after = op.get("after")
        if after:
            at = ix.end_of_section(ix.sections(after)[-1])
        else:
            at = len(ix.flat)
        edits.append(_Edit("insert", at, lines, unit, seq))
    elif kind in ("set", "comment_out"):
        if "key" not in op:
            raise PatchError(f"{kind} needs 'key'")
        if kind == "set" and "value" not in op:
            raise PatchError("set needs 'value'")
        for sec in ix.sections(op):
            targets = _target_entries(sec, op)
            if not targets and kind == "set" and op.get("add_missing", True) \
                    and op.get("field") is None and not op.get("where"):
                edits.append(_Edit("insert", ix.end_of_entries(sec),
                                   [f"{op['key']} = {op['value']}"], unit, seq))
                continue
            for e in targets:
                if kind == "set":
                    nl = _new_line_for(e, op)
                    if nl is None:
                        continue
                    edits.append(_Edit("replace", ix.pos[id(e)], [nl], unit, seq))
                else:
                    edits.append(_Edit("replace", ix.pos[id(e)], [], unit, seq))
    else:
        raise PatchError(f"unknown op {kind!r}")
    return edits


def _check_unit(u: dict) -> None:
    uid = u.get("id")
    if not uid or not _ID_RE.match(uid):
        raise PatchError(f"bad unit id {uid!r} (allowed: letters, digits, _ . : -)")
    v = u.get("version", 1)
    if not isinstance(v, int) or v < 1:
        raise PatchError(f"unit {uid}: version must be a positive int")
    if not isinstance(u.get("ops"), list) or not u["ops"]:
        raise PatchError(f"unit {uid}: needs a non-empty 'ops' list")


def apply_units(pristine: str, units: list[dict]) -> str:
    """Apply ``units`` (in order) to ``pristine`` text that holds no carrier-mod regions."""
    if region_ids(pristine):
        raise PatchError("apply_units() needs pristine text; strip() it first")
    seen = set()
    for u in units:
        _check_unit(u)
        if u["id"].lower() in seen:
            raise PatchError(f"duplicate unit id {u['id']!r} for one file")
        seen.add(u["id"].lower())
    ix = _Index(pristine)
    lines = [[ln.text, ln.eol] for ln in ix.flat]
    eol = _dominant_eol(lines)
    edits: list[_Edit] = []
    for ui, u in enumerate(units):
        for si, op in enumerate(u["ops"]):
            edits.extend(_edits_for_op(ix, op, ui, si))
    replaced: dict[int, _Edit] = {}
    for ed in edits:
        if ed.kind == "replace":
            if ed.index in replaced:
                raise PatchError(f"two ops replace line {ed.index + 1}: units "
                                 f"{units[replaced[ed.index].unit]['id']} and {units[ed.unit]['id']}")
            replaced[ed.index] = ed
    inserts: dict[int, list[_Edit]] = {}
    for ed in edits:
        if ed.kind == "insert":
            inserts.setdefault(ed.index, []).append(ed)
    for v in inserts.values():
        v.sort(key=lambda ed: (ed.unit, ed.seq))

    # Build regions in file order. A region is either one insert edit, or a maximal run of
    # consecutive replaced lines belonging to the same unit.
    regions: list[tuple[int, list[list[str]], bool]] = []  # (unit, body lines, noeol)
    out: list[list[str] | tuple] = []
    n = len(lines)
    i = 0

    def emit_inserts(at: int):
        for ed in inserts.get(at, []):
            noeol = False
            if out and isinstance(out[-1], list) and out[-1][1] == "":
                out[-1][1] = eol
                noeol = True
            out.append(("region", ed.unit, [[t, eol] for t in ed.new], noeol))

    while i <= n:
        emit_inserts(i)
        if i == n:
            break
        if i in replaced:
            ed0 = replaced[i]
            body: list[list[str]] = []
            noeol = False
            j = i
            while j < n and j in replaced and replaced[j].unit == ed0.unit:
                t, e = lines[j]
                if e == "":
                    e = eol
                    noeol = True
                body.append([DISABLED + t, e])
                body.extend([[nt, eol] for nt in replaced[j].new])
                j += 1
                if j in inserts:
                    break
            out.append(("region", ed0.unit, body, noeol))
            i = j
            continue
        out.append(list(lines[i]))
        i += 1

    # name regions
    counts: dict[int, int] = {}
    for item in out:
        if isinstance(item, tuple):
            counts[item[1]] = counts.get(item[1], 0) + 1
    seen_k: dict[int, int] = {}
    final: list[list[str]] = []
    for item in out:
        if not isinstance(item, tuple):
            final.append(item)
            continue
        _r, ui, body, noeol = item
        u = units[ui]
        seen_k[ui] = seen_k.get(ui, 0) + 1
        rid = u["id"] if counts[ui] == 1 else f"{u['id']}#{seen_k[ui]}"
        ver = u.get("version", 1)
        final.append([f"{MARK_OPEN}{rid} v{ver}" + (" noeol" if noeol else ""), eol])
        final.extend(body)
        final.append([f"{MARK_CLOSE}{rid}", eol])
    return _render(final)


# ---------------------------------------------------------------------------------------------
# files + state

def _now() -> str:
    return _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class PatchState:
    """Per-root record of baselines and applied units (JSON)."""

    def __init__(self, path: str | os.PathLike):
        self.path = Path(path)
        self.data = {"version": 1, "files": {}, "log": []}
        if self.path.exists():
            try:
                self.data = json.loads(self.path.read_text(encoding="utf-8"))
                if not isinstance(self.data.get("files"), dict):
                    raise ValueError("no 'files' mapping")
            except (OSError, ValueError) as e:
                raise PatchError(f"patch state {self.path} is unreadable or corrupt ({e}); "
                                 "inspect it, or delete it to re-baseline every file") from None

    @staticmethod
    def key(rel: str) -> str:
        return rel.replace("\\", "/").lower()

    def file(self, rel: str) -> dict | None:
        return self.data["files"].get(self.key(rel))

    def set_file(self, rel: str, rec: dict | None) -> None:
        k = self.key(rel)
        if rec is None:
            self.data["files"].pop(k, None)
        else:
            self.data["files"][k] = rec

    def log(self, msg: str) -> None:
        self.data.setdefault("log", []).append(f"{_now()} {msg}")

    def save(self) -> None:
        refuse_play_prefix(self.path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_name(self.path.name + ".tmp")
        tmp.write_text(json.dumps(self.data, indent=1, sort_keys=True) + "\n", encoding="utf-8")
        os.replace(tmp, self.path)

    def save_or_remove(self) -> None:
        """Save; or, when no file is recorded any more (nothing left to undo), delete the state
        file so a fully unpatched install is byte-identical to the original."""
        if self.data["files"]:
            self.save()
            return
        refuse_play_prefix(self.path)
        for p in (self.path, self.path.with_name(self.path.name + ".tmp")):
            if p.exists():
                p.unlink()


def _write_atomic(path: Path, data: bytes) -> None:
    refuse_play_prefix(path)
    tmp = path.with_name(path.name + ".carrier-mod.tmp")
    tmp.write_bytes(data)
    try:
        os.chmod(tmp, path.stat().st_mode & 0o7777)
    except OSError:
        pass
    os.replace(tmp, path)


def _pristine(path: Path) -> tuple[bytes, str]:
    raw = path.read_bytes()
    txt, _ = strip(raw.decode("latin-1"))
    return raw, txt


def _check_baseline(state: PatchState, rel: str, pristine: bytes, force: bool,
                    log=print) -> None:
    rec = state.file(rel)
    got = sha256(pristine)
    if rec is None:
        return
    if rec.get("original_sha256") != got:
        if not force:
            raise PatchError(
                f"{rel}: the unpatched content changed since it was baselined "
                f"(expected {rec.get('original_sha256')}, found {got}). Something else edited "
                "this file. Re-run with --force to re-baseline.")
        msg = f"re-baselined {rel}: {rec.get('original_sha256')} -> {got} (--force)"
        state.log(msg)
        log(f"[fltools.patch] {msg}")


@dataclass
class FilePlan:
    """What applying units would do to one file (computed in memory; nothing written)."""
    rel: str
    path: Path
    raw: bytes
    out: bytes
    record: dict | None

    @property
    def changes(self) -> bool:
        return self.out != self.raw


def plan_file(root: Path, rel: str, wanted: list[dict], st: PatchState, *, force: bool = False,
              log=print) -> FilePlan:
    """Strip, check the baseline, and apply ``wanted`` units to one file, in memory. The
    target must stay under ``root`` lexically (no absolute path, no ``..``) and must not resolve
    into the play prefix (a symlinked file is refused here, before anything is written)."""
    from .ini import ci_path
    try:
        rel = contained_rel(rel)
    except UnsafePathError as e:
        raise PatchError(f"patch target: {e}") from None
    path = ci_path(root, rel)
    if path is None or not path.is_file():
        raise PatchError(f"{rel}: no such file under {root}")
    refuse_play_prefix(path, "patch")
    raw, pristine_txt = _pristine(path)
    pristine = pristine_txt.encode("latin-1")
    _check_baseline(st, rel, pristine, force, log)
    out = apply_units(pristine_txt, wanted).encode("latin-1") if wanted else pristine
    rec = ({"original_sha256": sha256(pristine), "patched_sha256": sha256(out), "units": wanted}
           if wanted else None)
    return FilePlan(rel, path, raw, out, rec)


def _commit(plan: FilePlan, st: PatchState) -> bool:
    if plan.changes:
        _write_atomic(plan.path, plan.out)
    st.set_file(plan.rel, plan.record)
    return plan.changes


def _commit_durable(plan: FilePlan, st: PatchState) -> bool:
    """Like :func:`_commit`, but the saved state always covers the file on disk, even if the
    process dies between the two writes: a file that will carry regions is recorded (and the
    state saved) before it is written; a file being restored is written before its record is
    dropped. A record whose file was not written yet is harmless: stripping finds no regions
    and the pristine sha256 still matches."""
    if plan.record is not None:
        st.set_file(plan.rel, plan.record)
        st.save()
        if plan.changes:
            _write_atomic(plan.path, plan.out)
    else:
        if plan.changes:
            _write_atomic(plan.path, plan.out)
        st.set_file(plan.rel, None)
    st.save()
    return plan.changes


def patch_file(root: str | os.PathLike, rel: str, units: list[dict], *,
               state: PatchState | None = None, force: bool = False, replace_all: bool = False,
               log=print) -> bool:
    """Apply ``units`` to ``<root>/<rel>`` (merged with already-applied units of other ids,
    unless ``replace_all``). Returns True when the file changed."""
    root = Path(root)
    refuse_play_prefix(root, "patch")
    own_state = state is None
    st = state or PatchState(root / STATE_NAME)
    rec = st.file(rel) or {}
    new_ids = {u["id"].lower() for u in units}
    wanted = [] if replace_all else [u for u in rec.get("units", [])
                                     if u["id"].lower() not in new_ids]
    wanted += [dict(u, file=rel) for u in units]
    changed = _commit_durable(plan_file(root, rel, wanted, st, force=force, log=log), st)
    if own_state:
        st.save_or_remove()
    return changed


def unpatch_file(root: str | os.PathLike, rel: str, ids: list[str] | None = None, *,
                 state: PatchState | None = None, force: bool = False, log=print) -> bool:
    """Remove all (or the given unit ids') regions from ``<root>/<rel>``."""
    from .ini import ci_path
    root = Path(root)
    refuse_play_prefix(root, "unpatch")
    own_state = state is None
    st = state or PatchState(root / STATE_NAME)
    rec = st.file(rel) or {}
    if ids is not None and not rec.get("units"):
        # no state: strip just those regions from the markers
        path = ci_path(root, rel)
        if path is None or not path.is_file():
            raise PatchError(f"{rel}: no such file under {root}")
        raw = path.read_bytes()
        out = strip(raw.decode("latin-1"), set(ids))[0].encode("latin-1")
        if out != raw:
            _write_atomic(path, out)
        return out != raw
    drop = {i.lower() for i in ids} if ids is not None else None
    keep = [] if drop is None else [u for u in rec.get("units", []) if u["id"].lower() not in drop]
    changed = _commit_durable(plan_file(root, rel, keep, st, force=force, log=log), st)
    if own_state:
        st.save_or_remove()
    return changed


def is_preserved(uid: str) -> bool:
    """True for unit ids in a reserved namespace (:data:`PRESERVED_PREFIXES`, D107)."""
    return str(uid).lower().startswith(PRESERVED_PREFIXES)


def _merge_preserved(old: list[dict], new: list[dict]) -> list[dict]:
    """``new`` plus the preserved units of ``old``, each kept right after the overlay unit it
    followed before (the last one that still exists), or first if none did. With an unchanged
    overlay the list, and so the file bytes, are unchanged; preserved units keep their order."""
    if not any(is_preserved(u["id"]) for u in old):
        return list(new)
    survivors = {u["id"].lower() for u in new}
    anchors: dict[str | None, list[dict]] = {}
    prev = None
    for u in old:
        if is_preserved(u["id"]):
            anchors.setdefault(prev, []).append(u)
        elif u["id"].lower() in survivors:
            prev = u["id"].lower()
    out = list(anchors.pop(None, []))
    for u in new:
        out.append(u)
        out.extend(anchors.pop(u["id"].lower(), []))
    return out


def plan_overlay_patches(root: str | os.PathLike, units: list[dict], *, force: bool = False,
                         state: PatchState | None = None, log=print
                         ) -> tuple[PatchState, list[FilePlan]]:
    """Compute, without writing, what :func:`apply_overlay_patches` would do. Raises
    PatchError (bad unit, reserved id, missing target, changed baseline, corrupt state) before
    any write. Units in a reserved namespace that are already applied (:func:`is_preserved`)
    are carried over unchanged, in place."""
    root = Path(root)
    refuse_play_prefix(root, "patch")
    st = state or PatchState(root / STATE_NAME)
    by_file: dict[str, list[dict]] = {}
    for u in units:
        if is_preserved(u.get("id", "")):
            raise PatchError(f"unit id {u.get('id')!r} is in a reserved namespace "
                             f"{PRESERVED_PREFIXES}; only the harness applies those (patch_file)")
        by_file.setdefault(PatchState.key(u["file"]), []).append(u)

    def wanted(k: str, us: list[dict]) -> list[dict]:
        old = (st.data["files"].get(k) or {}).get("units", [])
        return _merge_preserved(old, [dict(u) for u in us])

    plans = [plan_file(root, us[0]["file"], wanted(k, us), st, force=force, log=log)
             for k, us in sorted(by_file.items())]
    plans += [plan_file(root, k, wanted(k, []), st, force=force, log=log)
              for k in sorted(set(st.data["files"]) - set(by_file))]
    return st, plans


def apply_overlay_patches(root: str | os.PathLike, units: list[dict], *, force: bool = False,
                          state_path: str | os.PathLike | None = None, log=print) -> list[str]:
    """Make ``root`` carry exactly ``units`` (grouped by their ``file``) plus any already
    applied reserved-namespace units (D107); files patched before but absent now are restored.
    Every file is planned (and every error raised) before the first write; the state is saved
    after each file. Returns the list of changed files."""
    st = PatchState(state_path) if state_path else None
    st, plans = plan_overlay_patches(root, units, force=force, state=st, log=log)
    return commit_plans(st, plans)


def commit_plans(st: PatchState, plans: list[FilePlan]) -> list[str]:
    """Write planned files one by one; the saved state covers every file on disk at each step
    (:func:`_commit_durable`). Returns changed files."""
    changed = []
    for plan in plans:
        if _commit_durable(plan, st):
            changed.append(plan.rel)
    st.save_or_remove()
    return changed


def main(argv: list[str] | None = None) -> int:
    import argparse
    ap = argparse.ArgumentParser(prog="flpatch", description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    a1 = sub.add_parser("apply", help="apply units from a JSON file (list of units)")
    a1.add_argument("--root", required=True, help="install root (paths in units are relative)")
    a1.add_argument("units", help="JSON file: a list of units, or {'units': [...]}")
    a1.add_argument("--force", action="store_true", help="re-baseline changed files (logged)")
    a2 = sub.add_parser("unpatch", help="remove regions")
    a2.add_argument("--root", required=True)
    a2.add_argument("--file", action="append", help="install-relative file (default: all known)")
    a2.add_argument("--id", action="append", help="unit id to remove (default: all)")
    a2.add_argument("--force", action="store_true")
    a3 = sub.add_parser("status", help="list patched files and regions")
    a3.add_argument("--root", required=True)
    a = ap.parse_args(argv)
    root = Path(a.root)
    try:
        if a.cmd == "apply":
            spec = json.loads(Path(a.units).read_text(encoding="utf-8"))
            units = spec["units"] if isinstance(spec, dict) else spec
            st = PatchState(root / STATE_NAME)
            by_file: dict[str, list[dict]] = {}
            for u in units:
                by_file.setdefault(u["file"], []).append(u)
            for rel, us in by_file.items():
                ch = patch_file(root, rel, us, state=st, force=a.force)
                print(f"{'patched' if ch else 'unchanged'} {rel}")
            st.save_or_remove()
        elif a.cmd == "unpatch":
            st = PatchState(root / STATE_NAME)
            files = a.file or sorted(st.data["files"])
            for rel in files:
                ch = unpatch_file(root, rel, a.id, state=st, force=a.force)
                print(f"{'restored' if ch else 'unchanged'} {rel}")
            st.save_or_remove()
        else:
            st = PatchState(root / STATE_NAME)
            for k, rec in sorted(st.data["files"].items()):
                print(k, rec["original_sha256"][:12], [u["id"] for u in rec.get("units", [])])
    except (PatchError, RuntimeError, OSError, ValueError) as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
