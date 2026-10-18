# P0-SIDECAR: Copilot sidecar skeleton, IPC protocol v1, fake client, voice smoke

- **Type:** impl
- **Wave:** Phase 0
- **Depends on:** — → **Unblocks:** W1-SIDECAR, W2-REFLEX (IPC client), W4-BRAIN.

## Goal

A native Linux Python service that the in-game DLL will talk to over TCP loopback. In Phase 0 it delivers:

- the locked protocol;
- a server that speaks it;
- a fake game client for tests;
- a venv where GPU speech-to-text and CPU text-to-speech run offline.

The game must never depend on it: the reflex layer and gameplay work with the sidecar absent (DESIGN D-11.3).

## Requirements

- **REQ-P0-SIDECAR-1: layout.** `sidecar/` Python package `flcopilot`:
  - `sidecar/pyproject.toml` (deps pinned);
  - venv at **`$FLMOD_SIDECAR_VENV` (`/home/user/freelancer/carrier-mod/local/sidecar-venv`, CONVENTIONS §1)**, never inside the repo or a worktree, with Python 3.13 (`/usr/bin/python3.13`);
  - launcher `sidecar/run.sh`, which finds the venv via `FLMOD_SIDECAR_VENV`;
  - public config `sidecar/config/flcopilot.toml` (committed, no secrets, **no device names**), overlaid at runtime by the gitignored `$FLMOD_LOCAL/sidecar.local.yaml`, which the orchestrator created with Adam's `mic_match` and `ptt_key`;
  - models and caches only under **`$FLMOD_MODELS`** (gitignored);
  - logs under `$FLMOD_LOCAL/sidecar-logs/` in dev, configurable for the play install;
  - tests in `sidecar/tests/` (pytest from the sidecar venv).
- **REQ-P0-SIDECAR-2: transport** (R6 §2, VERIFIED from the Proton 11 Wine source):
  - TCP only: Wine maps Winsock INET sockets to host sockets. Windows named pipes stay inside wineserver, and there is **no AF_UNIX** for Windows programs in Wine 11.
  - Listen on **`127.0.0.1:29170`** only. Never `0.0.0.0`: the host has LAN, VPN and tailnet interfaces. Port 29170 was free and below the ephemeral range, VERIFIED R6 §2.2.
  - The port is configurable via `FLCOPILOT_PORT` and the config file. Test lanes use **`29170 + N`** for lane N (CONVENTIONS §7; `lane.sh` exports `FLCOPILOT_PORT`), so concurrent lanes never cross-connect. The play install uses 29170.
  - One active connection: a new connection replaces the old one (game restart).
- **REQ-P0-SIDECAR-3: protocol v1** (NDJSON). Write `docs/spec/ipc.md`, adapted from R6 §3.
  - **Framing:** one UTF-8 JSON object per `\n`-terminated line, at most 64 KiB.
  - **Envelope:** `{"v":1,"t":"<type>","seq":<int>,"gt":<game ms, DLL side>,...}`.
  - **Handshake:** the DLL sends `hello{v,dll,game,char,save,policy}`; the sidecar replies `welcome{v,sidecar,features}`. On a version mismatch the sidecar sends `bye{reason:"version"}` and closes.
  - **Heartbeat:** `ping`/`pong` every 2 s; 3 misses means reconnect.
  - **Commands** from the sidecar carry `"id"`. The DLL answers `ack{id, ok, applied|err}`.
  - **Message types** (define every one, with field types and ranges):
    - game→sidecar `state`: coalesced snapshots at 2 / 0.5 / 0.1 Hz (combat / calm / docked-or-paused);
    - game→sidecar events: `ev.hull`, `ev.shield`, `ev.reflex`, `ev.low_stock`, `ev.target`, `ev.kill`, `ev.hostiles`, `ev.hit`, `ev.dock`, `ev.undock`, `ev.system`, `ev.lane`, `ev.cruise`, `ev.wing`, `ev.carrier`, `ev.death`, `ev.load`, `ev.save`, `ev.pause`, `ptt{down}`;
    - sidecar→game commands: `policy.set{scope:player|carrier, auto_bots, bots_hull_below, bots_reserve, critical_hull, release_reserve_when, auto_batts, batts_shield_below, batts_reserve}`, `act{do:use_bots|use_batts}`, `wing.formation`, `wing.focus`, `wing.order`, `wing.policy`, `say{speaker,text,prio,subtitle}`.
  - **DLL-side clamps** (documented in the spec; enforced later by W2-REFLEX): `0.05 ≤ *_below ≤ 0.95`; enums whitelisted; `critical_hull` is a hard floor the LLM can't override; at most 10 commands/s and 2 policy changes/s.
  - Leave room for carrier, wingmen and hiring events in later waves, with explicit **extension rules**: unknown `t` values are ignored with a log line; new fields are optional.
- **REQ-P0-SIDECAR-4: server.**
  - `asyncio.start_server` with `reader.readline()` and a 64 KiB `limit`. Rejects malformed lines with a log line, without dropping the connection.
  - Dispatches through a registry that later waves extend: `register_handler(t, fn)`.
  - Structured JSON log to `$FLMOD_LOCAL/sidecar-logs/sidecar.log` (configurable); rotate at 10 MB.
  - No outbound network at all in P0. The LLM comes in W4-BRAIN.
  - **Profiles** (CONVENTIONS §13):
    - `--profile live` is the default for play.
    - `--profile test` is mandatory for every harness, lane, soak and CI use. It uses a **null audio sink** (no speaker output) and accepts `--mic-file <wav>` in place of the mic, which W1-SIDECAR completes. Its LLM hook is a deterministic fake responder; the real brain arrives in W4-BRAIN.
    - Implement the profile switch and the null sink now.
- **REQ-P0-SIDECAR-5: fake game client.** `sidecar/tools/fakegame.py`:
  - connects, sends `hello`, replays an NDJSON script file (`sidecar/tests/scripts/*.ndjson`), asserts on expected replies, and supports `ptt` down/up sequences;
  - used by pytest and by later packages' tests.
- **REQ-P0-SIDECAR-6: voice environment (offline smoke only).**
  - The venv (`$FLMOD_SIDECAR_VENV`) installs `faster-whisper==1.2.1`, `ctranslate2` (as faster-whisper requires), `kokoro-onnx==0.5.0`, `onnxruntime` (CPU), `sounddevice`, `soundfile`, `numpy`, `pytest`, **plus CUDA-12 libraries `nvidia-cublas-cu12` and `nvidia-cudnn-cu12==9.*`**.
  - **Offline only:** `HF_HUB_OFFLINE=1`, and `WhisperModel(..., local_files_only=True)` (CONVENTIONS §13). Model files are read from the existing HF cache or a copy or symlink in `$FLMOD_MODELS`; the sidecar never downloads at runtime.
  - ctranslate2 4.7.1 needs `libcublas.so.12`. The system `/opt/cuda` and the aria venv have CUDA 13 only (VERIFIED R6 §4.1).
  - `run.sh` exports `LD_LIBRARY_PATH` to the venv's `nvidia/cublas/lib` and `nvidia/cudnn/lib` **before** starting Python.
  - Smoke test `sidecar/tools/voice_smoke.py`:
    1. Kokoro synthesizes "save nanobots for the cruiser" to a temp WAV.
    2. faster-whisper `large-v3-turbo` (fp16, cuda) transcribes it, using the already-cached model at `~/.cache/huggingface/hub/models--mobiuslabsgmbh--faster-whisper-large-v3-turbo` (VERIFIED present, R6 §1.2), with `initial_prompt`/`hotwords` holding game vocabulary.
    3. Assert the transcript contains "nanobots" and "cruiser".
    4. Report STT latency (R6 cites ~0.25 s per 3 s clip on this GPU) and TTS first-audio latency.
  - Kokoro model files: **copy** `kokoro-v1.0.onnx` and `voices-v1.0.bin` from the owner's existing model folder (path in `$FLMOD_RESEARCH/R6-copilot-sidecar.md` §1.3) into `$FLMOD_MODELS/kokoro/`. Never commit them: `sidecar/models/` and `*.onnx` are gitignored, and check_public rejects files over 5 MB. **Never import the owner's other projects' modules** (R6 §1.4: one has a hidden phone-push side effect, and they all import a secret config).
  - Code may be adapted from Adam's own projects by copying pure functions with a provenance comment:
    - `WhisperEngine`, `EnergyVAD` and `resample` from `/home/user/aria/whisper_engine.py`;
    - `prepare_for_speech` and `split_sentences` from `/home/user/G2CC/audio/pipeline/tts_daemon.py` (VERIFIED: no network or phone side effects).
  - check_public blocks those path names outside `docs/plan/`. In code comments, write "adapted from the owner's prior voice-assistant code" instead.
- **REQ-P0-SIDECAR-7: audio devices.**
  - Mic: resolve the capture source by the substring **`mic_match` from `$FLMOD_LOCAL/sidecar.local.yaml`** in `pactl list short sources` (DESIGN D-11.3). The public default config has no device name; if no match is configured or found, log it and run with voice input disabled. Never write the device name into a committed file.
  - Output: the default PipeWire sink through `sounddevice` (`pipewire`/`pulse`/`default` devices are visible to PortAudio, VERIFIED R6 §4.2).
  - Capture design: a 16 kHz mono `InputStream` kept open while a game is connected, with a 300 ms pre-roll ring. `ptt down` starts accumulating; `ptt up` adds a 150 ms tail and hands the audio to STT (R6 §4.2).
  - P0 implements the capture plumbing behind a flag and tests it with mocks. Live mic capture is exercised in W1-SIDECAR.
- **REQ-P0-SIDECAR-8: push-to-talk.** The DLL (W2-REFLEX) polls the key and sends `ptt{down:true|false}`. The default key is **numpad period, VK_DECIMAL = 110 (0x6E)**. Numpad minus (109) is bound in vanilla `keymap.ini` to the hidden `USER_ZOOM_IN` (VERIFIED 2026-10-17), and `ptt_key = numpad_minus` is an option (DESIGN D-11.3).
  - The sidecar never reads keys itself in P0. Put the config key and the protocol field in place.
- **REQ-P0-SIDECAR-9: safety.**
  - Bind loopback only. No `import` of aria or aria2. No writes to aria or aria2 databases.
  - Tests mock at the defining module (`patch("sounddevice.OutputStream")`, `patch("sounddevice.InputStream")`); no real audio in unit tests.
  - Temp SQLite or files under `tmp_path`.

## Context pack

- `$FLMOD_RESEARCH/R6-copilot-sidecar.md`: **all** (§0 recommendations, §2 IPC with Wine evidence, §3 protocol and event model, §4 voice I/O, §6 memory schema to anticipate, §7 safety)
- `docs/plan/DESIGN.md` §11 (copilot); `docs/plan/CONVENTIONS.md` §1, §7, §13 (authoritative)
- `CLAUDE.md` guardrails 6 and 7; `docs/plan/AUTONOMY.md` §2 (never import aria)
- Read-only reference code: `/home/user/aria/whisper_engine.py`, `/home/user/G2CC/audio/pipeline/tts_daemon.py`, `/home/user/rt-zomboid/daemon/{claude_session.py,memory_store.py}` (later waves)

## Ownership

- **Owns:** `sidecar/`, `docs/spec/ipc.md`.
- **Reads:** the reference projects above (read-only); the HF cache.
- **Must not touch:** anything in `~/aria*`, `~/G2CC`, `~/rt-zomboid`; global Python; `docs/plan/`; `state/`.

## Contract

- **Provides:**
  - `docs/spec/ipc.md` (protocol v1; frozen by ARCH-0 after review; later changes bump `v` or add optional fields);
  - `flcopilot` server with a handler registry;
  - `fakegame.py`;
  - `run.sh`.
- **Consumes:** —

## Tasks

1. Write `docs/spec/ipc.md`.
2. Write the server, registry and logging. Unit tests over a real loopback socket on an ephemeral port: handshake, ping timeout, malformed line, oversize line, version mismatch, reconnect replacing the old connection.
3. `fakegame.py` plus 3 scripts: handshake-only, a policy round trip (the sidecar sends a canned `policy.set` on `ptt` up in test mode; the fake client acks), and a disconnect/reconnect.
4. Create the venv; install the deps; write `run.sh` with `LD_LIBRARY_PATH`; run `voice_smoke.py`.
5. Mic discovery and the capture skeleton (mocked tests).
6. `sidecar/README.md`: install, run, config, ports, safety notes.

## Acceptance (automated)

- `$FLMOD_SIDECAR_VENV/bin/pytest -q sidecar/tests` all pass. This includes the 6 socket tests, the 3 fakegame scripts, and a test that `--profile test` produces no output-device stream (null sink).
- `sidecar/run.sh --selftest` starts the server, the fake client completes the handshake, and the server shuts down cleanly. Attach the log.
- `ss -ltnp` while running shows `127.0.0.1:29170` only.
- `voice_smoke.py` → transcript contains the target words. Reports `stt_ms` and `tts_first_audio_ms`, plus `nvidia-smi` evidence that CUDA was used, or an explicit CPU fallback with the reason.
- Mic discovery prints the resolved source name, or "not found". It goes to the log and report only, never to a committed file.
- A run with `HF_HUB_OFFLINE=1` and no network still passes the voice smoke (proves offline).
- `grep -rn "import aria\|from aria" sidecar/` → nothing; check_public passes.

## Engine facts to rely on / verify

- VERIFIED (source): Wine sockets are host sockets; no AF_UNIX; named pipes are internal.
- UNVERIFIED: loopback TCP from **inside** the running Freelancer process (S-UI E9 settles it); `GetAsyncKeyState` delivery of VK 110 and XBUTTON under Wine (S-UI E10).

## Pitfalls

- Every Winsock recv/send is a wineserver round trip, so the DLL side must keep sockets on a worker thread. Document this in `ipc.md` for W2-REFLEX (R6 §2.1).
- Use `127.0.0.1`, never `localhost` (`::1` surprises).
- The default PipeWire source may change; always resolve by substring.
- Don't download models in tests. Use the HF cache, and skip with a reason if it's absent.

## Fallbacks and degrade path

| Problem | Fallback |
|---|---|
| CUDA-12 libs fail | Whisper on CPU `int8` (slower), recorded |
| CUDA-12 libs fail, alternative | G2CC's warm ASR daemon as a subprocess (`/home/user/G2CC/audio/venv`; stdin WAV path → framed stdout, R6 §1.2). It couples to that venv; record it as a decision. |
| Kokoro fails | Piper (installed in the aria venv; copy the model path, never import aria code) |
| TTS fails entirely | Subtitles only (`say{subtitle:true}`) |

## Report

AGENT_BRIEF_TEMPLATE format. Include the protocol summary, latencies, the resolved mic source, and venv package versions.

## Gate-time addendum

(Orchestrator: attempt number, commit trailer.)
