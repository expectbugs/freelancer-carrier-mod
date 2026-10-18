#!/usr/bin/env python3
"""Offline voice smoke: Kokoro TTS -> WAV -> faster-whisper STT on the GPU.

    sidecar/run.sh --tool voice_smoke [--out DIR] [--model-source models|hf-cache] [--device cuda|cpu]

1. Kokoro (CPU) synthesizes the phrase to a WAV in the run dir.
2. faster-whisper large-v3-turbo (fp16, CUDA) transcribes it with game-vocabulary biasing.
3. The transcript must contain every target word.
4. Reports stt_ms (warm), tts_first_audio_ms (warm), load times, the device actually used,
   and nvidia-smi evidence that this process held GPU memory (or the CPU fallback reason).

No audio is played: sounddevice is never imported. Models load with local_files_only=True and
HF_HUB_OFFLINE=1, so nothing is downloaded. Output goes to $FLMOD_TESTRUNS/<UTC>-voice-smoke/.
Exit code 0 = pass.
"""
from __future__ import annotations

import argparse
import json
import os
import socket
import statistics
import subprocess
import sys
import time
from pathlib import Path

os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")

from flcopilot.audio.dsp import resample  # noqa: E402
from flcopilot.voice.stt import WhisperEngine  # noqa: E402
from flcopilot.voice.tts import KokoroEngine  # noqa: E402

PHRASE = "save nanobots for the cruiser"
TARGETS = ("nanobots", "cruiser")
HF_REPO_DIR = Path.home() / ".cache" / "huggingface" / "hub" / "models--mobiuslabsgmbh--faster-whisper-large-v3-turbo"


def gpu_snapshot() -> dict:
    """GPU memory in use, and per-process usage, from nvidia-smi (empty dict if unavailable)."""
    out: dict = {}
    try:
        g = subprocess.run(["nvidia-smi", "--query-gpu=name,memory.used,memory.total,driver_version",
                            "--format=csv,noheader,nounits"], capture_output=True, text=True, timeout=10)
        name, used, total, driver = [x.strip() for x in g.stdout.strip().splitlines()[0].split(",")]
        out.update(gpu=name, mem_used_mib=int(used), mem_total_mib=int(total), driver=driver)
        a = subprocess.run(["nvidia-smi", "--query-compute-apps=pid,used_memory", "--format=csv,noheader,nounits"],
                           capture_output=True, text=True, timeout=10)
        apps = {}
        for line in a.stdout.strip().splitlines():
            pid, mem = [x.strip() for x in line.split(",")]
            apps[int(pid)] = int(mem)
        out["this_pid_mib"] = apps.get(os.getpid())
    except (OSError, ValueError, IndexError, subprocess.SubprocessError) as exc:
        out["error"] = f"{type(exc).__name__}: {exc}"[:200]
    return out


def interfaces() -> list[str]:
    try:
        return sorted(name for _, name in socket.if_nameindex())
    except OSError:
        return []


def default_out() -> Path:
    base = os.environ.get("FLMOD_TESTRUNS") or str(Path.cwd())
    stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    return Path(base) / f"{stamp}-voice-smoke"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", type=Path, default=None, help="run dir (default $FLMOD_TESTRUNS/<UTC>-voice-smoke)")
    ap.add_argument("--text", default=PHRASE)
    ap.add_argument("--voice", default="am_michael")
    ap.add_argument("--model-source", choices=("models", "hf-cache"), default="models",
                    help="models = $FLMOD_MODELS/whisper copy; hf-cache = by name from ~/.cache/huggingface (offline)")
    ap.add_argument("--device", default="cuda")
    ap.add_argument("--compute-type", default=None, help="default float16 on cuda, int8 on cpu")
    ap.add_argument("--warm-runs", type=int, default=5)
    args = ap.parse_args(argv)

    models = Path(os.environ.get("FLMOD_MODELS") or "")
    out = args.out or default_out()
    out.mkdir(parents=True, exist_ok=True)
    report: dict = {
        "phrase": args.text, "targets": list(TARGETS), "voice": args.voice, "pid": os.getpid(),
        "env": {"HF_HUB_OFFLINE": os.environ.get("HF_HUB_OFFLINE"),
                "LD_LIBRARY_PATH_has_cublas12": "nvidia/cublas/lib" in os.environ.get("LD_LIBRARY_PATH", ""),
                "interfaces": interfaces()},
    }
    ok = True
    try:
        # ---- TTS ------------------------------------------------------------------------
        import numpy as np
        import soundfile

        tts = KokoroEngine(models / "kokoro")
        if not tts.available():
            raise FileNotFoundError(f"Kokoro model files missing under {models / 'kokoro'}")
        tts.load()

        def synth() -> tuple[float, "np.ndarray", int]:
            t0 = time.perf_counter()
            it = tts.synthesize(args.text, voice=args.voice)
            first, rate = next(it)
            first_ms = (time.perf_counter() - t0) * 1000.0
            parts = [np.asarray(first, dtype=np.float32)] + [np.asarray(p, dtype=np.float32) for p, _ in it]
            return first_ms, np.concatenate(parts), rate

        cold_first_ms, pcm, rate = synth()
        warm = [synth()[0] for _ in range(3)]
        wav = out / "tts.wav"
        soundfile.write(str(wav), pcm, rate)
        report["tts"] = {"engine": "kokoro-onnx 0.5.0 (CPU)", "load_ms": round(tts.load_ms, 1),
                         "first_audio_ms_cold": round(cold_first_ms, 1),
                         "tts_first_audio_ms": round(statistics.median(warm), 1),
                         "first_audio_ms_warm_runs": [round(x, 1) for x in warm],
                         "audio_s": round(len(pcm) / rate, 3), "rate": rate, "wav": str(wav)}

        # ---- STT ------------------------------------------------------------------------
        if args.model_source == "models":
            model_path = models / "whisper" / "faster-whisper-large-v3-turbo"
        else:
            model_path = None  # resolve "large-v3-turbo" from the HF cache, local_files_only
            if not HF_REPO_DIR.exists():
                raise FileNotFoundError(f"HF cache entry missing: {HF_REPO_DIR}")
        compute = args.compute_type or ("float16" if args.device == "cuda" else "int8")
        stt = WhisperEngine(model_path, device=args.device, compute_type=compute, beam_size=1)
        gpu_before = gpu_snapshot()
        stt.load()
        gpu_loaded = gpu_snapshot()
        audio, file_rate = soundfile.read(str(wav), dtype="float32")
        clip16 = resample(audio, file_rate, 16000)
        t0 = time.perf_counter()
        first = stt.transcribe(clip16)
        cold_ms = (time.perf_counter() - t0) * 1000.0
        warm_ms = []
        texts = [first.text]
        for _ in range(args.warm_runs):
            t0 = time.perf_counter()
            r = stt.transcribe(clip16)
            warm_ms.append((time.perf_counter() - t0) * 1000.0)
            texts.append(r.text)
        gpu_after = gpu_snapshot()
        transcript = first.text
        low = transcript.lower()
        missing = [w for w in TARGETS if w not in low]
        stable = len(set(texts)) == 1
        report["stt"] = {
            "engine": "faster-whisper 1.2.1 large-v3-turbo",
            "model_source": args.model_source, "model": str(model_path) if model_path else "large-v3-turbo (HF cache)",
            "device": stt.device, "compute_type": stt.compute_type, "fallback_reason": stt.fallback_reason,
            "load_ms": round(stt.load_ms or 0, 1), "first_transcribe_ms": round(cold_ms, 1),
            "stt_ms": round(statistics.median(warm_ms), 1) if warm_ms else round(cold_ms, 1),
            "warm_runs_ms": [round(x, 1) for x in warm_ms],
            "clip_s": round(len(clip16) / 16000, 3),
            "transcript": transcript, "missing": missing, "stable_across_runs": stable,
        }
        report["gpu"] = {"before": gpu_before, "after_load": gpu_loaded, "after_transcribe": gpu_after,
                         "vram_delta_mib": (gpu_loaded.get("mem_used_mib", 0) - gpu_before.get("mem_used_mib", 0))
                         if "mem_used_mib" in gpu_loaded and "mem_used_mib" in gpu_before else None,
                         "cuda_used": stt.device == "cuda" and bool(gpu_loaded.get("this_pid_mib"))}
        if missing:
            ok = False
        if args.device == "cuda" and stt.device != "cuda":
            report["note"] = f"CPU fallback: {stt.fallback_reason}"
    except Exception as exc:
        ok = False
        report["error"] = f"{type(exc).__name__}: {exc}"[:500]

    report["result"] = "pass" if ok else "fail"
    (out / "summary.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))
    s, t, g = report.get("stt", {}), report.get("tts", {}), report.get("gpu", {})
    print(f"VOICE_SMOKE {'ok' if ok else 'FAIL'} transcript={s.get('transcript')!r} stt_ms={s.get('stt_ms')} "
          f"tts_first_audio_ms={t.get('tts_first_audio_ms')} device={s.get('device')}/{s.get('compute_type')} "
          f"this_pid_gpu_mib={g.get('after_load', {}).get('this_pid_mib')} out={out}", flush=True)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
