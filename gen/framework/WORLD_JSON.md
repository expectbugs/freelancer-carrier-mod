# `world.json` schema (`fcm.world.v1`)

Produced by `fltools.worldexport` from an install (optionally combined with an overlay). It is
built at deploy time (`gen/run.py build` writes `<overlay>/world.json`, by default
`$FLMOD_LOCAL/gen/overlay/world.json`) and is **never committed**: every value comes from the
local game data. ARCH-0 promotes this file to `docs/spec/world_json.md`.

The output is deterministic: the same install bytes give the same JSON bytes (UTF-8, `indent=1`,
key order as below, no paths or timestamps).

## Conventions

| Item | Rule |
|---|---|
| Units | metres; angles in degrees |
| `pos` | `[x, y, z]` floats, system space |
| `rotate` | `[rx, ry, rz]` degrees; `world = Rz(rz) @ Ry(ry) @ Rx(rx) @ local` (column vectors). VERIFIED empirically on 2,172 patrol-path joints (R3 §3.4) |
| Zone `size` | SPHERE `[r]`; ELLIPSOID `[a, b, c]` semi-axes; BOX `[x, y, z]` full extents; CYLINDER `[radius, length]`, axis local +Y, centred on `pos`; RING treated as CYLINDER |
| IDS | global id = `dll_index * 65536 + local_id`; `name` fields are the resolved strings (null when the IDS is 0 or missing) |
| Nicknames | as written in the data (case preserved); compare case-insensitively |
| Numbers | INI integers become JSON ints, values written with a decimal point become floats |

`fltools.geometry` implements these conventions (`rot`, `contains`, `cylinder_endpoints`) and the
reference route-exposure algorithm (`exposure`).

## Top level

| Key | Type | Content |
|---|---|---|
| `schema` | string | `"fcm.world.v1"` |
| `source` | object | `freelancer_ini_universe_sha256` (fingerprint of `EXE/freelancer.ini` + `universe.ini`), `resource_dlls` (index-ordered DLL names) |
| `conventions` | object | the conventions above, as text |
| `systems` | object | system nickname -> system (below), in `universe.ini` order |
| `links` | list | one entry per directed jump connection |
| `objects` | object | system nickname -> list of objects |
| `hazards` | object | system nickname -> list of hazards |
| `trade_lanes` | list | one entry per trade-lane ring chain |
| `zones` | object | system nickname -> list of encounter/path zones |
| `factions` | object | faction (`InitialWorld [Group]`) nickname -> faction data |
| `player_start_reps` | object | faction -> starting reputation, from `EXE/newplayer.fl` `house = rep, faction` |

## `systems[<nick>]`

`nickname`, `name` (from `strid_name`), `strid_name`, `ids_info`, `navmap_pos` (`[x, y]`, nav-map grid),
`region` (from `DATA/UNIVERSE/Territory.ini`: the format text with the system name removed,
e.g. "<HOUSE> Space" for house systems, "<GROUP NAME>" for `[Systems]` groups; null when the system
is not listed), `house` (the house name string for house systems, else null), `file`
(universe-relative system file), `visit`, `navmapscale`, and `missing_file: true` if the system file
does not resolve.

## `links[]`

| Field | Meaning |
|---|---|
| `from_system`, `from_object` | system and object holding the `goto` |
| `to_system`, `to_object`, `tunnel` | the three `goto` values |
| `kind` | `jumpgate` (solar type JUMP_GATE), `jumphole` (JUMP_HOLE), `airlock` (AIRLOCK_GATE), `nomad_gate` (archetype `nomad_gate`) |
| `archetype` | object archetype |
| `from_pos`, `to_pos` | positions of the two objects (`to_pos` null if the target object is missing) |
| `reputation`, `name` | owning faction and resolved object name |
| `locked_player` | the object's CreateID is in `InitialWorld [locked_gates] locked_gate` or in `newplayer.fl` `locked_gate` (story locks) |
| `lock_sources` | which of `initialworld` / `newplayer` lock it |
| `locked_npc` | the object's CreateID is in `npc_locked_gate` (NPCs never path through it) |

HDE: 232 directed links (84 jumpgate, 140 jumphole, 6 airlock, 2 nomad_gate), every one with a
matching return link (tests compare against R3's extract).

## `objects[<sys>][]`

`nickname`, `archetype`, `type` (solararch `type`, e.g. PLANET, SUN, STATION, JUMP_GATE,
TRADELANE_RING), `pos`, `rotate`, `ids_name`, `name`, `base`, `dock_with`, `reputation`, `loadout`,
`parent`, `visit`, `ids_info`, `atmosphere_range`, `radius` (solararch `solar_radius`; for planets/suns
without one, the archetype's numeric suffix), `dockable` (archetype has a `docking_sphere`),
`death_zone_radius` (radius of a damaging SPHERE zone centred within 1 m of the object, else null),
`exclusion_radius` (largest asteroid/nebula exclusion SPHERE centred on the object, else null),
`goto` (`{system, object, tunnel}`, jump objects only), and for trade-lane rings `next_ring`,
`prev_ring`, `tradelane_space_name`.

## `hazards[<sys>][]`

Every entry has `kind` and its geometry (`shape`, `pos`, `rotate`, `size`, as for zones) where it
has one.

| `kind` | Extra fields |
|---|---|
| `sun`, `planet` | `object`, `pos`, `radius`, `death_zone_radius` |
| `death_zone` | `zone`, `damage`, `object` (the sun/planet it is centred on, or null) |
| `asteroid_field`, `nebula` | `zone`, `file` (field INI), `exclusions` (zone nicknames), optional `damage`, `interference`, `drag_modifier`, `property_flags` of the field zone; `missing_zone: true` if the zone is not in the system |
| `exclusion` | `zone`, `fields` (field zones that exclude it), `object` (centred object or null) |
| `effect_zone` | `zone`, `interference` and/or `drag_modifier` (zones with an effect that are neither fields nor death zones) |

## `trade_lanes[]`

`system`, `rings` (ring object nicknames in `next_ring` order), `ring_positions`, `start_pos`,
`end_pos`, `start_name`, `end_name` (resolved `tradelane_space_name` of the first/last ring; null if
none), `reputation` (first ring), `length_m` (sum of ring-to-ring distances, rounded). A chain starts
at every ring whose `prev_ring` is not a ring of the same system. HDE: 124 chains.

## `zones[<sys>][]`

Zones that have at least one `encounter` or a `path_label` (HDE: 3,801 zones, 6,608
zone x encounter x faction rows).

| Field | Meaning |
|---|---|
| `nickname`, `shape`, `pos`, `rotate`, `size` | identity and geometry |
| `comment`, `ids_name` | as written |
| `toughness`, `density`, `repop_time`, `max_battle_size`, `relief_time` | numbers (null when absent) |
| `pop_type` | list of words, or null |
| `path_label` | `[label, leg_index]` or null |
| `usage`, `mission_eligible` | as written (`patrol` / `trade` ...) |
| `density_restriction` | list of `[count, ship_class]` |
| `attack_ids`, `tradelane_attack`, `property_flags` | numbers or null |
| `encounters` | list of `{encounter, level, chance, factions: [[faction, weight], ...]}`; each `faction` line belongs to the `encounter` line before it |
| `factions` | every `faction` line of the zone in order (the zone population list), `[[faction, weight], ...]` |

## `factions[<nick>]`

`name`, `short_name` (resolved `ids_name` / `ids_short_name`), `legality` (`faction_prop.ini`),
`n_npc_ships` (its `npc_ship` entries that exist in `npcships.ini`), `npc_ships_by_level`
(`{"<N>": count}` over the `dN` words of each ship's `npc_class`), `cd_fraction_by_level`
(`{"<N>": fraction}` of those ships whose loadout mounts a cruise disruptor:
`cruise_disruptor01_mark01`, `cruise_disruptor01_mark02`, `nomad_cruise_disruptor01`, or any
`[CruiseDisruptor]` equipment).

## Route-exposure reference data

`flworldexport --route-exposure-golden <dir>` writes `<dir>/route_exposure.json`: a list of
gate-to-gate legs chosen from the data (no hard-coded coordinates), each with the inputs (`system`,
`a`, `b`, `step` 500 m, `hostile_threshold` -0.6, reputations = `player_start_reps`) and
`geometry.exposure`'s result per hostile faction (`metres_inside`, `weighted`, `max_level`, `zones`).
The tests check this port against R3's own `route_exposure.py` on R3's extracts. Write it to
`$FLMOD_GOLDEN/route_exposure/` for W1-WORLD's golden tests; never commit it.
