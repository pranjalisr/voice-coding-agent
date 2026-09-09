"""Agent orchestration — streaming version.

Yields text chunks as Claude generates them, so the TTS pipeline can start
speaking before the full response is done. Cuts perceived latency from
~2s (wait for full response then start TTS) to ~500ms (first sentence).

Emits typed events:
    ("text", str)             — a complete sentence, ready to speak
    ("done", history: list)   — turn finished, updated history
"""
import re
from typing import List, Dict, Any, AsyncIterator, Tuple
from anthropic import AsyncAnthropic
import config
from src.agent.tools import TOOL_SCHEMAS, execute_tool
from src.agent.prompts import build_system_prompt
from src.agent.memory import maybe_compact

_SYSTEM_PROMPT = None  # built once on first turn


def _get_system_prompt() -> str:
    global _SYSTEM_PROMPT
    if _SYSTEM_PROMPT is None:
        _SYSTEM_PROMPT = build_system_prompt()
        print(f"[agent] workspace tree injected ({len(_SYSTEM_PROMPT)} chars)")
    return _SYSTEM_PROMPT


_client = AsyncAnthropic(api_key=config.ANTHROPIC_API_KEY)

SENT_RE = re.compile(r'[.!?]+["\')\]]?\s+|\n\n+')


def _drain_sentences(buf: str) -> Tuple[List[str], str]:
    """Return complete sentences and the remaining unfinished tail."""
    chunks = []
    while True:
        m = SENT_RE.search(buf)
        if not m:
            break
        end = m.end()
        chunk = buf[:end].strip()
        if chunk:
            chunks.append(chunk)
        buf = buf[end:]
    return chunks, buf


async def _stream_once(messages):
    """One Claude call. Yields ('text', sentence) then ('final', message)."""
    async with _client.messages.stream(
        model=config.CLAUDE_MODEL,
        max_tokens=1024,
        system=_get_system_prompt(),
        tools=TOOL_SCHEMAS,
        messages=messages,
    ) as stream:
        buf = ""
        async for text in stream.text_stream:
            buf += text
            chunks, buf = _drain_sentences(buf)
            for c in chunks:
                yield ("text", c)
        if buf.strip():
            yield ("text", buf.strip())
        final = await stream.get_final_message()
        yield ("final", final)


def _clean_history(messages):
    """Remove orphaned tool_use blocks (no matching tool_result after them).

    Happens when a turn is cancelled mid-tool-call via barge-in — the
    tool_use gets appended to history but the tool_result never arrives,
    causing a 400 from the API on the next turn.
    """
    cleaned = list(messages)
    while cleaned:
        last = cleaned[-1]
        if last["role"] != "assistant":
            break
        content = last.get("content", [])
        if not isinstance(content, list):
            break
        has_tool_use = any(
            isinstance(b, dict) and b.get("type") == "tool_use"
            for b in content
        )
        if not has_tool_use:
            break
        # Orphaned tool_use — drop it
        cleaned.pop()
    return cleaned


async def run_turn_streaming(
    history: List[Dict[str, Any]], user_text: str
) -> AsyncIterator[Tuple[str, Any]]:
    """Run a turn, streaming text chunks + tool loop.

    Yields ('text', sentence) as Claude produces them, then ('done', history)
    when the whole turn (including all tool iterations) is complete.
    """
    history = await maybe_compact(list(history))
    history = _clean_history(history)
    history = history + [{"role": "user", "content": user_text}]
    max_turns = 6

    while max_turns > 0:
        max_turns -= 1
        final = None
        async for kind, payload in _stream_once(history):
            if kind == "text":
                yield ("text", payload)
            elif kind == "final":
                final = payload

        assistant_content = []
        tool_uses = []
        for block in final.content:
            if block.type == "text":
                assistant_content.append({"type": "text", "text": block.text})
            elif block.type == "tool_use":
                assistant_content.append({
                    "type": "tool_use", "id": block.id,
                    "name": block.name, "input": block.input,
                })
                tool_uses.append(block)
        history.append({"role": "assistant", "content": assistant_content})

        if final.stop_reason == "tool_use" and tool_uses:
            tool_results = []
            for tu in tool_uses:
                blocks = await execute_tool(tu.name, tu.input)
                preview = next(
                    (b["text"] for b in blocks if b.get("type") == "text"), "[image]"
                )
                print(f"[tool] {tu.name}({list(tu.input.keys())}) -> {preview[:100]}...")
                tool_results.append({
                    "type": "tool_result", "tool_use_id": tu.id, "content": blocks,
                })
            history.append({"role": "user", "content": tool_results})
            continue
        break

    yield ("done", history)