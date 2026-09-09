"""Local TTS via Kokoro-ONNX.

Fully offline, no API key needed. Runs on CPU, ~150-200ms latency on M-series.
Downloads ~80MB model on first run, cached after that.

Replaces ElevenLabs — same interface (stream() async generator yielding PCM16 bytes).
"""
import asyncio
import io
from typing import Optional

import numpy as np
import soundfile as sf
from pathlib import Path

# Kokoro outputs 24kHz — we resample to 16kHz for our player
OUTPUT_SAMPLE_RATE = 24000
PLAYER_SAMPLE_RATE = 16000

_kokoro = None
_kokoro_lock = asyncio.Lock()


def _load_kokoro():
    global _kokoro
    if _kokoro is not None:
        return _kokoro
    from kokoro_onnx import Kokoro
    model_path = Path.home() / ".cache" / "kokoro" / "kokoro-v1.0.onnx"
    voices_path = Path.home() / ".cache" / "kokoro" / "voices-v1.0.bin"
    model_path.parent.mkdir(parents=True, exist_ok=True)

    if not model_path.exists() or not voices_path.exists():
        print("[tts] downloading Kokoro model (~80MB, one-time)...")
        import urllib.request
        base = "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/"
        for fname, path in [("kokoro-v1.0.onnx", model_path), ("voices-v1.0.bin", voices_path)]:
            if not path.exists():
                print(f"[tts] downloading {fname}...")
                urllib.request.urlretrieve(base + fname, path)
        print("[tts] download complete")

    _kokoro = Kokoro(str(model_path), str(voices_path))
    print("[tts] kokoro loaded")
    return _kokoro


def _resample(audio: np.ndarray, from_rate: int, to_rate: int) -> np.ndarray:
    """Simple linear resample."""
    if from_rate == to_rate:
        return audio
    ratio = to_rate / from_rate
    new_len = int(len(audio) * ratio)
    indices = np.linspace(0, len(audio) - 1, new_len)
    return np.interp(indices, np.arange(len(audio)), audio)


def _to_pcm16(audio: np.ndarray) -> bytes:
    audio = np.clip(audio, -1.0, 1.0)
    return (audio * 32767).astype(np.int16).tobytes()


class ElevenLabsTTS:
    """Drop-in replacement — same interface as the ElevenLabs version."""

    def __init__(self, voice_id: str = None):
        self.voice = "af_heart"  # warm female voice, sounds great
        # voice_id param kept for API compat, ignored

    async def stream(self, text: str):
        """Yield PCM16 mono @ 16kHz bytes."""
        if not text.strip():
            return

        async with _kokoro_lock:
            kokoro = await asyncio.get_event_loop().run_in_executor(None, _load_kokoro)

        # Generate in executor so we don't block the event loop
        def _generate():
            samples, rate = kokoro.create(text, voice=self.voice, speed=1.0, lang="en-us")
            resampled = _resample(samples, rate, PLAYER_SAMPLE_RATE)
            return _to_pcm16(resampled)

        pcm = await asyncio.get_event_loop().run_in_executor(None, _generate)

        # Yield in 4KB chunks so the player can start immediately
        chunk_size = 4096
        for i in range(0, len(pcm), chunk_size):
            yield pcm[i:i + chunk_size]

    def _preload(self):
        """Synchronously load (and if needed download) the Kokoro model.
        Call this once at startup before connecting to any streaming APIs."""
        _load_kokoro()