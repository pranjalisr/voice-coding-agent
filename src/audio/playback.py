"""TTS audio playback with cancellation support."""
import asyncio
import io
import sounddevice as sd
import numpy as np


# ElevenLabs streams pcm_16000 mono when we request it, so no decoding needed.


class Player:
    def __init__(self, sample_rate=16000):
        self.sample_rate = sample_rate
        self._stream = None
        self._playing = False
        self._cancel = asyncio.Event()

    def open(self):
        self._stream = sd.RawOutputStream(
            samplerate=self.sample_rate,
            channels=1,
            dtype="int16",
        )
        self._stream.start()

    def close(self):
        if self._stream:
            self._stream.stop()
            self._stream.close()

    async def play_stream(self, chunk_iter):
        """Play an async iterator of PCM16 bytes. Cancellable."""
        self._playing = True
        self._cancel.clear()
        try:
            async for chunk in chunk_iter:
                if self._cancel.is_set():
                    break
                if not chunk:
                    continue
                # sounddevice write is blocking; offload to thread
                await asyncio.get_event_loop().run_in_executor(
                    None, self._stream.write, chunk
                )
        finally:
            self._playing = False

    def cancel(self):
        self._cancel.set()

    @property
    def is_playing(self):
        return self._playing
