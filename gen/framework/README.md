# Generator framework (`gen/framework/`, entry point `gen/run.py`)

Owned by P0-DATATOOLS. W1-DATA and later packages add generators; they never edit this folder.

## Commands

Run everything with `$FLMOD_VENV/bin/python -I gen/run.py ...`.

| Command | What it does |
|---|---|
| `build --install <HDE> [--out <dir>] [--only a,b] [--text-ids <f>] [--data-dir <d>] [--no-world]` | Runs the generators against the *pristine* install view and writes an overlay (default `$FLMOD_LOCAL/gen/overlay/`). Never writes into the install. |
| `deploy --install <HDE> [--overlay <dir>] [--force]` | Builds into a temp overlay (or takes `--overlay`), copies its files onto the install and applies its patch units. Idempotent; refuses the play prefix and refuses to overwrite files that are not ours. |
| `undeploy --install <HDE> [--force]` | Removes every file and patch region a deploy added; the install returns to its original bytes. |
| `validate --install <HDE> [--overlay <dir>] [--json <f>]` | `fltools.validate` + `fltools.hashscan` on install + overlay; exit 1 on any ERROR or hash collision (CI stage 40 uses this). |
| `list` | Lists discovered generators. |

"Pristine": carrier-mod marker regions are stripped on read and files listed in the install's
`carrier-mod.deploy.json` are hidden, so a build never depends on whether the install was
deployed before.

**Deploy is transactional.** Before the first write it checks the overlay (manifest schema, every
file's sha256, `patches.json` against the manifest), the target's `[Resources]` index against
`MANIFEST.ids_index`, foreign or changed files, the deploy and patch state files, and plans every
patch unit in memory against its baseline; any problem is one `ERROR:` line and nothing is
written. Then it saves an `in_progress` deploy state listing every file (and every directory it
will create) before copying, and the patch state records a file before it gains marker regions.
After any interruption (disk error, kill), `undeploy` returns the install to its original files
and directories (also removing our `*.carrier-mod.tmp` leftovers; it deletes the deploy state
last), and a plain re-deploy also completes. Every write path refuses the play prefix
(`fltools.safety`).

- **Locking:** `deploy` and `undeploy` hold `$FLMOD_LOCKS/deploy-<sha256(realpath)[:16]>.lock`,
  so two of them never interleave on one install (they wait up to `DEPLOY_LOCK_TIMEOUT`, 900 s).
- **Temp overlay:** `deploy` without `--overlay` builds under `$TMPDIR` (else `$TEMP`, `$TMP`,
  `/tmp`) and refuses a temp dir inside the play prefix without writing anything there.
- **Paths:** generator paths (`write_file`, `write_data`, `patch`), manifest entries and deploy
  state entries are root-relative; absolute paths and `..` are refused, and a destination that
  resolves outside the install root (e.g. through a symlinked directory) is refused.

## Writing a generator

A generator is `gen/<name>/generator.py` or `gen/plugins/<area>/generator.py` (W1-DATA owns `gen/`
outside `framework/` and `models/`):

```python
ORDER = 100          # optional, default 500; runs in (ORDER, name) order
ENABLED = True       # optional; False keeps it out of default builds (--only still runs it)

def generate(ctx):
    ids = ctx.strings.register("carrier.name.fleet", "Fleet Carrier")      # -> global IDS
    ctx.write_data("EQUIPMENT/fcm_carrier_good.ini",
                   "[Good]\r\nnickname = fcm_carrier_good\r\nids_name = %d\r\n" % ids)
    ctx.add_data_file("goods", r"equipment\fcm_carrier_good.ini")          # [Data] append
    ctx.patch("DATA/MISSIONS/mbases.ini", "carrier_base", [                 # marker-block edit
        {"op": "add_section", "lines": ["[MBase]", "nickname = fcm_carrier_base_li01"]}])
    ctx.declare_runtime_base("fcm_carrier_base_li01")  # dock solar spawned at runtime
```

`ctx` provides:

| Member | Use |
|---|---|
| `ctx.install` | `fltools.install.Install` (pristine, read-only). `ctx.ini(data_rel)` / `ctx.exe_ini(rel)` return cached `fltools.ini.Document`s; treat them as read-only. |
| `ctx.write_file(root_rel, data)` / `ctx.write_data(data_rel, data)` | Add a **new** file to the overlay (str is encoded latin-1). A path that exists in the install is refused: HDE files are only patched. |
| `ctx.patch(root_rel, block, ops, version=1)` | Register an `fltools.patch` unit (id `<generator>.<block>`). Ops: `append`, `add_section`, `set`, `comment_out` (see `fltools/patch.py`). |
| `ctx.add_data_file(key, data_rel)` | Shortcut: insert `key = data_rel` into `freelancer.ini [Data]` right after the last existing line of that key (`append` op with `after_key`), so load order holds (e.g. new solars still load before `universe`). |
| `ctx.patcher`, `ctx.resdll` | The `fltools.patch` and `fltools.resdll` modules (previews, extra DLLs). |
| `ctx.strings` | Strings registry (`gen/framework/strings.py`): `register(key, text, kind="name"|"infocard", rdl=None, id=None)` returns the global IDS. `data/**/strings*.yaml` are loaded first. |
| `ctx.ids_index` | Our resource DLL's `[Resources]` index (8 on HDE, detected; the build fails loudly otherwise). |
| `ctx.declare_runtime_base(nick)` | Tells the validator a base's dock solar is spawned at runtime. |
| `ctx.log(msg)` | Prefixed log line. |

Every nickname a generator creates starts with `fcm_` (CONVENTIONS §2). Values taken from the
game (positions, prices, loadouts) are read through `ctx` at build time, never committed (§12).

After the generators, the framework builds `EXE/fcm_text.dll` from the strings registry (if any),
appends `DLL = fcm_text.dll` to `[Resources]`, saves the text-id map
(`$FLMOD_LOCAL/gen/text_ids.json`), and exports `world.json` from install + overlay
(`WORLD_JSON.md`).

## Overlay layout

```
<out>/MANIFEST.json   schema fcm.overlay.v1: generators, files {path: sha256,size,generator},
                      patched_files, patches_sha256, resource_dll, ids_index, text_ids,
                      strings_sources, runtime_bases, world_json_sha256
<out>/patches.json    {"version": 1, "units": [...]}
<out>/files/...       new files, install-root relative (EXE/..., DATA/...)
<out>/world.json      not copied into the game by deploy
```

Same install + same repo + same text-id map give byte-identical overlays (tested).

## Strings YAML (provisional until `docs/spec/text_ids.md`)

```yaml
strings:        {carrier.name.fleet: Fleet Carrier}
infocards:      {carrier.info.fleet: "Paragraph one.\n\nParagraph two."}
entries:        {carrier.info.raw: {kind: infocard, rdl: "<RDL>...</RDL>", id: 40}}
```

Ids never move once allocated; retired keys keep their ids reserved; new keys get the next id above
the highest ever used, YAML keys first in sorted order.
