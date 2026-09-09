# Voice Coding Agent

A real-time voice-controlled coding assistant for macOS. Speak naturally while looking at your editor — the agent hears you, sees your screen, reads and edits your code, runs commands, and talks back.

> Say "there are red errors in this file, can you fix them?" — it takes a screenshot of your screen, reads the source file, diagnoses the issue, and applies a surgical diff. Then tells you what it changed in one sentence.

---

## How It Works

```
Mic → VAD → Deepgram STT → Claude (streaming + tools) → Kokoro TTS → Speaker
                                    │
                                    ├── get_editor_context (macOS accessibility)
                                    ├── see_screen (multi-monitor screenshot)
                                    ├── read_file / write_file / apply_diff
                                    ├── run_shell (sandboxed)
                                    └── list_directory
```

Text streams from Claude to TTS one sentence at a time — you hear the first sentence while Claude is still generating the rest. Time-to-first-audio is around 500ms.

On the first turn, the agent discovers your project structure automatically by scanning the workspace. It injects the full file tree into its system prompt so it always uses exact paths — no guessing, no "file not found" errors. Works with any project you point it at.

When you stop talking for a while, Deepgram's connection drops naturally. The next time you speak, it reconnects in about 200ms. No keepalive spam, no reconnect noise in the terminal.

Long conversations are automatically summarized by Haiku when they exceed the context limit. The last 3 turns are always kept verbatim. You can talk to the agent for hours without hitting token limits.

---

## Prerequisites

Make sure you have these installed before starting.

**macOS** Monterey 12 or later (tested on Sequoia).

**Python 3.11 or newer.** Check with `python3 --version`. If you need it:

```bash
brew install python@3.11
```

**PortAudio.** Required for microphone access. Without it, the app installs fine but crashes on launch.

```bash
brew install portaudio
```

**Xcode Command Line Tools.** Needed to compile some dependencies.

```bash
xcode-select --install
```

If you don't have Homebrew yet, install it from https://brew.sh first.

---

## Setup

### 1. Get the project

```bash
cd ~/Downloads
unzip voice-coding-agent.zip
cd voice-coding-agent
```

### 2. Create a virtual environment and install dependencies

```bash
python3.11 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```

This takes 2-3 minutes. The `pyobjc` packages are the slowest part.

If you hit errors during install:

- `webrtcvad` fails to build — run `xcode-select --install` and retry
- `pkg_resources` not found — run `pip install setuptools`
- `webrtcvad` imports but crashes — run `pip uninstall webrtcvad -y && pip install webrtcvad-wheels`
- Deepgram import errors — run `pip install "deepgram-sdk==3.7.7"`

### 3. Get your API keys

You need two keys. The TTS runs locally for free.

**Anthropic** — this is the brain. Go to https://console.anthropic.com, create an API key under your personal account (not a workspace/org key). Add at least $5 credit. The key starts with `sk-ant-api03-`.

**Deepgram** — this handles speech-to-text. Go to https://console.deepgram.com, sign up for free (no credit card needed, you get $200 in credit), and create an API key.

### 4. Configure your environment

```bash
cp .env.example .env
```

Open `.env` and fill in your keys:

```
ANTHROPIC_API_KEY=sk-ant-api03-xxxxxxxxxxxxx
DEEPGRAM_API_KEY=xxxxxxxxxxxxx
WORKSPACE_DIR=/Users/yourname/code/my-project
CLAUDE_MODEL=claude-sonnet-4-5-20250929
```

The `WORKSPACE_DIR` is the folder the agent can read and write in. Point it at a real project, or create a test folder:

```bash
mkdir -p ~/code/test-project
```

The agent is sandboxed to this folder. It cannot touch anything outside it.

### 5. Grant macOS permissions

You need to grant two permissions to whichever terminal app you'll run the agent from. If you're using VS Code's integrated terminal (recommended), most of this may already be done.

**Microphone.** Run this command — macOS will show a permission dialog:

```bash
python -c "import sounddevice as sd; sd.rec(1600, samplerate=16000, channels=1); sd.wait(); print('mic OK')"
```

Click Allow. You can verify it worked in System Settings → Privacy & Security → Microphone.

**Accessibility.** This lets the agent read what's on your screen.

Go to System Settings → Privacy & Security → Accessibility. Make sure you're on the page that says "Allow the applications below to control your computer" (not the VoiceOver/Zoom settings page — they both say "Accessibility" which is confusing).

Click the + button, add your terminal app (VS Code, Terminal.app, iTerm, etc.), and toggle it on. Then fully quit your terminal with Cmd+Q and reopen it. The permission doesn't apply to processes that were already running.

To verify it works:

```bash
source .venv/bin/activate
python -m src.screen.a11y
```

You should see the name of your focused app and possibly its window contents. If you just see the app name without text content, that's fine — the agent automatically falls back to screenshots when the accessibility tree is thin.

### 6. Run

```bash
python main.py 2>/dev/null
```

The `2>/dev/null` hides background WebSocket noise. You'll see:

```
[tts] warming up voice model...
[tts] kokoro loaded
[tts] ready
[stt] connected
[mic] listening at 16000Hz — mode: always-on

============================================================
Ready. Start talking. Ctrl+C to quit.
============================================================
```

On the very first run, Kokoro downloads its voice model (about 80MB). This takes around 30 seconds. After that it's cached at `~/.cache/kokoro/` and startup is instant.

### 7. Talk to it

Open a code file in your editor, click into it, and try these:

- "What am I looking at?" — reads your screen, describes the file
- "Can you see the red errors?" — takes a screenshot, identifies errors
- "Fix the errors in this file" — reads the file, applies diffs
- "Add a docstring to this function" — writes the docstring
- "Run the tests" — executes your test command
- "Create a new file called utils.py with a debounce function" — creates it
- "List the files in this directory" — shows workspace contents

You can interrupt the agent mid-speech by talking over it. Press Ctrl+C to quit.

---

## Project Structure

```
voice-coding-agent/
├── main.py                        Main orchestrator
├── config.py                      Environment variables and tuning
├── requirements.txt               Python dependencies
├── .env.example                   Template for API keys
│
└── src/
    ├── audio/
    │   ├── capture.py             Mic input, VAD, optional wake word
    │   └── playback.py            Audio output with cancellation
    │
    ├── stt/
    │   └── deepgram_client.py     Streaming speech-to-text
    │
    ├── tts/
    │   └── elevenlabs_client.py   Local Kokoro TTS (no API needed)
    │
    ├── screen/
    │   ├── a11y.py                macOS accessibility tree
    │   └── capture.py             Multi-monitor screenshots
    │
    └── agent/
        ├── graph.py               Streaming agent with tool loop
        ├── tools.py               7 tools for file ops, shell, screen
        ├── prompts.py             Dynamic system prompt
        └── memory.py              History compaction via Haiku
```

---

## Features

**Streaming pipeline.** Claude streams tokens to TTS sentence by sentence. You hear the first sentence while the rest is still generating.

**Screen reading.** Two methods — accessibility tree for structured text (fast, precise) and screenshot fallback for terminals, image viewers, and anything the accessibility API misses. The agent picks the right one automatically.

**Dynamic workspace discovery.** On first turn, the agent scans your project and learns the file tree. It uses exact paths from that point on. Switch projects by changing `WORKSPACE_DIR` — no prompt editing needed.

**Connect-on-demand STT.** Deepgram connects when you start speaking and drops when idle. No keepalive noise, no reconnect spam. Reconnects in about 200ms when you speak again.

**Barge-in.** Talk over the agent to interrupt it. TTS stops immediately and your new command takes priority.

**History compaction.** Old conversation turns are summarized by Haiku when the context gets large. Recent turns are kept verbatim.

**Orphan cleanup.** If a turn gets cancelled mid-tool-call, dangling state is cleaned automatically before the next turn. No manual recovery needed.

**Workspace sandbox.** All file operations are restricted to `WORKSPACE_DIR`. Dangerous shell commands like `rm -rf`, `sudo`, and `git push --force` are refused.

**Wake word (optional).** Set `WAKE_WORD=computer` and `PORCUPINE_ACCESS_KEY` in your `.env` to enable voice activation. Say the wake word, speak your command, the agent processes it and goes back to sleep. Free tier key available at https://console.picovoice.ai. Built-in wake words include computer, jarvis, terminator, and others.

---

## Agent Tools

The agent has 7 tools available:

- `get_editor_context` — reads the macOS accessibility tree to see the focused app, window, text, cursor position, and selected text
- `see_screen` — takes a live screenshot and sends it to Claude's vision API, used as a fallback when the accessibility tree is thin
- `read_file` — reads a file from the workspace, truncated at 20k characters for large files
- `write_file` — creates or overwrites a file, used for new files or full rewrites
- `apply_diff` — replaces one unique string with another inside a file, safer than write_file for small edits
- `list_directory` — lists files in a directory relative to the workspace root
- `run_shell` — runs a shell command with a 30 second timeout, refuses dangerous command patterns

---

## Tuning

These can be set in `.env` or edited in `config.py`:

- `VAD_AGGRESSIVENESS` (default 2) — noise filtering level from 0 to 3. Lower it if the agent cuts you off. Raise it if it picks up background noise.
- `SILENCE_FRAMES_TO_END` (default 25, about 750ms) — how long you need to pause before the agent considers your utterance complete. Increase to 35-40 if it cuts you off mid-thought.
- `MAX_HISTORY_CHARS` (default 200000) — when to trigger history compaction.
- `KEEP_LAST_N_TURNS` (default 3) — how many recent turns to keep verbatim during compaction.
- `SCREENSHOT_MAX_WIDTH` (default 1600) — screenshots are downscaled to this width before sending to the vision API.

---

## Troubleshooting

**Nothing happens when I talk.** Check that your terminal app has microphone permission in System Settings. Run the sounddevice test from Step 5.

**Transcript appears but no response from the agent.** Your Anthropic API key is wrong or you're out of credit. Check `.env` and your account balance at console.anthropic.com.

**Error about anthropic-workspace-id.** You're using a workspace/org API key. Create a personal key instead.

**Agent responds in text but no voice output.** The Kokoro model might not have downloaded properly. Delete the cache and restart:

```bash
rm -rf ~/.cache/kokoro
python main.py 2>/dev/null
```

**Screen says "screen unavailable".** Accessibility permission is missing or your terminal wasn't restarted after granting it. Quit your terminal fully with Cmd+Q, reopen, and try again.

**Agent cuts me off mid-sentence.** Open `config.py` and increase `SILENCE_FRAMES_TO_END` from 25 to 35 or 40.

**Agent picks up background noise or its own voice.** Increase `VAD_AGGRESSIVENESS` to 3 in `config.py`.

---

## Costs

Anthropic Claude is the only real cost — about $0.003 per turn with Sonnet. Five dollars lasts weeks of normal use.

Deepgram gives you $200 in free credit on signup. No credit card required. That's months of use.

Kokoro TTS is completely free. It runs locally on your Mac's CPU with no API calls.

Picovoice (for the optional wake word) has a free tier.

---

## Limitations

This only runs on macOS. The accessibility APIs and screenshot capture use macOS-specific frameworks. Linux and Windows would need different backends for screen reading.

The latency floor is around 500ms to 2 seconds depending on response length. Getting below that would require a fundamentally different architecture using something like the OpenAI Realtime API (single WebSocket doing STT, LLM, and TTS together).

Conversation history resets when you restart the agent. Adding persistence would be about 10 lines of code to pickle the history on shutdown and load it on start.

Screenshots capture from the display containing the focused app. It won't screenshot two monitors at once.

---

## Safety

The agent is sandboxed to your `WORKSPACE_DIR` and cannot access files outside it. Shell commands matching dangerous patterns are refused. This is a safety net, not a security boundary — don't point it at code you can't afford to lose.

Audio and screenshots are sent to Deepgram and Anthropic's APIs. Don't use this with sensitive code or personal information visible on screen.

---

## Tech Stack

- Anthropic Claude Sonnet — LLM with streaming and tool use
- Deepgram Nova-3 — streaming speech-to-text
- Kokoro ONNX — local text-to-speech, zero API cost
- WebRTC VAD — voice activity detection
- pyobjc — macOS accessibility tree access
- mss — cross-platform screenshot capture
- Picovoice Porcupine — optional wake word detection
- Python 3.11+

---

## License

MIT
