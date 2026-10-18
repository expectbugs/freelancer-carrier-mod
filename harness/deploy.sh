#!/bin/bash
# Deploy a build into a held lane (REQ-P0-HARNESS-10, TESTING §Lanes "Freshness").
#   deploy.sh --lane N [--artifacts <dir>] [--dacom-lib <name.dll> ...] [--fluf-module <dll> ...] [--overlay <dir>]
#             [--pipeline auto|skip] [--no-refresh] [--fixture <spec-name> ...]
# Steps: lane-scoped wineserver -k/-w; rsync --delete the HDE dir from the lane's baseline (unless --no-refresh);
# copy DLLs + dacom.ini marker block (`; >>> carrier-mod` ... `; <<< carrier-mod`, end of [Libraries]);
# FLUF modules (Track A); overlay (new files only unless manifest-listed patches); gen/run.py deploy if present;
# fixtures (harness/fixtures/gen_fixture.py) into the lane's save dir; <HDE>/DEPLOY_MANIFEST.json.
source /home/user/freelancer/carrier-mod/tools/env.sh
source "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")/lib/common.sh"
set -u

lane=""; refresh=1; fixtures=(); pass=()
while [ $# -gt 0 ]; do
  case "$1" in
    --lane) lane=$2; pass+=("$1" "$2"); shift ;;
    --no-refresh) refresh=0 ;;
    --fixture) fixtures+=("$2"); shift ;;
    --artifacts) pass+=("$1" "$(realpath -m -- "$2")"); shift ;;
    --overlay) pass+=("$1" "$(realpath -m -- "$2")"); shift ;;
    --dacom-lib|--fluf-module|--pipeline) pass+=("$1" "$2"); shift ;;
    *) hdie "deploy: unknown option $1" 2 ;;
  esac; shift
done
[ -n "$lane" ] || hdie "usage: deploy.sh --lane N ..." 2
envf="$FLMOD_LOCKS/lane-$lane.env"
[ -f "$envf" ] || hdie "lane $lane is not held (harness/lane.sh acquire)"
eval "$(cat "$envf")"
assert_owned_prefix "$WINEPREFIX"
base=$(base_prefix "$LANE_TRACK")

lane_wineserver_kill "$WINEPREFIX"
if [ "$refresh" = 1 ]; then
  hlog "refreshing lane $lane HDE dir from $(basename "$base") (rsync --delete)"
  with_baseline_lock -s "$LANE_TRACK" rsync -a --delete "$(hde_of "$base")/" "$HDE/" || hdie "rsync refresh failed"
  mkdir -p "$FL_SAVEDIR" "$FL_DEVBRIDGE_DIR"
fi

hpy "$HARNESS_DIR/lib/deploy.py" --hde "$HDE" --track "$LANE_TRACK" --repo "$(cd "$HARNESS_DIR/.." && pwd)" \
    --git-sha "$(git_sha)" "${pass[@]}" || hdie "deploy failed"

for f in "${fixtures[@]}"; do
  hpy "$HARNESS_DIR/fixtures/gen_fixture.py" --install "$HDE" --spec "$f" --out "$FL_SAVEDIR" || hdie "fixture $f failed"
done
hlog "deployed lane $lane"
