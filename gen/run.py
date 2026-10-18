#!/usr/bin/env python3
"""The single generator entry point (P0-DATATOOLS REQ-11).

    gen/run.py build    --install <HDE dir> [--out <dir>] [--only <gen>[,<gen>...]]
    gen/run.py deploy   --install <HDE dir> [--overlay <built dir>] [--force]
    gen/run.py undeploy --install <HDE dir> [--force]
    gen/run.py validate --install <HDE dir> [--overlay <dir>] [--json <file>]
    gen/run.py list

Run with ``$FLMOD_VENV/bin/python -I gen/run.py ...``. ``build`` never writes into the install;
``deploy``/``undeploy`` write only into the install given (refused inside the play prefix).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
for _p in (str(_REPO / "tools"), str(_REPO)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from fltools.patch import PatchError  # noqa: E402
from fltools.resdll import ResourceIndexError  # noqa: E402
from fltools.safety import PlayPrefixError, refuse_play_prefix  # noqa: E402
from gen.framework import core  # noqa: E402
from gen.framework.strings import StringsError  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="gen/run.py", description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build", help="build an overlay (never touches the install)")
    b.add_argument("--install", required=True)
    b.add_argument("--out", help="overlay dir (default $FLMOD_LOCAL/gen/overlay)")
    b.add_argument("--only", help="comma-separated generator names")
    b.add_argument("--text-ids", help="text id map (default $FLMOD_LOCAL/gen/text_ids.json)")
    b.add_argument("--data-dir", help="strings YAML root (default <repo>/data)")
    b.add_argument("--no-world", action="store_true", help="skip world.json")
    d = sub.add_parser("deploy", help="build (or take --overlay) and install into a lane copy")
    d.add_argument("--install", required=True)
    d.add_argument("--overlay", help="deploy this already-built overlay")
    d.add_argument("--only")
    d.add_argument("--text-ids")
    d.add_argument("--data-dir")
    d.add_argument("--force", action="store_true", help="re-baseline changed files (logged)")
    u = sub.add_parser("undeploy", help="remove everything a deploy added")
    u.add_argument("--install", required=True)
    u.add_argument("--force", action="store_true")
    v = sub.add_parser("validate", help="cross-reference validator + hash scan")
    v.add_argument("--install", required=True)
    v.add_argument("--overlay")
    v.add_argument("--json", help="write a JSON summary here")
    sub.add_parser("list", help="list discovered generators")
    a = ap.parse_args(argv)
    try:
        if a.cmd == "build":
            only = [x for x in (a.only or "").split(",") if x] or None
            m = core.build(Path(a.install), Path(a.out) if a.out else None, only,
                           text_ids=a.text_ids, data_dir=a.data_dir, world=not a.no_world)
            print(f"[gen] built {len(m['files'])} files, {len(m['patched_files'])} patched files, "
                  f"{len(m['text_ids'])} strings (IDS index {m['ids_index']}) from "
                  f"{[g['name'] for g in m['generators']]}")
        elif a.cmd == "deploy":
            kw = {}
            if not a.overlay:
                kw = {"only": [x for x in (a.only or "").split(",") if x] or None,
                      "text_ids": a.text_ids, "data_dir": a.data_dir}
            core.deploy(Path(a.install), Path(a.overlay) if a.overlay else None, force=a.force,
                        **kw)
        elif a.cmd == "undeploy":
            core.undeploy(Path(a.install), force=a.force)
        elif a.cmd == "validate":
            if a.json:
                refuse_play_prefix(a.json)
            rc, summary = core.run_validate(Path(a.install),
                                            Path(a.overlay) if a.overlay else None)
            if a.json:
                Path(a.json).write_text(json.dumps(summary, indent=1, sort_keys=True) + "\n",
                                        encoding="utf-8")
            return rc
        elif a.cmd == "list":
            for g in core.discover():
                print(f"{g.order:5} {g.name:30} {'' if g.enabled else '(disabled) '}{g.path}")
    except (core.GenError, PatchError, ResourceIndexError, StringsError,
            PlayPrefixError) as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1
    except (OSError, ValueError, KeyError) as e:      # corrupt JSON, bad paths, ...
        print(f"ERROR: {type(e).__name__}: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
