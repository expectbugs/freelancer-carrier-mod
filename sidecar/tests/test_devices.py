"""Mic discovery with a mocked pactl (synthetic device names only; never a real one)."""
from __future__ import annotations

import subprocess
from unittest.mock import patch

from flcopilot import cli
from flcopilot.audio import devices

PACTL = (
    "51\talsa_output.pci-0000_00_00.1.hdmi-stereo.monitor\tPipeWire\ts32le 2ch 48000Hz\tSUSPENDED\n"
    "52\talsa_input.usb-Example_Headset_SN0000-00.analog-stereo\tPipeWire\ts16le 2ch 48000Hz\tRUNNING\n"
    "53\talsa_input.usb-Generic_Desk_Mic-00.mono-fallback\tPipeWire\ts16le 1ch 48000Hz\tSUSPENDED\n"
    "54\talsa_output.usb-Example_Headset_SN0000-00.analog-stereo.monitor\tPipeWire\ts16le 2ch 48000Hz\tIDLE\n"
    "garbage line\n"
)


def _pactl_ok(stdout=PACTL, returncode=0):
    return subprocess.CompletedProcess(args=["pactl"], returncode=returncode, stdout=stdout, stderr="boom")


def test_parse_short_sources():
    srcs = devices.parse_short_sources(PACTL)
    assert [s.index for s in srcs] == [51, 52, 53, 54]
    assert srcs[0].is_monitor and not srcs[1].is_monitor
    assert srcs[1].state == "RUNNING" and srcs[2].spec.startswith("s16le 1ch")


def test_resolve_skips_monitors_and_is_case_insensitive():
    srcs = devices.parse_short_sources(PACTL)
    src, n = devices.resolve_source("example_headset", srcs)
    assert src.index == 52 and n == 1  # the .monitor of the same device is not a mic
    src, n = devices.resolve_source("nothing-like-this", srcs)
    assert src is None and n == 0


def test_discover_not_configured_runs_nothing():
    with patch("subprocess.run") as sp:
        d = devices.discover("")
    assert d.status == "not_configured"
    sp.assert_not_called()


def test_discover_resolved_and_not_found():
    with patch("shutil.which", return_value="/usr/bin/pactl"), patch("subprocess.run", return_value=_pactl_ok()) as sp:
        d = devices.discover("Desk_Mic")
        assert d.status == "resolved" and d.source.index == 53
        assert sp.call_args.args[0][1:] == ["list", "short", "sources"]
        assert sp.call_args.kwargs["timeout"] == devices.PACTL_TIMEOUT_S
        d = devices.discover("Missing_Device")
        assert d.status == "not_found" and d.source is None


def test_discover_errors_are_contained():
    with patch("shutil.which", return_value=None):
        assert devices.discover("x").status == "error"
    with patch("shutil.which", return_value="/usr/bin/pactl"), \
            patch("subprocess.run", return_value=_pactl_ok(returncode=1)):
        d = devices.discover("x")
        assert d.status == "error" and "exited 1" in d.detail
    with patch("shutil.which", return_value="/usr/bin/pactl"), \
            patch("subprocess.run", side_effect=subprocess.TimeoutExpired("pactl", 3)):
        assert devices.discover("x").status == "error"


def test_cli_discover_mic(capsys, tmp_path):
    overlay = tmp_path / "local.yaml"
    overlay.write_text('mic_match: "Example_Headset"\n', encoding="utf-8")
    with patch("shutil.which", return_value="/usr/bin/pactl"), patch("subprocess.run", return_value=_pactl_ok()):
        rc = cli.main(["--discover-mic", "--local-config", str(overlay), "--log-file", str(tmp_path / "s.log"),
                       "--quiet"])
    out = capsys.readouterr().out
    assert rc == 0 and out.startswith("mic: resolved index=52 name=alsa_input.usb-Example_Headset")
    overlay.write_text('mic_match: "Absent_Device"\n', encoding="utf-8")
    with patch("shutil.which", return_value="/usr/bin/pactl"), patch("subprocess.run", return_value=_pactl_ok()):
        rc = cli.main(["--discover-mic", "--local-config", str(overlay), "--log-file", str(tmp_path / "s.log"),
                       "--quiet"])
    assert rc == 1 and capsys.readouterr().out.strip() == "mic: not found"
