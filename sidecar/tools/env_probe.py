#!/usr/bin/env python3
"""Print the environment run.sh gives the sidecar, as JSON (launcher diagnostics).

    sidecar/run.sh --tool env_probe
"""
import json
import os
import sys

print(json.dumps({
    "python": sys.version.split()[0],
    "prefix": sys.prefix,
    "ld_library_path": os.environ.get("LD_LIBRARY_PATH", "").split(":") if os.environ.get("LD_LIBRARY_PATH") else [],
    "hf_hub_offline": os.environ.get("HF_HUB_OFFLINE"),
    "pythonpath": os.environ.get("PYTHONPATH"),
    "no_user_site": bool(sys.flags.no_user_site),
    "safe_path": bool(sys.flags.safe_path),
    "sys_path0": sys.path[0] if sys.path else None,
}, indent=2))
