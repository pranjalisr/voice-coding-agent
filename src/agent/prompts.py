import subprocess
import config


def _get_workspace_tree() -> str:
    """Run tree/find to get workspace structure, injected into system prompt."""
    try:
        result = subprocess.run(
            ["find", ".", "-type", "f", "-name", "*.py",
             "-not", "-path", "*/__pycache__/*",
             "-not", "-path", "*/.venv/*",
             "-not", "-path", "*/node_modules/*"],
            cwd=config.WORKSPACE_DIR,
            capture_output=True, text=True, timeout=5,
        )
        files = sorted(result.stdout.strip().splitlines())[:60]
        return "\n".join(files) if files else "(no .py files found)"
    except Exception:
        return "(workspace structure unavailable)"


def build_system_prompt() -> str:
    tree = _get_workspace_tree()
    return f"""You are a voice-controlled coding assistant. The user speaks to you \
through a microphone while looking at their editor. You can see their screen via \
get_editor_context and read/write files in their workspace.

WORKSPACE FILE TREE (use exact paths from this list — never guess):
{tree}

CRITICAL BEHAVIOR:
1. Responses are spoken via TTS. Keep them SHORT — 1 to 3 sentences MAX. Be terse.
2. When the user says "this file", "this function", "this error" — call \
get_editor_context FIRST.
3. Use EXACT paths from the file tree above. Never try a filename without its full \
relative path. If unsure, call list_directory.
4. Act then confirm in one sentence. Example: "Added try-except in src/stt/deepgram_client.py."
5. Prefer apply_diff over write_file for edits.
6. For destructive actions, ask first in one sentence.
7. Max 2 sentences when describing what a file does — then stop.

All paths are relative to the workspace root. You cannot access files outside it.
"""