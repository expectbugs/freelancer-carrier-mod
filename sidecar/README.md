# flcopilot: the copilot sidecar

A native Linux Python service that the in-game mod DLL talks to over TCP loopback. It hosts the copilot's voice (speech-to-text, text-to-speech) and later its brain. The game never depends on it: with the sidecar absent, the reflex layer and all gameplay work the same, and only voice is missing (DESIGN D-11.3).

- **Protocol:** NDJSON v1, specified in [`docs/spec/ipc.md`](../docs/spec/ipc.md) (machine-readable twin: `flcopilot/protocol.py`).
- **Status (P0):** server, protocol, handler registry, profiles, fake game client, push-to-talk capture plumbing, and an offline GPU speech smoke. The live voice pipeline is W1-SIDECAR; the LLM brain is W4-BRAIN.

## Install

The venv lives outside the repo at `$FLMOD_SIDECAR_VENV` (`/home/user/freelancer/carrier-mod/local/sidecar-venv`), with Python 3.13.

```bash
source tools/env.sh                     # exports FLMOD_* (CONVENTIONS §1)
sidecar/setup_venv.sh                   # create/refresh the venv from sidecar/requirements.lock
KOKORO_SRC=<dir with kokoro-v1.0.onnx + voices-v1.0.bin> sidecar/setup_venv.sh --models
```

`--models` copies the Kokoro files and the faster-whisper `large-v3-turbo` snapshot (default: from the Hugging Face cache) into `$FLMOD_MODELS/{kokoro,whisper}/`. Models are never committed; `*.onnx` and `sidecar/models/` are gitignored.

**CUDA:** ctranslate2 4.7.1 needs `libcublas.so.12` + cuDNN 9, but the host has CUDA 13 only. The venv carries `nvidia-cublas-cu12` and `nvidia-cudnn-cu12`, and `run.sh` puts their lib dirs on `LD_LIBRARY_PATH` before Python starts. Without them, speech-to-text falls back to CPU `int8` (slow: about 8 s per 2 s clip on this host).

## Run

```bash
sidecar/run.sh                          # live profile, 127.0.0.1:29170 (the play install)
sidecar/run.sh --profile test           # harness, lanes, soaks, CI: null sink, fakes, no devices
sidecar/run.sh --profile test --port 29171 --mic-file order.wav
sidecar/run.sh --selftest               # server up, fake client handshake, clean shutdown, exit 0/1
sidecar/run.sh --discover-mic           # resolve mic_match to a capture source (prints the name locally)
sidecar/run.sh --print-config           # effective config (mic_match masked)
sidecar/run.sh --tool voice_smoke       # offline Kokoro -> WAV -> Whisper (GPU) smoke, into $FLMOD_TESTRUNS
sidecar/run.sh --tool fakegame --port 29170 sidecar/tests/scripts/handshake.ndjson
```

When serving, the sidecar prints `FLCOPILOT ready host=127.0.0.1 port=<n> profile=<p> pid=<pid>` on stdout and stops cleanly on SIGTERM/SIGINT (it sends `bye{reason:"shutdown"}` first). Exit codes: 0 ok, 1 selftest/discovery failed, 2 config or profile error, 3 cannot listen.

## Ports

| Who | Port |
|---|---|
| Play install | 29170 |
| Test lane N | 29170 + N, from `FLCOPILOT_PORT` (exported by `harness/lane.sh`, CONVENTIONS §7) |
| Unit tests | ephemeral (`--port 0`) |

Precedence: `--port` > `FLCOPILOT_PORT` > local overlay > `config/flcopilot.toml`. The listen address is always `127.0.0.1` and is not configurable.

## Config

- `config/flcopilot.toml`: committed public defaults. No secrets and **no device names**.
- `$FLMOD_LOCAL/sidecar.local.yaml` (gitignored; override the path with `--local-config` or `FLCOPILOT_LOCAL_CONFIG`): Adam's local settings, e.g. `mic_match` (a substring of the PipeWire capture source name) and `ptt_key` (`numpad_period` = VK 110, the default; or `numpad_minus` = VK 109). Flat keys or `[section]` mappings.
- Logs: structured JSON lines at `$FLMOD_LOCAL/sidecar-logs/sidecar.log` (rotated at 10 MB, 5 backups), plus `[carrier] sidecar.<subsystem>: …` lines on stderr. The play install passes `--log-file`.

## Extending (later waves)

Register handlers on the registry instead of editing the server (see `flcopilot/app.py`):

```python
registry.register_handler("ev.kill", on_kill)      # exact type
registry.register_handler("ev.*", on_any_event)    # prefix
registry.on_session_start(fn); registry.on_session_end(fn)
fut = await session.send_command("policy.set", scope="player", bots_reserve=7)  # -> ack dict or None
```

New message types go into `docs/spec/ipc.md` and `flcopilot/protocol.py` together (ipc.md §10); `tests/test_protocol.py` fails if they disagree.

## Tests

```bash
$FLMOD_SIDECAR_VENV/bin/pytest -q sidecar/tests
```

They use real loopback sockets on ephemeral ports, the test profile, and mocks at the defining module (`patch("sounddevice.OutputStream")`, `patch("sounddevice.InputStream")`, `patch("subprocess.run")`). They never open an audio device, load a model or touch the network. Under the shared `$FLMOD_VENV` the audio-library tests skip with a reason. The fake game client `tools/fakegame.py` is stdlib-only and independent of `flcopilot`, so it doubles as a second implementation of the protocol.

## Safety

- Binds `127.0.0.1` only (never `0.0.0.0`); a non-loopback peer is refused. No outbound network in P0; in W4 the only outbound path is the Claude Code CLI the brain launches (no tools, no MCP, empty cwd; CONVENTIONS §13).
- The test profile never opens an audio device: output goes to a null sink, input comes from `--mic-file` or nothing. `--profile live` refuses to start under pytest or when `FLCOPILOT_FORCE_TEST_PROFILE=1`.
- Models load offline only (`HF_HUB_OFFLINE=1`, `local_files_only=True`); nothing is downloaded at runtime.
- No code from the owner's other projects is imported. A few pure functions were copied, with a provenance note in their docstrings.
- The mic device name is resolved at runtime and written only to the local log.
- `run.sh` sets `DBUS_SESSION_BUS_ADDRESS=disabled:` when no session bus is set, so importing `sounddevice` cannot hang on a D-Bus autolaunch through X11 (see `NOTES.md` B-2).
