"""Deepgram streaming STT — connect-on-demand version.

Instead of staying connected and fighting idle timeouts, we:
1. Connect when the first audio frame arrives
2. Stay connected while audio is flowing
3. Let it drop naturally when idle (no keepalive spam)
4. Reconnect instantly when new audio comes in

This eliminates the reconnect cycling that kills the mic during idle.
"""
import asyncio
import logging
from typing import Callable, Awaitable
from deepgram import (
    DeepgramClient,
    LiveTranscriptionEvents,
    LiveOptions,
)
from config import DEEPGRAM_API_KEY, SAMPLE_RATE

logging.getLogger("deepgram").setLevel(logging.CRITICAL)
logging.getLogger("websockets").setLevel(logging.CRITICAL)
logging.getLogger("asyncio").setLevel(logging.WARNING)


def _make_options():
    return LiveOptions(
        model="nova-3",
        language="en-US",
        encoding="linear16",
        sample_rate=SAMPLE_RATE,
        channels=1,
        interim_results=True,
        smart_format=True,
        punctuate=True,
        endpointing=300,
    )


class DeepgramSTT:
    def __init__(self, on_transcript: Callable[[str, bool], Awaitable[None]]):
        self.on_transcript = on_transcript
        self._client = DeepgramClient(DEEPGRAM_API_KEY)
        self._conn = None
        self._alive = False
        self._lock = asyncio.Lock()
        self._printed_first = False

    async def start(self):
        """Initial connect."""
        await self._ensure_connected()

    async def send(self, pcm_bytes: bytes):
        """Send audio — reconnects automatically if needed."""
        if not self._alive:
            await self._ensure_connected()
        if self._alive and self._conn:
            try:
                await self._conn.send(pcm_bytes)
            except Exception:
                self._alive = False
                # Will reconnect on next send()

    async def close(self):
        self._alive = False
        if self._conn:
            try:
                await self._conn.finish()
            except Exception:
                pass

    async def _ensure_connected(self):
        """Connect if not already connected."""
        if self._alive:
            return
        async with self._lock:
            if self._alive:
                return
            try:
                conn = self._client.listen.asyncwebsocket.v("1")

                def _on_message(_c, result, **kw):
                    try:
                        alt = result.channel.alternatives[0]
                        text = alt.transcript
                        if text:
                            asyncio.create_task(self.on_transcript(text, result.is_final))
                    except Exception:
                        pass

                def _on_error(_c, error, **kw):
                    self._alive = False

                def _on_close(_c, **kw):
                    self._alive = False

                conn.on(LiveTranscriptionEvents.Transcript, _on_message)
                conn.on(LiveTranscriptionEvents.Error, _on_error)
                conn.on(LiveTranscriptionEvents.Close, _on_close)

                ok = await conn.start(_make_options())
                if ok:
                    self._conn = conn
                    self._alive = True
                    if not self._printed_first:
                        self._printed_first = True
                        print("[stt] connected")
            except Exception as e:
                self._alive = False