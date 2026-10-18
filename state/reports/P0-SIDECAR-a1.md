PACKAGE: P0-SIDECAR   ATTEMPT: 1   RESULT: DONE
BRANCH: wp/P0-SIDECAR @ cf21a75 (5 commits on e85fc2d; changes only `sidecar/` and `docs/spec/ipc.md`)

SUMMARY: Every REQ is implemented, with passing evidence.
- **Server:** the `flcopilot` sidecar is an asyncio server on 127.0.0.1 only, speaking NDJSON. It has a handler registry (`register_handler`: exact type, `prefix.*` or `*`, plus session start/end hooks), heartbeat, futures that resolve on each command's ack, a rotating JSON log (10 MB), and live/test profiles with a null sink.
- **Protocol:** v1 is written up in `docs/spec/ipc.md`. Its machine-readable twin is `protocol.py`, and a test checks the two list the same message types.
- **Fake client:** `tools/fakegame.py` is stdlib-only and does not import flcopilot, so it is an independent second implementation. It checks the sidecar's message envelopes, rejects bad script steps, and clamps `policy.set` the way the DLL must.
- **Voice:** a CUDA-12 venv and an offline GPU voice smoke. Mic discovery and push-to-talk capture plumbing are in place and tested with mocks.
- **Review:** an independent review agent found 9 defects; all are fixed. The worst two let one hostile line (very deep JSON, `1e400`, a lone `\ud800`) drop the game's connection. 33 regression tests fail on the pre-fix code and pass now.

PROTOCOL:
- TCP on 127.0.0.1:29170, port from `FLCOPILOT_PORT`, 29170+N for lane N.
- Lines are capped at 64 KiB; an oversize line is skipped up to its newline.
- Envelope is `{v,t,seq,gt,id}`, where a top-level `id` is always a command id.
- hello/welcome handshake; a version mismatch gets `bye{version,supported}`. ping/pong every 2 s; 3 missed pongs close the session. The newest connection to complete hello replaces the old one.
- All listed events are defined; `state` is sent at 2/0.5/0.1 Hz.
- Commands get `ack{applied|err}`. DLL clamps, rate limits (10 commands/s, 2 policy changes/s) and extension rules are specified, along with worker-thread notes for W2-REFLEX.

FILES: `docs/spec/ipc.md`; `sidecar/{pyproject.toml, requirements.lock, run.sh, setup_venv.sh, README.md, NOTES.md, config/flcopilot.toml}`; `sidecar/flcopilot/**`; `sidecar/tools/{fakegame,voice_smoke,env_probe}.py`; `sidecar/tests/**` (4 NDJSON scripts).

TESTS (run dirs are under `$FLMOD_TESTRUNS`):
- `pytest -q sidecar/tests`, sidecar venv — PASS, 253 tests. Covers the 6 socket tests, the 3 required scripts plus a version-mismatch script, and the test-profile no-output-device test (patched at `sounddevice.*`). Run 20× with 0 failures: `20261018T060000Z-sidecar-pytest-x20`.
- Same suite under the shared `$FLMOD_VENV` — PASS 235, SKIP 11 (audio-library tests, skipped with a reason).
- `run.sh --selftest` — PASS: `20261018T061000Z-sidecar-selftest/{stdout.txt,sidecar.log}` (`loopback_only=True handshake_script=pass shutdown_bye=shutdown port_closed_after=True`).
- `ss -ltnp` — PASS: only `127.0.0.1:29170`, no IPv6 listener, SIGTERM exits 0 (`20261018T061100Z-sidecar-ss/ss.txt`).
- `voice_smoke` on GPU — PASS: transcript "Save nanobots for the cruiser.", `stt_ms` 117–124 (warm median), `tts_first_audio_ms` 387–390, cuda/float16; nvidia-smi shows this process holding 2336 MiB (`20261018T044011Z-voice-smoke`).
- Offline proof — PASS under `unshare -rn` (no network, only `lo`), loading the model both from the `$FLMOD_MODELS` copy and by name from the HF cache (`20261018T061200Z-voice-smoke-netns`, `20261018T044700Z-voice-smoke-hfcache-netns`).
- CPU fallback — PASS but slow: `stt_ms` 9351 (`20261018T044900Z-voice-smoke-cpu`).
- Mic discovery — PASS: `mic: resolved index=63 matches=1`. The device name is only in the local log (D12).
- `grep "import aria|from aria" sidecar/` — PASS, nothing found. `check_public.py` (copy from the P0-REPO branch) — PASS in `--tree` mode and in `--commits e85fc2d..wp/P0-SIDECAR` mode.

VENV (`$FLMOD_SIDECAR_VENV`, Python 3.13.15; lockfile `sidecar/requirements.lock`): faster-whisper 1.2.1, ctranslate2 4.7.1, kokoro-onnx 0.5.0, onnxruntime 1.24.3 (CPU), sounddevice 0.5.5, soundfile 0.13.1, numpy 2.4.2, PyYAML 6.0.3, pytest 9.1.1, nvidia-cublas-cu12 12.9.2.10, nvidia-cudnn-cu12 9.27.0.42. The models are copies under `$FLMOD_MODELS/{kokoro,whisper/faster-whisper-large-v3-turbo}`.

DECISIONS (full text in `sidecar/NOTES.md`):
- D1: read lines with `readuntil`, not `readline`. `readline` would parse the tail of an oversize line as a new message.
- D2: a new connection replaces the old one at hello, not at connect.
- D3: top-level `id` is reserved for command ids, so the payload fields are named `ev.target.obj`, `ev.wing.wing` and `ev.carrier.carrier`.
- D4: changes from R6: `ev.hit.dmg` is a fraction; `hull_critical` is dropped; `state.carriers` is a list; `say` is acked.
- D5: `critical_hull` is clamped to [INI floor 0.25, 0.95].
- D6: the test profile advertises stt/tts/llm (all fakes).
- D7: the live profile refuses to start under pytest or when `FLCOPILOT_FORCE_TEST_PROFILE=1`.
- D8: the package is named `flcopilot`.
- D9: public config is TOML; the local overlay stays YAML.
- D11: `DBUS_SESSION_BUS_ADDRESS=disabled:` is set when it is unset.
- D12: the mic name goes only to the local log, because reports are committed.
- D14: the sidecar validates its own commands before sending them.

ENGINE FACTS LEARNED: none from in-game runs (this package has no game runs). Host facts, VERIFIED:
- ctranslate2 runs CUDA fp16 with the venv's CUDA-12 wheels (voice-smoke runs).
- PortAudio on this host has only the ALSA host API.
- `import sounddevice` hangs while X `:0` is unresponsive and no D-Bus session address is set (NOTES B-2, import probe).

OPEN QUESTIONS / BLOCKERS: none blocking. Proposals:
- (a) `harness/lane.sh` exports `FLCOPILOT_FORCE_TEST_PROFILE=1`.
- (b) CI stage 30 runs `$FLMOD_SIDECAR_VENV/bin/pytest -q sidecar/tests`.
- (c) W1-SIDECAR's spec says `python -m sidecar`; it should say `sidecar/run.sh` or `python -m flcopilot`.
- (d) Agents without a session bus should export `DBUS_SESSION_BUS_ADDRESS`.
- Observation: from about 04:50Z to 05:10Z, new X11 connections to `:0` hung (15 s timeout) while a lane was writing a `winedbg --minidump` of a hung Freelancer. X recovered by 05:15Z. Cause UNVERIFIED.

KNOWN ISSUES:
- Whisper on CPU int8 takes about 8–9 s per 2 s clip; changing the thread count made no difference. It is only the fallback, so W1 should pick a smaller CPU model.
- Kokoro warm first audio is about 390 ms, above W1's 0.3 s target. It was measured while lanes were running; cause UNVERIFIED.
- Selecting the capture source through `PULSE_SOURCE` is UNVERIFIED until W1's live test.
- Loopback TCP from inside Wine and `GetAsyncKeyState(110)` stay UNVERIFIED until S-UI.
- I rewrote this branch's history once, before any push, with `filter-branch`, to remove a hardware literal from the local blocklist that check_public found in NOTES.md. All 5 commits now pass `--commits`.
