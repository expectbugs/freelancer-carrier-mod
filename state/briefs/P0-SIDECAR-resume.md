# Resume: P0-SIDECAR (attempt 1, review r1 fix round 1, continued)

Read `state/briefs/P0-SIDECAR.md` (your brief), then `state/briefs/RESUME-2026-10-18.md` (common resume rules, which win), then this file.

- **Start point:** `git checkout wp/P0-SIDECAR`; expect HEAD `dbc1c9f`.
- **Read first:** the RESUME POINT in `sidecar/NOTES.md`, then the review `state/reports/P0-SIDECAR-r1.md`.
- **Remaining (per the ledger):** tests for pause, late ack, PTT cancel, send timeout, ids, ports, brain, `voice_smoke` (mocked), and the `critical_hull` clamp; the README port; the 20× suite run; check_public; the fix report.
- **CUDA:** the GPU is healthy again, so re-run `voice_smoke --require-cuda` for real and record the device, the latency numbers and the run dir. Offline only (`HF_HUB_OFFLINE=1`, models from `$FLMOD_MODELS`). No audio to the speakers: use the null sink.
- **Brain tests** never launch the real Claude CLI except a single sandbox-verification run if your spec requires it (CONVENTIONS §13: empty cwd outside the repo, allowlisted env, `--tools ""`, `--strict-mcp-config`). Mock it everywhere else, at the defining module.
