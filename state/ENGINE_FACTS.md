# Engine facts verified in game

This file holds facts **proven in this build's own in-game tests**. They override the research files wherever the two disagree.

Only the orchestrator appends entries, copying them from package reports. Each entry needs evidence: a log path, `HARNESS` lines and/or a screenshot path.

Format:

```
## EF-<nnn> — <one-line fact>
- Status: VERIFIED | DISPROVEN (research claim was wrong) | PARTIAL
- Evidence: <paths>
- Source package: <ID> (attempt n), date
- Supersedes: <research file §, if any>
- Notes / how to use:
```

## Facts

## EF-001 — Wine's builtin vcruntime140 kills the process when an exception leaves a catch block into a try in the same function, unless code is built with `-mstackrealign`
- Status: VERIFIED
- Evidence: `$FLMOD_TESTRUNS/20261018T072930Z-toolchain-loadproof/`, `20261018T072950Z-ehprobe/` (37 PASS / 3 KNOWN-BROKEN / 0 FAIL per track × CRT); negative control `20261018T054555Z-ehprobe/` and the r3 review's `R/24` (without the flag: 4 FAIL under builtin, 0 under native)
- Source package: P0-TOOLCHAIN (attempt 1), 2026-10-18
- Notes / how to use: `/clang:-mstackrealign` is in every TU's flags (stage 10's `check_flags.py` enforces it). Native vcruntime140 also avoids it. Prebuilt code we don't compile (FLUF, HDE DLLs) can still hit it under the builtin runtime. Run `toolchain/ehprobe.sh --crt both` per D110.

## EF-002 — `__try` at /O2 returns with EBX/ESI/EDI clobbered after a handled fault; `catch(...)` sees an access violation only under /EHa and only inside an opaque call
- Status: VERIFIED (both runtimes, both tracks)
- Evidence: ehprobe cases `a_seh_regs_raw`, `b_catchall_av_inline`, `b_catchall_av_call` (KNOWN-BROKEN in every run above)
- Source package: P0-TOOLCHAIN (attempt 1), 2026-10-18
- Notes / how to use: coding rules, no flag fixes them: use the `flmod_seh_guard` clobber barrier (toolchain/ABI.md §6.1) and the §6.7 hook template (work under the guard, try/catch inside it, `catch(...)` logged as "possibly SEH").

## EF-003 — A fault inside Common.dll is caught by `flmod_seh_guard` with the caller's registers intact; C++ EH works across msvcrt.dll frames, worker threads, nested guards and VC6-style `_CxxThrowException`
- Status: VERIFIED (both runtimes, both tracks; host process loading the game DLLs, not an in-game run)
- Evidence: ehprobe `hook` group (13 cases) in the runs above; `PhySys::DeactivatePhysics((CObject*)0x10)` as the engine fault
- Source package: P0-TOOLCHAIN (attempt 1, fix round 2), 2026-10-18
- Notes / how to use: in-game items (exceptions through FLUF.dll frames, VEH/SetUnhandledExceptionFilter crash handlers, throws in DllMain/static init) are untested: toolchain/ABI.md §6.8, for P0-TRACK-A/B.

## EF-004 — The dev/play prefixes set `msvcp140*`, `vcruntime140*`, `ucrtbase`, `concrt140`, `msvcp1?0` (and others) to `native,builtin`, so a CRT DLL dropped next to Freelancer.exe silently switches the whole process's runtime
- Status: VERIFIED
- Evidence: P0-TOOLCHAIN `+loaddll` runs E1/E2 (toolchain/NOTES.md "Question 3"); r3 review confirms the full list (toolchain/ABI.md §6.6)
- Source package: P0-TOOLCHAIN (attempt 1), 2026-10-18
- Notes / how to use: deploy must assert no stray CRT DLL in the EXE dir. Default runtime is Wine's builtin (D110 / f1 recommendation); the app-local native redist is the Track A fallback.

## EF-005 — Wine drops console stdout redirected to a regular file; pipes work
- Status: VERIFIED
- Evidence: P0-TOOLCHAIN load proof (toolchain/NOTES.md)
- Source package: P0-TOOLCHAIN (attempt 1), 2026-10-18
- Notes / how to use: pipe console output (`| tee`) when capturing from Wine console programs.

## EF-006 — Faster-whisper on the RTX 3090 (CUDA, float16): ~120–140 ms speech-to-text for a 2 s clip warm (~710 ms first); Kokoro TTS first audio ~360–400 ms; ~2.3 GB VRAM; CPU fallback ~7.8 s per 2 s clip
- Status: VERIFIED (host, not in game)
- Evidence: `$FLMOD_TESTRUNS/20261018T064806Z-voice-smoke`, `…064822Z-voice-smoke-netns` (offline, loopback only), r2 review `…070235Z-review-P0-SIDECAR-r2/voice-smoke/`
- Source package: P0-SIDECAR (attempt 1), 2026-10-18
- Notes / how to use: the CPU fallback is far too slow for push-to-talk; W1-SIDECAR must require CUDA for live voice or degrade to text.


## Research claims queued for verification (from local/research)

| Claim | Research source | Verified by |
|---|---|---|
| FLUF server event hooks fire in single player with client id 1 | R1 §2 | P0-TRACK-A |
| No FLUF server tick in single player | R1 §2.4 | P0-TRACK-A |
| Frame function 0x5B2890 runs once per frame and pauses only in the F1 menu | R5 §1.3 | P0-TRACK-B |
| Saves are plain text, and unknown keys are dropped on save | R5 §3 | S-BASE |
| A runtime solar is visible in single player (3 spawn paths) | R2 fact 4 | S-BASE |
| A base can be re-pointed to another system at runtime | R5 §4.2 | S-BASE |
| Launch-position override at server.dll+0x8420C works in single player | R5 §4.2 | P0-TRACK-*/S-BASE |
| Systems without the player are frozen | R2 fact 1 | S-NPC |
| API-spawned NPCs don't despawn | R2 fact 2 | S-NPC |
| Capital NPCs use cruise or not; JumpIn visuals | R2 §4.3 | S-NPC |
| Nanobot/battery use can be triggered server-side | R2 §6 | S-NPC |
| Death loot is capped at about 6 crates | R2 fact 9 | S-NPC |
| Runtime loadout composition and added hardpoints | — | S-LOADOUT |
| Wine TCP loopback from a game DLL | R6 §2 | S-UI |
| `GetAsyncKeyState` sees VK 110 and the X mouse buttons under Wine | R6 §4.3 | S-UI |
| NPC-count scale limits and `Act_PlayerEnemyClamp` | R4 §A1.3 | S-PERF |
