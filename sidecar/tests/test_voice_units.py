"""Voice building blocks without models: text prep, fakes, and the engines with mocked libraries."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from flcopilot.brain import FakeBrain
from flcopilot.voice import stt, tts


def test_prepare_for_speech_strips_markdown_and_parens():
    out = tts.prepare_for_speech("**Shields** down (again)!\n\n- use `nanobots`\n[docs](http://example.com)")
    assert "*" not in out and "(" not in out and "`" not in out and "http" not in out
    assert "Shields down again!" in out and "use nanobots" in out


def test_ensure_tts_splits_breaks_long_runs():
    long = " ".join(["word"] * 120)  # ~600 chars, no punctuation
    out = tts.ensure_tts_splits(long)
    assert "," in out
    assert all(len(run) < 200 for run in out.split(","))


def test_split_sentences_first_unit_small_and_hard_max():
    text = "Shields at half. " * 30
    units = tts.split_sentences(text.strip())
    assert len(units[0]) <= tts.SENTENCE_FIRST_TARGET_CHARS
    assert all(len(u) <= tts.SENTENCE_HARD_MAX_CHARS for u in units)
    assert " ".join(units).replace("  ", " ") == text.strip()
    monster = "a" * 1000
    assert all(len(u) <= tts.SENTENCE_HARD_MAX_CHARS for u in tts.split_sentences(monster))


def test_fake_tts_is_deterministic_and_numpy_free():
    f = tts.FakeTTS()
    a = list(f.synthesize("three word line"))
    b = list(f.synthesize("three word line"))
    assert a == b and a[0][1] == 24000 and len(a[0][0]) == 3 * 1200
    assert isinstance(a[0][0], list)


def test_kokoro_engine_with_mocked_library(tmp_path):
    (tmp_path / "kokoro-v1.0.onnx").write_bytes(b"x")
    (tmp_path / "voices-v1.0.bin").write_bytes(b"x")
    with patch("kokoro_onnx.Kokoro") as kokoro:
        kokoro.return_value.create.return_value = ([0.1] * 2400, 24000)
        eng = tts.KokoroEngine(tmp_path)
        out = list(eng.synthesize("First sentence. Second one.", voice="bf_emma"))
        import kokoro_onnx
        assert kokoro_onnx.MAX_PHONEME_LENGTH == 509
    kokoro.assert_called_once_with(str(tmp_path / "kokoro-v1.0.onnx"), str(tmp_path / "voices-v1.0.bin"))
    assert out and all(sr == 24000 for _, sr in out)
    assert kokoro.return_value.create.call_args.kwargs["voice"] == "bf_emma"


def test_kokoro_engine_missing_files(tmp_path):
    eng = tts.KokoroEngine(tmp_path)
    assert not eng.available()
    with pytest.raises(FileNotFoundError):
        eng.load()


def test_whisper_engine_offline_options_and_cpu_fallback(tmp_path):
    np = pytest.importorskip("numpy")
    (tmp_path / "model.bin").write_bytes(b"x")
    seg = MagicMock(start=0.0, end=1.0, text=" save nanobots for the cruiser ")
    info = MagicMock(language="en", duration=1.0)
    calls = []

    def fake_model(src, device, compute_type, local_files_only):
        calls.append((src, device, compute_type, local_files_only))
        if device == "cuda":
            raise RuntimeError("Library libcublas.so.12 is not found")
        m = MagicMock()
        m.transcribe.return_value = (iter([seg]), info)
        return m

    with patch("faster_whisper.WhisperModel", side_effect=fake_model):
        eng = stt.WhisperEngine(tmp_path, device="cuda", compute_type="float16")
        res = eng.transcribe(np.zeros(24000, dtype=np.float32), sample_rate=24000)
    assert calls[0] == (str(tmp_path), "cuda", "float16", True)
    assert calls[1] == (str(tmp_path), "cpu", "int8", True)
    assert "libcublas" in eng.fallback_reason
    assert res.text == "save nanobots for the cruiser" and res.device == "cpu"
    kwargs = eng._model.transcribe.call_args.kwargs
    assert kwargs["language"] == "en" and kwargs["beam_size"] == 1 and kwargs["without_timestamps"] is True
    assert kwargs["condition_on_previous_text"] is False and kwargs["vad_filter"] is False
    assert "nanobots" in kwargs["hotwords"] and "cruiser" in kwargs["initial_prompt"]
    assert len(eng._model.transcribe.call_args.args[0]) == 16000  # resampled 24 kHz -> 16 kHz


def test_whisper_source_falls_back_to_cache_name(tmp_path):
    eng = stt.WhisperEngine(tmp_path / "absent")
    assert eng._source() == "large-v3-turbo"


@pytest.mark.parametrize("utterance,t,fields", [
    ("save nanobots for the cruiser", "policy.set", {"bots_reserve": 9, "release_reserve_when": "capital_hostile_present"}),
    ("Keep the bots for the big one!", "policy.set", {"bots_reserve": 9}),
    ("use nanobots", "act", {"do": "use_bots"}),
])
def test_fake_brain_commands(utterance, t, fields):
    reply = FakeBrain().respond(utterance, {"ship": {"bots": 9}})
    assert reply.commands and reply.commands[0].t == t
    for k, v in fields.items():
        assert reply.commands[0].fields[k] == v
    assert reply.say


def test_fake_brain_default_and_unknown():
    assert FakeBrain(default_reserve=4).respond("save the bots", None).commands[0].fields["bots_reserve"] == 4
    r = FakeBrain().respond("what a lovely nebula", None)
    assert r.commands == [] and r.say == "Say again?"
