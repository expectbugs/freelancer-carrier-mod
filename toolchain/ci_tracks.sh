# toolchain/ci_tracks.sh: sourced by harness/ci.d/10-build.sh and 50-import-check.sh, so both stages pick the
# same win32 tracks (review r2 F4). Not executable on its own.
#
# flmod_ci_win32_tracks
#   in:  FLMOD_TRACK (A | B | unset/empty = every track whose inputs exist), XWIN_ROOT, FLMOD_VENDOR
#   out: FLMOD_CI_TRACKS=(A B ...)   tracks to build / check
#        FLMOD_CI_NOTES=(...)        human-readable reasons for tracks left out
#   returns 0, or 2 when FLMOD_TRACK has an invalid value (FLMOD_CI_NOTES holds the message)
flmod_ci_win32_tracks() {
  local llvm=/usr/lib/llvm/22/bin
  local xwin=${XWIN_ROOT:-/home/user/opt/xwin}
  local vendor=${FLMOD_VENDOR:-/home/user/freelancer/carrier-mod/vendor}
  local want t
  FLMOD_CI_TRACKS=()
  FLMOD_CI_NOTES=()
  case "${FLMOD_TRACK:-}" in
    A) want=(A) ;;
    B) want=(B) ;;
    "") want=(A B) ;;
    *) FLMOD_CI_NOTES=("FLMOD_TRACK='${FLMOD_TRACK}' is not A, B or empty"); return 2 ;;
  esac
  if [[ ! -x $llvm/clang-cl || ! -d "$xwin/VC/Tools/MSVC" ]]; then
    FLMOD_CI_NOTES=("win32 skipped: no clang-cl or XWIN_ROOT splat")
    return 0
  fi
  for t in "${want[@]}"; do
    if [[ $t == A && ! -f $vendor/FLUF/.flmod-pin ]]; then
      FLMOD_CI_NOTES+=("trackA skipped: no FLUF vendor")
      continue
    fi
    FLMOD_CI_TRACKS+=("$t")
  done
  return 0
}
