# W2-YARD: Carrier Yard panel (buy, configure, retrofit)

- **Type:** impl
- **Wave:** 2 (sub-wave 2c, CONVENTIONS §8)
- **Depends on:** W2-CARRIER-GAME (merged), ARCH-1
- **Unblocks:** M1-PLAYTEST, W3-NOMAD (Gammu yard enablement), W4-* (fleet)

## Goal

At designated yard bases the player opens a **Carrier Yard** panel from the base menu. There they:

1. browse that yard's carrier classes;
2. configure upgrades from that yard's catalog;
3. name the carrier and pay;
4. find their new carrier waiting, Stopped, near the yard.

Later, a carrier parked within 10 km of any yard can be retrofitted there with that yard's catalog. This is how the player shapes their fleet (D-5).

## Requirements

- **REQ-W2-YARD-1** (D-5.1, D-6): **yard bases and button.** A "Carrier Yard" button appears in the base menu **only** at the yard bases listed in `data/yards` (initially the D-6 table: `Li01_07_Base`, `Br01_02_Base`, `Ku01_03_Base`, `Rh01_02_Base`, `Bw03_01_Base`, `Bw06_01_Base`, `Bw02_01_Base`, `Ew04_01_Base`, `Ew06_02_Base`).
  - Use the native NavBar button helper (W1-UI). If the platform has no proven native button, use the fallback entry chosen by W1-UI (hotkey plus overlay prompt).
- **REQ-…-2** (D-5.1, D-4.1, D-4.2): **buy flow.**
  1. Pick a class (only classes this yard offers, per `data/yards`).
  2. Preview the stats (hold, hull, bays, mounts, speed, services, operating-cost hint) and the slot layout.
  3. Configure upgrades from **this yard's catalog** (only valid combinations, validated by W2-LOADOUT's composer).
  4. Name the carrier.
  5. Pay. Price = tier base × class multiplier + upgrades; full price, no refunds (D-3.3).
  6. The carrier spawns **Stopped at a safe point near the yard base** (W1-WORLD safe stop; ≤ 5 km from the base, outside its docking ring and exclusion zones).
- **REQ-…-3** (D-1.6, D-2.1): **no player-level gating.**
  - The only purchase conditions are enough credits and the player's reputation with the yard base's faction being non-hostile, i.e. the player can dock there (decision: "if I have the faction" = not hostile; log it).
  - The Nomad yard additionally requires the Nomad unlock flag (REQ-7).
- **REQ-…-4** (D-5.2): **retrofit.** Lists the player's carriers that are **Stopped within 10 km of this yard base** (distance between carrier and base solar, from `CarrierObjectRegistry`).
  - For one carrier: install, remove or replace upgrades from this yard's catalog.
  - Removed upgrades go into that carrier's hold as items (W1-INVENTORY). No refunds.
  - Installing an upgrade from the hold costs nothing but the slot. Installing from the catalog costs its price.
  - Changes apply immediately: W2-LOADOUT apply, then a solar respawn.
- **REQ-…-5** (D-3.1): **fleet cap reporting.** Show "Fleet: n / cap" with the cap and its reason from the base-binding mechanism (W2-CARRIER-GAME contract). A cap reached disables Buy with that reason. Never hide the cap.
- **REQ-…-6** (D-5.4): **per-yard catalogs.** Exactly as given in `data/yards/<yard>.yaml` (W1-CARRIER-DESIGN): categories, Mk levels, prices. The panel shows only what this yard sells, and marks items better than the player could buy elsewhere so far (optional nicety).
- **REQ-…-7** (D-12.1): **the Gammu yard is locked** until the persistent flag **`nomad_gate_unlocked`** (CONVENTIONS §2) is set. Locked text, in Freelancer voice: "The machines here do not build for strangers. Prove yourself against the Nomad battleship in this system." It shows nothing for sale. The flag check is live; no reload is needed after unlocking.
- **REQ-…-8** (D-15.2, D-15.3):
  - Freelancer look via the W1-UI kit.
  - Usable at 1280×720 and 3744×2106.
  - Keyboard: Tab/arrows/Enter/Esc. Mouse: everything.
  - Names: 1–32 printable characters, unique within the fleet.
- **REQ-…-9:** **transaction safety.**
  - Deduct credits and create the carrier atomically on the main thread: if the spawn fails, refund and show the error.
  - The new carrier and the credits are saved together on the next save.
  - Devbridge (CONVENTIONS §4, `yard.*` namespace) drives the same code path as the UI:
    - `yard.open`
    - `yard.buy class=<c> tier=<t> name=<n> [upgrades=<a,b>]`
    - `yard.install <carrier> <upgrade>` / `yard.remove <carrier> <upgrade>`
    - `yard.state`
    - `yard.test_unlock_gammu`: test-only; sets `nomad_gate_unlocked` through the flags service

    Events: `ev=yard.purchase carrier=… price=…`, `ev=yard.refused reason=…`.

## Context pack (read before writing code)

- `CLAUDE.md`
- `CONVENTIONS.md` (all; §2 flags, §4 devbridge, §8 sub-waves)
- `DESIGN.md` §2.1, §3, §4, §5, §6, §12.1, §15
- `TESTING.md` §Scenarios, §Vision, §Playbot
- `state/ENGINE_FACTS.md`: S-UI (native button, panel input), S-BASE (purchase transaction from a custom panel, spawn near base)
- `docs/design/CARRIERS.md`, `data/carriers/`, `data/yards/`
- Contracts: UI kit, text, inventory/economy (wallet, transactions), carrier model (create carrier), loadout service (validate, apply), base binding (fleet cap), world (safe stop near base), flags (Nomad unlock)
- `local/research/R3-game-data.md` §6 (shipyards and lore), §2.4 (Gammu), §5 (prices for context)
- `local/research/R1-fluf.md` §3.2 (NavBar button template `ship_dealer_enhancements`) if Track A

## Ownership

- **Owns:** `src/logic/yard/`, `src/game/ui/yard/`
- **Test assets:** per the BUILD_PLAN §6 conventions: `src/logic/yard/tests/`, `src/game/ui/yard/scenarios/`, `harness/rubrics/yard_*`.
- **Reads:** `src/contracts/`, `src/game/ui/kit/`, `src/game/text/`, `src/logic/economy/`, `src/logic/carrier/`, `src/game/loadout/`, `src/game/carrier/`, `data/`
- **Must not touch:** everything else; the yard data files belong to W1-CARRIER-DESIGN

## Contract

- **Consumes:** UI kit (window, list, button, text input, confirm dialog), text service, wallet and inventory, the carrier model's `CreateCarrier`, loadout validate and apply, the base-binding cap query, the safe-stop query, the flags service.
- **Provides:** the yard logic API (offers, quote, validate, purchase, retrofit) and its devbridge commands.

## Tasks

1. Yard logic (engine-free): offers per yard, quoting, validation via the composer, purchase/retrofit transactions with rollback.
2. Panel UI: class list, stat preview, slot configurator, name entry, confirmation, fleet cap line, locked state.
3. Base-menu entry (native button or fallback) at yard bases only.
4. Retrofit flow with the 10 km eligibility check.
5. Devbridge commands; scenarios.

## Acceptance (all automated; the agent runs them and attaches evidence)

- **Host tests:**
  - quotes for every yard × class (price formula);
  - validation rejects slot overflow;
  - transaction rollback on simulated spawn failure;
  - retrofit moves removed items into the hold;
  - fleet cap behavior.
- **In-game scenarios:**

  | Scenario | Steps and expected result |
  |---|---|
  | `yard_button_only_at_yards` | Fixture `HARNESS_yard_Li01_07_Base`, then `base Li01_01_Base` (Manhattan). **Expect** `ui.find yard.navbutton` → `visible=1` at Norfolk and `visible=0` at Manhattan; screenshots; vision: "a Carrier Yard button is present in the base menu" true/false. |
  | `yard_buy_fleet_carrier` | Fixture `HARNESS_yard_Li01_07_Base` (60M credits), input lane. Open the panel via input (playbot clicks) and buy a Fleet Carrier with 2 upgrades. **Expect** credits reduced by exactly the quoted price; `ev=carrier.state … state=Stopped` within 5 km of `Li01_07_Base`; screenshot of the panel (vision: classes listed, prices legible, no overlapping text at 1280×720). |
  | `yard_insufficient_funds` | `cash 1000`. **Expect** Buy is disabled with a reason (`ev=yard.refused reason=funds`); no credit change. |
  | `yard_retrofit_10km` | One carrier Stopped 8 km from the yard is eligible. Another, moved to 15 km with `carrier.teleport_model`, is shown greyed with "too far (15.0 km; must be within 10 km)", and `yard.install` on it is refused (`ev=yard.refused reason=distance`). On the eligible one: install turrets, remove plating. **Expect** plating in the hold and the loadout change visible (`carrier.loadout <id> show`). |
  | `yard_gammu_locked_then_unlocked` | Fixture `HARNESS_yard_Ew06_02_Base`. Gammu without the flag shows the locked text. `yard.test_unlock_gammu`. **Expect** offers appear without a reload. |
  | `yard_ui_4k` | The same panel at 3744×2106. Vision: readable, scaled, within the screen bounds. |

- **Negative tests:** duplicate name; buying during F1 pause (blocked, or deferred safely); save immediately after purchase then reload (the carrier exists, credits are consistent).

## Engine facts to rely on / verify

- S-UI: the NavBar button and click path; overlay input capture while docked.
- S-BASE: spawning a solar near a base right after a panel transaction is safe when deferred one tick.

## Pitfalls

- Credits change via `pub::Player::AdjustCash` on the main thread; never from a UI callback that runs mid-engine-iteration. Defer one tick.
- Don't show the Yard at the Osiris mission bases or at story systems.

## Fallbacks and degrade path

- **Without a native button:** a hotkey plus an on-dock toast "Carrier Yard available: press <key>".
- **Degraded:** the retrofit UI offers only whole-package swaps per slot category (if W2-LOADOUT degraded to variants).

## Report (the agent's final message)

Per the template, with screenshots of each panel state.

## Gate-time addendum

Track, UI facts, base plan (cap), contract paths, lanes, attempt and prior notes.
