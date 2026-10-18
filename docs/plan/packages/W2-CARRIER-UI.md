# W2-CARRIER-UI: Aboard and in-space carrier UI

- **Type:** impl
- **Wave:** 2 (sub-wave 2c, CONVENTIONS §8)
- **Depends on:** W2-CARRIER-GAME (merged), ARCH-1
- **Unblocks:** M1-PLAYTEST, W3-ESCORT (in-space order path), W3-AMBUSH (alert UI hooks), W4-HIRING (roster entry point)

## Goal

**Aboard a carrier**, the player gets a "Carrier" menu beside the shops. From it they can:

- order travel to in-system points, adjoining systems or any reachable system;
- watch progress ("two systems out, arriving in 4 minutes");
- Stop;
- see the carrier's status;
- move cargo between their ship and the carrier's hold;
- resupply nanobots and munitions.

**In space**, a carrier command panel and hotkey let them order a nearby carrier to travel (escort mode, wired fully by W3-ESCORT) or stop.

## Requirements

- **REQ-W2-CARRIER-UI-1** (D-7.1): **"Travel to" in the docked menu, beside the shops.**
  - A native NavBar button "Carrier" (or the W1-UI fallback) appears only when docked at a carrier base. It opens the Carrier panel.
  - Destinations:
    - in-system points (planets, bases and stations, gates and holes in the carrier's current system, from W1-WORLD);
    - adjoining systems;
    - "Plot course…" (any reachable system, searchable list).
  - Unreachable destinations show the reason ("No route: gate locked").
- **REQ-…-2b** (CONVENTIONS §9): **re-route.** While in DockedTravel the Travel tab stays usable. Picking a new destination re-routes from the current position (state stays DockedTravel). The UI shows the new route without a Stop.
- **REQ-…-2** (D-7.2): **progress display.** While in DockedTravel, show the W2-CARRIER-LOGIC progress sentence, the route list with the current leg highlighted, the ETA in minutes, and a progress bar. Update at least once per second of game time.
  - Also mirror the sentence into the base info text (runtime infocard override via the text service) so it is visible without opening the panel.
- **REQ-…-3** (D-7.3): **Stop button** while travelling. After Stop, show "Holding at <nearest named place>" and enable launch.
  - Launch attempts while in warp show the reason. The block itself is in W2-CARRIER-GAME; this package supplies the text.
- **REQ-…-4:** **status page:**
  - name, class, tier, look;
  - hull %, shield % (if fitted);
  - nanobot stock / capacity, missile and torpedo stock / capacity;
  - hold used / capacity;
  - docking bays used / total;
  - crew wingmen (from the W4 contract later; show a placeholder now);
  - state and location;
  - operating-cost hint (estimated resupply cost per hour of combat, from W1-CARRIER-DESIGN data).
- **REQ-…-5** (D-3.2, D-4.5): **hold transfer.** A two-list transfer (player ship cargo ↔ carrier hold) with quantity selection.
  - Uses W1-INVENTORY transactions (`pub::Player::RemoveCargo` / `AddCargo` under the hood) and respects the player ship's hold and nanobot/battery limits and the carrier's hold capacity.
  - Border/Edge and up: the hold can also buy and sell commodities at this base's market prices (D-4.5 "commodity trading in the hold"). Implement only if W1-INVENTORY exposes market prices; otherwise log a degrade note.
- **REQ-…-6** (D-8.6): **quartermaster.** Bulk-buy nanobots (`ge_s_repair_01` at its goods price, default 200 cr), missiles and torpedoes for the carrier's launchers, at data prices, up to capacity. Shows "Resupply to full: N cr" as a one-click action.
- **REQ-…-7** (D-7.4): **in-space carrier command.**
  - A hotkey (default: configurable, no conflict with the vanilla keymap; propose one, document it) plus a small overlay panel listing the player's carriers.
  - For a carrier **within 10 km**: Travel (escort mode; destination picker as in REQ-1), Stop.
  - For carriers elsewhere: status and location only, read-only.
  - Escort orders call the carrier model. If W3-ESCORT isn't merged yet, the command shows "Escort travel not yet available" behind a capability flag.
- **REQ-…-8:** **fleet overview.** An all-carriers list (name, state, system, ETA, hull) reachable from both panels.
- **REQ-…-9** (D-15.2, D-15.3):
  - Freelancer look; readable at 1280×720 and 3744×2106.
  - Keyboard and mouse.
  - Never covers the native Launch button.
  - Closes on launch.
  - No input capture leaks to flight controls after closing.

## Context pack (read before writing code)

- `CLAUDE.md`
- `CONVENTIONS.md` (all; §4 devbridge/ui verbs, §8 sub-waves, §9 state machine)
- `DESIGN.md` §3, §4.5, §7.1–7.4, §8.6, §15
- `TESTING.md` §Scenarios, §Vision, §Playbot
- `state/ENGINE_FACTS.md`: S-UI (native button, overlay, base info override, key polling)
- Contracts: UI kit, text service (IDS override), carrier model (orders, progress), world (destinations, names), inventory (transfer, resupply), carrier object registry, base-binding (which carrier I'm aboard), platform key input
- `local/research/R5-sp-architecture.md` §4.1 (room UI, NavBar), §5 (messaging), §7 (keys)
- `local/research/R1-fluf.md` §3 (UI tech) if Track A

## Ownership

- **Owns:** `src/game/ui/carrier/`
- **Test assets:** per the BUILD_PLAN §6 conventions: `src/game/ui/carrier/scenarios/`, `harness/rubrics/carrier_ui_*`.
- **Reads:** `src/contracts/`, `src/game/ui/kit/`, `src/game/text/`, `src/logic/carrier/`, `src/logic/world/`, `src/logic/economy/`, `src/game/carrier/`
- **Must not touch:** everything else

## Contract

- **Consumes:** the contracts listed above.
- **Provides:**
  - the Carrier panel and the in-space command panel;
  - a capability hook for W3-ESCORT (escort orders) and W3-AMBUSH (alert banner);
  - a roster tab placeholder for W4-HIRING / W4-WINGMEN (an extension point declared in the contract);
  - panels openable for screenshots via the W1-UI verbs `ui.open carrier.panel[:<tab>]` / `ui.open carrier.command`. Widget ids: `carrier.navbutton`, `carrier.launch`, `carrier.stop`, `carrier.travel.<dest>`, … (CONVENTIONS §4; `ui.find`/`ui.click`).

## Tasks

1. Base-menu entry at carrier bases; Carrier panel with tabs: Travel, Status, Hold, Quartermaster, Fleet.
2. Destination picker (points, adjoining systems, plot course) with reachability reasons.
3. Live progress, the base-info mirror, Stop.
4. Hold transfer and quartermaster through W1-INVENTORY.
5. In-space command panel and hotkey.
6. Scenarios with screenshots and vision rubrics.

## Acceptance (all automated; the agent runs them and attaches evidence)

- **Host tests:** destination list building (fixture world), sorting and labels; quantity clamps for transfers; resupply cost math.
- **In-game scenarios** (playbot input on an input lane):

  | Scenario | Steps and expected result |
  |---|---|
  | `carrier_ui_travel_order` | Aboard in Li01 (`carrier.buy …`, `base carrier:<name>`): open the panel by synthetic click on `carrier.navbutton`, pick "Colorado" (adjoining), confirm. **Expect** `ev=carrier.state … state=DockedTravel dest=Li03`; screenshot; vision: "a travel progress line similar to 'one system out, arriving in N minutes' is visible". |
  | `carrier_ui_plot_course` | Pick a 2+ hop destination. **Expect** the route list shows all systems in order; HARNESS route matches. |
  | `carrier_ui_reroute` | While travelling, pick a different destination. **Expect** state stays DockedTravel, the route list updates, and no Stop is needed. |
  | `carrier_ui_stop` | Stop mid-trip. **Expect** "Holding at …" shown; launch succeeds. |
  | `carrier_ui_hold_transfer` | Move 20 units of a commodity ship→carrier and back. **Expect** exact quantities on both sides; capacity limits enforced. |
  | `carrier_ui_resupply` | Nanobots 0 → full. **Expect** credits reduced by the exact cost; stock = capacity. |
  | `carrier_ui_inspace_command` | In space within 10 km, press the hotkey. **Expect** the panel lists the carrier with Travel and Stop enabled; at 15 km Travel is disabled with the reason. |
  | `carrier_ui_layout_res` | All tabs at 1280×720 and 3744×2106. Vision: no clipped or overlapping text; the Launch button is not covered. |

- **Negative tests:** panel open when the carrier gets ambushed (W3 later; here: a forced state change while open must refresh, not crash); F1 pause with the panel open; close on launch.

## Engine facts to rely on / verify

- S-UI: infocard override visible in the base info panel; NavBar button; key polling in docked and space contexts.

## Pitfalls

- FmtStr-based native text needs IDS (R5 §5). Use the text service (overrides or our resource DLL) for native widgets; the overlay can render raw strings.
- Don't poll the engine for distances every frame for every carrier. Throttle to 4 Hz.

## Fallbacks and degrade path

- **Without native buttons:** a docked hotkey plus toast.
- **Without the base-info override:** panel only.
- **Degraded:** hold commodity trading disabled (`carrier.hold_trading = false`).

## Report (the agent's final message)

Per the template, with screenshots of each tab at both resolutions.

## Gate-time addendum

Track, UI facts, contract paths, lanes, attempt and prior notes.
