"""Profiles: the test profile never opens an audio device; the live profile is guarded."""
from __future__ import annotations

from unittest.mock import patch

import pytest

from conftest import SCRIPTS_DIR, make_cfg, run, running_app
from flcopilot.audio.capture import FileMic, NullMic
from flcopilot.audio.sinks import DeviceSink, NullSink
from flcopilot.profiles import ProfileError, build_profile, guard_live


def test_test_profile_produces_no_output_stream(fakegame):
    """A full PTT -> policy.set -> say round trip in the test profile: audio is 'played', but only
    into the null sink. sounddevice is patched at its defining module, so any device use shows."""
    with patch("sounddevice.OutputStream") as out_stream, patch("sounddevice.InputStream") as in_stream, \
            patch("sounddevice.play") as sd_play, patch("sounddevice.rec") as sd_rec:
        async def body():
            async with running_app("test") as (app, port):
                assert isinstance(app.profile.sink, NullSink)
                assert isinstance(app.profile.mic, NullMic)
                await fakegame.run_script_file(SCRIPTS_DIR / "policy_roundtrip.ndjson", port)
                return app
        app = run(body())
        assert app.profile.sink.plays == 1 and app.profile.sink.samples > 0
        out_stream.assert_not_called()
        in_stream.assert_not_called()
        sd_play.assert_not_called()
        sd_rec.assert_not_called()


def test_null_sink_can_write_wavs(tmp_path):
    sink = NullSink(wav_dir=tmp_path)
    sink.play([0.0, 0.5, -0.5] * 100, 24000, label="x")
    files = list(tmp_path.glob("*.wav"))
    assert len(files) == 1 and files[0].stat().st_size > 44


def test_live_profile_refused_under_pytest():
    with pytest.raises(ProfileError, match="pytest"):
        build_profile("live", make_cfg())


def test_live_guard_env_switch():
    with pytest.raises(ProfileError):
        guard_live({"FLCOPILOT_FORCE_TEST_PROFILE": "1"})
    guard_live({})  # no pytest, no switch: allowed


def test_live_profile_build_opens_nothing():
    """Building the live profile (guard bypassed) resolves the mic but opens no stream."""
    pactl = "0\talsa_input.usb-Example_Headset-00.mono-fallback\tPipeWire\ts16le 1ch 48000Hz\tSUSPENDED\n"
    with patch("sounddevice.OutputStream") as out_stream, patch("sounddevice.InputStream") as in_stream, \
            patch("shutil.which", return_value="/usr/bin/pactl"), patch("subprocess.run") as sp_run:
        sp_run.return_value.returncode = 0
        sp_run.return_value.stdout = pactl
        sp_run.return_value.stderr = ""
        cfg = make_cfg(**{"audio.mic_match": "example_headset", "audio.capture_enabled": True})
        prof = build_profile("live", cfg, env={})
        assert isinstance(prof.sink, DeviceSink)
        assert prof.mic.name == "device" and prof.mic.source_name.endswith("mono-fallback")
        assert prof.features == () and prof.brain is None and prof.transcriber is None
        assert prof.mic_discovery.status == "resolved"
        out_stream.assert_not_called()
        in_stream.assert_not_called()


def test_live_profile_capture_disabled_by_default():
    with patch("shutil.which", return_value=None):
        prof = build_profile("live", make_cfg(), env={})
    assert isinstance(prof.mic, NullMic)
    assert prof.mic_discovery.status == "not_configured"


def test_device_sink_uses_output_stream():
    with patch("sounddevice.OutputStream") as out_stream:
        DeviceSink("default").play([0.0] * 240, 24000, label="t")
    out_stream.assert_called_once()
    kwargs = out_stream.call_args.kwargs
    assert kwargs["samplerate"] == 24000 and kwargs["channels"] == 1 and kwargs["device"] is None
    stream = out_stream.return_value.__enter__.return_value
    assert stream.write.call_args.args[0].shape == (240, 1)


def test_mic_file_requires_test_profile(tmp_path):
    with pytest.raises(ProfileError, match="mic-file"):
        build_profile("live", make_cfg(), mic_file=tmp_path / "x.wav", env={})


def test_unknown_profile():
    with pytest.raises(ProfileError):
        build_profile("prod", make_cfg())


def test_mic_file_feeds_the_pipeline(tmp_path, fakegame):
    np = pytest.importorskip("numpy")
    sf = pytest.importorskip("soundfile")
    wav = tmp_path / "order.wav"
    t = np.arange(48000) / 48000.0
    sf.write(str(wav), (0.2 * np.sin(2 * np.pi * 440 * t)).astype("float32"), 48000)  # 1 s at 48 kHz

    with patch("sounddevice.InputStream") as in_stream:
        async def body():
            async with running_app("test", mic_file=wav) as (app, port):
                assert isinstance(app.profile.mic, FileMic)
                await fakegame.run_script_file(SCRIPTS_DIR / "policy_roundtrip.ndjson", port)
                return app
        app = run(body())
        in_stream.assert_not_called()
    assert app.profile.mic.uses == 1
    assert app.profile.transcriber.last_clip_len == 16000  # resampled to 16 kHz mono
