**REVIEW: P0-REPO-b ROUND 1 — VERDICT: PASS**

All four round-3 items are fixed and nothing above MINOR is left. Two new MINORs: a crafted image can stall the checker for minutes, and our own generated `.wav` file names are blocked under the marker. Evidence: `local/testruns/20261018T084340Z-review-P0-REPO-b/`. No commits, no push; my temporary worktree and venv are removed and the main checkout is clean.

```
REVIEW: P0-REPO-b ROUND 1   VERDICT: PASS
R3 FINDINGS:
1 marker form: fixed — A1–A16 and the new B-series give the same result in --staged, --tree and --commits (probesb.txt):
  - Still rejected: one-line JSON (A14), prose mention (A15), YAML string value (A16), the old _check_public key, a // line in .json, a marker inside a block comment at line 7, a ' * ' continuation line.
  - Siblings: a sibling for a file outside the allowed dirs has no effect; an empty or punctuation-only sibling has no reason; a sibling for the directory or with the stem name doesn't match; nothing inside a zip ever counts.
  - Accepted as designed: CRLF files and CRLF siblings work; a JSON file with a sibling passes and is listed.
  - The marker never overrides another rule: R1, R2, R4 (IP and email, including an email inside the sibling file), base64 and gzip are all still rejected.
2 protection under the marker: fixed — real HDE INI converted and committed under data/ with a marker (realisticb.log):
  - YAML with a comment marker: 70.1% rejected (90.7% with the reference index).
  - Compact JSON with a sibling file: 68.4% rejected (81.2% with the index).
  - Hand-picked extracts with no asset paths: 0% rejected (18% without the marker).
  Every escape is printed as "check_public: AUTHORED-DATA <path>". ci.sh puts the count on the public stage line and adds a summary.md section; verified on a temp repo (ci-escape-summary.txt). Judgement: adequate. What remains needs a deliberate marker with a reason, is listed in every CI run, and CONVENTIONS §12 makes the reason a reviewer check.
3 image metadata: fixed — a private IP or email is now caught in each place I tried: tEXt, zTXt, compressed iTXt, an unknown private chunk, after IEND, JPEG COM, EXIF APP1, after EOI (P9–P16). Truncated or broken PNG/JPEG files and a 6 MB zTXt or iCCP are rejected as malformed (P1–P7). All 261 real harness screenshots of 512 KB or less in $FLMOD_TESTRUNS pass when vetted with a .source file. Clean PNG and JPEG metadata passes.
4 dict-literal recall: improved to 94.2% (93.9% pretty-printed), still short of 95%; accepted as optional.

REPRODUCED:
pytest on Python 3.13.15: 243 passed. Fresh 3.11.16 venv built only from requirements-dev.txt: 243 passed.
ci.sh --quick: PASS (161 files).
--tree on the branch: OK, 161 files. --tree on the main checkout (6280be4, read-only): OK, 313 files.
--commits=main..wp/P0-REPO-b: fully clean (1 commit). --commits=main: OK (95 commits).
False positives:
  - main and every sibling tip are clean: HARNESS 6520d4e (367 files), DATATOOLS, SIDECAR, TOOLCHAIN.
  - main..wp/P0-HARNESS fails only at a5bafe5 (old decomp citations, D106 squash item).
  - Text forms are unchanged: .md 98.8%, compact and minified JSON 96.5%, flow-style YAML 95.7%.
  - Minified R3-data extracts: 15/15 rejected with the index.
  - The r2 samples without a marker are still rejected, as designed.
--staged on a 43-file commit: 0.20 s.

FINDINGS:
1. [MINOR] tools/check_public.py bounded_inflate / png_parts — the 5 MB cap is per chunk, not per image. A 410 KB PNG with 80 zTXt chunks, each inflating to just under 5 MB (400 MB in total), took 490 s and 633 MB of memory, then passed (image-parser.txt P8). Adversarial only, but one such image would stall a pre-commit for 8 minutes. Required change: cap the total decompressed metadata per image (e.g. 5 MB) and reject as malformed beyond it.
2. [MINOR] ASSET_REF_RE under the marker — our own generated asset names are treated as game assets. A data/audio YAML for our copilot voice lines with is_2d keys and file: fcm_vo_….wav is rejected with or without the marker (B15/B15b). The message "game asset paths are never our own" is wrong here. Required change: exempt fcm_-prefixed names, or tell W2-REFLEX in CONVENTIONS §12 to leave the extension off.
3. [MINOR, nit] AUTHORED_DATA_LINE_RE — two accidental matches (B11/B12):
   - a "# check_public: authored-data …" line inside a YAML block scalar counts;
   - a Markdown heading with the marker text counts as a comment.
   Both need deliberate text in an allowed directory; no change required.
```
