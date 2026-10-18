"""Static safety checks over the sidecar sources (REQ-P0-SIDECAR-9, CLAUDE.md guardrails 5-7)."""
from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

from conftest import REPO_DIR, SIDECAR_DIR
from flcopilot import config

PY_FILES = sorted(p for p in SIDECAR_DIR.rglob("*.py") if "__pycache__" not in p.parts)
TEXT_FILES = sorted(p for p in SIDECAR_DIR.rglob("*")
                    if p.is_file() and "__pycache__" not in p.parts and p.suffix in
                    (".py", ".md", ".toml", ".ndjson", ".sh", ".txt", ".lock", ".yaml", ".yml")) \
    + [REPO_DIR / "docs" / "spec" / "ipc.md"]

# The owner's other projects. Spelled in pieces so this file itself carries no such literal.
_A = "ar" + "ia"
FORBIDDEN_TOP_LEVEL = {_A, _A + "2", "g2" + "cc", "G2" + "CC", "rt_" + "zom" + "boid", "zom" + "boid"}


def imported_top_levels(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            names.add(node.module.split(".")[0])
        elif isinstance(node, ast.Call) and getattr(node.func, "id", getattr(node.func, "attr", "")) in (
                "import_module", "__import__") and node.args and isinstance(node.args[0], ast.Constant):
            names.add(str(node.args[0].value).split(".")[0])
    return names


@pytest.mark.parametrize("path", PY_FILES, ids=lambda p: str(p.relative_to(SIDECAR_DIR)))
def test_no_imports_from_owner_projects(path):
    bad = {n for n in imported_top_levels(path) if n in FORBIDDEN_TOP_LEVEL or n.lower().startswith(_A)}
    assert not bad, f"{path} imports {bad}"


def test_no_textual_import_of_owner_projects():
    """The acceptance grep, done in Python: 'import <x>' / 'from <x>' for the owner's projects."""
    pat = re.compile(r"\b(import|from)\s+" + _A + r"\b")
    hits = [str(p) for p in PY_FILES if pat.search(p.read_text(encoding="utf-8"))]
    assert hits == []


NETWORK_MODULES = {"socket", "urllib", "http", "requests", "httpx", "httpx2", "aiohttp", "websockets", "ssl", "smtplib",
                   "ftplib", "telnetlib", "xmlrpc"}
#: Modules allowed to import a network module, and which.
NETWORK_ALLOW = {
    "flcopilot/server.py": {"socket"},     # the loopback listener
    "flcopilot/cli.py": {"socket"},        # selftest: checks the port is closed after shutdown
}
SUBPROCESS_ALLOW = {"flcopilot/audio/devices.py"}  # pactl, read-only listing


def test_network_and_subprocess_use_is_confined():
    for path in sorted((SIDECAR_DIR / "flcopilot").rglob("*.py")):
        rel = str(path.relative_to(SIDECAR_DIR))
        names = imported_top_levels(path)
        net = names & NETWORK_MODULES
        assert net <= NETWORK_ALLOW.get(rel, set()), f"{rel} imports {net}"
        if "subprocess" in names:
            assert rel in SUBPROCESS_ALLOW, f"{rel} imports subprocess"


def test_listener_host_is_the_loopback_constant():
    src = (SIDECAR_DIR / "flcopilot" / "server.py").read_text(encoding="utf-8")
    assert "host=protocol.LOOPBACK_HOST" in src
    assert "0.0.0.0" not in src and "localhost" not in src
    from flcopilot import protocol
    assert protocol.LOOPBACK_HOST == "127.0.0.1"


def test_no_secret_markers_in_sidecar():
    markers = ["PHONE_" + "IP", "PHONE_" + "PORT", "api" + "_key", "sk-" + "ant-", "gh" + "p_", "gh" + "o_",
               "PRIVATE " + "KEY"]
    for path in TEXT_FILES:
        text = path.read_text(encoding="utf-8", errors="replace")
        for m in markers:
            assert m not in text, f"{path}: contains a secret marker"


def test_no_private_ip_literals():
    pat = re.compile(r"\b(10\.\d+\.\d+\.\d+|192\.168\.\d+\.\d+|172\.(1[6-9]|2\d|3[01])\.\d+\.\d+|"
                     r"100\.(6[4-9]|[7-9]\d|1[01]\d|12[0-7])\.\d+\.\d+)\b")
    for path in TEXT_FILES:
        assert not pat.search(path.read_text(encoding="utf-8", errors="replace")), path


def test_local_mic_name_never_committed():
    """The real mic_match value from the gitignored overlay appears in no sidecar file (value not printed)."""
    path = config.default_local_overlay()
    if path is None or not path.exists():
        pytest.skip("no local overlay on this machine")
    value = str(config.load(None, local_path=path, env={}).get("audio.mic_match") or "").strip().lower()
    if not value:
        pytest.skip("local overlay sets no mic_match")
    offenders = [str(p.relative_to(REPO_DIR)) for p in TEXT_FILES
                 if value in p.read_text(encoding="utf-8", errors="replace").lower()]
    assert offenders == [], "the local mic name appears in committed files"


def test_no_model_or_audio_files_in_sidecar():
    bad = [p for p in SIDECAR_DIR.rglob("*") if p.is_file() and (
        p.suffix in (".onnx", ".bin", ".wav", ".mp3", ".ogg", ".pt", ".safetensors") or p.stat().st_size > 1_000_000)]
    assert bad == []
