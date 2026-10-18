#!/bin/bash
# Launch the game on a held lane, drive it, collect evidence, tear down (REQ-P0-HARNESS-11).
#   run.sh --lane N [--save <pattern>] [--timeout S] [--cmds <file>] [--name <run-name>] [--expect <regex> ...]
#          [--load-method auto|fluf|devbridge|none] [--launch-in-space] [--renderer auto|dxvk|wined3d|wined3d-sw]
#          [--no-quit] [--keep-running] [--hang-s S] [--hold-s S] [--spew-check strict|report] [--shot <name> ...]
#   (full list: run.sh --help)
# --cmds lines: devbridge commands (`!` prefix = failure expected; `[timeout_s=N]` prefix = runner budget for a long
# command, not sent; `perf <s>` gets s+30 automatically) and runner steps (@sleep, @shot, @key, @console, @click,
# @wait_state; README.md). Keys/clicks need a lane acquired with --input.
# Run dir: $FLMOD_TESTRUNS/<UTC YYYYmmdd-HHMMSS>-lane<N>-<name>/ (printed as `rundir=`). Exit 0 iff verdict PASS.
# The lane must be held (harness/lane.sh acquire) for the whole run: the run aborts if the lock holder dies.
source /home/user/freelancer/carrier-mod/tools/env.sh
source "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")/lib/common.sh"
exec "$FLMOD_VENV/bin/python" -I "$HARNESS_DIR/lib/runner.py" "$@"
