# toolchain/prefix_clone.sh: sourced by toolchain/load_proof.sh and toolchain/ehprobe.sh. Not executable.
#
# Throwaway Wine prefixes for Wine-only checks (no game run). A clone is a reflink copy of a SOURCE prefix:
#   --from prefix-dev-base-B   (default) P0-HARNESS's Track B dev baseline: HDE intact + test tweaks
#   --from prefix-dev-base-A   the Track A baseline
#   --from play                Adam's play prefix (/home/user/freelancer/prefix), only while it is idle
# The source is only read (cp -a --reflink=always), never written, and must not be in use. Clones are named
# prefix-dev-<something> (never prefix-dev-base-*), live in /home/user/freelancer/, and are deleted afterwards.

FLMOD_FL_ROOT=/home/user/freelancer
FLMOD_PLAY_PREFIX_PATH=$FLMOD_FL_ROOT/prefix
FLMOD_DEFAULT_CLONE_SOURCE=prefix-dev-base-B

# flmod_prefix_in_use <prefix>: 0 (and prints the processes) if any process has its cwd inside <prefix> or
# WINEPREFIX=<prefix>; 1 if idle. Same test as tools/play_prefix_busy.sh, for any prefix. Read-only.
# Both sides are normalised with `realpath -m`, like the wine guards (D110), so //, /./, x/.. and trailing-slash
# spellings of WINEPREFIX (or of <prefix>) can't hide a user. /proc/<pid>/cwd is already canonical.
flmod_prefix_in_use() {
  local P d pid cwd envp busy=1
  P=$(realpath -m -- "$1")
  for d in /proc/[0-9]*; do
    pid=${d#/proc/}
    cwd=$(readlink "$d/cwd" 2>/dev/null) || continue
    envp=$(tr '\0' '\n' <"$d/environ" 2>/dev/null | grep -m1 '^WINEPREFIX=' | cut -d= -f2-)
    [[ -n $envp ]] && envp=$(realpath -m -- "$envp" 2>/dev/null)
    case "$cwd/" in "$P"/*) ;; *) [[ -n $envp && $envp == "$P" ]] || continue ;; esac
    echo "in use: pid $pid $(tr '\0' ' ' <"$d/cmdline" 2>/dev/null | cut -c1-120)"
    busy=0
  done
  return $busy
}

# flmod_clone_source_path <from>: prints the absolute source prefix for a --from value; returns 2 if invalid.
flmod_clone_source_path() {
  local from=$1
  case "$from" in
    play) printf '%s\n' "$FLMOD_PLAY_PREFIX_PATH" ;;
    prefix-dev-base-*)
      [[ $from == */* ]] && return 2
      printf '%s\n' "$FLMOD_FL_ROOT/$from" ;;
    *) return 2 ;;
  esac
}

# flmod_check_clone_source <from>: validates a --from value. On success prints the source path; on failure prints
# the reason to stderr and returns 2 (bad value), 3 (in use) or 77 (does not exist, or a baseline without
# BASELINE.json, i.e. not finished by harness/baseline.sh; lane.sh applies the same rule).
flmod_check_clone_source() {
  local from=$1 src
  src=$(flmod_clone_source_path "$from") || {
    echo "--from must be prefix-dev-base-<X> or 'play' (got '$from')" >&2; return 2; }
  if [[ ! -d $src/drive_c ]]; then
    echo "clone source $src is not a Wine prefix (create it with harness/baseline.sh, or use --from play)" >&2
    return 77
  fi
  if [[ $from != play && ! -f $src/BASELINE.json ]]; then
    echo "clone source $src has no BASELINE.json (not a finished baseline; run harness/baseline.sh create)" >&2
    return 77
  fi
  if [[ $from == play ]]; then
    local busy
    if busy=$(/home/user/freelancer/carrier-mod/tools/play_prefix_busy.sh); then
      printf '%s\nplay prefix is busy, refusing to clone it\n' "$busy" >&2; return 3
    fi
  elif flmod_prefix_in_use "$src" >&2; then
    echo "clone source $src is in use, refusing to clone it" >&2; return 3
  fi
  printf '%s\n' "$src"
}

# flmod_check_clone_name <name>: a fresh throwaway clone name. Prints the clone path, or the reason to stderr and
# returns 2.
flmod_check_clone_name() {
  local name=$1
  case "$name" in
    prefix-dev-base*) echo "--clone must not be a baseline name (prefix-dev-base*)" >&2; return 2 ;;
    prefix-dev*) ;;
    *) echo "--clone must start with prefix-dev (got '$name')" >&2; return 2 ;;
  esac
  [[ $name == */* ]] && { echo "--clone takes a name, not a path" >&2; return 2; }
  if [[ -e $FLMOD_FL_ROOT/$name ]]; then
    echo "$FLMOD_FL_ROOT/$name already exists; pick another --clone name or delete it (throwaway clone)" >&2
    return 2
  fi
  printf '%s\n' "$FLMOD_FL_ROOT/$name"
}

# flmod_game_exe_dir <prefix>: prints the game's EXE dir (the one holding Common.dll) inside <prefix>, or nothing.
flmod_game_exe_dir() {
  local d
  for d in "$1"/drive_c/Games/*/EXE "$1"/drive_c/Program\ Files*/*/EXE; do
    [[ -d $d ]] || continue
    if compgen -G "$d/[Cc][Oo][Mm][Mm][Oo][Nn].[Dd][Ll][Ll]" >/dev/null; then printf '%s\n' "$d"; return 0; fi
  done
  return 1
}

# flmod_win_path <prefix> <unix path under prefix/drive_c>: prints the C:\... form.
flmod_win_path() {
  local rel=${2#"$1"/drive_c/}
  printf 'C:\\%s\n' "${rel//\//\\}"
}
