# Voice Coding Agent

Real-time voice-controlled coding assistant for macOS. Speak while looking at your editor, Claude sees what you're looking at and edits code in your workspace.

## Architecture

```
mic → VAD → Deepgram STT → Claude (streaming) → sentence chunks → ElevenLabs Flash → speaker
              │                    │
              │                    ├── read_file / write_file / apply_diff
              │                    ├── run_shell (sandboxed)
              │                    ├── get_editor_context (macOS a11y)
              │                    └── see_screen (multi-monitor screenshot)
              │
              └── optional: Porcupine wake word ("computer")
```

Text streams from Claude to TTS one sentence at a time — speech starts on the first sentence while Claude is still generating the rest. Typical time-to-first-audio: ~500ms.

## Setup (5 min)

### 1. Install
```bash
python3.11 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 2. Get API keys
- Anthropic: https://console.anthropic.com
- Deepgram: https://console.deepgram.com (free tier: $200 credit)
- ElevenLabs: https://elevenlabs.io (free tier: 10k chars/mo)
- Picovoice (optional, wake word only): https://console.picovoice.ai (free tier)

### 3. Configure
```bash
cp .env.example .env
# edit .env with your keys + your project path
```

### 4. Grant macOS Accessibility permission
This is the one manual step you can't skip. Without it, the agent can't see your screen.

`System Settings → Privacy & Security → Accessibility → +` add your terminal (Terminal, iTerm, WezTerm, whatever) or the Python binary.

Test it:
```bash
python -m src.screen.a11y
```
You should see the focused window's contents. If you see `[screen unavailable]` — permission is missing.

### 5. Run
```bash
python main.py
```

## Try saying

- "What am I looking at?" — sanity check that a11y works
- "Add error handling to this function"
- "Rename the variable foo to userId everywhere in this file"
- "Run the tests"
- "Create a new file utils.py with a debounce function"
- "What error is in my terminal?" — triggers see_screen since Terminal.app has no a11y text

## Optional: wake word mode

By default the agent is always listening. If you want push-to-talk-by-voice, set in `.env`:

```
WAKE_WORD=computer
PORCUPINE_ACCESS_KEY=your-key-from-picovoice
```

Say "computer" to wake it, then speak your command. It goes back to sleep after each response. Built-in wake words: `alexa`, `americano`, `blueberry`, `bumblebee`, `computer`, `grapefruit`, `grasshopper`, `hey google`, `hey siri`, `jarvis`, `ok google`, `picovoice`, `porcupine`, `terminator`. Custom wake words require training on the Picovoice console.

## Features

- **Streaming pipeline**: Claude streams tokens → sentence chunker → ElevenLabs Flash → speaker. TTS starts on the first sentence, not after Claude finishes.
- **Vision fallback**: when the a11y tree is thin (Terminal, image viewers, non-native apps), the agent calls `see_screen` for a live screenshot.
- **Multi-monitor aware**: screenshot grabs from the display containing the focused app, not always the primary.
- **History compaction**: when the message list crosses `MAX_HISTORY_CHARS` (~50k tokens by default), older turns are summarized by Haiku and replaced with a synthetic briefing, keeping the last 3 turns verbatim.
- **Barge-in**: talk over the agent, TTS + agent both cancel.
- **Optional wake word**: sleep until you say the wake word, process one utterance, sleep again.
- **Workspace sandbox**: file ops scoped to `WORKSPACE_DIR`, destructive shell patterns refused.

## Files

```
main.py                       # orchestrator - run this
config.py                     # env vars + tuning
src/audio/capture.py          # mic + VAD + optional Porcupine wake
src/audio/playback.py         # TTS speaker output
src/stt/deepgram_client.py    # streaming STT
src/tts/elevenlabs_client.py  # streaming TTS (Flash v2.5)
src/screen/a11y.py            # macOS accessibility tree
src/screen/capture.py         # multi-monitor screenshot
src/agent/graph.py            # streaming agent with tool loop
src/agent/tools.py            # file ops, shell, editor context, see_screen
src/agent/prompts.py          # system prompt
src/agent/memory.py           # history compaction via Haiku
```

## Rough edges

- Deepgram utterance detection sometimes cuts you off mid-thought. Tune `SILENCE_FRAMES_TO_END` in `config.py`.
- Interruption cancels the agent task but tool executions in flight complete. Not a data corruption risk (all ops are atomic), but wasted API calls.
- Sub-500ms latency needs a rewrite onto OpenAI Realtime API or Gemini Live (one WebSocket doing STT+LLM+TTS). Current best is ~500ms time-to-first-audio which is the sentence-chunking limit.
- Wake word only fires on a full utterance boundary, not mid-sentence.

## Safety notes

- The agent is scoped to `WORKSPACE_DIR` — it cannot read/write outside it.
- Shell commands matching dangerous patterns (`rm -rf`, `sudo`, `git push --force`, etc.) are refused. Not a security boundary — a determined agent could work around it. Only point this at code you're OK losing.
- All API calls send audio, screen contents, and screenshots to third parties (Deepgram, Anthropic, ElevenLabs). Don't use with sensitive code or PII on screen.
