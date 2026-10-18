# Spew allow-lists (REQ-P0-HARNESS-15)

`spew_allow_<track>_<renderer>.txt` lists the FLSpew `ERROR`/`WARNING` lines that a healthy baseline run of
track A or B produces with that renderer (`dxvk`, `wined3d-sw`; the runner picks the file from the run's track
and renderer). `harness/verdict.py` reports every other `ERROR`/`WARNING` line as a **new spew error**. The files
are our own derived regexes, not game files, so they are committed.

| File | Built from (`$FLMOD_TESTRUNS/…`) | Recipe |
|---|---|---|
| `spew_allow_B_dxvk.txt` | `20261018-070458-lane1-spewbase-B-dxvk-1`, `…-070737-…-2`, `…-071049-…-3` | boot → load `HARNESS_new_story` (devbridge) → launch (console) → 120 s in space → quit |
| `spew_allow_B_wined3d-sw.txt` | `20261018-071330-lane1-spewbase-B-wined3d-sw-1`, `…-071921-lane2-…-2`, `…-072222-lane2-…-3` | same |
| `spew_allow_A_dxvk.txt` | `20261018-065427-lane2-spewbase-A-dxvk-1`, `…-065649-…-2`, `…-065919-lane1-…-3` | boot → main menu → 120 s → close. **No save load:** any `.fl` crashes the A profile at the menu (`harness/NOTES.md` N7); rebuild once P0-TRACK-A fixes that |
| `spew_allow_A_wined3d-sw.txt` | `20261018-070500-lane2-spewbase-A-wined3d-sw-1`, `…-070711-…-2`, `…-070941-…-3` | same as A dxvk |

Cross-check: `spew_allow.py check --allow spew_allow_B_dxvk.txt` on an independent B DXVK run
(`20261018-065426-lane1-spewbase-B-dxvk-1`) reports nothing uncovered.

## File format

- One Python regex per line. It is matched with `re.search` against the **normalized** spew line.
- A line whose first non-blank character is `#` is a comment. Blank lines are ignored.
  There are no inline comments; write a literal leading `#` as `\#`.
- Leading and trailing whitespace on a line is ignored. Use `\s` or `[ ]` if a pattern must end in a space.
- A line that doesn't compile is reported in the verdict reasons and skipped; it doesn't abort the run.
- Keep patterns short and anchored. Hand-written patterns are fine; `build --merge` keeps them.

## Normalization (`harness/lib/spew_allow.py`)

`normalize(line)` strips the line ending, the `[YYYY-MM-DD HH:MM:SS] ` prefix that flplusplus adds, and
trailing whitespace. Lines written before flplusplus loads have no prefix and are unchanged.

A line counts as `ERROR`/`WARNING` when the text after the source location `<path>(<n>) : ` (or the
start of a line without one) begins with `ERROR`, `WARNING`, `FATAL` or `ASSERT`, optionally after `***`,
or when the line contains `*** ERROR` / `*** WARNING` anywhere. `NOTICE` lines are never checked.

`build_allow()` turns each observed line into a pattern:

| Part of the line | Pattern |
|---|---|
| `C:\work\...\File.cpp(123) : ` | `^.*File\.cpp\(\d+\) : ` (path dropped, line number free) |
| no source location | `^` |
| hex pointers: `0x...`, or 8+ hex digits standing alone | `[0-9A-Fa-fx]+` |
| standalone decimal numbers (`5`, `-3`, `1.25`, `1.1.2`) | `\d+`, `-?\d+`, `[\d.]+` |
| digits inside identifiers (`Li01_01_Base`, `dx8`, `MP3`) | kept literally |
| everything else | escaped literally |
| end of the message | `$`; after 120 characters of message the pattern is cut and has no `$` |

Duplicate patterns are dropped, so lines that differ only in pointers, numbers or timestamps collapse
into one.

**Always allowed** (built into `spew_allow.py`, whatever the file says): `StreamingSound: missing MP3 codec\?$`.
This line is benign on this install (R4 §B8).

## How verdict.py picks the allow file and mode

1. `--allow <file>`. If the file is missing, only the built-in patterns are allowed and the verdict says so.
2. Otherwise run.json `spew_allow`, if that file exists.
3. Otherwise `harness/baseline/spew_allow_<track>.txt`, with the track taken from `--track` or run.json `track`
   (legacy name; `run.sh` always passes `--allow spew_allow_<track>_<renderer>.txt`).

The mode is `strict` unless `--spew-check report` is given: the check **fails closed** (review r1 m4), so a
track/renderer without an allow-list (e.g. hardware `wined3d`) FAILs on any ERROR/WARNING line beyond the
built-in patterns. In strict mode, new spew errors make the run FAIL. In report mode they are listed in
`verdict.json` `new_spew_errors` but don't change the verdict.

## Regenerating

For each track, take 3 baseline runs (boot → main menu → load `HARNESS_new_story` → launch → 120 s in
space → quit) and build from their copied-out `FLSpew.txt` files:

```
$FLMOD_VENV/bin/python -I harness/lib/spew_allow.py build --out harness/baseline/spew_allow_B_dxvk.txt \
    $FLMOD_TESTRUNS/<run1>/FLSpew.txt $FLMOD_TESTRUNS/<run2>/FLSpew.txt $FLMOD_TESTRUNS/<run3>/FLSpew.txt
```

- Add `--merge` to keep the patterns (including hand-written ones) already in the file.
- `spew_allow.py check --allow <file> <FLSpew...>` lists the lines a file doesn't cover. It exits 1 if
  there are any.
- Review the diff before committing. A pattern must not contain game text beyond the short
  message it allows.
