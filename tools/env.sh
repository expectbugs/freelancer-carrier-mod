# Build environment. Sourced by every shell that may run game/wine tools, and loaded into the
# orchestrator session via CLAUDE_ENV_FILE (tools/start-build.sh). See docs/plan/CONVENTIONS.md §1, §15.
export FLMOD_REPO=/home/user/freelancer/carrier-mod
export FLMOD_LOCAL=$FLMOD_REPO/local
export FLMOD_RESEARCH=$FLMOD_LOCAL/research
export FLMOD_REFS=/home/user/freelancer/refs
export FLMOD_LOCKS=$FLMOD_LOCAL/locks
export FLMOD_TESTRUNS=$FLMOD_LOCAL/testruns
export FLMOD_GOLDEN=$FLMOD_LOCAL/golden
export FLMOD_VENDOR=$FLMOD_REPO/vendor
export FLMOD_VENV=$FLMOD_REPO/.venv
export FLMOD_SIDECAR_VENV=$FLMOD_LOCAL/sidecar-venv
export FLMOD_MODELS=$FLMOD_LOCAL/models
export FLMOD_PLAY_PREFIX=/home/user/freelancer/prefix      # NEVER modify
export XWIN_ROOT=/home/user/opt/xwin
export DISPLAY=${DISPLAY:-:0}
export HF_HUB_OFFLINE=1
case ":$PATH:" in *":$FLMOD_REPO/tools/bin:"*) ;; *) export PATH="$FLMOD_REPO/tools/bin:/usr/lib/llvm/22/bin:$PATH" ;; esac
# Sentinel: any wine call without an explicit allowed prefix is refused by the guards; an unguarded wine
# would create a junk prefix here instead of touching ~/.wine.
export WINEPREFIX=/home/user/freelancer/prefix-UNSET
mkdir -p "$FLMOD_LOCKS" "$FLMOD_TESTRUNS" "$FLMOD_GOLDEN" "$FLMOD_MODELS" 2>/dev/null || true
