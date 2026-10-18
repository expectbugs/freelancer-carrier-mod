"""Tests for tools/check_public.py, the .githooks gates and harness/ci.sh (P0-REPO).

Every fixture is synthetic and created in tmp_path: no game files, no real personal
values. Literals that the checker forbids are assembled at runtime (j(...)) so this
file passes the checker itself. The one test that uses the real local blocklist
writes the literal only into tmp_path, never prints it, and deletes it afterwards.
Corpus tests read $FLMOD_REFS read-only, never copy it, and skip when it is absent.
"""
from __future__ import annotations

import base64
import gzip
import importlib.util
import io
import json
import os
import posixpath
import re
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile
import zipfile
import zlib
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
CHECKER = REPO / "tools" / "check_public.py"
HOOKS = REPO / ".githooks"
CI_SH = REPO / "harness" / "ci.sh"
REFS = Path(os.environ.get("FLMOD_REFS") or "/home/user/freelancer/refs")
REAL_BLOCKLIST_CANDIDATES = [
    Path(os.environ["FLMOD_LOCAL"]) / "public_blocklist.txt" if os.environ.get("FLMOD_LOCAL") else None,
    Path("/home/user/freelancer/carrier-mod/local/public_blocklist.txt"),
]

SYN_LITERAL = "Zq-Synthetic-Personal-Literal-4242"


def j(*parts: str) -> str:
    return "".join(parts)


# Values the checker must reject, assembled so they never appear verbatim here.
BAD_IPS = {
    "rfc1918-10": ".".join(["10", "20", "30", "40"]),
    "rfc1918-192": ".".join(["192", "168", "7", "9"]),
    "rfc1918-172": ".".join(["172", "20", "1", "5"]),
    "cgnat": ".".join(["100", "101", "5", "6"]),
    "leading-zero": ".".join(["192", "168", "050", "010"]),
}
BAD_EMAIL = j("someone", "@", "mailhost", ".io")
SECRET_MARKERS = [
    j("PHONE", "_IP = 1"),
    j("PHONE", "_PORT = 2"),
    j("client(api", "_key=k)"),
    j("ANTHROPIC", "_API", "_KEY=x"),
    j("ANTHROPIC", "_API", "_KEY = x"),
    j("cfg = {'api", "_key': k}"),
    j("api", "_key: str"),
    j("OPENAI_API", "_KEY=y"),
    j("token sk-", "ant-"),
    j("token gh", "p_"),
    j("token gh", "o_"),
    j("token github", "_pat_"),
    j("-----BEGIN RSA PRIV", "ATE KEY-----"),
]
REAL_SHAPE_SECRETS = [
    j("sk-", "ant-", "api03-", "A" * 40),
    j("gh", "p_", "B" * 36),
    j("gh", "s_", "C" * 36),
    j("gh", "u_", "D" * 36),
    j("github", "_pat_", "E" * 82),
    j("-----BEGIN OPENSSH PRIV", "ATE KEY-----"),
]
PERSONAL_TERMS = [j("~/", "aria/x.py"), j("/home/user/", "aria/y.py"), j("aria", "2 db"), j("G2", "CC"), j("rt-", "zomboid")]
DECOMP_MARKERS = [j("Freelancer", "-Decomp"), j("Freelancer", " Decomp: a reimplementation"), j("freelancer", "_decomp"),
                  j("FREELANCER", "DECOMP"), j("This file was reconstructed", " by reverse engineering the binaries")]
UTF_BLOB = b"UTF \x01\x01\x00\x00" + bytes(range(256)) * 8

# Content signatures (synthetic heads) that must be rejected whatever the name.
MAGIC_CASES = {
    "fl-utf": UTF_BLOB,
    "bini": b"BINI\x01\x00\x00\x00" + bytes(64),
    "pe": b"MZ\x90\x00" + bytes(200),
    "wave": b"RIFF\x24\x00\x00\x00WAVEfmt " + bytes(64),
    "ogg": b"OggS\x00\x02" + bytes(64),
    "mp3": b"ID3\x03\x00\x00" + bytes(64),
    "minidump": b"MDMP\x93\xa7\x00\x00" + bytes(64),
    "dds": b"DDS \x7c\x00\x00\x00" + bytes(124),
    "pdb": b"Microsoft C/C++ MSF 7.00\r\n\x1aDS\x00\x00\x00" + bytes(64),
    "lua": b"\x1bLuaQ\x00\x01\x04" + bytes(64),
    "asf": b"\x30\x26\xb2\x75\x8e\x66\xcf\x11\xa6\xd9" + bytes(64),
    "elf": b"\x7fELF\x01\x01\x01" + bytes(64),
    "otf": b"OTTO\x00\x0a\x00\x80" + bytes(64),
    "ttf": b"\x00\x01\x00\x00\x00\x0a\x00\x80\x00\x03\x00\x20OS/2" + bytes(64),
    "bink": b"BIKi\x10\x2a\x00\x00" + bytes(64),
    "bink2": b"KB2j\x10\x2a\x00\x00" + bytes(64),
    "pdb2": b"Microsoft C/C++ program database 2.00\r\n\x1aJG\x00\x00" + bytes(64),
}


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def base_env(tmp_path: Path, blocklist: Path | None = None, index: Path | None = None) -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if not k.startswith(("GIT_", "CI_"))}
    env.update(
        GIT_CONFIG_GLOBAL=os.devnull,
        GIT_CONFIG_NOSYSTEM="1",
        GIT_AUTHOR_NAME="Test",
        GIT_AUTHOR_EMAIL="test@example.com",
        GIT_COMMITTER_NAME="Test",
        GIT_COMMITTER_EMAIL="test@example.com",
    )
    if blocklist is None:
        blocklist = tmp_path / "_blocklist.txt"
        if not blocklist.exists():
            blocklist.write_text("# synthetic test blocklist\n" + SYN_LITERAL + "\n")
    env["FLMOD_PUBLIC_BLOCKLIST"] = str(blocklist)
    env["FLMOD_PUBLIC_INDEX"] = str(index or tmp_path / "_no_index")  # deterministic: no R7 unless given
    return env


def check(tmp_path: Path, *args: str, cwd: Path | None = None, env: dict[str, str] | None = None):
    proc = subprocess.run(
        [sys.executable, "-I", str(CHECKER), *args],
        cwd=cwd, env=env or base_env(tmp_path), capture_output=True, text=True,
    )
    return proc.returncode, proc.stdout + proc.stderr


def tree(tmp_path: Path, files: dict[str, str | bytes], *extra: str, env: dict[str, str] | None = None):
    root = Path(tempfile.mkdtemp(prefix="tree", dir=tmp_path))  # fresh root per call
    write(root, files)
    return check(tmp_path, "--tree", str(root), *extra, env=env)


def write(root: Path, files: dict[str, str | bytes]) -> None:
    for rel, content in files.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(content, bytes):
            p.write_bytes(content)
        else:
            p.write_text(content)


def git(repo: Path, *args: str, env: dict[str, str], check_rc: bool = True) -> subprocess.CompletedProcess:
    proc = subprocess.run(["git", *args], cwd=repo, env=env, capture_output=True, text=True)
    if check_rc and proc.returncode != 0:
        raise AssertionError(f"git {' '.join(args)} failed: {proc.stderr}")
    return proc


def init_repo(tmp_path: Path, name: str = "repo") -> tuple[Path, dict[str, str]]:
    repo = tmp_path / name
    repo.mkdir()
    env = base_env(tmp_path)
    git(repo, "init", "-q", "-b", "main", env=env)
    return repo, env


def install_hooks(repo: Path, env: dict[str, str]) -> None:
    shutil.copytree(HOOKS, repo / ".githooks")
    (repo / "tools").mkdir(exist_ok=True)
    shutil.copy2(CHECKER, repo / "tools" / "check_public.py")
    git(repo, "config", "core.hooksPath", ".githooks", env=env)
    git(repo, "add", ".githooks", "tools", env=env)
    git(repo, "commit", "-q", "-m", "hooks", env=env)


def ini_blocks(n_blocks: int) -> str:
    return "".join("[Ship]\nnickname = x\nhit_pts = 1\n" for _ in range(n_blocks))


def load_module():
    spec = importlib.util.spec_from_file_location("check_public_under_test", CHECKER)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = mod
    saved, sys.dont_write_bytecode = sys.dont_write_bytecode, True  # no tools/__pycache__
    try:
        spec.loader.exec_module(mod)
    finally:
        sys.dont_write_bytecode = saved
    return mod


def authored_catalog_yaml() -> str:
    """A ~200-line authored carrier class / yard catalog shaped like our own future data YAML."""
    looks = [("li", "li_dreadnought", "li_n_grp"), ("br", "br_battleship", "br_n_grp"),
             ("ku", "ku_battleship", "ku_n_grp"), ("rh", "rh_battleship", "rh_n_grp")]
    tiers = [("core", 3000000, 4), ("advanced", 6500000, 6), ("elite", 12000000, 8)]
    out = ["# Carrier classes and yards: our own design values; vanilla content referenced by nickname only.",
           "schema: 1", "carrier_classes:"]
    for prefix, look, faction in looks:
        for tier, price, slots in tiers:
            nick = f"fcm_carrier_{prefix}_balanced_{tier}"
            out += [f"  - nickname: {nick}", f"    name_key: carrier.class.{prefix}_balanced_{tier}",
                    f"    archetype: {nick}_arch", f"    look: {look}", f"    faction: {faction}",
                    f"    tier: {tier}", f"    price: {price}", f"    upgrade_slots: {slots}",
                    f"    hangar_slots: {slots // 2}", f"    hold_capacity: {slots * 1250}",
                    f"    nanobots: {slots * 50}", f"    batteries: {slots * 50}", f"    loadout: {nick}_ld",
                    f"    mounts: {{gun: {slots}, turret: {slots // 2}, missile: 2}}"]
    out.append("yards:")
    for i, (prefix, look, faction) in enumerate(looks):
        out += [f"  - nickname: fcm_yard_{prefix}01", f"    base: {prefix}01_01_base", f"    faction: {faction}",
                f"    pos: [{1000 + i * 250}, 0, {-2000 - i * 125}]", f"    rotate: [0, {i * 30}, 0]",
                f"    sells: [fcm_carrier_{prefix}_balanced_core, fcm_carrier_{prefix}_balanced_advanced]",
                "    rep_required: -0.6"]
    return "\n".join(out) + "\n"


# ---------------------------------------------------------------------------
# CLI basics
# ---------------------------------------------------------------------------


def test_no_mode_is_usage_error(tmp_path):
    rc, out = check(tmp_path)
    assert rc == 2 and "required" in out


def test_explain_lists_every_rule(tmp_path):
    rc, out = check(tmp_path, "--explain")
    assert rc == 0
    for rid in ("R1-ext", "R1-magic", "R1-binary", "R1-embedded", "R1-size", "R1-image", "R1-archive", "R1-symlink",
                "R2-ini-location", "R2-ini-headers", "R3-path", "R3-save-sidecar", "R4-blocklist", "R4-ip",
                "R4-email", "R4-host", "R4-secret", "R4-personal-project", "R4-decomp", "R5-fl-data",
                "R6-identity", "R7-refs-copy"):
        assert rid in out


def test_tree_missing_dir_is_usage_error(tmp_path):
    rc, out = check(tmp_path, "--tree", str(tmp_path / "nope"))
    assert rc == 2


def test_allow_binaries_requires_release(tmp_path):
    rc, out = check(tmp_path, "--tree", str(tmp_path), "--allow-binaries")
    assert rc == 2


def test_repo_itself_is_clean(tmp_path):
    """Acceptance: check_public.py --tree <repo> exits 0 with the real local blocklist and index when present."""
    env = base_env(tmp_path)
    env.pop("FLMOD_PUBLIC_BLOCKLIST")
    env.pop("FLMOD_PUBLIC_INDEX")
    rc, out = check(tmp_path, "--tree", str(REPO), env=env)
    assert rc == 0, out


def test_tree_on_git_ignored_dir_is_an_error_not_ok(tmp_path):
    repo, env = init_repo(tmp_path)
    write(repo, {".gitignore": "/local/\n", "local/research/R1.md": "notes\n", "README.md": "x\n"})
    rc, out = check(tmp_path, "--tree", str(repo / "local" / "research"), env=env)
    assert rc == 2 and "ignored by git" in out


def test_empty_scans(tmp_path):
    repo, env = init_repo(tmp_path)
    write(repo, {"a.md": "x\n"})
    git(repo, "add", ".", env=env)
    git(repo, "commit", "-q", "-m", "a", env=env)
    rc, out = check(tmp_path, "--staged", cwd=repo, env=env)
    assert rc == 0 and "WARNING: no files to check" in out
    empty = tmp_path / "empty"
    empty.mkdir()
    rc, out = check(tmp_path, "--release", str(empty))
    assert rc == 2 and "nothing to scan" in out


def test_staged_from_a_subdirectory_sees_root_files(tmp_path):
    repo, env = init_repo(tmp_path)
    write(repo, {"docs/a.md": "x\n"})
    git(repo, "add", ".", env=env)
    git(repo, "commit", "-q", "-m", "a", env=env)
    write(repo, {"foo.cmp": b"\x00"})
    git(repo, "add", "foo.cmp", env=env)
    rc, out = check(tmp_path, "--staged", cwd=repo / "docs", env=env)
    assert rc == 1 and "FAIL foo.cmp: [R1-ext]" in out


# ---------------------------------------------------------------------------
# R1: extensions, content signatures, binaries, size, images, archives
# ---------------------------------------------------------------------------

FORBIDDEN = (".cmp .3db .mat .txm .utf .ale .vms .thn .sph .sur .wav .mp3 .ogg .bini .fl .exe .dll .lib .pdb .dmp "
             ".mdmp .dfm .fx .fxh .ttf .otf .woff2 .wma .wmv .bik").split()


def test_r1_every_forbidden_extension_rejected(tmp_path):
    files = {f"assets/f{i}{ext}": b"x" for i, ext in enumerate(FORBIDDEN)}
    files["assets/UPPER.CMP"] = b"x"
    rc, out = tree(tmp_path, files)
    assert rc == 1
    for rel in files:
        assert f"FAIL {rel}: [R1-ext]" in out, rel


def test_r1_ordinary_files_pass(tmp_path):
    rc, out = tree(tmp_path, {"src/a.cpp": "int main() { return 0; }\n", "docs/notes.md": "# notes\n",
                              "data/carriers.yaml": "carriers:\n  - id: fcm_x\n", "empty.txt": "",
                              "docs/utf.md": "UTF notes: plain text that starts like a signature\n"})
    assert rc == 0, out


@pytest.mark.parametrize("kind", sorted(MAGIC_CASES))
def test_r1_content_signatures_rejected_whatever_the_name(tmp_path, kind):
    rc, out = tree(tmp_path, {"assets/blob.bin": MAGIC_CASES[kind], "docs/x.cmp.txt": MAGIC_CASES[kind]})
    assert rc == 1
    assert "FAIL assets/blob.bin: [R1-magic]" in out and "FAIL docs/x.cmp.txt: [R1-magic]" in out


def test_r1_text_that_starts_like_a_short_signature_is_text(tmp_path):
    rc, out = tree(tmp_path, {f"docs/{i}.txt": t for i, t in enumerate([
        "Bink videos are not used by the mod.\n", "BIKi and KB2 are Bink headers.\n",
        "MSCF is the cabinet signature.\n", "8BPS starts a Photoshop file.\n", "ID3 tags carry MP3 titles.\n",
        "Microsoft C/C++ MSF 7.00 is the PDB container format.\n", "DDS textures are never committed.\n"])})
    assert rc == 0, out
    rc, out = tree(tmp_path, {"a.bin": b"MSCF\x00\x00\x00\x00" + bytes(64), "docs/b.png": b"8BPS\x00\x01" + bytes(64),
                              "docs/b.png.source": "own work\n"})
    assert rc == 1 and "FAIL a.bin: [R1-archive] cab" in out and "FAIL docs/b.png: [R1-image]" in out and "psd" in out


def test_r1_unknown_binary_and_nul_padded_text_rejected(tmp_path):
    rc, out = tree(tmp_path, {"data/blob.dat": bytes(range(256)) * 4,
                              "notes/ships.txt": ini_blocks(10).encode() + b"\x00"})
    assert rc == 1
    assert "FAIL data/blob.dat: [R1-binary]" in out
    # text rules still apply to a lossy decode of NUL-containing data
    assert "FAIL notes/ships.txt: [R1-binary]" in out and "FAIL notes/ships.txt: [R5-fl-data]" in out


def test_r1_utf16_without_bom_is_text(tmp_path):
    rc, out = tree(tmp_path, {"notes/w.txt": f"host {BAD_IPS['rfc1918-192']}\n".encode("utf-16-le"),
                              "notes/ok.txt": "plain words only\n".encode("utf-16-le")})
    assert rc == 1 and "FAIL notes/w.txt: [R4-ip]" in out and "notes/ok.txt" not in out


def test_r1_base64_payloads_are_decoded(tmp_path):
    hexes = "".join(f"{i:02x}" * 32 + "\n" for i in range(4))  # hex digests are not base64 payloads
    rc, out = tree(tmp_path, {
        "docs/blob.txt": base64.encodebytes(UTF_BLOB).decode(),
        "docs/net.md": "x\n" + base64.b64encode((f"lan {BAD_IPS['rfc1918-10']} " * 16).encode()).decode() + "\n",
        "docs/hashes.txt": hexes,
    })
    assert rc == 1
    assert "FAIL docs/blob.txt: [R1-embedded]" in out and "FL UTF container" in out
    assert "docs/net.md!base64@2: [R4-ip]" in out
    assert "hashes.txt" not in out


def _zip(members: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, data in members.items():
            zf.writestr(name, data)
    return buf.getvalue()


def _tgz(members: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tf:
        for name, data in members.items():
            info = tarfile.TarInfo(name)
            info.size = len(data)
            tf.addfile(info, io.BytesIO(data))
    return buf.getvalue()


def test_r1_archive_members_are_vetted(tmp_path):
    rc, out = tree(tmp_path, {
        "bundle.zip": _zip({"pkg/README.md": b"hi\n", "pkg/data/ship.cmp": b"\x00"}),
        "src.tar.gz": _tgz({"src-1.0/notes.txt": BAD_IPS["rfc1918-10"].encode()}),
    })
    assert rc == 1
    assert "bundle.zip!pkg/data/ship.cmp: [R1-ext]" in out
    assert "src.tar.gz!src-1.0/notes.txt: [R4-ip]" in out


def test_r1_archives_opened_by_signature_whatever_the_name(tmp_path):
    rc, out = tree(tmp_path, {
        "tools/x.jar": _zip({"m/ship.cmp": UTF_BLOB}),
        "assets/x.gz": gzip.compress(UTF_BLOB),
        "assets/payload.bin": gzip.compress(UTF_BLOB),
        "assets/disguised.txt": _zip({"a/b.bin": UTF_BLOB}),
    })
    assert rc == 1
    assert "tools/x.jar!m/ship.cmp: [R1-ext]" in out
    assert "assets/x.gz!x: [R1-magic]" in out
    assert "assets/payload.bin!payload.bin.unpacked: [R1-magic]" in out
    assert "assets/disguised.txt!a/b.bin: [R1-magic]" in out


def test_r1_clean_archive_passes_and_unvettable_rejected(tmp_path):
    rc, out = tree(tmp_path, {"bundle.zip": _zip({"pkg/README.md": b"hi\n", "pkg/harness/config/a.ini": b"[x]\n"})})
    assert rc == 0, out
    rc, out = tree(tmp_path, {"blob.7z": b"7z\xbc\xaf"})
    assert rc == 1 and "[R1-archive]" in out
    rc, out = tree(tmp_path, {"blob.bin": b"7z\xbc\xaf\x27\x1c" + bytes(32)})
    assert rc == 1 and "FAIL blob.bin: [R1-archive] 7z" in out


def test_r1_compression_bomb_is_bounded(tmp_path):
    bomb = gzip.compress(bytes(40 * 1024 * 1024))  # 40 MB of zeros, ~40 KB compressed
    rc, out = tree(tmp_path, {"assets/z.gz": bomb})
    assert rc == 1 and "decompresses to more than 5 MB" in out


def test_r1_file_over_5mb_rejected_in_git_repo(tmp_path):
    repo, env = init_repo(tmp_path)
    (repo / "big.txt").write_bytes(b"x" * (6 * 1024 * 1024))
    (repo / "small.txt").write_bytes(b"y" * (1024 * 1024))
    rc, out = check(tmp_path, "--tree", str(repo), env=env)
    assert rc == 1
    assert "FAIL big.txt: [R1-size]" in out
    assert "small.txt" not in out


def png_chunk(ctype: bytes, payload: bytes) -> bytes:
    return len(payload).to_bytes(4, "big") + ctype + payload + zlib.crc32(ctype + payload).to_bytes(4, "big")


def make_png(idat: bytes = bytes(100), chunks: tuple = (), trailing: bytes = b"") -> bytes:
    """A structurally valid PNG: IHDR, the given ancillary chunks, one IDAT (payload as given), IEND."""
    ihdr = (16).to_bytes(4, "big") * 2 + bytes([8, 2, 0, 0, 0])
    body = png_chunk(b"IHDR", ihdr) + b"".join(png_chunk(t, p) for t, p in chunks) + png_chunk(b"IDAT", idat)
    return b"\x89PNG\r\n\x1a\n" + body + png_chunk(b"IEND", b"") + trailing


def make_jpeg(segments: tuple = (), scan: bytes = bytes(100), trailing: bytes = b"") -> bytes:
    """A structurally valid JPEG: SOI, APP0 JFIF, the given (marker, payload) segments, DQT, SOS + scan, EOI."""
    def seg(marker: int, payload: bytes) -> bytes:
        return bytes([0xFF, marker]) + (len(payload) + 2).to_bytes(2, "big") + payload
    head = seg(0xE0, b"JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00") + b"".join(seg(m, p) for m, p in segments)
    head += seg(0xDB, bytes(65)) + seg(0xDA, b"\x01\x01\x00\x00\x3f\x00")
    return b"\xff\xd8" + head + scan.replace(b"\xff", b"\xff\x00") + b"\xff\xd9" + trailing


def test_r1_image_allowlist(tmp_path):
    png = make_png()
    jpg = make_jpeg()
    files = {
        "docs/ok.png": png, "docs/ok.png.source": "own work (diagram)\n",
        "docs/ok2.jpg": jpg, "docs/ok2.source": "generated by tools/plot.py\n",
    }
    rc, out = tree(tmp_path, files)
    assert rc == 0, out


@pytest.mark.parametrize("files,rule,why", [
    ({"docs/a.png": b"\x89PNG\r\n\x1a\n\x00"}, "R1-image", "missing sibling"),
    ({"docs/a.png": b"\x89PNG\r\n\x1a\n\x00", "docs/a.png.source": "from the game\n"}, "R1-image", "does not say"),
    ({"art/a.png": b"\x89PNG\r\n\x1a\n\x00", "art/a.png.source": "own work\n"}, "R1-image", "only under docs/"),
    ({"docs/a.tga": b"\x00\x00\x02\x00" + bytes(64), "docs/a.tga.source": "own work\n"}, "R1-image", "never allowed"),
    ({"docs/a.dds": b"DDS \x7c\x00\x00\x00" + bytes(64), "docs/a.dds.source": "own work\n"}, "R1-magic", "DDS"),
    ({"docs/big.png": b"\x89PNG\r\n\x1a\n" + b"\x00" * (600 * 1024), "docs/big.png.source": "own work\n"},
     "R1-image", "> 512 KB"),
    ({"art/shot.bin": b"\x89PNG\r\n\x1a\n" + bytes(100)}, "R1-image", "only under docs/"),
    ({"docs/g.png": b"GIF89a" + bytes(64), "docs/g.png.source": "own work\n"}, "R1-image", "'gif'"),
])
def test_r1_image_rejections(tmp_path, files, rule, why):
    rc, out = tree(tmp_path, files)
    assert rc == 1 and f"[{rule}]" in out and why in out, out


# ---------------------------------------------------------------------------
# R2: .ini placement and section headers
# ---------------------------------------------------------------------------


def test_r2_ini_allowed_locations_pass(tmp_path):
    files = {f"{d}a.ini": "[Options]\nkey = 1\n" for d in
             ("harness/config/", "sidecar/config/", "toolchain/", "tests/fixtures-authored/")}
    files["toolchain/twenty.ini"] = "[BaseGood]\nfoo_key = 1\n\n" * 20  # exactly the limit
    rc, out = tree(tmp_path, files)
    assert rc == 0, out


def test_r2_ini_outside_allowed_locations_rejected(tmp_path):
    rc, out = tree(tmp_path, {"data/fcm_goods.ini": "[Options]\n", "harness/x.INI": "[a]\n"})
    assert rc == 1
    assert "FAIL data/fcm_goods.ini: [R2-ini-location]" in out
    assert "FAIL harness/x.INI: [R2-ini-location]" in out


@pytest.mark.parametrize("header", ["[ship]", "[BaseGood]", "[MRoom]", "[Anything Else]"])
def test_r2_ini_with_more_than_20_section_headers_rejected(tmp_path, header):
    rc, out = tree(tmp_path, {"tests/fixtures-authored/x.ini": f"{header}\nfoo_key = 1\n\n" * 21})
    assert rc == 1 and "FAIL tests/fixtures-authored/x.ini: [R2-ini-headers] 21 [Section] header lines" in out


# ---------------------------------------------------------------------------
# R3: path rules
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("rel", ["local/notes.md", "build/x.txt", "out/gen.yaml", "vendor/lib/a.h", "refs/r.txt",
                                 ".venv/lib/x.py", "spikes/track_a/build/log.txt", "Local/x.txt",
                                 "docs/local/research/R6.md"])
def test_r3_forbidden_dirs_rejected(tmp_path, rel):
    rc, out = tree(tmp_path, {rel: "x\n"})
    assert rc == 1 and f"FAIL {rel}: [R3-path]" in out


def test_r3_similar_names_pass(tmp_path):
    rc, out = tree(tmp_path, {"docs/locale.txt": "x\n", "src/output.cpp": "x\n", "tools/build.sh": "x\n",
                              "data/save.json": "{}\n"})
    assert rc == 0, out


def test_r3_save_sidecar_rejected(tmp_path):
    rc, out = tree(tmp_path, {"tests/slot1.carrier.json": "{}\n"})
    assert rc == 1 and "[R3-save-sidecar]" in out


def test_r3_git_tree_lists_only_ls_files(tmp_path):
    """Ignored local/ vendor/ build/ and .claude/worktrees/ are never scanned in a git work tree."""
    repo, env = init_repo(tmp_path)
    write(repo, {
        ".gitignore": "/local/\n/vendor/\n/build/\n",
        "README.md": "ok\n",
        "local/secret.md": SYN_LITERAL + "\n",
        "vendor/x.dll": b"MZ\x00",
        "build/a.pdb": b"\x00",
        ".claude/worktrees/agent/foo.cmp": b"\x00",
    })
    rc, out = check(tmp_path, "--tree", str(repo), env=env)
    assert rc == 0, out
    # Without the ignore file, the same tree is rejected (proves the listing matters).
    (repo / ".gitignore").unlink()
    rc, out = check(tmp_path, "--tree", str(repo), env=env)
    assert rc == 1 and "local/secret.md" in out and "vendor/x.dll" in out
    assert ".claude/worktrees" not in out


def test_r3_claude_dir_outside_worktrees_is_scanned(tmp_path):
    repo, env = init_repo(tmp_path)
    write(repo, {".claude/settings.json": json.dumps({"note": f"host {BAD_IPS['cgnat']}"}) + "\n",
                 ".claude/worktrees/agent-x/foo.cmp": b"\x00"})
    rc, out = check(tmp_path, "--tree", str(repo), env=env)
    assert rc == 1 and "FAIL .claude/settings.json: [R4-ip]" in out and "foo.cmp" not in out


# ---------------------------------------------------------------------------
# R4: blocklist
# ---------------------------------------------------------------------------


def test_r4_blocklist_hit_case_insensitive_and_never_printed(tmp_path):
    rc, out = tree(tmp_path, {"notes.md": "line one\ncontact: " + SYN_LITERAL.upper() + "\n"})
    assert rc == 1 and "FAIL notes.md: [R4-blocklist]" in out and "line 2" in out
    leaked = SYN_LITERAL.lower() in out.lower()
    assert not leaked


def test_r4_blocklist_in_path_and_binary_utf16(tmp_path):
    rc, out = tree(tmp_path, {
        f"docs/{SYN_LITERAL}.md": "x\n",
        "bin.dat": b"\x00\x01" + SYN_LITERAL.encode("utf-16-le") + b"\x00",
    })
    assert rc == 1
    assert "file path contains local blocklist entry #1" in out
    assert "bin.dat: [R4-blocklist] binary content" in out
    leaked = SYN_LITERAL.lower() in out.lower()
    assert not leaked


def test_r4_blocklist_clean_file_passes(tmp_path):
    rc, out = tree(tmp_path, {"notes.md": "nothing personal here\n"})
    assert rc == 0, out


WORD_LIT = "zqhost"


def test_r4_blocklist_word_entries_match_whole_words_only(tmp_path):
    bl = tmp_path / "_word_blocklist.txt"
    bl.write_text("# synthetic\n" + SYN_LITERAL + "\nw:" + WORD_LIT.upper() + "\n")
    env = base_env(tmp_path, blocklist=bl)
    rc, out = tree(tmp_path, {
        "a.md": f"ssh {WORD_LIT} now\n",
        "b.md": f"the mega{WORD_LIT}ia and {WORD_LIT}_backup and {WORD_LIT}2 are fine\n",
        "c.md": f"({WORD_LIT.upper()}).\n",
        f"docs/{WORD_LIT}-notes.md": "x\n",
        f"docs/x{WORD_LIT}x.md": "x\n",
        "d.dat": b"\x00\x01 " + WORD_LIT.encode() + b"\x00",
        "e.dat": b"\x00\x01" + f"[{WORD_LIT}]".encode("utf-16-le") + b"\x00",
        "f.dat": b"\x00\x01" + f"x{WORD_LIT}x".encode("utf-16-le") + b"\x00" + f"y{WORD_LIT}y".encode(),
    }, env=env)
    assert rc == 1
    hits = {ln.split(":")[0][5:] for ln in out.splitlines() if "[R4-blocklist]" in ln}
    assert hits == {"a.md", "c.md", "docs/***-notes.md", "d.dat", "e.dat"}, out
    assert "entry #2" in out
    assert WORD_LIT not in out.lower()


def test_r4_missing_blocklist_and_index_warn_and_keep_generic_rules(tmp_path):
    env = base_env(tmp_path, blocklist=tmp_path / "does-not-exist.txt")
    write(tmp_path / "t", {"a.md": "fine\n"})
    rc, out = check(tmp_path, "--tree", str(tmp_path / "t"), env=env)
    assert rc == 0 and "WARNING: local blocklist not found" in out
    assert "WARNING: reference fingerprint index not found" in out
    write(tmp_path / "t", {"b.md": BAD_IPS["cgnat"] + "\n"})
    rc, out = check(tmp_path, "--tree", str(tmp_path / "t"), env=env)
    assert rc == 1 and "[R4-ip]" in out


def test_r4_real_local_blocklist_line_is_rejected(tmp_path):
    """Acceptance: one literal from local/public_blocklist.txt, written only into tmp_path."""
    real = next((p for p in REAL_BLOCKLIST_CANDIDATES if p and p.is_file()), None)
    if real is None:
        pytest.skip("local/public_blocklist.txt absent (fresh clone or CI runner)")
    literal = next((ln.strip() for ln in real.read_text(errors="replace").splitlines()
                    if ln.strip() and not ln.strip().startswith("#")), None)
    if literal is None:
        pytest.skip("local blocklist has no entries")
    rc, hit, leaked = _scan_with_real_literal(tmp_path, real, literal)
    del literal  # keep the literal out of this frame (pytest --showlocals)
    assert rc == 1
    assert hit
    assert not leaked, "checker output must never contain a blocklist literal"


def _scan_with_real_literal(tmp_path: Path, real: Path, literal: str) -> tuple[int, bool, bool]:
    target = tmp_path / "scan" / "leak.txt"
    target.parent.mkdir()
    try:
        target.write_text("prefix " + literal + " suffix\n")
        rc, out = check(tmp_path, "--tree", str(target.parent), env=base_env(tmp_path, blocklist=real))
        return rc, "[R4-blocklist]" in out, literal.lower() in out.lower()
    finally:
        target.unlink()


# ---------------------------------------------------------------------------
# R4: generic IP / email / host rules
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("kind", sorted(BAD_IPS))
def test_r4_private_ips_rejected(tmp_path, kind):
    rc, out = tree(tmp_path, {"notes.md": f"host at {BAD_IPS[kind]}:80\n"})
    assert rc == 1 and "[R4-ip]" in out
    assert BAD_IPS[kind] not in out  # matched values are never echoed


def test_r4_non_private_and_version_strings_pass(tmp_path):
    text = ("loopback 127.0.0.1, bind 0.0.0.0, public 8.8.8.8\n"
            "Windows SDK 10.0.22621.0, version 10.0.19041.1, five-part 10.1.2.3.4\n"
            "ranges 10.0.0.0/8 172.16.0.0/12 192.168.0.0/16 100.64.0.0/10\n"
            "not private 172.32.1.1 100.128.0.1 192.169.1.1\n")
    rc, out = tree(tmp_path, {"notes.md": text})
    assert rc == 0, out


def test_r4_synthetic_values_allowed_only_where_cited(tmp_path):
    text = "synthetic 10.1.2.3 and 192.168.1.77 and someone@example.net\n"
    rc, out = tree(tmp_path, {"tests/py/test_x.py": text, "docs/plan/x.md": text, "state/x.md": text})
    assert rc == 0, out
    rc, out = tree(tmp_path, {"zz_notes.txt": "synthetic 192.168.1.77\n"})
    assert rc == 1 and "FAIL zz_notes.txt: [R4-ip]" in out


def test_r4_email_rules(tmp_path):
    ok = ("Co-Authored-By: Claude <noreply@anthropic.com>\n"
          "Author: 123+someone@users.noreply.github.com\n"
          "placeholder a.b@example.com, c@example.org, d@mail.example.net\n"
          "not emails: @pytest.fixture, react@18.3.1, user@localhost\n")
    rc, out = tree(tmp_path, {"docs/a.md": ok})
    assert rc == 0, out
    rc, out = tree(tmp_path, {"docs/b.md": f"mail me: {BAD_EMAIL}\n"})
    assert rc == 1 and "FAIL docs/b.md: [R4-email]" in out and BAD_EMAIL not in out


def test_r4_git_ssh_clone_urls_are_not_emails(tmp_path):
    ok = ("git clone git@github.com:someowner/freelancer-carrier-mod.git\n"
          "git remote add gl ssh://git@gitlab.example.com/owner/repo.git\n"
          "pip install git+ssh://git@github.com/owner/pkg.git\n")
    rc, out = tree(tmp_path, {"README.md": ok})
    assert rc == 0, out
    rc, out = tree(tmp_path, {"README.md": j("write to git", "@", "mailhost", ".io today\n")})
    assert rc == 1 and "FAIL README.md: [R4-email]" in out


def _noise_png(extra: bytes = b"") -> bytes:
    """A valid PNG whose pixel data contains short generic patterns (address-, IP- and token-prefix-like)."""
    body = bytes((i * 131 + 7) % 256 for i in range(4000))
    noise = j("q", "@", "xk.zz ").encode() + ".".join(["10", "9", "8", "7"]).encode() + j(" gh", "p_ ").encode()
    return make_png(idat=body[:1500] + noise + extra + body[1500:])


def test_r1_vetted_docs_image_pixels_get_blocklist_secret_shapes_and_r5_only(tmp_path):
    src = "own work (diagram)\n"
    rc, out = tree(tmp_path, {"docs/img/a.png": _noise_png(), "docs/img/a.png.source": src})
    assert rc == 0, out
    rc, out = tree(tmp_path, {"docs/img/b.png": _noise_png(SYN_LITERAL.encode("utf-16-le")),
                              "docs/img/b.png.source": src,
                              "docs/img/c.png": _noise_png(REAL_SHAPE_SECRETS[1].encode()),
                              "docs/img/c.png.source": src,
                              "docs/img/d.png": _noise_png(b"\x00" + npc_yaml_fixture(n=12).encode()),
                              "docs/img/d.png.source": src,
                              "docs/img/e.png": _noise_png()})  # not vetted: no .source
    assert rc == 1
    assert "FAIL docs/img/b.png: [R4-blocklist]" in out
    assert "FAIL docs/img/c.png: [R4-secret]" in out
    assert "FAIL docs/img/d.png: [R5-fl-data]" in out
    assert "FAIL docs/img/e.png: [R1-image]" in out and "FAIL docs/img/e.png: [R4-email]" in out
    assert "a.png" not in out


def test_r1_vetted_docs_image_metadata_gets_every_text_rule(tmp_path):
    src = "own work (diagram)\n"
    ip, host = BAD_IPS["rfc1918-192"], j("zzhost.tail0a1b2", ".ts", ".net")
    itxt = b"Comment\x00\x01\x00en\x00\x00" + zlib.compress(f"render host {host}".encode())
    clean = make_png(chunks=((b"tEXt", b"Software\x00matplotlib version 3.9.2, https://matplotlib.org/"),
                             (b"pHYs", bytes(9))))
    files = {
        "docs/i/clean.png": clean,
        "docs/i/clean.jpg": make_jpeg(((0xFE, b"made with our plot script"),)),
        "docs/i/t.png": make_png(chunks=((b"tEXt", b"Author\x00lan box " + ip.encode()),)),
        "docs/i/z.png": make_png(chunks=((b"zTXt", b"Comment\x00\x00" + zlib.compress(BAD_EMAIL.encode())),)),
        "docs/i/x.png": make_png(chunks=((b"iTXt", itxt),)),
        "docs/i/p.png": make_png(chunks=((b"prVt", npc_yaml_fixture(n=12).encode()),)),
        "docs/i/tail.png": make_png(trailing=f"\nsee {ip}\n".encode()),
        "docs/i/c.jpg": make_jpeg(((0xFE, f"shot on {ip}".encode()),)),
        "docs/i/e.jpg": make_jpeg(((0xE1, b"Exif\x00\x00II*\x00" + BAD_EMAIL.encode()),)),
        "docs/i/bad.png": make_png()[:-20],
    }
    for rel in list(files):
        files[rel + ".source"] = src
    rc, out = tree(tmp_path, files)
    assert rc == 1
    expected = ["docs/i/t.png!tEXt: [R4-ip]", "docs/i/z.png!zTXt: [R4-email]", "docs/i/x.png!iTXt: [R4-host]",
                "docs/i/p.png!prVt: [R5-fl-data]", "docs/i/tail.png!after-IEND: [R4-ip]",
                "docs/i/c.jpg!COM: [R4-ip]", "docs/i/e.jpg!APP1: [R4-email]",
                "docs/i/bad.png: [R1-image] malformed PNG"]
    for exp in expected:
        assert "FAIL " + exp in out, exp
    assert "clean.png" not in out and "clean.jpg" not in out
    assert ip not in out and BAD_EMAIL not in out


def test_r4_ip_and_email_in_file_paths(tmp_path):
    rc, out = tree(tmp_path, {f"docs/notes-{BAD_IPS['rfc1918-192']}.md": "x\n", f"docs/{BAD_EMAIL}.md": "x\n",
                              "docs/example-v10.0.22621.0.md": "x\n", "tests/py/net-192.168.1.77.txt": "x\n"})
    assert rc == 1
    assert "file path contains a private/CGNAT IPv4 address" in out and "file path contains an email address" in out
    assert "example-v10" not in out and "net-192" not in out


def test_r4_tailnet_host_names(tmp_path):
    rc, out = tree(tmp_path, {"notes/ts.txt": j("ssh zzhost.tail0a1b2", ".ts", ".net\n")})
    assert rc == 1 and "[R4-host]" in out
    rc, out = tree(tmp_path, {"notes/ok.txt": "the TS.NET suffix is Tailscale's; posts.network is fine\n"})
    assert rc == 0, out


# ---------------------------------------------------------------------------
# R4: secrets, personal projects, decompilation marker
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("marker", SECRET_MARKERS)
def test_r4_secret_markers_rejected_outside_plan(tmp_path, marker):
    rc, out = tree(tmp_path, {"sidecar/brain.py": f"x = 1\n{marker}\n"})
    assert rc == 1 and "FAIL sidecar/brain.py: [R4-secret]" in out


def test_r4_secret_marker_names_allowed_in_plan_docs(tmp_path):
    body = "Forbidden strings: " + ", ".join(SECRET_MARKERS[:-1]) + "\n"
    rc, out = tree(tmp_path, {"docs/plan/packages/X.md": body, "state/briefs/X.md": body})
    assert rc == 0, out


@pytest.mark.parametrize("secret", REAL_SHAPE_SECRETS)
def test_r4_real_secret_shapes_rejected_even_in_plan(tmp_path, secret):
    rc, out = tree(tmp_path, {"docs/plan/x.md": f"oops {secret}\n"})
    assert rc == 1 and "[R4-secret]" in out


def test_r4_secret_negative(tmp_path):
    rc, out = tree(tmp_path, {"sidecar/brain.py": "env = {k: v for k, v in os.environ.items() if k in ALLOW}\n"
                                                  "# the brain uses the subscription login, no key\n"
                                                  "laughs_count = 3  # contains no token prefix\n"})
    assert rc == 0, out


@pytest.mark.parametrize("term", PERSONAL_TERMS)
def test_r4_personal_projects_rejected_outside_plan(tmp_path, term):
    rc, out = tree(tmp_path, {"sidecar/stt.py": f"# adapted from {term}\n"})
    assert rc == 1 and "[R4-personal-project]" in out


def test_r4_personal_projects_allowed_in_plan_and_ledger(tmp_path):
    body = "Never import " + ", ".join(PERSONAL_TERMS) + "\n"
    rc, out = tree(tmp_path, {"docs/plan/packages/W1.md": body, "state/briefs/W1.md": body,
                              "sidecar/stt.py": "# adapted from the owner's prior voice-assistant code\n"})
    assert rc == 0, out


@pytest.mark.parametrize("marker", DECOMP_MARKERS)
@pytest.mark.parametrize("rel", ["src/game/spawn.cpp", "sidecar/x.py", "spikes/s-x/c.cpp", "gen/plugins/d.py",
                                 "tools/x.py", "harness/x.sh", "tests/host/t.cpp", "data/x.yaml"])
def test_r4_decomp_marker_in_any_code_file(tmp_path, marker, rel):
    rc, out = tree(tmp_path, {rel: f"// {marker}\nint a;\n"})
    assert rc == 1 and f"FAIL {rel}: [R4-decomp]" in out


def test_r4_decomp_marker_may_be_cited_in_docs(tmp_path):
    body = "".join(f"cites {m}\n" for m in DECOMP_MARKERS)
    rc, out = tree(tmp_path, {"docs/spec/x.md": body, "docs/spec/notes.cpp": body, "src/game/NOTES.md": body,
                              "harness/README.txt": body, "tools/fltools/NOTES-hash.md": body,
                              "state/reports/X-r1.md": body, "src/game/readme.rst": body})
    assert rc == 0, out


@pytest.mark.parametrize("rel", ["src/game/spawn.cpp.txt", "src/game/design.md", "harness/fixtures/hash.txt",
                                 "state/briefs/x.py", "tests/notes/x.md", "spikes/s/NOTES.cpp"])
def test_r4_decomp_marker_doc_exemption_is_limited(tmp_path, rel):
    rc, out = tree(tmp_path, {rel: f"// {DECOMP_MARKERS[1]}\nint a;\n"})
    assert rc == 1 and f"FAIL {rel}: [R4-decomp]" in out, out


def test_r4_api_key_names_are_markers_only_in_assignment_form(tmp_path):
    ok = ("def " + j("test_no_api", "_key_in_env") + "():\n"
          "    assert " + j("'api", "_key' not in out") + "\n"
          "    if cfg." + j("api", "_key == ''") + ":\n"
          "        pass\n"
          '    environ = {"' + j("ANTHROPIC_API", "_KEY") + '": "dummy", "HOME": "/h"}\n'
          '    environ.pop("' + j("ANTHROPIC_API", "_KEY") + '", None)\n')
    rc, out = tree(tmp_path, {"sidecar/tests/test_env.py": ok})
    assert rc == 0, out
    for bad in (j("api", "_key = 'x'"), j('{"api', '_key": "x"}'), j("api", "_key: x"), j("API", "_KEY=x"),
                j("export OPENAI_API", "_KEY=x"), j("Client(api", "_key=k)")):
        rc, out = tree(tmp_path, {"sidecar/brain.py": f"x = 1\n{bad}\n"})
        assert rc == 1 and "FAIL sidecar/brain.py: [R4-secret]" in out, bad


# ---------------------------------------------------------------------------
# R5: FL game data in INI, YAML or JSON form
# ---------------------------------------------------------------------------


def test_r5_acceptance_markdown_with_30_ini_lines_rejected(tmp_path):
    text = "# Notes\n\n```ini\n" + ini_blocks(10) + "```\n"
    assert text.count("\n") >= 30
    rc, out = tree(tmp_path, {"docs/design/ships.md": text})
    assert rc == 1 and "FAIL docs/design/ships.md: [R5-fl-data]" in out


NPC_BLOCKS = "".join(
    f"[NPCShipArch]\nnickname = zz_n_x{i}\nloadout = zz_l{i}\nlevel = d1\nship_archetype = zz_a\n"
    f"pilot = zz_p\nstate_graph = FIGHTER\nnpc_class = lawful, d1\n\n" for i in range(40))
LOADOUT_BLOCKS = "".join(
    f"[Loadout]\nnickname = zz_lo{i}\narchetype = zz_a{i}\nequip = zz_gun, HpWeapon01\n"
    f"equip = zz_gun, HpWeapon02\nequip = zz_shield, HpShield01\ncargo = zz_bot, 10\n\n" for i in range(40))
MARKET_BLOCKS = "".join(f"[BaseGood]\nbase = zz{i}_base\n" + "".join(
    f"MarketGood = zz_good{k}, 0, -1, 150, 500, 0, 1\n" for k in range(12)) + "\n" for i in range(10))
YAML_EXTRACT = "".join(
    f"- nickname: zz_ship{i}\n  ids_name: {1000 + i}\n  ids_info: {2000 + i}\n  hit_pts: {3000 + i}\n"
    f"  DA_archetype: ships\\zz\\zz{i}.cmp\n  material_library: ships\\zz\\zz.mat\n" for i in range(40))
JSON_EXTRACT = "[\n" + ",\n".join(
    f'  {{"nickname": "zz_base{i}", "ids_name": {1000 + i}, "pos": [1, 2, 3], "rotate": [0, 0, 0], '
    f'"archetype": "zz_station", "faction": "zz_grp"}}' for i in range(60)) + "\n]\n"
QUOTED_INI = "".join(f"> nickname = zz{i}\n> ids_name = {i}\n> hit_pts = 1\n\n" for i in range(20))
TSV_EXTRACT = "system\tzone\tpop_type\tpath_label\tpos\ttoughness\tdensity\tfaction\n" + "".join(
    f"zz{i:02d}\tzone_{i}\tpatrol\tlane{i}\t1, 0, {i}\t5\t3\tzz_grp\n" for i in range(25))


@pytest.mark.parametrize("rel,text", [
    ("notes/npc.md", NPC_BLOCKS), ("notes/loadouts.md", LOADOUT_BLOCKS), ("notes/market.md", MARKET_BLOCKS),
    ("data/ships.yaml", YAML_EXTRACT), ("data/bases.json", JSON_EXTRACT), ("docs/q.md", QUOTED_INI),
    ("docs/zones.tsv", TSV_EXTRACT),
])
def test_r5_fl_data_rejected_in_any_text_form(tmp_path, rel, text):
    rc, out = tree(tmp_path, {rel: text})
    assert rc == 1 and f"FAIL {rel}: [R5-fl-data]" in out, out


def test_r5_authored_yaml_catalog_passes(tmp_path):
    """Our own data YAML uses nickname/archetype/loadout/faction/pos and game nicknames: it must pass."""
    yaml_text = authored_catalog_yaml()
    assert 190 <= yaml_text.count("\n") <= 260
    rc, out = tree(tmp_path, {"data/carriers/classes.yaml": yaml_text,
                              "docs/design/CARRIERS.md": "# Carriers\n\n```yaml\n" + yaml_text + "```\n"})
    assert rc == 0, out


def test_r5_code_templates_and_configs_pass(tmp_path):
    template = "".join(f"nickname = {{nick{i}}}\nhit_pts = <hp>\narchetype = ${{arch}}\n" for i in range(20))
    code = "".join(f"nickname = row['nickname{i}']\npos = (x, y, z)\nloadout = get(n)\n" for i in range(20))
    dataclass_src = "class Ship:\n" + "".join(f"    {k}: int\n" for k in
                                               ("ids_name", "ids_info", "hit_pts", "mass", "explosion_arch") * 6)
    toml = "".join(f"[section_{i}]\nenabled = true\nlevel = {i}\n\n" for i in range(7))
    rc, out = tree(tmp_path, {"gen/t.py": template, "gen/c.py": code, "tools/fltools/model.py": dataclass_src,
                              "sidecar/config/x.toml": toml})
    assert rc == 0, out


def test_r5_does_not_apply_to_ini_files_governed_by_r2(tmp_path):
    rc, out = tree(tmp_path, {"tests/fixtures-authored/ships.ini": ini_blocks(10)})
    assert rc == 0, out  # 10 headers <= 20 in an allowed location
    rc, out = tree(tmp_path, {"tests/fixtures-authored/ships.md": ini_blocks(10)})
    assert rc == 1 and "[R5-fl-data]" in out and "tests/fixtures-authored/*.ini" in out


# --- R5 marker for our own authored data (D108, D112) --------------------------------------------------

AUTHORED = j("check_public: ", "authored-data")
SIB = ".authored-data"


def world_json_fixture(n_systems: int = 3, per_system: int = 4, indent: int | None = 1) -> str:
    """A synthetic fcm.world.v1 world.json fixture (our own schema, FL-native key names)."""
    doc: dict = {"schema": "fcm.world.v1"}
    doc["systems"] = {f"zz{s:02d}": {"nickname": f"zz{s:02d}", "name": f"Test System {s}", "strid_name": 900 + s,
                                     "ids_info": 950 + s, "navmap_pos": [s, s + 1], "visit": 0}
                      for s in range(n_systems)}
    doc["links"] = [{"from_system": f"zz{s:02d}", "from_object": f"zz{s:02d}_gate", "to_system": f"zz{s + 1:02d}",
                     "to_object": f"zz{s + 1:02d}_gate", "kind": "jumpgate", "archetype": "zz_gate"}
                    for s in range(n_systems - 1)]
    doc["objects"] = {f"zz{s:02d}": [{"nickname": f"zz{s:02d}_obj{o}", "archetype": "zz_station", "type": "STATION",
                                      "pos": [1000.0 * o, 0.0, -500.0 * s], "rotate": [0, 15 * o, 0],
                                      "ids_name": 1000 + 10 * s + o, "ids_info": 2000 + 10 * s + o,
                                      "base": f"zz{s:02d}_{o:02d}_base", "dock_with": f"zz{s:02d}_{o:02d}_base",
                                      "reputation": "zz_grp", "loadout": None}
                                     for o in range(per_system)] for s in range(n_systems)}
    return json.dumps(doc, indent=indent) + "\n"


def npc_yaml_fixture(header: str | None = None, n: int = 12) -> str:
    """Synthetic NPC definitions with the field names W1-DATA uses (ship_archetype, state_graph, npc_class)."""
    out = [f"# {header}"] if header is not None else []
    out += ["# Ambusher NPC definitions (synthetic test data).", "npcs:"]
    for i in range(n):
        out += [f"  - nickname: fcm_zz_ambusher_{i:02d}", f"    ship_archetype: zz_ship_{i % 3}",
                f"    loadout: zz_loadout_{i % 4}", "    level: d10", "    pilot: zz_pilot_hard",
                "    state_graph: FIGHTER", f"    npc_class: [unlawful, d{8 + i % 4}]"]
    return "\n".join(out) + "\n"


def npc_lines(n: int = 12) -> str:
    return npc_yaml_fixture(n=n).split("\n", 1)[1]  # without the leading descriptive comment


ALLOWED_AUTHORED = ["tests/fixtures/world/world_mini.json", "data/world/world.json", "gen/framework/world.json",
                    "harness/fixtures/world.json", "docs/spec/world_example.json", "src/game/tests/world.json"]


@pytest.mark.parametrize("rel", ALLOWED_AUTHORED)
def test_r5_authored_data_sibling_file_accepts_world_json_in_allowed_dirs(tmp_path, rel):
    plain = world_json_fixture()
    assert sum(len(v) for v in json.loads(plain)["objects"].values()) >= 12
    rc, out = tree(tmp_path, {rel: plain})
    assert rc == 1 and f"FAIL {rel}: [R5-fl-data]" in out, out
    assert "only for our own values" in out and "<file>.authored-data" in out  # the message names the marker
    rc, out = tree(tmp_path, {rel: plain, rel + SIB: "synthetic fcm.world.v1 test fixture, our own values\n"})
    assert rc == 0, out
    assert f"WARNING: {rel}: [R5-fl-data]" in out
    assert f"check_public: AUTHORED-DATA {rel} (sibling {posixpath.basename(rel)}{SIB})" in out


@pytest.mark.parametrize("rel", ["data/npcs/ambushers.yaml", "tests/fixtures/npcs.yaml", "harness/fixtures/n.yaml",
                                 "gen/npcs/ambushers.yaml", "src/game/npc/tests/defs.yaml"])
def test_r5_authored_data_comment_line_accepts_npc_yaml_in_allowed_dirs(tmp_path, rel):
    rc, out = tree(tmp_path, {rel: npc_yaml_fixture(n=10)})
    assert rc == 1 and f"FAIL {rel}: [R5-fl-data]" in out, out
    rc, out = tree(tmp_path, {rel: npc_yaml_fixture(header=AUTHORED + " our NPC schema uses FL field names", n=10)})
    assert rc == 0 and f"WARNING: {rel}: [R5-fl-data]" in out, out
    assert f"check_public: AUTHORED-DATA {rel} (comment line 1)" in out


@pytest.mark.parametrize("line", [f"# {AUTHORED} ours", f"## {AUTHORED} ours", f"// {AUTHORED} ours",
                                  f"; {AUTHORED} ours", f"-- {AUTHORED} ours", f"<!-- {AUTHORED} ours -->",
                                  f"/* {AUTHORED} ours */", f"   # {AUTHORED} ours"])
def test_r5_authored_data_every_comment_form_counts(tmp_path, line):
    rc, out = tree(tmp_path, {"data/x.txt": "\n" + line + "\n" + npc_lines()})
    assert rc == 0 and "check_public: AUTHORED-DATA data/x.txt (comment line 2)" in out, out


@pytest.mark.parametrize("name,text", [
    # A14: buried inside a one-line JSON document (also: the dropped "_check_public" key form)
    ("data/a14.json", json.dumps({"_check_public": "x", "notes": AUTHORED + " ours", **json.loads(world_json_fixture())})),
    ("data/a14b.json", '{"_check_public": "' + AUTHORED + ' ours",\n' + world_json_fixture()[1:]),
    # .json takes only the sibling form, even with a comment line
    ("data/a14c.json", "// " + AUTHORED + " ours\n" + world_json_fixture()),
    # A15: a prose mention in docs/spec
    ("docs/spec/a15.md", "# Data\n\nOur files carry " + AUTHORED + " <reason> as a comment.\n\n" + npc_lines()),
    # A16: inside a YAML string value, not a comment
    ("data/a16.yaml", 'note: "# ' + AUTHORED + ' ours"\n' + npc_lines()),
    ("data/a16b.yaml", "title: " + AUTHORED + " ours\n" + npc_lines()),
])
def test_r5_authored_data_mentions_and_buried_markers_do_not_count(tmp_path, name, text):
    rc, out = tree(tmp_path, {name: text})
    assert rc == 1 and f"FAIL {name}: [R5-fl-data]" in out and "AUTHORED-DATA" not in out, out


@pytest.mark.parametrize("rel", ["docs/design/npcs.yaml", "sidecar/npcs.yaml", "src/game/npcs.yaml",
                                 "tools/fltools/npcs.yaml", "docs/plan/x.yaml", "spikes/s/n.yaml"])
def test_r5_authored_data_marker_outside_allowed_dirs_has_no_effect(tmp_path, rel):
    rc, out = tree(tmp_path, {rel: npc_yaml_fixture(header=AUTHORED + " our own schema", n=12)})
    assert rc == 1 and f"FAIL {rel}: [R5-fl-data]" in out and "has no effect here" in out, out
    rc, out = tree(tmp_path, {rel: npc_lines(), rel + SIB: "our own schema\n"})
    assert rc == 1 and f"FAIL {rel}: [R5-fl-data]" in out and "has no effect here" in out, out


def test_r5_authored_data_marker_needs_a_reason_within_the_first_5_lines(tmp_path):
    rc, out = tree(tmp_path, {"data/a.yaml": npc_yaml_fixture(header=AUTHORED, n=12),
                              "data/b.yaml": npc_yaml_fixture(header=AUTHORED + " :-- ", n=12),
                              "data/c.yaml": "#\n#\n#\n#\n#\n" + npc_yaml_fixture(header=AUTHORED + " late", n=12),
                              "data/d.json": world_json_fixture(), "data/d.json" + SIB: "\n  -- \n"})
    assert rc == 1
    for name in ("a.yaml", "b.yaml", "c.yaml", "d.json"):
        assert f"FAIL data/{name}: [R5-fl-data]" in out, name
    assert out.count("has no reason") == 3


def test_r5_authored_data_marker_keeps_asset_paths_as_violations(tmp_path):
    hdr = "# " + AUTHORED + " our own values\n"
    recs = json.loads(world_json_fixture())
    recs["objects"]["zz00"][0]["mesh"] = j("solar\\dockable\\zz_station", ".cmp")
    rc, out = tree(tmp_path, {
        "data/a.yaml": hdr + npc_lines() + "    mesh: " + j("ships\\liberty\\li_elite\\li_elite", ".cmp") + "\n",
        "data/b.yaml": hdr + npc_lines() + "    sound: " + j("zz_engine", ".wav") + "\n",
        "data/c.yaml": hdr + npc_lines() + "    icon: equipment\\models\\zz\n",
        "data/d.json": json.dumps(recs), "data/d.json" + SIB: "our own world fixture\n",
        "data/ok.yaml": hdr + "# meshes come from the vanilla zz_station" + j(".cmp", " at deploy time\n") + npc_lines(),
    })
    assert rc == 1, out
    for name in ("a.yaml", "b.yaml", "c.yaml", "d.json"):
        assert f"FAIL data/{name}: [R5-fl-data] authored-data marker" in out and "only for our own values" in out
    assert "FAIL data/ok.yaml" not in out and "AUTHORED-DATA data/ok.yaml" in out


def test_r5_authored_data_marker_never_rescues_r1_r2_r4_or_r7(tmp_path, synthetic_index):
    hdr = "# " + AUTHORED + " synthetic fixture\n"
    env = base_env(tmp_path, index=synthetic_index)
    rc, out = tree(tmp_path, {
        "data/copy.cpp": "// " + AUTHORED + " not really\n" + _ref_source("somemod"),       # R7
        "data/nul.yaml": (hdr + npc_yaml_fixture(n=12)).encode() + b"\x00",               # R1-binary
        "data/emb.yaml": hdr + base64.encodebytes(UTF_BLOB).decode(),                     # R1-embedded
        "data/b64.yaml": hdr + base64.encodebytes(npc_yaml_fixture(n=12).encode()).decode(),  # R5 in base64
        "tests/fixtures-authored/x.ini": "; " + AUTHORED + " fixture\n" + "[Ship]\nfoo_key = 1\n\n" * 21,  # R2
        "data/ip.yaml": hdr + f"host: {BAD_IPS['rfc1918-10']}\n" + npc_yaml_fixture(n=12),  # R4
        "data/arc.zip": _zip({"data/n.yaml": (hdr + npc_lines()).encode(), "README.md": b"x\n"}),  # archived
    }, env=env)
    assert rc == 1
    assert "FAIL data/copy.cpp: [R7-refs-copy]" in out
    assert "FAIL data/nul.yaml: [R1-binary]" in out and "FAIL data/nul.yaml: [R5-fl-data]" in out
    assert "FAIL data/emb.yaml: [R1-embedded]" in out
    assert "data/b64.yaml!base64@2: [R5-fl-data]" in out
    assert "FAIL tests/fixtures-authored/x.ini: [R2-ini-headers]" in out
    assert "FAIL data/ip.yaml: [R4-ip]" in out and "FAIL data/ip.yaml: [R5-fl-data]" not in out
    assert "FAIL data/arc.zip!data/n.yaml: [R5-fl-data]" in out


# --- R5 tables -------------------------------------------------------------------------------------------


def _rows(n: int, cols: int, sep: str) -> str:
    return "".join(sep.join(f"v{r}_{c}" for c in range(cols)) + "\n" for r in range(n))


def test_r5_table_counts_only_distinctive_columns(tmp_path):
    generic = "system\tfaction\tlevel\tambush_weight\tcooldown_s\n" + _rows(26, 5, "\t")
    rc, out = tree(tmp_path, {"data/tuning/ambush.tsv": generic,
                              "data/tuning/ambush.csv": generic.replace("\t", ","),
                              "docs/design/ambush.md": "| system | faction | level | weight |\n|---|---|---|---|\n"
                                                       + _rows(26, 4, " | ")})
    assert rc == 0, out


def test_r5_table_header_after_comments_and_markdown_and_html_tables(tmp_path):
    cols = ["zone", "pop_type", "path_label", "toughness", "repop_time", "faction"]
    csv_text = "# zone extract\n# columns below\n\n" + ",".join(cols) + "\n" + _rows(25, len(cols), ",")
    md = ("# Zones\n\nSome prose first.\n\n| " + " | ".join(cols) + " |\n|" + "---|" * len(cols) + "\n"
          + "".join("| " + " | ".join(f"v{r}{c}" for c in range(len(cols))) + " |\n" for r in range(25)))
    th = "<table><tr>" + "".join(f"<th>{c}</th>" for c in cols) + "</tr>" + "".join(
        "<tr>" + "".join(f"<td>v{r}{c}</td>" for c in range(len(cols))) + "</tr>" for r in range(25)) + "</table>"
    td = th.replace("<th>", "<td>").replace("</th>", "</td>")
    rc, out = tree(tmp_path, {"docs/z.csv": csv_text, "docs/z.md": md, "docs/z.html": "<html>" + th + "</html>\n",
                              "docs/z2.md": "<p>x</p>\n" + td + "\n"})
    assert rc == 1, out
    for rel in ("docs/z.csv", "docs/z.md", "docs/z.html", "docs/z2.md"):
        assert f"FAIL {rel}: [R5-fl-data] looks like FL game data: a table" in out, rel


# --- R5 compact JSON, flow YAML, dict literals, long lines ------------------------------------------------


def _fl_records(n: int) -> list[dict]:
    return [{"nickname": f"zz_ship{i}", "ids_name": 1000 + i, "ids_info": 2000 + i, "hit_pts": 3000 + i,
             "mass": 100 + i, "explosion_arch": f"zz_explosion{i}"} for i in range(n)]


def test_r5_compact_json_flow_yaml_dict_literals_and_long_lines_rejected(tmp_path):
    import pprint
    recs = _fl_records(60)
    compact = json.dumps(recs)
    assert len(compact) > 4000 and "\n" not in compact
    flow = "".join("- {" + ", ".join(f"{k}: {v}" for k, v in r.items()) + "}\n" for r in recs[:40])
    padded = "".join(f"nickname = zz{i}{' ' * 4100}; pad\nids_name = {i}{' ' * 4100}\nhit_pts = 1\n\n"
                     for i in range(25))
    files = {
        "data/a.json": compact + "\n",
        "data/b.json": json.dumps(recs, separators=(",", ":")) + "\n",
        "data/c.yaml": flow,
        "tools/d.py": "DATA = " + pprint.pformat(recs[:30], width=100) + "\n",
        "tools/e.py": "DATA = " + repr(recs[:30]) + "\n",
        "docs/f.txt": repr(recs) + "\n",
        "docs/g.md": padded,
        # repeated vector-valued keys (map = x, y) become one list per section in compact JSON
        "docs/h.json": json.dumps([{"section": "ZzMap", "zz_map": [f"{i}, {i + 1}" for i in range(45)]}]) + "\n",
        # the same as a pretty-printed Python literal: string-encoded vectors, one per line
        "tools/i.py": "DATA = " + pprint.pformat([{"section": "ZzMap", "zz_map": [f"{i}, {i + 1}" for i in range(45)]}],
                                                 width=60) + "\n",
    }
    rc, out = tree(tmp_path, files)
    assert rc == 1
    for rel in files:
        assert f"FAIL {rel}: [R5-fl-data]" in out, rel


def test_r5_own_code_with_fl_names_passes(tmp_path):
    ops = "".join(f'    U("u{i}", [{{"op": "append", "section": "BaseGood", "after_key": "marketgood", '
                  f'"nth": {i}}}]),\n' for i in range(40))
    sig = "".join(f"def f{i}(self, hit_pts: int, mass: float = 1.0, ids_name: int | None = None): ...\n"
                  for i in range(30))
    tmpl = "".join(f'    rows.append({{"ids_name": ids[{i}], "hit_pts": row["hp"], "mass": m * {i}}})\n'
                   for i in range(30))
    rows = "".join(f"    [{i}.0, 0.0, {-i}.5],\n" for i in range(60))  # numeric array rows: ordinary in code
    enums = "".join(f'    "zz{i}": {{"ship_class": ["fighter", "freighter"], "hit_pts": [100, 200]}},\n' for i in range(5))
    rc, out = tree(tmp_path, {"tests/py/test_patch_ops.py": "UNITS = [\n" + ops + "]\n", "tools/fltools/api.py": sig,
                              "gen/emit.py": "def emit(rows):\n" + tmpl,
                              "tests/py/test_geometry.py": "VECS = [\n" + rows + "]\nCLASSES = {\n" + enums + "}\n"})
    assert rc == 0, out


KV = re.compile(r"^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*?)\s*$")
SEC = re.compile(r"^\s*\[([^\]]+)\]\s*$")


def _ini_to_yaml(text: str) -> str:
    out = []
    for line in text.splitlines():
        m = SEC.match(line)
        if m:
            out.append(f"- section: {m.group(1)}")
            continue
        m = KV.match(line)
        if m:
            out.append(f"  {m.group(1)}: {m.group(2)}")
        elif not line.strip():
            out.append("")
    return "\n".join(out) + "\n"


def _ini_to_json(text: str) -> str:
    secs: list[dict] = []
    cur: dict | None = None
    for line in text.splitlines():
        m = SEC.match(line)
        if m:
            cur = {"section": m.group(1)}
            secs.append(cur)
            continue
        m = KV.match(line)
        if m:
            if cur is None:
                cur = {}
                secs.append(cur)
            k, v = m.group(1), m.group(2)
            if k in cur:
                cur[k] = (cur[k] if isinstance(cur[k], list) else [cur[k]]) + [v]
            else:
                cur[k] = v
    return json.dumps(secs, indent=2) + "\n"


def _ini_sections(text: str) -> list[dict]:
    return json.loads(_ini_to_json(text))


def _ini_to_flow_yaml(text: str) -> str:
    def val(v: str) -> str:
        return json.dumps(v) if re.search(r"[,:{}\[\]#'\"]", v) or not v else v
    out = []
    for sec in _ini_sections(text):
        pairs = [(k, x) for k, v in sec.items() for x in (v if isinstance(v, list) else [v])]
        out.append("- {" + ", ".join(f"{k}: {val(x)}" for k, x in pairs) + "}")
    return "\n".join(out) + "\n"


CORPUS_FORMS = {
    "md": (".md", lambda t: "```ini\n" + t + "\n```\n"),
    "txt": (".txt", lambda t: t),
    "yaml-block": (".yaml", _ini_to_yaml),
    "yaml-flow": (".yaml", _ini_to_flow_yaml),
    "json-indented": (".json", _ini_to_json),
    "json-compact": (".json", lambda t: json.dumps(_ini_sections(t)) + "\n"),
    "json-minified": (".json", lambda t: json.dumps(_ini_sections(t), separators=(",", ":")) + "\n"),
    "repr-dump": (".txt", lambda t: repr(_ini_sections(t)) + "\n"),
}


def test_r5_corpus_hde_ini_rejected_in_every_text_form():
    """>= 95% of real HDE INI files with >= 50 key lines are rejected as Markdown, text, block and flow YAML,
    indented, compact and minified JSON, and a Python repr dump (read-only; nothing is written)."""
    hde = REFS / "freelancer-hd-edition"
    if not hde.is_dir():
        pytest.skip("$FLMOD_REFS/freelancer-hd-edition absent")
    mod = load_module()
    total = 0
    caught = dict.fromkeys(CORPUS_FORMS, 0)
    for p in sorted(hde.rglob("*")):
        if p.suffix.lower() != ".ini" or not p.is_file() or p.stat().st_size > mod.MAX_FILE_BYTES:
            continue
        text = mod.decode_text(p.read_bytes())
        if text is None or sum(1 for ln in text.splitlines() if KV.match(ln)) < 50:
            continue
        total += 1
        for form, (ext, conv) in CORPUS_FORMS.items():
            if mod.fl_data_verdict("docs/notes/x" + ext, conv(text)):
                caught[form] += 1
    assert total >= 300
    for form, n in caught.items():
        assert n / total >= 0.95, f"{form}: {n}/{total}"


def test_r5_r7_corpus_minified_r3data_extracts_rejected(tmp_path):
    """Every R3-data JSON extract, minified to one line, is rejected by R5 or by R7 against an index of the
    extracts (built in tmp_path; the copies stay in memory)."""
    research = Path(os.environ.get("FLMOD_RESEARCH") or "/home/user/freelancer/carrier-mod/local/research")
    r3 = research / "R3-data"
    if not r3.is_dir():
        pytest.skip("$FLMOD_RESEARCH/R3-data absent")
    mod = load_module()
    (tmp_path / "norefs").mkdir()
    mod.build_index(str(tmp_path / "idx"), [str(tmp_path / "norefs")], [str(r3)], lambda s: None)
    index = mod.RefIndex(str(tmp_path / "idx"))
    names = sorted(p.name for p in r3.glob("*.json"))
    assert len(names) >= 10
    missed = []
    for name in names:
        data = (json.dumps(json.loads((r3 / name).read_text()), separators=(",", ":")) + "\n").encode()
        sc = mod.Scanner([], index=index)
        sc.scan_entries([mod.Entry("docs/notes/" + name, len(data), lambda d=data: d)], mod.Listing([]))
        if not any(v.rule in ("R5-fl-data", "R7-refs-copy") for v in sc.violations):
            missed.append(name)
    assert not missed, missed


def test_r4_corpus_decomp_files_rejected_in_src():
    """Every decomp file carrying its header is rejected as src/ code, without the index (read-only)."""
    dec = REFS / j("Freelancer", "-Decomp")
    if not dec.is_dir():
        pytest.skip("decomp reference absent")
    mod = load_module()
    total = flagged = 0
    for p in sorted(dec.rglob("*")):
        if p.suffix.lower() not in (".c", ".cpp", ".h", ".hpp", ".inl") or not p.is_file() or ".git" in p.parts:
            continue
        total += 1
        sc = mod.Scanner([])
        sc.scan_entries([mod.Entry("src/game/" + p.name, p.stat().st_size, p.read_bytes)], mod.Listing([]))
        flagged += any(v.rule == "R4-decomp" for v in sc.violations)
    assert total >= 1000 and flagged / total >= 0.90, f"{flagged}/{total}"


# ---------------------------------------------------------------------------
# R7: reference fingerprint index (synthetic refs in tmp_path)
# ---------------------------------------------------------------------------


def _ref_source(tag: str, n: int = 80) -> str:
    return "".join(f"int {tag}_compute_value_{i}(int a) {{ return a * {i} + {i * 7}; }}\n" for i in range(n))


@pytest.fixture()
def synthetic_index(tmp_path):
    refs = tmp_path / "refs"
    write(refs, {"SomeMod/src/mod.cpp": _ref_source("somemod"),
                 "freelancer-hd-edition/DATA/x.txt": _ref_source("hdedata"),
                 "SomeMod/vendor/lib/skip.cpp": _ref_source("vendored"),
                 "SomeMod/LICENSE.txt": _ref_source("licensetext"),
                 "wine-11.0/dlls/x.c": _ref_source("winesrc")})
    (tmp_path / "noresearch").mkdir()
    idx = tmp_path / "idx"
    rc, out = check(tmp_path, "--build-index", "--refs", str(refs), "--research", str(tmp_path / "noresearch"),
                    "--index", str(idx))
    assert rc == 0 and "index built" in out and "2 reference files" in out, out
    return idx


def test_r7_copy_of_reference_file_rejected(tmp_path, synthetic_index):
    env = base_env(tmp_path, index=synthetic_index)
    own = "".join(f"double own_helper_{i}(double x) {{ return x / {i + 1}.0; }}\n" for i in range(200))
    rc, out = tree(tmp_path, {"src/game/x.cpp": "// mine\n" + _ref_source("somemod"),
                              "src/game/own.cpp": own + _ref_source("somemod", 6),  # small overlap: allowed
                              "src/game/v.cpp": _ref_source("vendored"),          # vendored trees not indexed
                              "src/game/w.cpp": _ref_source("winesrc")}, env=env)
    assert rc == 1
    assert "FAIL src/game/x.cpp: [R7-refs-copy]" in out and "SomeMod/src/mod.cpp" in out and "derived-from" in out
    assert "own.cpp" not in out and "v.cpp" not in out and "w.cpp" not in out


def test_r7_derived_from_header_is_a_warning(tmp_path, synthetic_index):
    env = base_env(tmp_path, index=synthetic_index)
    rc, out = tree(tmp_path, {"src/game/x.cpp": "// check_public: derived-from SomeMod MIT\n" + _ref_source("somemod")},
                   env=env)
    assert rc == 0 and "WARNING: src/game/x.cpp: [R7-refs-copy]" in out and "derived-from SomeMod MIT" in out
    rc, out = tree(tmp_path, {"src/game/y.cpp": "// check_public: derived-from OtherMod MIT\n" + _ref_source("somemod")},
                   env=env)
    assert rc == 1 and "[R7-refs-copy]" in out  # header names a different repo


def test_r7_game_data_and_decomp_are_not_escapable(tmp_path, synthetic_index):
    env = base_env(tmp_path, index=synthetic_index)
    rc, out = tree(tmp_path, {"docs/x.md": "check_public: derived-from freelancer-hd-edition MIT\n"
                                           + _ref_source("hdedata")}, env=env)
    assert rc == 1 and "FAIL docs/x.md: [R7-refs-copy]" in out


def test_r7_explicit_missing_index_is_an_error(tmp_path):
    rc, out = check(tmp_path, "--tree", str(tmp_path), "--index", str(tmp_path / "nope"))
    assert rc == 2 and "index not found" in out


# ---------------------------------------------------------------------------
# --release
# ---------------------------------------------------------------------------


def test_release_dll_needs_allow_binaries(tmp_path):
    rel = tmp_path / "release"
    write(rel, {"carrier_endgame.dll": b"MZ\x90\x00" + b"\x00" * 64, "README.md": "build notes\n"})
    rc, out = check(tmp_path, "--release", str(rel))
    assert rc == 1 and "carrier_endgame.dll: [R1-ext]" in out and "--allow-binaries" in out
    rc, out = check(tmp_path, "--release", str(rel), "--allow-binaries")
    assert rc == 0, out


def test_release_allow_binaries_is_dll_only_and_still_vets_content(tmp_path):
    rel = tmp_path / "release"
    write(rel, {"tool.exe": b"MZ\x00", "x.pdb": b"\x00", "renamed.bin": b"MZ\x90\x00" + bytes(64),
                "mod.dll": b"MZ\x00" + SYN_LITERAL.encode("utf-16-le")})
    rc, out = check(tmp_path, "--release", str(rel), "--allow-binaries")
    assert rc == 1
    assert "tool.exe: [R1-ext]" in out and "x.pdb: [R1-ext]" in out and "renamed.bin: [R1-magic]" in out
    assert "mod.dll: [R4-blocklist]" in out


def test_release_rejects_symlinks(tmp_path):
    rel = tmp_path / "release"
    write(rel, {"README.md": "x\n"})
    target = tmp_path / "elsewhere.dll"
    target.write_bytes(b"MZ\x90\x00" + bytes(64))
    (rel / "carrier.dll").symlink_to(target)
    rc, out = check(tmp_path, "--release", str(rel))
    assert rc == 1 and "FAIL carrier.dll: [R1-symlink]" in out


def test_release_source_archive_vetted(tmp_path):
    rel = tmp_path / "release"
    write(rel, {"src.zip": _zip({"freelancer-carrier-mod-1.0/README.md": b"ok\n",
                                 "freelancer-carrier-mod-1.0/harness/config/lane.ini": b"[lane]\nn = 1\n"})})
    rc, out = check(tmp_path, "--release", str(rel))
    assert rc == 0, out
    write(rel, {"bad.zip": _zip({"mod/DATA/SHIPS/shiparch.ini": b"[Ship]\n"})})
    rc, out = check(tmp_path, "--release", str(rel))
    assert rc == 1 and "bad.zip!mod/DATA/SHIPS/shiparch.ini: [R2-ini-location]" in out


# ---------------------------------------------------------------------------
# --staged and --commits
# ---------------------------------------------------------------------------


def test_staged_reads_index_content_not_worktree(tmp_path):
    repo, env = init_repo(tmp_path)
    (repo / "a.md").write_text("clean\n")
    git(repo, "add", "a.md", env=env)
    git(repo, "commit", "-q", "-m", "init", env=env)
    rc, out = check(tmp_path, "--staged", cwd=repo, env=env)
    assert rc == 0, out  # nothing staged
    (repo / "a.md").write_text(f"ip {BAD_IPS['rfc1918-172']}\n")
    git(repo, "add", "a.md", env=env)
    (repo / "a.md").write_text("clean again in the work tree only\n")
    rc, out = check(tmp_path, "--staged", cwd=repo, env=env)
    assert rc == 1 and "FAIL a.md: [R4-ip]" in out
    git(repo, "add", "a.md", env=env)
    rc, out = check(tmp_path, "--staged", cwd=repo, env=env)
    assert rc == 0, out


def test_staged_initial_commit_and_forbidden_file(tmp_path):
    repo, env = init_repo(tmp_path)
    (repo / "foo.cmp").write_bytes(b"\x00")
    git(repo, "add", "foo.cmp", env=env)
    rc, out = check(tmp_path, "--staged", cwd=repo, env=env)
    assert rc == 1 and "FAIL foo.cmp: [R1-ext]" in out


def test_commits_catches_file_deleted_later_and_bad_identity(tmp_path):
    repo, env = init_repo(tmp_path)
    (repo / "a.md").write_text("ok\n")
    git(repo, "add", ".", env=env)
    git(repo, "commit", "-q", "-m", "one", env=env)
    rc, out = check(tmp_path, "--commits", "HEAD", cwd=repo, env=env)
    assert rc == 0, out
    (repo / "local").mkdir()
    (repo / "local" / "notes.md").write_text("research\n")
    git(repo, "add", ".", env=env)
    git(repo, "commit", "-q", "-m", "oops", env=env)
    git(repo, "rm", "-q", "-r", "local", env=env)
    git(repo, "commit", "-q", "-m", "remove", env=env)
    assert not (repo / "local").exists()
    rc, out = check(tmp_path, "--tree", str(repo), env=env)
    assert rc == 0, out  # the tree is clean...
    rc, out = check(tmp_path, "--commits", "HEAD", cwd=repo, env=env)
    assert rc == 1 and ":local/notes.md: [R3-path]" in out  # ...but history is not
    bad = dict(env, GIT_AUTHOR_EMAIL=BAD_EMAIL)
    (repo / "b.md").write_text("ok\n")
    git(repo, "add", ".", env=bad)
    git(repo, "commit", "-q", "-m", f"msg with {BAD_IPS['cgnat']}", env=bad)
    rc, out = check(tmp_path, "--commits", "HEAD~1..HEAD", cwd=repo, env=env)
    assert rc == 1 and "[R6-identity] commit author email" in out and "<commit message>: [R4-ip]" in out
    assert BAD_EMAIL not in out


def test_commits_checks_annotated_tag_messages(tmp_path):
    repo, env = init_repo(tmp_path)
    (repo / "a.md").write_text("ok\n")
    git(repo, "add", ".", env=env)
    git(repo, "commit", "-q", "-m", "one", env=env)
    git(repo, "tag", "-a", "v0.1", "-m", "release notes: ok", env=env)
    git(repo, "tag", "-a", "v0.2", "-m", f"notes mention {BAD_IPS['rfc1918-10']}", env=env)
    rc, out = check(tmp_path, "--commits", "v0.1", cwd=repo, env=env)
    assert rc == 0 and "1 annotated tag(s)" in out, out
    rc, out = check(tmp_path, "--commits", "v0.2", cwd=repo, env=env)
    assert rc == 1 and "<tag message>: [R4-ip]" in out


# ---------------------------------------------------------------------------
# .githooks (installed into temp repos; acceptance negative tests)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("rel,content,rule", [
    ("foo.cmp", b"\x00dummy", "R1-ext"),
    ("notes/ships.md", ini_blocks(10), "R5-fl-data"),
    ("notes/net.txt", "lan box 192.168.1.77\n", "R4-ip"),
    ("notes/who.txt", "contact " + SYN_LITERAL + "\n", "R4-blocklist"),
])
def test_pre_commit_hook_blocks(tmp_path, rel, content, rule):
    repo, env = init_repo(tmp_path)
    install_hooks(repo, env)
    write(repo, {rel: content})
    git(repo, "add", rel, env=env)
    proc = git(repo, "commit", "-q", "-m", "bad", env=env, check_rc=False)
    out = proc.stdout + proc.stderr
    assert proc.returncode != 0
    assert f"FAIL {rel}: [{rule}]" in out and "commit blocked" in out
    git(repo, "reset", "-q", env=env)
    (repo / rel).unlink()
    assert git(repo, "status", "--porcelain", env=env).stdout.strip() == ""


def test_pre_commit_hook_allows_clean_commit_and_checks_merges(tmp_path):
    repo, env = init_repo(tmp_path)
    install_hooks(repo, env)
    (repo / "ok.md").write_text("fine\n")
    git(repo, "add", "ok.md", env=env)
    assert git(repo, "commit", "-q", "-m", "clean", env=env, check_rc=False).returncode == 0
    # A branch carrying a forbidden file (committed with --no-verify) cannot be merged.
    git(repo, "checkout", "-q", "-b", "wp/x", env=env)
    (repo / "x.dll").write_bytes(b"MZ")
    git(repo, "add", "x.dll", env=env)
    git(repo, "commit", "-q", "--no-verify", "-m", "sneak", env=env)
    git(repo, "checkout", "-q", "main", env=env)
    proc = git(repo, "merge", "--no-ff", "-m", "merge wp/x", "wp/x", env=env, check_rc=False)
    assert proc.returncode != 0 and "FAIL x.dll: [R1-ext]" in (proc.stdout + proc.stderr)
    git(repo, "merge", "--abort", env=env, check_rc=False)


def test_hooks_with_absolute_hookspath_cover_pre_merge_worktrees(tmp_path):
    """DECISIONS D101: core.hooksPath = <main checkout>/.githooks (absolute). A worktree branched before the
    hooks existed has no tools/check_public.py; its commits and merges still run main's checker."""
    main, env = init_repo(tmp_path, "main")
    write(main, {"README.md": "x\n"})
    git(main, "add", ".", env=env)
    git(main, "commit", "-q", "-m", "base", env=env)
    git(main, "branch", "wp/sibling", env=env)
    git(main, "branch", "wp/bad", env=env)
    shutil.copytree(HOOKS, main / ".githooks")
    (main / "tools").mkdir()
    shutil.copy2(CHECKER, main / "tools" / "check_public.py")
    git(main, "add", ".", env=env)
    git(main, "commit", "-q", "-m", "merge P0-REPO", env=env)
    git(main, "config", "core.hooksPath", str(main / ".githooks"), env=env)
    sib = tmp_path / "sib"
    git(main, "worktree", "add", "-q", str(sib), "wp/sibling", env=env)
    assert not (sib / "tools" / "check_public.py").exists()
    write(sib, {"ok.md": "clean\n"})
    git(sib, "add", "ok.md", env=env)
    proc = git(sib, "commit", "-q", "-m", "clean", env=env, check_rc=False)
    assert proc.returncode == 0 and "check_public: OK" in proc.stdout + proc.stderr
    write(sib, {"foo.cmp": b"\x00"})
    git(sib, "add", "foo.cmp", env=env)
    proc = git(sib, "commit", "-q", "-m", "bad", env=env, check_rc=False)
    assert proc.returncode != 0 and "FAIL foo.cmp: [R1-ext]" in proc.stdout + proc.stderr
    git(sib, "reset", "-q", env=env)
    (sib / "foo.cmp").unlink()
    # pre-merge-commit in the sibling: merging a branch that carries a forbidden file is blocked.
    bad = tmp_path / "bad"
    git(main, "worktree", "add", "-q", str(bad), "wp/bad", env=env)
    write(bad, {"x.dll": b"MZ"})
    git(bad, "add", "x.dll", env=env)
    git(bad, "commit", "-q", "--no-verify", "-m", "sneak", env=env)
    proc = git(sib, "merge", "--no-ff", "-m", "merge wp/bad", "wp/bad", env=env, check_rc=False)
    assert proc.returncode != 0 and "FAIL x.dll: [R1-ext]" in proc.stdout + proc.stderr
    git(sib, "merge", "--abort", env=env, check_rc=False)


def test_pre_push_hook_vets_history_and_tags(tmp_path):
    repo, env = init_repo(tmp_path)
    install_hooks(repo, env)
    remote = tmp_path / "remote.git"
    git(tmp_path, "init", "-q", "--bare", str(remote), env=env)
    git(repo, "remote", "add", "origin", str(remote), env=env)
    proc = git(repo, "push", "-q", "origin", "main", env=env, check_rc=False)
    assert proc.returncode == 0, proc.stderr
    git(repo, "tag", "-a", "v9", "-m", f"see {BAD_IPS['cgnat']}", env=env)
    proc = git(repo, "push", "-q", "origin", "v9", env=env, check_rc=False)
    assert proc.returncode != 0 and "<tag message>: [R4-ip]" in proc.stderr + proc.stdout
    (repo / "local").mkdir()
    (repo / "local" / "x.md").write_text("private\n")
    git(repo, "add", ".", env=env)
    git(repo, "commit", "-q", "--no-verify", "-m", "sneak", env=env)
    git(repo, "rm", "-q", "-r", "local", env=env)
    git(repo, "commit", "-q", "-m", "cleanup", env=env)
    proc = git(repo, "push", "-q", "origin", "main", env=env, check_rc=False)
    assert proc.returncode != 0 and "[R3-path]" in proc.stderr + proc.stdout and "push blocked" in proc.stderr
    remote_head = git(remote, "rev-parse", "main", env=env).stdout.strip()
    assert remote_head != git(repo, "rev-parse", "HEAD", env=env).stdout.strip()


# ---------------------------------------------------------------------------
# harness/ci.sh with a temporary ci.d (CI_D_DIR) and run dir (CI_RUNS_DIR)
# ---------------------------------------------------------------------------


def make_stage(ci_d: Path, fname: str, body: str, executable: bool = True) -> None:
    ci_d.mkdir(parents=True, exist_ok=True)
    p = ci_d / fname
    p.write_text("#!/usr/bin/env bash\n" + body + "\n")
    if executable:
        p.chmod(p.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def run_ci(tmp_path: Path, *args: str, ci_d: Path | None = None):
    repo = tmp_path / "cirepo"
    if not repo.exists():
        repo.mkdir()
        env0 = base_env(tmp_path)
        git(repo, "init", "-q", "-b", "main", env=env0)
        (repo / "README.md").write_text("clean\n")
    env = base_env(tmp_path)
    runs_dir = Path(tempfile.mkdtemp(prefix="runs", dir=tmp_path))  # one run per dir: no stamp collisions
    env.update(CI_REPO_ROOT=str(repo), CI_D_DIR=str(ci_d or tmp_path / "ci.d"), CI_RUNS_DIR=str(runs_dir))
    proc = subprocess.run([str(CI_SH), *args], env=env, capture_output=True, text=True, timeout=120)
    runs = sorted(runs_dir.glob("*-ci"))
    summary = (runs[-1] / "summary.md").read_text() if runs else ""
    return proc.returncode, proc.stdout + proc.stderr, summary, (runs[-1] if runs else None)


def test_ci_quick_pass_and_skip(tmp_path):
    make_stage(tmp_path / "ci.d", "10-alpha.sh", 'echo "CI alpha: PASS (fine)"; exit 0')
    make_stage(tmp_path / "ci.d", "20-beta.sh", 'echo "CI beta: SKIP (no prereq yet)"; exit 77')
    (tmp_path / "ci.d" / "README.md").write_text("ignored\n")
    rc, out, summary, rundir = run_ci(tmp_path, "--quick")
    assert rc == 0, out
    assert "CI public: PASS" in out and "CI alpha: PASS (fine)" in out and "CI beta: SKIP (no prereq yet)" in out
    assert rundir is not None and rundir.name.endswith("-ci") and rundir.parent.parent == tmp_path
    assert "VERDICT: PASS (2 pass, 1 skip, 0 fail, 0 not run)" in summary
    assert f"log: {rundir}/20-beta.log" in summary
    assert (rundir / "10-alpha.log").read_text().startswith("CI alpha: PASS")


def test_ci_failing_dropin_fails_run_and_stops(tmp_path):
    make_stage(tmp_path / "ci.d", "10-alpha.sh", 'echo "CI alpha: FAIL (broken)"; exit 1')
    make_stage(tmp_path / "ci.d", "20-beta.sh", 'echo "CI beta: PASS"; exit 0')
    rc, out, summary, _ = run_ci(tmp_path, "--quick")
    assert rc == 1
    assert "CI alpha: FAIL (broken)" in out and "CI beta: NOT RUN (stopped after alpha FAIL)" in out
    assert "VERDICT: FAIL (1 pass, 0 skip, 1 fail, 1 not run)" in summary


def test_ci_mode_cutoffs(tmp_path):
    for n in ("59", "60", "61"):
        make_stage(tmp_path / "ci.d", f"{n}-s{n}.sh", f'echo "CI s{n}: PASS"; exit 0')
    _, out, _, _ = run_ci(tmp_path, "--quick")
    assert "CI s59: PASS" in out and "s60" not in out and "s61" not in out
    _, out, _, _ = run_ci(tmp_path)
    assert "CI s59: PASS" in out and "CI s60: PASS" in out and "s61" not in out
    _, out, _, _ = run_ci(tmp_path, "--full")
    assert "CI s59: PASS" in out and "CI s60: PASS" in out and "CI s61: PASS" in out


def test_ci_only(tmp_path):
    make_stage(tmp_path / "ci.d", "10-alpha.sh", 'echo "CI alpha: PASS"; exit 0')
    make_stage(tmp_path / "ci.d", "80-soak-smoke.sh", 'echo "CI soak-smoke: SKIP (mode $CI_MODE)"; exit 77')
    rc, out, summary, _ = run_ci(tmp_path, "--only", "public")
    assert rc == 0 and "CI public: PASS" in out and "alpha" not in out
    rc, out, _, _ = run_ci(tmp_path, "--only=soak-smoke")
    assert rc == 0 and "CI soak-smoke: SKIP (mode default)" in out and "CI public" not in out
    rc, out, _, _ = run_ci(tmp_path, "--only", "alpha,data-validate")
    assert rc == 0 and "CI alpha: PASS" in out and "CI data-validate: SKIP (drop-in" in out
    rc, out, _, _ = run_ci(tmp_path, "--only", "nonsense")
    assert rc == 2 and "unknown stage" in out


def test_ci_passes_protocol_environment(tmp_path):
    make_stage(tmp_path / "ci.d", "10-envdump.sh",
               'echo "mode=$CI_MODE lanes=$CI_LANES rundir=$CI_RUNDIR q=$CI_QUARANTINE root=$CI_REPO_ROOT '
               'stage=$CI_STAGE cwd=$(pwd)"; echo "CI envdump: PASS"')
    rc, out, _, rundir = run_ci(tmp_path, "--quick", "--lanes", "3")
    assert rc == 0, out
    log = (rundir / "10-envdump.log").read_text()
    repo = tmp_path / "cirepo"
    assert (f"mode=quick lanes=3 rundir={rundir} q={repo}/state/QUARANTINE.md root={repo} "
            f"stage=envdump cwd={repo}") in log


def test_ci_non_executable_and_mismatched_verdicts_fail(tmp_path):
    make_stage(tmp_path / "ci.d", "10-noexec.sh", 'echo "CI noexec: PASS"', executable=False)
    rc, out, _, _ = run_ci(tmp_path, "--quick")
    assert rc == 1 and "CI noexec: FAIL (drop-in 10-noexec.sh is not executable)" in out
    shutil.rmtree(tmp_path / "ci.d")
    make_stage(tmp_path / "ci.d", "10-liar.sh", 'echo "CI liar: PASS (claims)"; exit 3')
    rc, out, _, _ = run_ci(tmp_path, "--quick")
    assert rc == 1 and "CI liar: FAIL (claims) [stage printed PASS but exited 3]" in out


def test_ci_public_stage_fails_on_violation(tmp_path):
    rc, out, summary, _ = run_ci(tmp_path, "--only", "public")
    assert rc == 0
    (tmp_path / "cirepo" / "leak.cmp").write_bytes(b"\x00")
    rc, out, summary, _ = run_ci(tmp_path, "--only", "public")
    assert rc == 1 and "CI public: FAIL" in out and "leak.cmp: [R1-ext]" in out
    assert "VERDICT: FAIL" in summary


def test_ci_public_stage_lists_every_authored_data_escape(tmp_path):
    rc, out, summary, _ = run_ci(tmp_path, "--only", "public")
    assert rc == 0 and "Authored-data escapes" not in summary
    repo = tmp_path / "cirepo"
    write(repo, {"data/npcs.yaml": npc_yaml_fixture(header=AUTHORED + " our NPC schema", n=12),
                 "tests/fixtures/w.json": world_json_fixture(), "tests/fixtures/w.json" + SIB: "our fixture\n"})
    rc, out, summary, _ = run_ci(tmp_path, "--only", "public")
    assert rc == 0, out
    assert "2 authored-data escape(s)" in out
    section = summary.split("## Authored-data escapes", 1)[1]
    assert "- data/npcs.yaml (comment line 1)" in section
    assert f"- tests/fixtures/w.json (sibling w.json{SIB})" in section


@pytest.mark.parametrize("args", [["--lanes", "0"], ["--quick", "--full"], ["--bogus"], ["--only"]])
def test_ci_usage_errors(tmp_path, args):
    rc, out, _, _ = run_ci(tmp_path, *args)
    assert rc == 2


# ---------------------------------------------------------------------------
# GitHub workflow (.github/workflows/public-safety.yml) and requirements-dev.txt
# ---------------------------------------------------------------------------

WORKFLOW = REPO / ".github" / "workflows" / "public-safety.yml"


def _workflow_steps() -> list[dict]:
    yaml = pytest.importorskip("yaml")
    doc = yaml.safe_load(WORKFLOW.read_text())
    return doc["jobs"]["public-safety"]["steps"]


def test_workflow_installs_requirements_dev_and_pins_current_action_majors():
    steps = _workflow_steps()
    uses = [s["uses"] for s in steps if "uses" in s]
    assert uses == ["actions/checkout@v7", "actions/setup-python@v7"]
    runs = "\n".join(s.get("run", "") for s in steps)
    assert "tools/check_public.py --tree ." in runs and "-r requirements-dev.txt" in runs
    reqs = (REPO / "requirements-dev.txt").read_text().lower()
    for pkg in ("pytest", "pyyaml", "jsonschema"):
        assert re.search(rf"^{pkg}\b", reqs, re.M), pkg


def _run_pytest_step(tmp_path: Path, dirs: list[str], rcs: dict[str, int]) -> tuple[int, list[str]]:
    script = next(s["run"] for s in _workflow_steps() if "pytest" in s.get("name", ""))
    work = tmp_path / "ws"
    work.mkdir(parents=True)
    for d in dirs:
        (work / d).mkdir(parents=True)
    stub = tmp_path / "stubbin"
    stub.mkdir()
    log = tmp_path / "calls.log"
    cases = "".join(f"  *{d}*) exit {rc} ;;\n" for d, rc in rcs.items())
    (stub / "python3").write_text(f'#!/bin/bash\necho "$*" >> {log}\ncase "$*" in\n{cases}esac\nexit 0\n')
    (stub / "python3").chmod(0o755)
    env = {"PATH": f"{stub}:/usr/bin:/bin", "HOME": str(tmp_path)}
    proc = subprocess.run(["bash", "-e", "-c", script], cwd=work, env=env, capture_output=True, text=True)
    calls = log.read_text().splitlines() if log.exists() else []
    return proc.returncode, calls


def test_workflow_runs_each_existing_test_dir_separately(tmp_path):
    rc, calls = _run_pytest_step(tmp_path / "a", ["tests/py", "sidecar/tests"], {})
    assert rc == 0 and calls == ["-m pytest tests/py -q", "-m pytest sidecar/tests -q"]
    rc, calls = _run_pytest_step(tmp_path / "b", ["tests/py"], {})
    assert rc == 0 and calls == ["-m pytest tests/py -q"]  # sidecar/tests not merged yet
    rc, calls = _run_pytest_step(tmp_path / "c", ["tests/py", "sidecar/tests"], {"tests/py": 1})
    assert rc == 1 and len(calls) == 2  # a failure fails the step, after every suite ran
    rc, calls = _run_pytest_step(tmp_path / "d", ["tests/py", "sidecar/tests"], {"sidecar/tests": 5})
    assert rc == 0  # 5 = nothing collected
    rc, calls = _run_pytest_step(tmp_path / "e", [], {})
    assert rc == 0 and calls == []
