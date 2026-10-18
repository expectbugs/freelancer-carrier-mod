# Review brief: P0-SIDECAR Sidecar skeleton, NDJSON server, protocol v1, fake game, CUDA voice smoke (round 2)

You are an independent reviewer in an autonomous build. Be adversarial: find what is wrong, missing, untested or risky before it reaches `main`. **You do not fix code.** You report findings; the author fixes them.

This is **round 2**. Round 1 (on `cf21a75`) returned CHANGES_REQUIRED with 11 findings. The author reports all fixed.

## Inputs

- **Package spec:** `docs/plan/packages/P0-SIDECAR.md`. **Brief:** `state/briefs/P0-SIDECAR.md`. **Round-1 brief** (full audit checklist and package-specific probes, still valid, including the safety audit and the NDJSON fuzzing list): `state/briefs/P0-SIDECAR-r1.md`.
- **Round-1 findings:** `state/reports/P0-SIDECAR-r1.md`. **Author's fix report:** `state/reports/P0-SIDECAR-f1.md`. Decisions D15–D26: `sidecar/NOTES.md` "Review r1 fix round" on the branch.
- **Branch:** `wp/P0-SIDECAR` @ `75da0e4`. Diff: `git -C /home/user/freelancer/carrier-mod diff main...wp/P0-SIDECAR`; fix-round delta: `git diff cf21a75..75da0e4`.
- **Standards:** `CLAUDE.md` guardrails (6: network; 7: tests), `docs/plan/CONVENTIONS.md` §7 ports and §13 sidecar safety (wins over the spec), `docs/plan/TESTING.md`, `local/research/R6-copilot-sidecar.md` §7.

## Do all of these

1. **Each round-1 finding:** confirm the fix in code and that its test fails on the old code and passes on the new. Mark each fixed | partially fixed | not fixed, with evidence.
2. **Re-run** with `$FLMOD_SIDECAR_VENV`: `pytest -q sidecar/tests` (at least 3 consecutive runs; report any flake), `run.sh --selftest` on an ephemeral port, and `ss -ltnup` while it runs (only 127.0.0.1, no IPv6, no UDP). Also run the shared `$FLMOD_VENV` pytest and confirm the skips are clean skips (that is what GitHub Actions will run: no GPU, no models, no `$FLMOD_LOCAL`; tests must skip, not fail, there).
3. **Protocol decisions for W2-REFLEX** (the C++ client is written from `docs/spec/ipc.md`): judge deferred acks while paused, late-ack reconciliation, PTT cancel with reason, per-process unique ids, abort-not-half-close, and "the DLL's IPC worker owns the link". Is the spec unambiguous enough for a C++ author who never reads the Python? List gaps as findings.
4. **Re-fuzz** the server with the round-1 list (malformed, deep, huge, partial, binary, slowloris lines; mid-message disconnects; 50 rapid reconnects), plus the new paths: pause/resume storms, acks arriving after session end, PTT cancel mid-utterance.
5. **Safety audit again** (CLAUDE.md 6, CONVENTIONS §13): loopback only; no outbound network except the future brain CLI; the brain sandbox (empty cwd outside the repo, env allowlist, `--tools ""`, `--strict-mcp-config`, `--disallowedTools 'mcp__*'`, `--setting-sources ""`) is encoded correctly; no import from Adam's other projects. Assess the open proposal (D7): `harness/lane.sh` exporting `FLCOPILOT_FORCE_TEST_PROFILE=1` with `FLCOPILOT_PORT`.
6. **Public safety:** `$FLMOD_VENV/bin/python -I $FLMOD_LOCAL/snapshots/check_public.py --tree <your checkout>` and `--commits=main..wp/P0-SIDECAR`.

## Verdict (your last message)

```
REVIEW: P0-SIDECAR ROUND 2   VERDICT: PASS | CHANGES_REQUIRED
R1 FINDINGS: <finding>: fixed|partially fixed|not fixed — evidence (one line each)
COVERAGE: REQ-…: covered|partial|missing (one line each)
REPRODUCED: <test> — reproduced|not reproduced — evidence
FINDINGS (ordered by severity): [BLOCKER|MAJOR|MINOR] file:line — problem — required change
```

PASS only if there are no BLOCKER or MAJOR findings and the test suite and selftest reproduced.

## Orchestrator notes

- `source /home/user/freelancer/carrier-mod/tools/env.sh` first.
- Inspect the branch detached in your worktree (`git checkout --detach wp/P0-SIDECAR`).
- **No audio may reach the speakers and nothing may call the real Claude CLI.** Test profile, null sink and fake LLM only. You may re-run `voice_smoke` only with a null or file sink (check the code first); it may use the GPU (check `nvidia-smi -q | grep 'Recovery Action'` is `None` before and after; if not, log to `$FLMOD_LOCAL/gpu-fault.log`). Offline only (`HF_HUB_OFFLINE=1`).
- Ports: ephemeral or ≥ 29179 that no lane uses; never 29170 (the play port). Bind 127.0.0.1 only.
- You never edit the branch, `main`, `state/`, `local/` (except your run dir) or the main checkout. Scratch output goes under `$FLMOD_TESTRUNS/<UTC stamp>-review-P0-SIDECAR-r2/`.
- Commits (you should make none): if you must, end with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>` and `Claude-Session: https://claude.ai/code/session_01FbAaS1xfbG3DHutbmesKK5`.
