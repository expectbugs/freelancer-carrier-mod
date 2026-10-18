"""Generator framework: discovery, build context, overlay output, deploy/undeploy, validate.

Overlay layout written by :func:`build` (``$FLMOD_LOCAL/gen/overlay/`` by default)::

    MANIFEST.json      what was built: generators, new files (+sha256), patch units, IDS map
    patches.json       {"version": 1, "units": [fltools.patch units]}
    files/<path>       new files, install-root relative (EXE/..., DATA/...)
    world.json         world export of install+overlay (not copied into the game)

Determinism: generators run in (ORDER, name) order; outputs carry no timestamps or absolute
paths; JSON is written with sorted keys. Same install + same repo -> identical bytes.
"""
from __future__ import annotations

import contextlib
import fcntl
import hashlib
import importlib.util
import json
import os
import shutil
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path

from fltools import patch as flpatch
from fltools import resdll, validate as flvalidate, hashscan as flhashscan
from fltools import worldexport
from fltools.ini import Document, ci_path
from fltools.install import DEPLOY_STATE, Install
from fltools.safety import (PlayPrefixError, UnsafePathError, contained_rel, is_within,
                            refuse_play_prefix)

from .strings import StringsRegistry

REPO = Path(__file__).resolve().parents[2]
GEN_DIR = REPO / "gen"
LOCAL = Path(os.environ.get("FLMOD_LOCAL", "/home/user/freelancer/carrier-mod/local"))
RESOURCE_DLL = "fcm_text.dll"
MANIFEST_SCHEMA = "fcm.overlay.v1"
MANIFEST_COPY = "carrier-mod.manifest.json"
SKIP_DIRS = {"framework", "models", "plugins", "tests", "__pycache__", "out"}
TEXT_IDS_LOCK_TIMEOUT = 600.0   # seconds to wait for the text-id map's flock (tests lower it)

__all__ = ["Context", "Generator", "discover", "build", "deploy", "undeploy", "run_validate",
           "GenError", "RESOURCE_DLL"]


class GenError(RuntimeError):
    pass


def _sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def _norm(rel: str) -> str:
    return rel.replace("\\", "/").strip("/")


def _rel(rel: str, what: str = "path") -> str:
    """A root-relative path that cannot escape its root (no absolute paths, no ``..``)."""
    try:
        return contained_rel(rel)
    except UnsafePathError as e:
        raise GenError(f"{what}: {e}") from None


def _dump_json(obj) -> bytes:
    return (json.dumps(obj, indent=1, sort_keys=True, ensure_ascii=False) + "\n").encode("utf-8")


@dataclass
class Generator:
    name: str
    path: Path
    order: int
    module: object
    enabled: bool = True


def discover(gen_dir: Path = GEN_DIR) -> list[Generator]:
    """``gen/<name>/generator.py`` and ``gen/plugins/<area>/generator.py``, sorted by
    (ORDER, name). A module may set ``ENABLED = False`` to stay out of default builds."""
    cands: list[tuple[str, Path]] = []
    if gen_dir.is_dir():
        for d in sorted(gen_dir.iterdir()):
            if d.is_dir() and d.name not in SKIP_DIRS and (d / "generator.py").is_file():
                cands.append((d.name, d / "generator.py"))
        pd = gen_dir / "plugins"
        if pd.is_dir():
            for d in sorted(pd.iterdir()):
                if d.is_dir() and (d / "generator.py").is_file():
                    cands.append((f"plugins.{d.name}", d / "generator.py"))
    gens = []
    for name, path in cands:
        spec = importlib.util.spec_from_file_location(f"fcm_gen_{name.replace('.', '_')}", path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        if not callable(getattr(mod, "generate", None)):
            raise GenError(f"{path}: no generate(ctx)")
        gens.append(Generator(name, path, int(getattr(mod, "ORDER", 500)), mod,
                              bool(getattr(mod, "ENABLED", True))))
    gens.sort(key=lambda g: (g.order, g.name))
    return gens


class Context:
    """What a generator gets. Read the install through ``ini()``/``install``; write only via
    ``write_file()`` (new files) and ``patch()`` (marker-block edits of existing files)."""

    def __init__(self, install: Install, out_dir: Path, strings: StringsRegistry,
                 ids_index: int, log=print):
        self.install = install
        self.out_dir = out_dir
        self.files_dir = out_dir / "files"
        self.strings = strings
        self.ids_index = ids_index
        self.resource_dll = RESOURCE_DLL
        self.patcher = flpatch      # fltools.patch (apply_units/strip for previews and tests)
        self.resdll = resdll        # fltools.resdll (extra DLLs; the main one is built for you)
        self.runtime_bases: list[str] = []
        self._log = log
        self.generator: str = "framework"
        self.units: list[dict] = []
        self.files: dict[str, dict] = {}
        self.data_rel = os.path.relpath(install.data_dir, install.root).replace(os.sep, "/")
        self.exe_rel = os.path.relpath(install.exe_dir, install.root).replace(os.sep, "/")

    # reading -------------------------------------------------------------------------------
    def ini(self, data_rel: str) -> Document | None:
        """A DATA-relative INI of the pristine install (cached; treat as read-only)."""
        return self.install.data_ini(data_rel)

    def exe_ini(self, rel: str) -> Document | None:
        return self.install.exe_ini(rel)

    def log(self, msg: str) -> None:
        self._log(f"[gen] {self.generator}: {msg}")

    # writing -------------------------------------------------------------------------------
    def write_file(self, root_rel: str, data: bytes | str) -> Path:
        """Add a new file to the overlay (install-root relative, e.g. ``DATA/EQUIPMENT/x.ini``).
        Refuses paths that exist in the install (HDE files are only ever patched) and paths
        that could leave the overlay (absolute, ``..``)."""
        rel = _rel(root_rel, f"{self.generator}: write_file")
        if self.install.resolver.resolve(self.install.root, rel) is not None and \
                self.install.path(rel) is not None:
            raise GenError(f"{self.generator}: {rel} exists in the install; patch it instead")
        if rel.lower() in {k.lower() for k in self.files}:
            raise GenError(f"{self.generator}: {rel} written twice")
        b = data.encode("latin-1") if isinstance(data, str) else bytes(data)
        p = self.files_dir / rel
        _check_target(p)
        if not is_within(p, self.files_dir):
            raise GenError(f"{self.generator}: {rel} resolves outside the overlay")
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b)
        self.files[rel] = {"sha256": _sha(b), "size": len(b), "generator": self.generator}
        return p

    def write_data(self, data_rel: str, data: bytes | str) -> Path:
        return self.write_file(f"{self.data_rel}/{_rel(data_rel, f'{self.generator}: write_data')}",
                               data)

    def patch(self, root_rel: str, block: str, ops: list[dict], version: int = 1) -> dict:
        """Register a patch unit for an existing install file; its id is ``<gen>.<block>``."""
        uid = f"{self.generator}.{block}" if self.generator != "framework" else f"fcm.{block}"
        if flpatch.is_preserved(uid):
            raise GenError(f"patch unit id {uid!r} is in the harness's reserved namespace "
                           f"{flpatch.PRESERVED_PREFIXES} (D107); rename the generator")
        u = {"file": _rel(root_rel, f"{self.generator}: patch"), "id": uid, "version": version,
             "ops": ops}
        if any(x["id"].lower() == uid.lower() and x["file"].lower() == u["file"].lower()
               for x in self.units):
            raise GenError(f"patch unit {uid} for {root_rel} registered twice")
        self.units.append(u)
        return u

    def add_data_file(self, key: str, data_rel: str) -> None:
        """Add ``key = data_rel`` to ``freelancer.ini [Data]`` right after the existing lines of
        the same key (keeps load order: e.g. new solars still load before ``universe``)."""
        self.patch(f"{self.exe_rel}/freelancer.ini", f"data.{key}.{_norm(data_rel).replace('/', '_')}",
                   [{"op": "append", "section": "Data", "after_key": key,
                     "lines": [f"{key} = {data_rel}"]}])

    def declare_runtime_base(self, base: str) -> None:
        """A base whose dock solar is spawned at runtime (the validator accepts it)."""
        if base not in self.runtime_bases:
            self.runtime_bases.append(base)


def _check_target(path: Path, what: str = "write into") -> Path:
    """Refuse paths inside the play prefix (fltools.safety); GenError for the CLI."""
    try:
        return refuse_play_prefix(path, what)
    except PlayPrefixError as e:
        raise GenError(str(e)) from None


def _load_json(path: Path, what: str):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise GenError(f"{what} missing: {path}") from None
    except (OSError, ValueError) as e:
        raise GenError(f"{what} {path} is unreadable or corrupt: {e}") from None


@contextlib.contextmanager
def _flock(lock_path: Path, timeout: float | None = None):
    """Exclusive flock (``$FLMOD_LOCKS/text_ids.lock`` for the shared text-id map); GenError
    after ``timeout`` seconds (default :data:`TEXT_IDS_LOCK_TIMEOUT`)."""
    if timeout is None:
        timeout = TEXT_IDS_LOCK_TIMEOUT
    _check_target(lock_path)
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(lock_path, os.O_RDWR | os.O_CREAT, 0o644)
    try:
        deadline = time.monotonic() + timeout
        while True:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() > deadline:
                    raise GenError(f"timed out waiting for {lock_path}") from None
                time.sleep(0.2)
        yield
    finally:
        os.close(fd)   # releases the lock


def _text_ids_lock(text_ids: Path) -> Path:
    if text_ids == LOCAL / "gen" / "text_ids.json":
        return Path(os.environ.get("FLMOD_LOCKS", str(LOCAL / "locks"))) / "text_ids.lock"
    return text_ids.with_name(text_ids.name + ".lock")


def build(install_root: Path, out_dir: Path | None = None, only: list[str] | None = None, *,
          text_ids: Path | None = None, data_dir: Path | None = None, world: bool = True,
          gen_dir: Path = GEN_DIR, expected_index: int | None = 8, log=print) -> dict:
    """Build an overlay from the pristine install. Returns the manifest dict. Writes only
    ``out_dir`` and ``text_ids`` (both refused inside the play prefix); the text-id map's
    read-modify-write runs under an exclusive flock."""
    out_dir = Path(out_dir) if out_dir else LOCAL / "gen" / "overlay"
    text_ids = Path(text_ids) if text_ids else LOCAL / "gen" / "text_ids.json"
    data_dir = Path(data_dir) if data_dir else REPO / "data"
    _check_target(out_dir)
    _check_target(text_ids)
    try:
        inst = Install(install_root, pristine=True)
        idx = resdll.detect_resource_index(inst, RESOURCE_DLL, expected=expected_index)
    except (OSError, ValueError, resdll.ResourceIndexError) as e:
        raise GenError(f"cannot read install {install_root}: {e}") from None
    if out_dir.exists():
        if not (out_dir / "MANIFEST.json").is_file() and any(out_dir.iterdir()):
            raise GenError(f"{out_dir} exists and is not an overlay; refusing to clear it")
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True)
    with _flock(_text_ids_lock(text_ids)):
        try:
            strings = StringsRegistry(text_ids, idx)
        except (OSError, ValueError, KeyError, TypeError) as e:
            raise GenError(f"text id map {text_ids} is unreadable or corrupt: {e}") from None
        yaml_files = strings.load_yaml_tree(data_dir)
        ctx = Context(inst, out_dir, strings, idx, log=log)
        gens = discover(gen_dir)
        names = {g.name for g in gens}
        if only:
            missing = [o for o in only if o not in names]
            if missing:
                raise GenError(f"unknown generator(s) {missing}; have {sorted(names)}")
            gens = [g for g in gens if g.name in only]
        else:
            gens = [g for g in gens if g.enabled]
        ran = []
        for g in gens:
            ctx.generator = g.name
            g.module.generate(ctx)
            ran.append({"name": g.name, "order": g.order,
                        "path": os.path.relpath(g.path, REPO).replace(os.sep, "/")})
        ctx.generator = "framework"
        dll_rel = None
        if strings.entries:
            dll_rel = f"{ctx.exe_rel}/{RESOURCE_DLL}"
            strings_t, cards_t = strings.tables()
            ctx.write_file(dll_rel, resdll.build_dll(strings_t, cards_t))
            ctx.patch(f"{ctx.exe_rel}/freelancer.ini", "resources",
                      [{"op": "append", "section": "Resources",
                        "lines": [f"DLL = {RESOURCE_DLL}"]}])
        strings.save()
    (out_dir / "patches.json").write_bytes(_dump_json({"version": 1, "units": ctx.units}))
    patched: dict[str, list[str]] = {}
    for u in ctx.units:
        patched.setdefault(u["file"], []).append(u["id"])
    manifest = {
        "schema": MANIFEST_SCHEMA,
        "generators": ran,
        "files": dict(sorted(ctx.files.items())),
        "patched_files": [{"file": f, "units": ids} for f, ids in sorted(patched.items())],
        "patches_sha256": _sha((out_dir / "patches.json").read_bytes()),
        "resource_dll": dll_rel,
        "ids_index": idx,
        "text_ids": strings.manifest(),
        "strings_sources": [os.path.relpath(p, REPO).replace(os.sep, "/") for p in yaml_files],
        "runtime_bases": sorted(ctx.runtime_bases),
    }
    (out_dir / "MANIFEST.json").write_bytes(_dump_json(manifest))
    if world:
        w = worldexport.export(Install(install_root, out_dir, pristine=True))
        wb = worldexport.dumps(w).encode("utf-8")
        (out_dir / "world.json").write_bytes(wb)
        manifest["world_json_sha256"] = _sha(wb)
        (out_dir / "MANIFEST.json").write_bytes(_dump_json(manifest))
    return manifest


# ---------------------------------------------------------------------------------------------
# deploy state: {"version": 2, "status": "in_progress"|"complete", "manifest_sha256": ...,
#                "files": {install-rel path: {"sha256": <deployed>, "accept": [<shas we may
#                remove or overwrite>]}}, "dirs": [install-rel dirs a deploy created]}
TMP_SUFFIX = ".carrier-mod.tmp"     # atomic-write temp names (copies here, patched files in patch)

def _accept(rec) -> set[str]:
    if isinstance(rec, str):            # version 1 state: plain sha
        return {rec}
    if isinstance(rec, dict):
        return set(rec.get("accept") or []) | ({rec["sha256"]} if rec.get("sha256") else set())
    return set()


def _state(root: Path) -> dict:
    p = root / DEPLOY_STATE
    if not p.exists():
        return {"version": 2, "status": "complete", "files": {}}
    st = _load_json(p, "deploy state")
    if not isinstance(st, dict) or not isinstance(st.get("files"), dict) or \
            not isinstance(st.get("dirs") or [], list):
        raise GenError(f"deploy state {p} is corrupt (no 'files' mapping)")
    for rel in list(st["files"]) + list(st.get("dirs") or []):
        try:
            if contained_rel(rel) != rel:
                raise UnsafePathError(f"non-canonical path {rel!r}")
        except UnsafePathError as e:
            raise GenError(f"deploy state {p} is corrupt: {e}") from None
    return st


def _save_state(root: Path, st: dict) -> None:
    p = root / DEPLOY_STATE
    _check_target(p)
    tmp = p.with_name(p.name + ".tmp")
    tmp.write_bytes(_dump_json(st))
    os.replace(tmp, p)


def _target_path(root: Path, rel: str) -> Path:
    """Map an overlay path onto the install, reusing existing directories' case."""
    parts = _norm(rel).split("/")
    cur = root
    for i, part in enumerate(parts):
        hit = ci_path(cur, part)
        if hit is not None and (i < len(parts) - 1 and hit.is_dir()):
            cur = hit
        elif i == len(parts) - 1 and hit is not None:
            cur = hit
        else:
            cur = cur / part
    return cur


def _copy_atomic(src: Path, dst: Path) -> None:
    _check_target(dst)
    dst.parent.mkdir(parents=True, exist_ok=True)
    tmp = dst.with_name(dst.name + TMP_SUFFIX)
    shutil.copyfile(src, tmp)
    os.replace(tmp, dst)


_FAIL = (OSError, ValueError, KeyError, TypeError, AttributeError, flpatch.PatchError,
         resdll.ResourceIndexError, PlayPrefixError)
DEPLOY_LOCK_TIMEOUT = 900.0     # seconds to wait for another deploy/undeploy of the same install


def deploy_lock_path(root: Path) -> Path:
    """``$FLMOD_LOCKS/deploy-<sha256(realpath(root))[:16]>.lock``."""
    key = hashlib.sha256(os.path.realpath(root).encode("utf-8", "surrogateescape")).hexdigest()
    return Path(os.environ.get("FLMOD_LOCKS", str(LOCAL / "locks"))) / f"deploy-{key[:16]}.lock"


def _deploy_lock(root: Path):
    """Per-install exclusive flock: two deploys/undeploys of one install never interleave (any
    worktree, any lane). GenError after :data:`DEPLOY_LOCK_TIMEOUT` seconds."""
    return _flock(deploy_lock_path(root), timeout=DEPLOY_LOCK_TIMEOUT)


def _temp_base() -> Path:
    """Where the temp overlay goes: ``$TMPDIR``/``$TEMP``/``$TMP`` or /tmp, as tempfile would
    pick, but WITHOUT tempfile's probe write, and refused inside a protected prefix."""
    for var in ("TMPDIR", "TEMP", "TMP"):
        if os.environ.get(var):
            base = Path(os.environ[var])
            break
    else:
        base = Path("/tmp")
    _check_target(base, "create temporary files in")
    return base


def deploy(install_root: Path, overlay: Path | None = None, *, force: bool = False,
           log=print, **build_kw) -> dict:
    """Build into a temp overlay (unless ``overlay`` is given), then install it.

    Transactional: every check (manifest, file hashes and paths, [Resources] index, foreign or
    changed files, every patch unit applied in memory against its baseline) runs before the
    first write. The deploy state records each file before it is copied, so ``undeploy`` / a
    re-deploy can always recover from an interrupted deploy. Runs under the install's deploy
    lock. Errors surface as GenError."""
    root = Path(install_root)
    _check_target(root)
    build_kw.setdefault("world", False)
    tmp = None
    with _deploy_lock(root):
        try:
            if overlay is None:
                tmp = Path(tempfile.mkdtemp(prefix="fcm-overlay-", dir=_temp_base()))
                overlay = tmp / "overlay"
                build(root, overlay, log=log, **build_kw)
            ov = Path(overlay)
            return _deploy(root, ov, force, log)
        except _FAIL as e:
            raise GenError(f"deploy failed: {type(e).__name__}: {e}") from None
        finally:
            if tmp is not None:
                shutil.rmtree(tmp, ignore_errors=True)


def _deploy(root: Path, ov: Path, force: bool, log) -> dict:
    # ---- checks (no writes) ----
    man = _load_json(ov / "MANIFEST.json", "overlay manifest")
    pj = _load_json(ov / "patches.json", "overlay patches")
    if not isinstance(man, dict) or man.get("schema") != MANIFEST_SCHEMA:
        raise GenError(f"{ov}/MANIFEST.json is not a {MANIFEST_SCHEMA} manifest")
    units = pj.get("units") if isinstance(pj, dict) else None
    if not isinstance(units, list):
        raise GenError(f"{ov}/patches.json has no 'units' list")
    if man.get("patches_sha256") and \
            _sha((ov / "patches.json").read_bytes()) != man["patches_sha256"]:
        raise GenError(f"{ov}/patches.json does not match its manifest sha256")
    files = man.get("files")
    if not isinstance(files, dict) or not all(
            isinstance(i, dict) and isinstance(i.get("sha256"), str) for i in files.values()):
        raise GenError(f"{ov}/MANIFEST.json: 'files' must map paths to {{'sha256': ...}}")
    for rel, info in files.items():
        if _rel(rel, "overlay manifest") != rel:
            raise GenError(f"overlay manifest: non-canonical path {rel!r}")
        src = ov / "files" / rel
        if not src.is_file() or _sha(src.read_bytes()) != info["sha256"]:
            raise GenError(f"overlay file {rel} is missing or does not match its manifest sha256")
    st = _state(root)
    old = st["files"]
    if man.get("resource_dll"):
        resdll.detect_resource_index(Install(root, pristine=True), RESOURCE_DLL,
                                     expected=man.get("ids_index"))
    pst, plans = flpatch.plan_overlay_patches(root, units, force=force, log=log)
    copies = []
    for rel, info in sorted(files.items()):
        dst = _target_path(root, rel)
        _check_target(dst)
        if not is_within(dst.parent, root):
            raise GenError(f"overlay file {rel} would land outside the install root "
                           f"({os.path.realpath(dst.parent)})")
        drel = os.path.relpath(dst, root).replace(os.sep, "/")
        if dst.exists():
            if drel not in old:
                raise GenError(f"{drel} exists in the install and is not ours")
            cur = _sha(dst.read_bytes())
            if cur not in _accept(old[drel]) and cur != info["sha256"] and not force:
                raise GenError(f"{drel} changed since we deployed it (--force to replace)")
        copies.append((ov / "files" / rel, dst, drel, info["sha256"]))
    new_rels = {c[2] for c in copies}
    dirs = set(st.get("dirs") or [])          # directories we created, removed by undeploy
    for _src, dst, _drel, _sha256 in copies:
        d = dst.parent
        while d != root and root in d.parents and not d.exists():
            dirs.add(os.path.relpath(d, root).replace(os.sep, "/"))
            d = d.parent
    removals = []
    for drel, rec in sorted(old.items()):
        if drel in new_rels:
            continue
        p = root / drel
        if p.exists() and _sha(p.read_bytes()) not in _accept(rec) and not force:
            raise GenError(f"{drel} changed since we deployed it (--force to remove)")
        removals.append(p)

    # ---- writes: record intent first, so an interruption is always recoverable ----
    intent = {drel: {"sha256": None, "accept": sorted(_accept(rec))} for drel, rec in old.items()}
    for _src, _dst, drel, sha in copies:
        intent[drel] = {"sha256": sha, "accept": sorted(_accept(old.get(drel)) | {sha})}
    _save_state(root, {"version": 2, "status": "in_progress", "files": dict(sorted(intent.items())),
                       "dirs": sorted(dirs)})
    for src, dst, _drel, _sha256 in copies:
        _copy_atomic(src, dst)
    for p in removals:
        if p.exists():
            _check_target(p)
            p.unlink()
    changed = flpatch.commit_plans(pst, plans)
    final = {drel: {"sha256": sha, "accept": [sha]} for _s, _d, drel, sha in copies}
    _save_state(root, {"version": 2, "status": "complete", "files": dict(sorted(final.items())),
                       "dirs": sorted(dirs),
                       "manifest_sha256": _sha((ov / "MANIFEST.json").read_bytes())})
    _copy_atomic(ov / "MANIFEST.json", root / MANIFEST_COPY)
    log(f"[gen] deployed {len(copies)} files, patched {len(changed)} files into {root}")
    return {"files": sorted(new_rels), "patched": changed, "manifest": man}


def undeploy(install_root: Path, *, force: bool = False, log=print) -> dict:
    """Remove every file and patch region a deploy added (also after an interrupted deploy);
    the install returns to its original bytes. Checks everything before the first write, runs
    under the install's deploy lock, and deletes the deploy state LAST, so a kill at any point
    leaves a state that a re-run of undeploy (or deploy) completes from."""
    root = Path(install_root)
    _check_target(root)
    with _deploy_lock(root):
        try:
            st = _state(root)
            pst, plans = flpatch.plan_overlay_patches(root, [], force=force, log=log)
            doomed = []
            for drel, rec in sorted(st["files"].items()):
                p = root / drel
                if p.exists():
                    _check_target(p)
                    if _sha(p.read_bytes()) not in _accept(rec) and not force:
                        raise GenError(f"{drel} changed since we deployed it (--force to remove)")
                    doomed.append((drel, p))
            for _drel, p in doomed:
                p.unlink()
            changed = flpatch.commit_plans(pst, plans)
            # leftovers of an interrupted deploy: our atomic-write temp files (exact names only)
            leftovers = [root / (drel + TMP_SUFFIX) for drel in st["files"]]
            leftovers += [pl.path.with_name(pl.path.name + TMP_SUFFIX) for pl in plans]
            leftovers += [root / (MANIFEST_COPY + TMP_SUFFIX), root / (MANIFEST_COPY + ".tmp"),
                          root / (flpatch.STATE_NAME + ".tmp"), root / (DEPLOY_STATE + ".tmp")]
            # the patch state stays while it still records harness units (D107)
            leftovers += [root / MANIFEST_COPY] + ([] if pst.data["files"]
                                                   else [root / flpatch.STATE_NAME])
            for p in leftovers:
                if p.is_file():
                    _check_target(p)
                    p.unlink()
            for drel in sorted(st.get("dirs") or [], key=lambda d: d.count("/"), reverse=True):
                p = root / drel
                if p.is_dir() and not any(p.iterdir()):
                    _check_target(p)
                    p.rmdir()
            p = root / DEPLOY_STATE                       # last: it lists what to clean up
            if p.exists():
                _check_target(p)
                p.unlink()
        except _FAIL as e:
            raise GenError(f"undeploy failed: {type(e).__name__}: {e}") from None
    removed = [d for d, _p in doomed]
    log(f"[gen] undeployed: removed {len(removed)} files, restored {len(changed)} files")
    return {"removed": removed, "restored": changed}


def run_validate(install_root: Path, overlay: Path | None = None, *, baseline=None,
                 log=print) -> tuple[int, dict]:
    try:
        inst = Install(install_root, overlay)
        rep = flvalidate.validate(inst, baseline=baseline)
        hs = flhashscan.scan(Install(install_root, overlay))
    except _FAIL as e:
        raise GenError(f"validate failed: {type(e).__name__}: {e}") from None
    for f in rep.findings:
        if f.severity in ("ERROR", "WARNING"):
            log(f.render())
    for c in hs.createid_collisions:
        log(f"ERROR    HASH CreateID collision {c}")
    for c in hs.faction_collisions:
        log(f"ERROR    HASH faction-hash collision {c}")
    summary = {"validate": {s: rep.count(s) for s in ("ERROR", "WARNING", "BASELINE", "INFO")},
               "hashscan": hs.summary()}
    rc = 1 if (rep.errors or not hs.ok) else 0
    log(f"[gen] validate: {summary['validate']}; nicknames {len(hs.nicknames)}, "
        f"CreateID collisions {len(hs.createid_collisions)}, factions {len(hs.factions)}, "
        f"faction collisions {len(hs.faction_collisions)} -> {'FAIL' if rc else 'PASS'}")
    return rc, summary
