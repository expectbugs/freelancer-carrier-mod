```
REVIEW: P0-SIDECAR ROUND 2b (polish check)   VERDICT: PASS
R2 MINORS:
- ipc.md spec gaps (a)–(f): fixed. Clear enough for a C++ author:
  - (a) tick reported after welcome, 5 s unknown→running fallback: safe. Commands stay untimed until the fallback, then get the normal 5 s timeout (probe: overdue at 1.5 s with a 1 s fallback and 0.5 s timeout).
  - (b) tick defined, one stopped flag, edge hook plus watchdog: clear.
  - (c) load-boundary generation counter: clear.
  - (d) ack order: clear.
  - (e) outbox: drop the oldest state, then the oldest droppable event; a never-drop list; close at a hard cap. Implementable.
  - (f) integer widths: enforced by the server. 9 tick and integer-width tests fail on 75da0e4.
- PTT state per session: fixed. On 824564a every case passes: a bare release, a stray cancel after release, a repeated press, ptt from a replaced session, pause/menu/load backstops. 8 tests fail on 75da0e4.
- Unknown-type log flood: fixed. A 3000-line flood gives 64 WARNINGs plus 1 cap notice. The test fails on 75da0e4.
- Play-port tests could bind 29170: fixed. With every guard disabled in a temp copy, 11 tests fail (they now run in a private network namespace). A poller on the host's 29170 saw 0 sockets.
- critical_hull doc: fixed; the test fails on 75da0e4.
The new tests on 75da0e4: 30 failed, 10 passed; the 10 are in-range accept cases, as the author reported.
REPRODUCED ($FLMOD_TESTRUNS/20261018T075004Z-review-P0-SIDECAR-r2b):
- Sidecar suite ×3: 351 passed each time. Shared venv: 326 passed, 15 skipped. 0 sockets seen on 29170 throughout.
- Selftest: ok on port 42487, 127.0.0.1 only. While serving on 43035, ss shows only 127.0.0.1:43035 (no IPv6, no UDP). The 4 fakegame scripts PASS. SIGTERM exits 0. `--profile test` with no port exits 2.
- In-process probes: 18 PASS, 0 FAIL, 2 OBS (finding below, and an old mic-level probe that the new pipeline check now covers).
- Out-of-process fuzz: 69/70 passed. The one failure (50_connect_close canary) is not a regression: `_on_client` is unchanged, and the 4-connection cap still counts sockets the peer already closed. In isolation the canary was refused right after the burst in 4 of 6 trials and got a pong 0.1 s later in 6 of 6.
- check_public: --tree OK (152 files); --commits OK (11 commits).
FINDINGS:
[MINOR] docs/spec/ipc.md §4.7.1 + §4.7.7, sidecar/flcopilot/pipeline.py on_tick_edge — A 1 s stall makes the watchdog send ev.pause{on:true}, and the sidecar cancels the held press. The DLL keeps treating the key as held and still sends the release, which the sidecar then ignores. Result: an order spoken through any frame hitch of 1 s or more is lost, with only a DEBUG log (VERIFIED: press, stall edge, release gave 0 utterances). Required change: mark watchdog edges (for example `ev.pause{on:true, stall:true}`) and skip the backstop for them, or have the DLL send its own cancel on a stall edge so both sides agree.
```

Nothing was committed, the worktree is clean at 824564a, and nothing used 29170 this round.
