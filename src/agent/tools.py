"""Tools exposed to the Claude agent.

All file ops are scoped to config.WORKSPACE_DIR to prevent the agent from
writing to arbitrary locations. Shell commands run in that dir. Destructive
patterns (rm -rf, git push --force, etc.) require explicit user confirmation
via the terminal.
"""
import asyncio
import difflib
import re
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Union
import config
from src.screen.capture import grab_screen_b64


DANGEROUS_PATTERNS = [
    r"\brm\s+-rf?\b", r"\bsudo\b", r"\bmkfs\b", r"\bdd\s+if=",
    r":\(\)\{", r">\s*/dev/sd", r"git\s+push\s+.*--force",
    r"git\s+reset\s+.*--hard", r"npm\s+publish", r"chmod\s+-R",
]


def _resolve(path: str) -> Path:
    p = (config.WORKSPACE_DIR / path).resolve() if not Path(path).is_absolute() else Path(path).resolve()
    try:
        p.relative_to(config.WORKSPACE_DIR)
    except ValueError:
        raise PermissionError(f"Path outside workspace: {p}")
    return p


def read_file(path: str) -> str:
    p = _resolve(path)
    if not p.exists():
        return f"ERROR: file not found: {path}"
    if p.is_dir():
        return f"ERROR: {path} is a directory"
    try:
        content = p.read_text(encoding="utf-8", errors="replace")
        if len(content) > 20000:
            content = content[:20000] + f"\n...[TRUNCATED — file is {len(content)} chars total]"
        return content
    except Exception as e:
        return f"ERROR reading {path}: {e}"


def write_file(path: str, content: str) -> str:
    p = _resolve(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    existed = p.exists()
    p.write_text(content, encoding="utf-8")
    return f"{'UPDATED' if existed else 'CREATED'} {p.relative_to(config.WORKSPACE_DIR)} ({len(content)} chars)"


def apply_diff(path: str, old_str: str, new_str: str) -> str:
    p = _resolve(path)
    if not p.exists():
        return f"ERROR: file not found: {path}"
    text = p.read_text(encoding="utf-8")
    count = text.count(old_str)
    if count == 0:
        return f"ERROR: old_str not found in {path}"
    if count > 1:
        return f"ERROR: old_str appears {count} times in {path} — make it unique"
    updated = text.replace(old_str, new_str, 1)
    p.write_text(updated, encoding="utf-8")
    diff = "\n".join(difflib.unified_diff(
        text.splitlines(), updated.splitlines(),
        fromfile=str(path), tofile=str(path), n=2, lineterm=""
    ))
    return f"PATCHED {path}\n{diff[:1500]}"


def list_directory(path: str = ".") -> str:
    p = _resolve(path)
    if not p.exists():
        return f"ERROR: not found: {path}"
    if not p.is_dir():
        return f"ERROR: not a directory: {path}"
    items = []
    for entry in sorted(p.iterdir()):
        if entry.name.startswith("."):
            continue
        marker = "/" if entry.is_dir() else ""
        items.append(f"  {entry.name}{marker}")
    return f"{path}:\n" + "\n".join(items[:200])


def run_shell(cmd: str, cwd: str = ".") -> str:
    for pattern in DANGEROUS_PATTERNS:
        if re.search(pattern, cmd):
            return f"REFUSED: command matches dangerous pattern ({pattern}). Ask the user to run this manually."
    workdir = _resolve(cwd)
    try:
        result = subprocess.run(
            cmd, shell=True, cwd=workdir,
            capture_output=True, text=True, timeout=30,
        )
        out = result.stdout[-4000:] if result.stdout else ""
        err = result.stderr[-2000:] if result.stderr else ""
        return f"exit={result.returncode}\nSTDOUT:\n{out}\nSTDERR:\n{err}"
    except subprocess.TimeoutExpired:
        return "ERROR: command timed out after 30s"
    except Exception as e:
        return f"ERROR: {e}"


def get_editor_context() -> str:
    """Fresh accessibility snapshot of what the user is looking at."""
    from src.screen.a11y import snapshot_text
    return snapshot_text()


def see_screen() -> List[Dict[str, Any]]:
    """Grab a live screenshot and return as image content block for Claude vision.

    Use when a11y tree is thin (terminals, native GUIs, image viewers)
    or when the user references visual elements not in text form.
    """
    b64, _ = grab_screen_b64(force=True)
    if b64 is None:
        return [{"type": "text", "text": "ERROR: could not capture screen"}]
    return [
        {"type": "text", "text": "Current screen contents (screenshot):"},
        {
            "type": "image",
            "source": {"type": "base64", "media_type": "image/png", "data": b64},
        },
    ]


TOOL_SCHEMAS: List[Dict[str, Any]] = [
    {
        "name": "read_file",
        "description": "Read a text file from the workspace. Returns the file content (truncated if very large).",
        "input_schema": {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]},
    },
    {
        "name": "write_file",
        "description": "Write or overwrite a file. Prefer apply_diff for small edits — use this for new files or full rewrites.",
        "input_schema": {"type": "object", "properties": {"path": {"type": "string"}, "content": {"type": "string"}}, "required": ["path", "content"]},
    },
    {
        "name": "apply_diff",
        "description": "Replace one unique occurrence of old_str with new_str in a file. Safer than write_file for edits. Fails if old_str is not unique.",
        "input_schema": {"type": "object", "properties": {"path": {"type": "string"}, "old_str": {"type": "string"}, "new_str": {"type": "string"}}, "required": ["path", "old_str", "new_str"]},
    },
    {
        "name": "list_directory",
        "description": "List files in a directory relative to the workspace.",
        "input_schema": {"type": "object", "properties": {"path": {"type": "string"}}, "required": []},
    },
    {
        "name": "run_shell",
        "description": "Run a shell command in the workspace. 30s timeout. Destructive commands are refused.",
        "input_schema": {"type": "object", "properties": {"cmd": {"type": "string"}, "cwd": {"type": "string"}}, "required": ["cmd"]},
    },
    {
        "name": "get_editor_context",
        "description": "Grab a fresh accessibility-tree snapshot of what the user is looking at (focused app, focused element, visible text, cursor position). Fast and precise for native text editors. Call this first when the user references 'this file', 'the function I'm looking at', 'this error', etc. If the returned text looks empty or unhelpful (e.g. Terminal, Preview, a non-native app), then call see_screen for a visual fallback.",
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "see_screen",
        "description": "Take a live screenshot of the user's screen and view it as an image. Use as a fallback when get_editor_context returns thin/empty text (Terminal output, image viewers, dialogs, non-native apps), or when the user asks about something visual (a chart, a design, error highlighting). More expensive than get_editor_context — prefer that first.",
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
]


TOOL_IMPL = {
    "read_file": read_file,
    "write_file": write_file,
    "apply_diff": apply_diff,
    "list_directory": list_directory,
    "run_shell": run_shell,
    "get_editor_context": get_editor_context,
    "see_screen": see_screen,
}


ToolResult = Union[str, List[Dict[str, Any]]]


async def execute_tool(name: str, arguments: dict) -> List[Dict[str, Any]]:
    """Execute a tool and always return a list of content blocks.

    String returns are wrapped as a single text block. Tools that need to
    return images (see_screen) return their own list of blocks directly.
    """
    fn = TOOL_IMPL.get(name)
    if not fn:
        return [{"type": "text", "text": f"ERROR: unknown tool {name}"}]
    try:
        result = await asyncio.get_event_loop().run_in_executor(
            None, lambda: fn(**arguments)
        )
    except Exception as e:
        return [{"type": "text", "text": f"TOOL ERROR ({name}): {e}"}]

    if isinstance(result, list):
        return result
    return [{"type": "text", "text": str(result)}]
