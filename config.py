"""Central config loaded from .env"""
import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

# API keys
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
DEEPGRAM_API_KEY = os.getenv("DEEPGRAM_API_KEY")
ELEVENLABS_API_KEY = os.getenv("ELEVENLABS_API_KEY")
ELEVENLABS_VOICE_ID = os.getenv("ELEVENLABS_VOICE_ID", "21m00Tcm4TlvDq8ikWAM")

# Workspace (agent is restricted to this dir for file ops)
WORKSPACE_DIR = Path(os.getenv("WORKSPACE_DIR", str(Path.home() / "code"))).expanduser().resolve()

# Model
CLAUDE_MODEL = os.getenv("CLAUDE_MODEL", "claude-sonnet-4-5-20250929")

# Audio
SAMPLE_RATE = 16000
FRAME_MS = 30
FRAME_SAMPLES = int(SAMPLE_RATE * FRAME_MS / 1000)
CHANNELS = 1

# VAD tuning
VAD_AGGRESSIVENESS = 0  # 0-3, higher = more aggressive filtering
SILENCE_FRAMES_TO_END = 25  # ~750ms of silence ends an utterance

# Screen
SCREENSHOT_MAX_WIDTH = 1600  # downscale large displays before sending to vision

# Memory / history compaction (see src/agent/memory.py)
# Overridable via env if you want to tune without editing code
MAX_HISTORY_CHARS = int(os.getenv("MAX_HISTORY_CHARS", "200000"))
KEEP_LAST_N_TURNS = int(os.getenv("KEEP_LAST_N_TURNS", "3"))
SUMMARIZER_MODEL = os.getenv("SUMMARIZER_MODEL", "claude-haiku-4-5-20251001")

# Wake word (optional). If WAKE_WORD is unset, agent is always listening.
# Built-in options: alexa, americano, blueberry, bumblebee, computer,
# grapefruit, grasshopper, hey google, hey siri, jarvis, ok google,
# picovoice, porcupine, terminator
WAKE_WORD = os.getenv("WAKE_WORD") or None
PORCUPINE_ACCESS_KEY = os.getenv("PORCUPINE_ACCESS_KEY")

DEBUG = os.getenv("DEBUG", "false").lower() == "true"

def check():
    missing = [k for k, v in {
        "ANTHROPIC_API_KEY": ANTHROPIC_API_KEY,
        "DEEPGRAM_API_KEY": DEEPGRAM_API_KEY,
        "ELEVENLABS_API_KEY": ELEVENLABS_API_KEY,
    }.items() if not v]
    if missing:
        raise RuntimeError(f"Missing env vars: {', '.join(missing)}. Copy .env.example to .env and fill in.")
    if WAKE_WORD and not PORCUPINE_ACCESS_KEY:
        raise RuntimeError("WAKE_WORD is set but PORCUPINE_ACCESS_KEY is missing. Get a free key at https://console.picovoice.ai/")
    if not WORKSPACE_DIR.exists():
        raise RuntimeError(f"WORKSPACE_DIR does not exist: {WORKSPACE_DIR}")
