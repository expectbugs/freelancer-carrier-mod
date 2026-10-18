#!/usr/bin/env bash
# Launch the copilot sidecar (flcopilot) from its venv.
#
#   sidecar/run.sh [flcopilot args]          e.g. --profile test --port 29171, --selftest, --discover-mic
#   sidecar/run.sh --tool <name> [args]      run sidecar/tools/<name>.py in the venv (e.g. voice_smoke)
#
# The venv comes from $FLMOD_SIDECAR_VENV (CONVENTIONS §1), else $FLMOD_LOCAL/sidecar-venv.
# CUDA-12 cuBLAS/cuDNN from the venv go on LD_LIBRARY_PATH *before* Python starts, because
# ctranslate2 needs libcublas.so.12 and the host only has CUDA 13.
set -euo pipefail

SIDECAR_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"

VENV="${FLMOD_SIDECAR_VENV:-}"
if [[ -z "$VENV" && -n "${FLMOD_LOCAL:-}" ]]; then
    VENV="$FLMOD_LOCAL/sidecar-venv"
fi
if [[ -z "$VENV" || ! -x "$VENV/bin/python" ]]; then
    echo "run.sh: sidecar venv not found (set FLMOD_SIDECAR_VENV, or source tools/env.sh; create it with sidecar/setup_venv.sh)" >&2
    exit 2
fi
PY="$VENV/bin/python"

SITE=""
for d in "$VENV"/lib/python3*/site-packages; do
    [[ -d "$d" ]] && SITE="$d" && break
done
CUDA_LIBS=""
for sub in nvidia/cublas/lib nvidia/cudnn/lib; do
    if [[ -n "$SITE" && -d "$SITE/$sub" ]]; then
        CUDA_LIBS="${CUDA_LIBS:+$CUDA_LIBS:}$SITE/$sub"
    fi
done
if [[ -n "$CUDA_LIBS" ]]; then
    export LD_LIBRARY_PATH="$CUDA_LIBS${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
fi

# Offline only: the sidecar never downloads models at runtime (CONVENTIONS §13).
export HF_HUB_OFFLINE=1
export HF_HUB_DISABLE_TELEMETRY=1

# The sidecar needs no D-Bus. Without a session bus address, PortAudio's ALSA device scan
# (import sounddevice) makes libdbus autolaunch dbus-launch through X11, which blocks for as
# long as the X server is unresponsive (VERIFIED 2026-10-17, sidecar/NOTES.md B-2). An
# unknown transport makes libdbus fail fast instead. A real session address is left alone.
if [[ -z "${DBUS_SESSION_BUS_ADDRESS:-}" ]]; then
    export DBUS_SESSION_BUS_ADDRESS="disabled:"
fi

# Import only our own package: no user site (-s), no cwd/script dir on sys.path (-P),
# PYTHONPATH pinned to this sidecar dir.
unset PYTHONHOME PYTHONSTARTUP PYTHONINSPECT
export PYTHONPATH="$SIDECAR_DIR"

if [[ "${1:-}" == "--tool" ]]; then
    name="${2:-}"
    if [[ ! "$name" =~ ^[a-z0-9_]+$ || ! -f "$SIDECAR_DIR/tools/$name.py" ]]; then
        echo "run.sh: unknown tool '${name}' (see sidecar/tools/)" >&2
        exit 2
    fi
    shift 2
    exec "$PY" -s -P "$SIDECAR_DIR/tools/$name.py" "$@"
fi

exec "$PY" -s -P -m flcopilot "$@"
