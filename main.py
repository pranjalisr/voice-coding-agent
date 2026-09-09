"""Voice-controlled coding agent — main orchestrator."""
import asyncio
import signal
import sys
import config
from src.audio.capture import MicStream
from src.audio.playback import Player
from src.stt.deepgram_client import DeepgramSTT
from src.tts.elevenlabs_client import ElevenLabsTTS
from src.agent.graph import run_turn_streaming


class VoiceAgent:
    def __init__(self):
        self.history = []
        self.finalized_transcript = ""
        self.mic: MicStream = None
        self.stt: DeepgramSTT = None
        self.tts = ElevenLabsTTS()
        self.player = Player(sample_rate=16000)
        self.utterance_ready = asyncio.Event()
        self._pending_utterance = None
        self.agent_task: asyncio.Task = None
        self.shutdown = asyncio.Event()

    async def on_transcript(self, text: str, is_final: bool):
        if is_final:
            self.finalized_transcript = (self.finalized_transcript + " " + text).strip()
            print(f"[stt-final] {text}")
        else:
            print(f"[stt-partial] {text}", end="\r")

    async def on_wake(self):
        pass

    async def on_speech_start(self):
        if self.player.is_playing:
            print("\n[barge-in] canceling response")
            self.player.cancel()
        if self.agent_task and not self.agent_task.done():
            self.agent_task.cancel()

    async def on_speech_end(self):
        await asyncio.sleep(0.4)
        text = self.finalized_transcript.strip()
        self.finalized_transcript = ""
        if text:
            print(f"\n[you] {text}")
            self._pending_utterance = text
            self.utterance_ready.set()

    async def _audio_forwarder(self):
        """Forward mic frames to Deepgram. Reconnect is handled inside DeepgramSTT."""
        while not self.shutdown.is_set():
            try:
                frame = await asyncio.wait_for(
                    self.mic.audio_queue.get(), timeout=0.5
                )
                await self.stt.send(frame)
            except asyncio.TimeoutError:
                continue
            except Exception as e:
                print(f"[fwd] {e}")

    async def _tts_worker(self, tts_queue: asyncio.Queue):
        while True:
            chunk = await tts_queue.get()
            if chunk is None:
                return
            try:
                print(f"[tts] {chunk}")
                async def _iter(text=chunk):
                    async for pcm in self.tts.stream(text):
                        yield pcm
                await self.player.play_stream(_iter())
            except Exception as e:
                print(f"[tts] error: {e}")

    async def _process_turn(self, user_text: str):
        tts_queue: asyncio.Queue = asyncio.Queue()
        self.mic.mute()
        worker = asyncio.create_task(self._tts_worker(tts_queue))
        try:
            async for kind, payload in run_turn_streaming(self.history, user_text):
                if kind == "text":
                    print(f"[claude] {payload}")
                    await tts_queue.put(payload)
                elif kind == "done":
                    self.history = payload
                    break
        except asyncio.CancelledError:
            self.player.cancel()
            raise
        except Exception as e:
            print(f"[agent] error: {e}")
        finally:
            await tts_queue.put(None)
            try:
                await worker
            except Exception:
                pass
            await asyncio.sleep(0.15)
            self.mic.unmute()
            self.mic.sleep()

    async def _turn_loop(self):
        while not self.shutdown.is_set():
            try:
                await asyncio.wait_for(self.utterance_ready.wait(), timeout=0.5)
            except asyncio.TimeoutError:
                continue
            self.utterance_ready.clear()
            user_text = self._pending_utterance
            self._pending_utterance = None
            if not user_text:
                continue
            self.agent_task = asyncio.create_task(self._process_turn(user_text))
            try:
                await self.agent_task
            except asyncio.CancelledError:
                pass

    async def run(self):
        config.check()
        print(f"[config] workspace: {config.WORKSPACE_DIR}")
        print(f"[config] model: {config.CLAUDE_MODEL}")

        # Pre-load Kokoro BEFORE opening Deepgram connection
        # so the 80MB download doesn't cause a timeout on first run
        print("[tts] warming up voice model...")
        await asyncio.get_event_loop().run_in_executor(
            None, self.tts._preload
        )
        print("[tts] ready")

        self.player.open()
        self.stt = DeepgramSTT(self.on_transcript)
        await self.stt.start()

        self.mic = MicStream(
            on_speech_start=self.on_speech_start,
            on_speech_end=self.on_speech_end,
            on_wake=self.on_wake,
            wake_word=config.WAKE_WORD,
        )
        self.mic.start()

        forwarder = asyncio.create_task(self._audio_forwarder())
        turn_loop = asyncio.create_task(self._turn_loop())

        print("\n" + "=" * 60)
        if config.WAKE_WORD:
            print(f"Ready. Say '{config.WAKE_WORD}' to wake me. Ctrl+C to quit.")
        else:
            print("Ready. Start talking. Ctrl+C to quit.")
        print("=" * 60 + "\n")

        try:
            await self.shutdown.wait()
        finally:
            forwarder.cancel()
            turn_loop.cancel()
            self.mic.stop()
            await self.stt.close()
            self.player.close()

    def request_shutdown(self):
        self.shutdown.set()


async def main():
    agent = VoiceAgent()
    loop = asyncio.get_event_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, agent.request_shutdown)
    await agent.run()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nbye")
        sys.exit(0)