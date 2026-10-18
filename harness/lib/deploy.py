#!/usr/bin/env python3
"""Deploy a build into a held lane (REQ-P0-HARNESS-10). Called by harness/deploy.sh after the lane-scoped
wineserver kill and the HDE refresh from the baseline.

  deploy.py --lane N --hde <HDE dir> --track A|B --artifacts <dir> [--dacom-lib X.dll ...] [--fluf-module X.dll ...]
            [--overlay <dir>] [--pipeline auto|skip] [--repo <worktree root>]

- --dacom-lib: copy <artifacts>/X.dll to EXE/ and list it at the end of dacom.ini [Libraries] through the
  fltools patch unit `harness.dacom` (D107: one writer of record per file; `gen/run.py deploy`/`undeploy` keep
  `harness.*` units in place, tools/fltools/README.md "Reserved unit namespace"). Without --dacom-lib the unit is
  removed (`unpatch_file`). The region reads `; >>> carrier-mod harness.dacom v1` ... `; <<< carrier-mod harness.dacom`.
  run.sh/verdict.py then check that every listed DLL really loaded (`dll_not_loaded`).
- --fluf-module (Track A): copy to EXE/fluf/modules/ and add to FLUF.yml clientConfig.modules.
- --overlay: copy files onto the HDE dir; new files only, unless <overlay>/overlay_manifest.json lists the
  relative path under "patches" (then the HDE file is replaced and recorded).
- data pipeline: `<repo>/gen/run.py deploy --install <HDE>` if present, else skipped with a log line.
- writes <HDE>/DEPLOY_MANIFEST.json (git SHA, every deployed file's sha256).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

LIB = Path(__file__).resolve().parent
sys.path.insert(0, str(LIB))
from baseline_tweaks import read_lines, write_lines  # noqa: E402

MARK = "carrier-mod"
DACOM_UNIT = "harness.dacom"


def sha256(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for c in iter(lambda: f.read(1 << 20), b""):
            h.update(c)
    return h.hexdigest()


def log(msg: str) -> None:
    print(f"[deploy] {msg}", file=sys.stderr, flush=True)


def _fltools(repo: Path):
    """fltools.patch from this checkout (tools/fltools, P0-DATATOOLS)."""
    tools = str(repo / "tools")
    if tools not in sys.path:
        sys.path.insert(0, tools)
    from fltools import patch as flpatch  # noqa: E402
    return flpatch


def drop_legacy_block(hde: Path) -> None:
    """Remove the pre-D107 `; >>> carrier-mod` ... `; <<< carrier-mod` block (lanes deployed before the switch)."""
    p = hde / "EXE" / "dacom.ini"
    lines, eol = read_lines(p)
    out, skip = [], False
    for ln in lines:
        s = ln.strip()
        if s == f"; >>> {MARK}":
            skip = True
            continue
        if s == f"; <<< {MARK}":
            skip = False
            continue
        if not skip:
            out.append(ln)
    if out != lines:
        write_lines(p, out, eol)


def dacom_block(hde: Path, libs: list[str], repo: Path) -> list[str]:
    """Apply (libs) or remove (no libs) the `harness.dacom` patch unit in EXE/dacom.ini [Libraries]."""
    flpatch = _fltools(repo)
    drop_legacy_block(hde)
    if libs:
        unit = {"id": DACOM_UNIT, "version": 1,
                "ops": [{"op": "append", "section": "Libraries", "lines": list(libs)}]}
        flpatch.patch_file(hde, "EXE/dacom.ini", [unit], log=log)
    else:
        try:
            flpatch.unpatch_file(hde, "EXE/dacom.ini", [DACOM_UNIT], log=log)
        except flpatch.PatchError as e:
            log(f"no {DACOM_UNIT} unit to remove ({e})")
    return list(libs)


def dacom_listed(hde: Path, libs: list[str]) -> list[str]:
    """The libs that are NOT listed (uncommented) in dacom.ini [Libraries] right now."""
    text = (hde / "EXE" / "dacom.ini").read_text(errors="replace")
    sec, have = None, set()
    for ln in text.splitlines():
        s = ln.split(";", 1)[0].strip()
        if s.startswith("["):
            sec = s.strip("[]").strip().lower()
        elif sec == "libraries" and s:
            have.add(s.split()[0].lower())
    return [x for x in libs if x.lower() not in have]


def fluf_modules(hde: Path, mods: list[str]) -> None:
    import yaml

    p = hde / "EXE" / "fluf" / "FLUF.yml"
    if not p.exists():
        sys.exit("deploy: --fluf-module needs EXE/fluf/FLUF.yml (Track A baseline)")
    d = yaml.safe_load(p.read_text()) or {}
    cc = d.setdefault("clientConfig", {}) or {}
    d["clientConfig"] = cc
    cur = list(cc.get("modules") or [])
    for m in mods:
        if m not in cur:
            cur.append(m)
    cc["modules"] = cur
    p.write_text(yaml.safe_dump(d, sort_keys=False, default_flow_style=False))


def overlay(hde: Path, src: Path, manifest: dict) -> list[str]:
    patches = set()
    mf = src / "overlay_manifest.json"
    if mf.exists():
        patches = set(json.loads(mf.read_text()).get("patches", []))
    done = []
    for f in sorted(src.rglob("*")):
        if not f.is_file() or f == mf:
            continue
        rel = f.relative_to(src).as_posix()
        dst = hde / rel
        if dst.exists() and rel not in patches:
            sys.exit(f"deploy: overlay would overwrite HDE file {rel} (not listed as a patch in overlay_manifest.json)")
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(f, dst)
        manifest["files"][rel] = sha256(dst)
        done.append(rel)
    return done


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--lane", type=int, required=True)
    ap.add_argument("--hde", required=True)
    ap.add_argument("--track", choices="AB", required=True)
    ap.add_argument("--artifacts")
    ap.add_argument("--dacom-lib", action="append", default=[])
    ap.add_argument("--fluf-module", action="append", default=[])
    ap.add_argument("--overlay")
    ap.add_argument("--pipeline", choices=["auto", "skip"], default="auto")
    ap.add_argument("--repo", required=True)
    ap.add_argument("--git-sha", default="unknown")
    a = ap.parse_args()
    hde = Path(a.hde)
    if not re.match(r"^/home/user/freelancer/prefix-lane-\d+/", str(hde) + "/"):
        sys.exit(f"deploy: refusing non-lane HDE dir {hde}")
    man = {"lane": a.lane, "track": a.track, "git_sha": a.git_sha, "time": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
           "files": {}, "dacom_libraries": [], "fluf_modules": [], "overlay": [], "pipeline": None}
    art = Path(a.artifacts) if a.artifacts else None
    prev = {}
    if (hde / "DEPLOY_MANIFEST.json").exists():
        prev = json.loads((hde / "DEPLOY_MANIFEST.json").read_text()).get("files", {})
    if (a.dacom_lib or a.fluf_module) and not art:
        sys.exit("deploy: --artifacts <dir> is required with --dacom-lib/--fluf-module")
    for dll in a.dacom_lib:
        src = art / dll
        if not src.is_file():
            sys.exit(f"deploy: {src} not found")
        dst = hde / "EXE" / dll
        if dst.exists() and f"EXE/{dll}" not in prev:
            sys.exit(f"deploy: refusing to overwrite HDE file EXE/{dll} (not deployed by us)")
        shutil.copy2(src, dst)
        man["files"][f"EXE/{dll}"] = sha256(dst)
        for extra in (src.with_suffix(".pdb"),):
            if extra.exists():
                shutil.copy2(extra, hde / "EXE" / extra.name)
    if a.dacom_lib:
        man["dacom_libraries"] = dacom_block(hde, a.dacom_lib, Path(a.repo))
        log(f"dacom.ini [Libraries] unit {DACOM_UNIT}: {a.dacom_lib}")
    else:
        dacom_block(hde, [], Path(a.repo))
    if a.fluf_module:
        if a.track != "A":
            sys.exit("deploy: --fluf-module is Track A only")
        for dll in a.fluf_module:
            src = art / dll
            if not src.is_file():
                sys.exit(f"deploy: {src} not found")
            dst = hde / "EXE" / "fluf" / "modules" / dll
            shutil.copy2(src, dst)
            man["files"][f"EXE/fluf/modules/{dll}"] = sha256(dst)
        fluf_modules(hde, a.fluf_module)
        man["fluf_modules"] = a.fluf_module
        log(f"FLUF.yml clientConfig.modules += {a.fluf_module}")
    if a.overlay:
        man["overlay"] = overlay(hde, Path(a.overlay), man)
        log(f"overlay: {len(man['overlay'])} files")
    gen = Path(a.repo) / "gen" / "run.py"
    if a.pipeline == "skip":
        man["pipeline"] = "skipped (--pipeline skip)"
    elif gen.exists():
        py = os.path.join(os.environ.get("FLMOD_VENV", "/home/user/freelancer/carrier-mod/.venv"), "bin", "python")
        r = subprocess.run([py, "-I", str(gen), "deploy", "--install", str(hde)], cwd=a.repo)
        man["pipeline"] = f"gen/run.py deploy rc={r.returncode}"
        if r.returncode != 0:
            (hde / "DEPLOY_MANIFEST.json").write_text(json.dumps(man, indent=2) + "\n")
            sys.exit(f"deploy: data pipeline failed rc={r.returncode}")
    else:
        man["pipeline"] = "skipped (gen/run.py absent)"
        log("data pipeline: gen/run.py absent; skipped")
    # the data pipeline must have left our unit alone (D107); a DLL that is not listed would silently not load
    missing = dacom_listed(hde, man["dacom_libraries"])
    if missing:
        (hde / "DEPLOY_MANIFEST.json").write_text(json.dumps(man, indent=2) + "\n")
        sys.exit(f"deploy: dacom.ini [Libraries] does not list {missing} after the pipeline (harness.dacom lost)")
    for rel in ("EXE/dacom.ini",) + (("EXE/fluf/FLUF.yml",) if a.track == "A" else ()):
        if (hde / rel).exists():
            man["files"][rel] = sha256(hde / rel)
    (hde / "DEPLOY_MANIFEST.json").write_text(json.dumps(man, indent=2) + "\n")
    print(json.dumps({"deployed": True, "manifest": str(hde / "DEPLOY_MANIFEST.json"), "files": len(man["files"])}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
