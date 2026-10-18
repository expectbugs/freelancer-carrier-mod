#!/usr/bin/env bash
# harness/ci.sh: the single CI entry point (REQ-P0-REPO-7; CONVENTIONS §5; TESTING §CI).
#
#   harness/ci.sh [--quick|--full] [--lanes N] [--only <stage>[,<stage>...]]
#
# Built-in stage: `public` (tools/check_public.py --tree <repo root>), always first.
# Every other stage is an executable drop-in harness/ci.d/NN-<name>.sh, run in
# lexical order; the protocol is documented in harness/ci.d/README.md.
#
# Output: $FLMOD_TESTRUNS/<UTC stamp>-ci/summary.md (+ one log per stage).
# Exit: 0 = no stage failed, 1 = a stage failed, 2 = usage or setup error.
#
# Overrides (tests and special runs only): CI_REPO_ROOT (tree under test; default:
# the repo containing this script), CI_D_DIR (drop-in dir; default
# $CI_REPO_ROOT/harness/ci.d), CI_RUNS_DIR (parent of the run dir; default
# $FLMOD_TESTRUNS), CI_QUARANTINE (default $CI_REPO_ROOT/state/QUARANTINE.md),
# CI_PYTHON (default python3).
set -uo pipefail

# Canonical drop-in stages (CONVENTIONS §5). `--only <one of these>` reports SKIP
# when the drop-in does not exist yet instead of a usage error.
KNOWN_STAGES="build host-tests pytest data-validate import-check scenarios-quick scenarios-full soak-smoke"
QUICK_MAX=59     # --quick: stages numbered below 60
DEFAULT_MAX=60   # default: up to and including 60
FAIL_TAIL_LINES=40

usage() {
    cat <<'EOF'
Usage: harness/ci.sh [--quick|--full] [--lanes N] [--only <stage>[,<stage>...]]

  (default)   public + drop-in stages numbered <= 60
  --quick     public + drop-in stages numbered < 60 (no game)
  --full      public + every drop-in stage
  --lanes N   lanes the scenario/soak stages may use (default 1); passed as CI_LANES
  --only S    run only the named stages (comma-separated or repeated), regardless of
              the mode's number cutoff; the mode is still passed as CI_MODE

Stages: public (built in), then harness/ci.d/NN-<name>.sh in lexical order.
Stops at the first FAIL. Writes $FLMOD_TESTRUNS/<UTC stamp>-ci/summary.md.
Exit codes: 0 green, 1 a stage failed, 2 usage/setup error.
EOF
}

die_usage() {
    echo "ci.sh: $*" >&2
    echo "Run 'harness/ci.sh --help' for usage." >&2
    exit 2
}

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
self_root="$(cd "$script_dir/.." && pwd)"

mode=default
mode_flag=""
lanes=1
only=""
while [ $# -gt 0 ]; do
    case "$1" in
        --quick|--full)
            [ -z "$mode_flag" ] || [ "$mode_flag" = "$1" ] || die_usage "--quick and --full are mutually exclusive"
            mode_flag="$1"; mode="${1#--}" ;;
        --lanes)
            [ $# -ge 2 ] || die_usage "--lanes needs a value"
            lanes="$2"; shift ;;
        --lanes=*) lanes="${1#*=}" ;;
        --only)
            [ $# -ge 2 ] || die_usage "--only needs a stage list"
            only="${only:+$only,}$2"; shift ;;
        --only=*) only="${only:+$only,}${1#*=}" ;;
        -h|--help) usage; exit 0 ;;
        *) die_usage "unknown argument: $1" ;;
    esac
    shift
done
[[ "$lanes" =~ ^[1-9][0-9]*$ ]] || die_usage "--lanes must be a positive integer (got '$lanes')"

# Shared paths and the wine guards (CONVENTIONS §1, §15) for every stage.
if [ -f "$self_root/tools/env.sh" ]; then
    # shellcheck source=/dev/null
    source "$self_root/tools/env.sh"
fi

repo_root="${CI_REPO_ROOT:-$self_root}"
[ -d "$repo_root" ] || die_usage "CI_REPO_ROOT is not a directory: $repo_root"
repo_root="$(cd "$repo_root" && pwd)"
ci_d="${CI_D_DIR:-$repo_root/harness/ci.d}"
runs_parent="${CI_RUNS_DIR:-${FLMOD_TESTRUNS:-$repo_root/local/testruns}}"
quarantine="${CI_QUARANTINE:-$repo_root/state/QUARANTINE.md}"
python="${CI_PYTHON:-python3}"
checker="$self_root/tools/check_public.py"

# ---- discover drop-ins --------------------------------------------------------
declare -a st_num=() st_name=() st_file=()
declare -A seen_name=()
if [ -d "$ci_d" ]; then
    while IFS= read -r f; do
        base="$(basename "$f")"
        if [[ "$base" =~ ^([0-9]{2})-([a-z0-9][a-z0-9-]*)\.sh$ ]]; then
            num="${BASH_REMATCH[1]}"; name="${BASH_REMATCH[2]}"
            if [ "$name" = "public" ]; then
                echo "ci.sh: WARNING: ignoring $base (stage name 'public' is built in)" >&2; continue
            fi
            if [ -n "${seen_name[$name]:-}" ]; then
                echo "ci.sh: WARNING: duplicate stage name '$name' ($base and ${seen_name[$name]})" >&2
            fi
            seen_name[$name]="$base"
            st_num+=("$num"); st_name+=("$name"); st_file+=("$f")
        else
            echo "ci.sh: WARNING: ignoring $base (drop-ins must be named NN-<name>.sh)" >&2
        fi
    done < <(find "$ci_d" -maxdepth 1 -name '*.sh' \( -type f -o -type l \) | LC_ALL=C sort)
fi

# ---- select stages --------------------------------------------------------------
declare -A want=()
declare -a missing_known=()
if [ -n "$only" ]; then
    IFS=',' read -r -a only_list <<< "$only"
    for s in "${only_list[@]}"; do
        s="${s// /}"
        [ -n "$s" ] || continue
        if [ "$s" = "public" ] || [ -n "${seen_name[$s]:-}" ]; then
            want[$s]=1
        elif [[ " $KNOWN_STAGES " == *" $s "* ]]; then
            want[$s]=1; missing_known+=("$s")
        else
            present="${!seen_name[*]}"
            die_usage "unknown stage '$s' (built in: public; drop-ins present: ${present:-none}; canonical: $KNOWN_STAGES)"
        fi
    done
    [ ${#want[@]} -gt 0 ] || die_usage "--only selected no stages"
fi

declare -a plan_kind=() plan_name=() plan_file=() plan_tag=()
if [ -z "$only" ] || [ -n "${want[public]:-}" ]; then
    plan_kind+=(builtin); plan_name+=(public); plan_file+=(""); plan_tag+=("00")
fi
for i in "${!st_name[@]}"; do
    n="${st_name[$i]}"; num="${st_num[$i]}"
    if [ -n "$only" ]; then
        [ -n "${want[$n]:-}" ] || continue
    else
        case "$mode" in
            quick)   [ $((10#$num)) -le $QUICK_MAX ] || continue ;;
            default) [ $((10#$num)) -le $DEFAULT_MAX ] || continue ;;
            full)    ;;
        esac
    fi
    plan_kind+=(dropin); plan_name+=("$n"); plan_file+=("${st_file[$i]}"); plan_tag+=("$num")
done
for n in "${missing_known[@]}"; do
    plan_kind+=(absent); plan_name+=("$n"); plan_file+=(""); plan_tag+=("--")
done

# ---- run dir ----------------------------------------------------------------------
mkdir -p "$runs_parent" 2>/dev/null || { echo "ci.sh: cannot create $runs_parent" >&2; exit 2; }
rundir=""
for _ in 1 2 3 4 5 6 7 8 9 10; do
    cand="$runs_parent/$(date -u +%Y%m%dT%H%M%SZ)-ci"
    if mkdir "$cand" 2>/dev/null; then rundir="$cand"; break; fi
    sleep 1
done
[ -n "$rundir" ] || { echo "ci.sh: could not create a unique run dir under $runs_parent" >&2; exit 2; }
summary="$rundir/summary.md"

head_sha="$(git -C "$repo_root" rev-parse HEAD 2>/dev/null || echo none)"
dirty="$(git -C "$repo_root" status --porcelain 2>/dev/null | wc -l | tr -d ' ')"
started="$(date -u +%Y-%m-%dT%H:%M:%SZ)"

declare -a res_line=()
n_pass=0; n_skip=0; n_fail=0; n_notrun=0

write_summary() {  # $1 = verdict
    {
        echo "# CI run $(basename "$rundir")"
        echo
        echo "- verdict: **$1**"
        echo "- mode: $mode; lanes: $lanes; only: ${only:--}"
        echo "- repo: $repo_root @ $head_sha (uncommitted paths: $dirty)"
        echo "- started: $started; finished: ${finished:-running}"
        echo "- run dir: $rundir"
        echo
        echo "## Stages"
        echo
        if [ ${#res_line[@]} -eq 0 ]; then echo "(none run yet)"; fi
        for l in "${res_line[@]}"; do echo "- $l"; done
        echo
        echo "VERDICT: $1 ($n_pass pass, $n_skip skip, $n_fail fail, $n_notrun not run)"
    } > "$summary.tmp" && mv -f "$summary.tmp" "$summary"
}

finished=""
trap 'finished="$(date -u +%Y-%m-%dT%H:%M:%SZ)"; write_summary ABORTED; echo "ci.sh: aborted" >&2; exit 2' INT TERM
write_summary RUNNING
echo "ci.sh: mode=$mode lanes=$lanes only=${only:--} run dir: $rundir"

# Read the last "CI <name>: VERDICT ..." line a stage printed.
stage_line() {  # $1 = log, $2 = name
    grep -E "^CI $2: (PASS|FAIL|SKIP)\b" "$1" 2>/dev/null | tail -n 1
}

stopped_after=""
for i in "${!plan_name[@]}"; do
    name="${plan_name[$i]}"; kind="${plan_kind[$i]}"; tag="${plan_tag[$i]}"
    if [ -n "$stopped_after" ]; then
        res_line+=("CI $name: NOT RUN (stopped after $stopped_after FAIL)")
        n_notrun=$((n_notrun + 1))
        echo "CI $name: NOT RUN (stopped after $stopped_after FAIL)"
        continue
    fi
    log="$rundir/${tag/--/xx}-$name.log"
    t0=$(date +%s)
    case "$kind" in
        builtin)
            if [ -f "$checker" ]; then
                "$python" -I "$checker" --tree "$repo_root" > "$log" 2>&1 < /dev/null
                rc=$?
            else
                echo "checker missing: $checker" > "$log"; rc=2
            fi
            last="$(grep -E '^check_public: (OK|FAIL)' "$log" | tail -n 1)"
            last="${last#check_public: }"; last="${last#OK: }"; last="${last#FAIL: }"
            last="${last%% (*}"; last="${last%%;*}"
            case $rc in
                0) echo "CI public: PASS (check_public --tree: $last)" >> "$log" ;;
                1) echo "CI public: FAIL (check_public --tree: $last; see log)" >> "$log" ;;
                *) echo "CI public: FAIL (check_public exited $rc: usage/internal error)" >> "$log"; rc=1 ;;
            esac ;;
        absent)
            echo "CI $name: SKIP (drop-in harness/ci.d/NN-$name.sh not present yet)" > "$log"; rc=77 ;;
        dropin)
            f="${plan_file[$i]}"
            if [ ! -x "$f" ]; then
                echo "CI $name: FAIL (drop-in $(basename "$f") is not executable)" > "$log"; rc=1
            else
                ( cd "$repo_root" && \
                  CI_MODE="$mode" CI_LANES="$lanes" CI_RUNDIR="$rundir" CI_QUARANTINE="$quarantine" \
                  CI_REPO_ROOT="$repo_root" CI_STAGE="$name" "$f" ) > "$log" 2>&1 < /dev/null
                rc=$?
            fi ;;
    esac
    secs=$(( $(date +%s) - t0 ))
    case $rc in
        0) verdict=PASS ;;
        77) verdict=SKIP ;;
        *) verdict=FAIL ;;
    esac
    printed="$(stage_line "$log" "$name")"
    reason=""
    if [ -n "$printed" ]; then
        pv="$(echo "$printed" | awk '{print $3}')"
        reason="$(echo "$printed" | cut -d' ' -f4-)"
        if [ "$pv" != "$verdict" ]; then
            reason="$reason [stage printed $pv but exited $rc]"
        fi
    else
        reason="(no 'CI $name:' line printed; exit $rc)"
    fi
    line="CI $name: $verdict ${reason} [${secs}s] log: $log"
    res_line+=("$line")
    echo "$line"
    case $verdict in
        PASS) n_pass=$((n_pass + 1)) ;;
        SKIP) n_skip=$((n_skip + 1)) ;;
        FAIL)
            n_fail=$((n_fail + 1)); stopped_after="$name"
            echo "---- last $FAIL_TAIL_LINES lines of $log ----"
            tail -n "$FAIL_TAIL_LINES" "$log"
            echo "----" ;;
    esac
    write_summary RUNNING
done

finished="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
trap - INT TERM
if [ "$n_fail" -gt 0 ]; then verdict=FAIL; else verdict=PASS; fi
write_summary "$verdict"
echo "CI VERDICT: $verdict ($n_pass pass, $n_skip skip, $n_fail fail, $n_notrun not run)"
echo "CI summary: $summary"
[ "$verdict" = PASS ]
