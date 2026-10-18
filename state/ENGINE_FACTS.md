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

(none yet; Phase 0 spikes fill this in)

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
