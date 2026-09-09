"""Microphone capture with VAD + optional wake-word gating.

Three states:
    muted    — hard cut, ignore frames entirely (used during TTS playback)
    asleep   — frames processed only for wake-word detection (wake mode)
    awake    — frames forwarded to STT + VAD segments utterances

Emits utterance boundaries via on_speech_start / on_speech_end callbacks.
"""
import asyncio
import queue
import struct
import sounddevice as sd
import webrtcvad
import config

try:
    import pvporcupine
    PORCUPINE_AVAILABLE = True
except ImportError:
    PORCUPINE_AVAILABLE = False


class MicStream:
    def __init__(self, on_speech_start=None, on_speech_end=None,
                 on_wake=None, wake_word=None):
        self.vad = webrtcvad.Vad(config.VAD_AGGRESSIVENESS)
        self.audio_queue: asyncio.Queue = asyncio.Queue()
        self._raw_queue: queue.Queue = queue.Queue()
        self._stream = None
        self._task = None
        self.on_speech_start = on_speech_start
        self.on_speech_end = on_speech_end
        self.on_wake = on_wake
        self._speaking = False
        self._silence_count = 0
        self.muted = False

        self.wake_enabled = bool(wake_word)
        self.porcupine = None
        self._pv_buffer = bytearray()
        self._pv_frame_bytes = 0
        if self.wake_enabled:
            if not PORCUPINE_AVAILABLE:
                raise RuntimeError("pvporcupine not installed. pip install pvporcupine")
            if not config.PORCUPINE_ACCESS_KEY:
                raise RuntimeError("PORCUPINE_ACCESS_KEY not set in .env")
            self.porcupine = pvporcupine.create(
                access_key=config.PORCUPINE_ACCESS_KEY,
                keywords=[wake_word],
            )
            self._pv_frame_bytes = self.porcupine.frame_length * 2
            self.awake = False
        else:
            self.awake = True

    def _callback(self, indata, frames, time_info, status):
        if status:
            print(f"[mic] {status}")
        self._raw_queue.put(bytes(indata))

    def _try_wake(self, frame_bytes: bytes) -> bool:
        if not self.porcupine:
            return False
        self._pv_buffer.extend(frame_bytes)
        detected = False
        while len(self._pv_buffer) >= self._pv_frame_bytes:
            chunk = bytes(self._pv_buffer[: self._pv_frame_bytes])
            del self._pv_buffer[: self._pv_frame_bytes]
            pcm = struct.unpack(f"{self.porcupine.frame_length}h", chunk)
            idx = self.porcupine.process(pcm)
            if idx >= 0:
                detected = True
        return detected

    async def _pump(self):
        while True:
            try:
                frame = await asyncio.get_event_loop().run_in_executor(
                    None, self._raw_queue.get
                )
            except Exception:
                break
            if self.muted:
                continue

            if not self.awake:
                if self._try_wake(frame):
                    self.awake = True
                    print("[wake] activated")
                    if self.on_wake:
                        await self._maybe_await(self.on_wake())
                continue

            is_speech = self.vad.is_speech(frame, config.SAMPLE_RATE)
            if is_speech:
                self._silence_count = 0
                if not self._speaking:
                    self._speaking = True
                    if self.on_speech_start:
                        await self._maybe_await(self.on_speech_start())
                await self.audio_queue.put(frame)
            else:
                if self._speaking:
                    await self.audio_queue.put(frame)
                    self._silence_count += 1
                    if self._silence_count >= config.SILENCE_FRAMES_TO_END:
                        self._speaking = False
                        self._silence_count = 0
                        if self.on_speech_end:
                            await self._maybe_await(self.on_speech_end())

    @staticmethod
    async def _maybe_await(x):
        if asyncio.iscoroutine(x):
            await x

    def start(self):
        self._stream = sd.RawInputStream(
            samplerate=config.SAMPLE_RATE,
            blocksize=config.FRAME_SAMPLES,
            channels=config.CHANNELS,
            dtype="int16",
            callback=self._callback,
        )
        self._stream.start()
        self._task = asyncio.create_task(self._pump())
        mode = f"wake-word ('{config.WAKE_WORD}')" if self.wake_enabled else "always-on"
        print(f"[mic] listening at {config.SAMPLE_RATE}Hz — mode: {mode}")

    def stop(self):
        if self._stream:
            self._stream.stop()
            self._stream.close()
        if self._task:
            self._task.cancel()
        if self.porcupine:
            self.porcupine.delete()

    def mute(self):
        self.muted = True

    def unmute(self):
        self.muted = False
        while not self._raw_queue.empty():
            try:
                self._raw_queue.get_nowait()
            except queue.Empty:
                break

    def sleep(self):
        """Return to wake-word-only mode. No-op if always-on."""
        if self.wake_enabled:
            self.awake = False
            print("[wake] sleeping")
