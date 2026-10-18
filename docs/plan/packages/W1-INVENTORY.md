# W1-INVENTORY: inventory and economy model, transactions, wages, cargo transfer

- **Type:** impl
- **Wave:** 1
- **Depends on:** ARCH-0 (contract `inventory.hpp`); sub-wave 1a (CONVENTIONS §8). The engine-free model and host tests come first. The game adapter's in-game scenarios need same-wave siblings and are marked `DEFERRED(<ID>)` where noted → **Unblocks:** W2-YARD, W2-CARRIER-UI (hold, quartermaster), W2-LOADOUT (stocks), W2-REFLEX (carrier nanobot stock), W3-LOSS (drop everything aboard), W4-HIRING (fees, wages)

## Goal

One correct, testable source of truth for everything the mod counts:

- **Carrier holds:** cargo and stored items, including uninstalled upgrades.
- **Consumable stocks:** nanobots, shield batteries, missiles, torpedoes.
- **Credits movements:** purchases, retrofits, resupply, hire fees, daily wages.
- **Transfers** between the player's ship and a carrier.

Credits and cargo belong to the game engine. Every transaction is therefore **atomic**: check, apply to the engine, apply to our model, and roll back on failure. A crash or reload must never duplicate or lose items or credits.

## Requirements

- **REQ-W1-INVENTORY-1: Engine-free model** (`src/logic/economy/`).
  - `Inventory` holds item entries `{good nickname hash, count, health, kind: commodity|equipment|upgrade|munition|consumable, volume}` and a capacity in volume units.
  - Per-carrier `Stocks` (nanobots, batteries, per-munition-type counts) have capacities from the carrier's class, tier and upgrades.
  - Must be JSON-serializable through `persistence`, with deterministic ordering.
- **REQ-W1-INVENTORY-2: Volumes and limits.**
  - Item volumes come from the data (`volume` in `goods.ini`/equipment). Nanobots `ge_s_repair_01` and batteries `ge_s_battery_01` have `volume = 0` (R3 §5); they are capped by the stock capacity, not by hold volume.
  - Capacities come from `data/carriers` (W1-CARRIER-DESIGN) through the contract.
  - Mission cargo (`cargo = …, mission` flag) can never be transferred or dropped (R5 §3.2).
- **REQ-W1-INVENTORY-3: Wallet.**
  - Read the player's credits from `pub::Player::InspectCash` (or the platform equivalent); apply changes with `pub::Player::AdjustCash` or the S-UI/W1-PLATFORM-proven call.
  - FL cash is a signed 32-bit int (UNVERIFIED max; treat it as 2,000,000,000). Refuse a transaction that would overflow or go negative.
  - Every debit and credit has a reason code, recorded in a ledger (the last 200 entries persisted) for the UI and for tests.
- **REQ-W1-INVENTORY-4: Transactions.** `Txn` = {cash delta, cargo deltas on the player ship, deltas on carrier inventories and stocks}.
  - **Two-phase:** validate everything (cash available, hold space on the player ship via `pub::Player::GetRemainingHoldSize`, carrier capacity, item existence) → apply engine changes (`pub::Player::RemoveCargo(client, slot, count)`, `AddCargo(client, good, count, health, mission=false)`, `AdjustCash`) → apply model changes.
  - **On partial engine failure,** reverse the engine steps already done, and log `HARNESS txn=rolled_back`.
  - **Atomic with respect to saves:** the save hook runs on the main thread between frames, and transactions complete within one frame.
- **REQ-W1-INVENTORY-5: Transfer APIs.**
  - `TransferToCarrier(carrierId, good, count)` and `TransferToShip(...)`, with all-or-partial modes.
  - The player must be docked at that carrier's base (D-7, hold access) or within the quartermaster range rule chosen by W2-CARRIER-UI.
  - Equipment that is **mounted** on the player ship can't be transferred until unmounted (the vanilla dealer handles that).
- **REQ-W1-INVENTORY-6: Resupply** (D-8.6).
  - `Resupply(carrierId, stockType, count)` debits credits at the item's price × the price multiplier at the current base (the market's price, if the base sells it; otherwise the data-driven quartermaster price from W1-CARRIER-DESIGN).
  - Consumption APIs `Consume(carrierId, stockType, n)` are used by the reflex layer and W2-LOADOUT. They return the actual amount consumed (never below 0).
- **REQ-W1-INVENTORY-7: Wages ledger** (D-11.5).
  - Per-roster-entry daily wage. At each in-game day rollover (clock event from W1-CORE), debit all wages.
  - Unpaid wages accumulate as debt per pilot. Debt for 3 in-game days fires `wingman.quit` (W4-HIRING consumes it).
  - A partial payment policy (oldest debt first) is configurable.
- **REQ-W1-INVENTORY-8: Drop-all** (D-8.4). `CollectAllAboard(carrierId)` returns everything aboard (hold, stored upgrades, stocks) as a bundled list for W3-LOSS. It groups by good and computes crate bundles under a configurable crate cap (default 6, the vanilla cap per R2 fact 9). Bundle priority is by total value, with low-value items merged into the last crate. It then clears the carrier inventory.
- **REQ-W1-INVENTORY-9: Prices.** `PriceOf(good, base)` reads the deploy-time `prices.json` produced by W1-DATA (REQ-W1-DATA-16): the deployed copy in the install, generated into `$FLMOD_LOCAL/gen/prices.json`. It is game-derived and never committed. Host tests use a small synthetic prices file. It is used by the ambush cargo-value multiplier (D-9.3): `CargoValue(carrierId)`.
- **REQ-W1-INVENTORY-10: Devbridge** (additive `inv.*` namespace; ARCH-1 records it in `docs/spec/devbridge.md`):
  - `inv.show <carrier|ship>`
  - `inv.give <carrier> <good> <n>`, `inv.take <carrier> <good> <n>`
  - `inv.transfer to_carrier|to_ship <carrier> <good> <n>`
  - `inv.stock <carrier> <type> <n>`
  - `inv.wallet` (balance plus the last 10 ledger lines)
  - `inv.wages_tick` (force a day rollover; scenarios may also use W1-CORE's `time.skip 1800`)
  - `inv.audit`

## Context pack

- `CLAUDE.md`, `docs/plan/CONVENTIONS.md` (§1 paths, §4 devbridge, §8 deferred scenarios, §12 game-data hygiene)
- `docs/plan/DESIGN.md` §3.2, §5.2, §8.4, §8.6, §9.3, §11.5
- `docs/plan/TESTING.md` §Layers, §Scenarios, §SaveCompat
- `state/ENGINE_FACTS.md`: cash API, cargo APIs, hold size, mission cargo
- `src/contracts/{inventory,persistence,events,clock}.hpp`
- Research:
  - `/home/user/freelancer/carrier-mod/local/research/R2-engine-api.md` §6 (cargo APIs: `EnumerateCargo`, `RemoveCargo(client, u16 slot, u32 count)`, `AddCargo(client, good, count, f32 status, bool mission)`, `GetRemainingHoldSize`)
  - `/home/user/freelancer/carrier-mod/local/research/R5-sp-architecture.md` §3.2 (save fields: `cargo = item, count, health, , mission`)
  - `/home/user/freelancer/carrier-mod/local/research/R3-game-data.md` §5 (nanobots and batteries: price 200, volume 0, `units_per_container = 15`; marketgood fields; commodity volumes)
  - `/home/user/freelancer/carrier-mod/local/research/R1-fluf.md` §2.2 (ReqAddItem / ReqRemoveItem / ReqChangeCash hooks)
- Reference: `/home/user/freelancer/refs/FLUF/FLUF/Source/Types/ClientId.cpp` (AddCargo, AdjustCash usage), `/home/user/freelancer/refs/DiscoveryFLHook/Plugins/Public/base_plugin/` (base storage)

## Ownership

- **Owns:** `src/logic/economy/` (with `tests/`), `src/game/economy/` (with `scenarios/`), and `harness/scenarios/inventory/`.
- **Reads:** contracts, core, platform API, generated `prices.json`/`world.json`.
- **Must not touch:** carrier state (W2), UI panels (W2), contracts.

## Contract

- **Provides:** `inventory.hpp` (Inventory, Stocks, Wallet, Txn, Transfer, Resupply, Consume, WagesLedger, CollectAllAboard, CargoValue, PriceOf); events `inventory.changed`, `wallet.changed`, `wingman.quit` (ownership of the event name per ARCH-0).
- **Consumes:** `clock` (day rollover), `persistence`, `platform` (cash and cargo calls through the adapter), `events`.

## Tasks

1. Model plus serialization plus exhaustive host tests (property tests: random transaction sequences preserve totals).
2. Wallet adapter with overflow and negative guards.
3. Transaction engine with rollback; fault-injection hooks for tests (`fail_after_step=N`).
4. Transfers, resupply and consume.
5. Wages ledger with the day-rollover hook.
6. Drop-all bundling.
7. Prices and cargo value.
8. Devbridge commands and in-game scenarios.

## Acceptance

- **Host tests:**
  - `inv_capacity_limits`
  - `inv_mission_cargo_rejected`
  - `txn_rollback_each_step` (fault injection at every step leaves the totals unchanged)
  - `txn_property_conservation` (10,000 random operations: items and credits conserved, except intended debits)
  - `wages_debt_and_quit_after_3_days`
  - `bundle_cap_6_value_priority`
  - `cargo_value_matches_prices`
  - `serialize_roundtrip_stable_order`
- **In-game scenarios:**
Every in-game scenario needs the production platform and core, both same-wave siblings, so all are `DEFERRED(W1-PLATFORM, W1-CORE)`. They run in the wave integration pass. Scenario 1 also needs W1-DATA's test carrier base and W1-SPAWN.

  1. `inv_transfer_roundtrip`: fixture `HARNESS_endgame_eagle` plus a test carrier base (from W1-DATA/W1-SPAWN), player ship holding 30 Light Arms. `inv.transfer to_carrier <c> commodity_light_arms 30` → ship 0, carrier 30 → save, load → still 30 → transfer back → ship 30. `inv.wallet` unchanged.
  2. `inv_resupply`: `inv.stock <c> nanobots 0` → resupply 500 nanobots at 200 cr each → cash −100,000 exactly; stock 500; ledger line present.
  3. `inv_rollback_ingame`: inject a fault after `RemoveCargo` → the player's cargo is restored; `HARNESS txn=rolled_back`; no item duplication after save and load.
  4. `inv_wages`: 2 test roster entries with wages 1,000/day → `inv.wages_tick` ×3 with cash 0 → debt grows → `wingman.quit` fires for both after day 3.
  5. `inv_overflow_guard`: cash set near the cap → a credit that would overflow is refused with a message.
- **Soak:** 15 minutes of random transfers, resupplies and save/load (part of the W1 soak mix `harness/soak/mixes/w1.yaml`). The totals invariant is checked every minute through `inv.audit`.

## Engine facts to rely on / verify

- The exact cash API and the int range: verify in scenario 5 and record in ENGINE_FACTS.
- That `AddCargo`/`RemoveCargo` work for a docked player in SP and update the client hold UI immediately: verify (screenshot of the cargo hold after a transfer).

## Pitfalls

- Slot ids from `EnumerateCargo` change after removals. Re-enumerate before each step.
- Health (`status`) of items must be preserved on transfer (damaged equipment).
- Don't trigger `ReqAddItem` re-entrancy loops: our own `AddCargo` calls raise platform cargo events. Tag our own calls so listeners can ignore them.

## Fallbacks and degrade path

1. If `AddCargo` doesn't refresh the client UI, send the refresh the S-UI facts identify, or force a room re-enter.
2. If cash adjustments can't be made atomic, debit first and credit back on failure, logging every compensation.

## Report

Use the standard report. Include the invariants list and the fault-injection coverage table.

## Gate-time addendum

The orchestrator fills:

- ENGINE_FACTS for cash, cargo and hold-UI refresh;
- the price source (`prices.json` from W1-DATA);
- lanes;
- attempt notes;
- the commit trailer.
