#!/usr/bin/env bash
# Create (or refresh) the sidecar venv at $FLMOD_SIDECAR_VENV from sidecar/requirements.lock,
# and stage the voice models under $FLMOD_MODELS. Build-time downloads are allowed (pip);
# the sidecar itself never downloads at runtime.
#
#   sidecar/setup_venv.sh            create the venv if missing, install the lockfile
#   sidecar/setup_venv.sh --models   also copy the voice models into $FLMOD_MODELS (paths below)
#
# Model sources (read-only; copied, never linked into the repo):
#   KOKORO_SRC   dir with kokoro-v1.0.onnx + voices-v1.0.bin (required for --models)
#   WHISPER_SRC  a faster-whisper-large-v3-turbo snapshot dir (default: the HF cache snapshot)
set -euo pipefail

SIDECAR_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
VENV="${FLMOD_SIDECAR_VENV:-${FLMOD_LOCAL:+$FLMOD_LOCAL/sidecar-venv}}"
PYTHON="${SIDECAR_PYTHON:-/usr/bin/python3.13}"
if [[ -z "$VENV" ]]; then
    echo "setup_venv.sh: set FLMOD_SIDECAR_VENV (source tools/env.sh)" >&2
    exit 2
fi
case "$VENV" in
    "$SIDECAR_DIR"*) echo "setup_venv.sh: the venv must not live inside sidecar/ (use \$FLMOD_SIDECAR_VENV)" >&2; exit 2 ;;
esac

if [[ ! -x "$VENV/bin/python" ]]; then
    "$PYTHON" -m venv "$VENV"
fi
"$VENV/bin/python" -I -m pip install --upgrade pip
"$VENV/bin/python" -I -m pip install -r "$SIDECAR_DIR/requirements.lock"
# DBUS_SESSION_BUS_ADDRESS: see run.sh (importing sounddevice must not autolaunch D-Bus via X11).
DBUS_SESSION_BUS_ADDRESS="${DBUS_SESSION_BUS_ADDRESS:-disabled:}" "$VENV/bin/python" -I -c "import faster_whisper, ctranslate2, kokoro_onnx, onnxruntime, sounddevice, soundfile, numpy, yaml; print('sidecar venv ok:', ctranslate2.__version__, faster_whisper.__version__)"

if [[ "${1:-}" == "--models" ]]; then
    MODELS="${FLMOD_MODELS:?set FLMOD_MODELS}"
    : "${KOKORO_SRC:?set KOKORO_SRC to the dir holding kokoro-v1.0.onnx and voices-v1.0.bin}"
    WHISPER_SRC="${WHISPER_SRC:-$(ls -d "$HOME"/.cache/huggingface/hub/models--mobiuslabsgmbh--faster-whisper-large-v3-turbo/snapshots/* | head -n1)}"
    mkdir -p "$MODELS/kokoro" "$MODELS/whisper"
    cp -a --reflink=auto "$KOKORO_SRC/kokoro-v1.0.onnx" "$KOKORO_SRC/voices-v1.0.bin" "$MODELS/kokoro/"
    if [[ ! -f "$MODELS/whisper/faster-whisper-large-v3-turbo/model.bin" ]]; then
        cp -rL --reflink=auto "$WHISPER_SRC" "$MODELS/whisper/faster-whisper-large-v3-turbo"
    fi
    ls -la "$MODELS/kokoro" "$MODELS/whisper/faster-whisper-large-v3-turbo"
fi
