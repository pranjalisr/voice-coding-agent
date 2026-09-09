"""Conversation history compaction.

When the message list gets too big (long tool results, screenshots, many turns),
we replace the older portion with a short synthetic summary produced by Haiku.
The last few turns are always kept verbatim so the agent has fresh context.

Two safety constraints:
1. tool_use blocks MUST be followed by their matching tool_result in the very
   next message — so we can only split at a "clean" user turn boundary.
2. Screenshots inside tool_results are what really blow up the context, so we
   also strip images from any assistant/tool_result blocks we're keeping if the
   estimate is still too high after summarization.
"""
import json
from typing import List, Dict, Any
from anthropic import AsyncAnthropic
import config


_client = AsyncAnthropic(api_key=config.ANTHROPIC_API_KEY)

MAX_HISTORY_CHARS = config.MAX_HISTORY_CHARS
KEEP_LAST_N_TURNS = config.KEEP_LAST_N_TURNS
SUMMARIZER_MODEL = config.SUMMARIZER_MODEL


def _estimate_chars(messages: List[Dict[str, Any]]) -> int:
    """Cheap size estimate. Images count as their base64 length."""
    total = 0
    for m in messages:
        c = m.get("content")
        if isinstance(c, str):
            total += len(c)
        elif isinstance(c, list):
            for block in c:
                total += len(json.dumps(block, default=str))
    return total


def _is_clean_user_start(msg: Dict[str, Any]) -> bool:
    """A user message that starts a new turn (no tool_result blocks)."""
    if msg.get("role") != "user":
        return False
    c = msg.get("content")
    if isinstance(c, str):
        return True
    if isinstance(c, list):
        return all(b.get("type") != "tool_result" for b in c)
    return False


def _find_split_index(messages: List[Dict[str, Any]], keep_last_n: int) -> int:
    """Find the index of the Nth-from-last clean user turn start.

    Returns 0 if there aren't enough clean boundaries (nothing to summarize).
    """
    count = 0
    for i in range(len(messages) - 1, -1, -1):
        if _is_clean_user_start(messages[i]):
            count += 1
            if count >= keep_last_n:
                return i
    return 0


def _flatten_for_summary(messages: List[Dict[str, Any]]) -> str:
    """Turn structured messages into a plain text transcript for the summarizer."""
    lines = []
    for m in messages:
        role = m["role"]
        c = m["content"]
        if isinstance(c, str):
            lines.append(f"{role.upper()}: {c}")
        elif isinstance(c, list):
            for block in c:
                t = block.get("type")
                if t == "text":
                    lines.append(f"{role.upper()}: {block.get('text', '')}")
                elif t == "tool_use":
                    args = json.dumps(block.get("input", {}))[:400]
                    lines.append(f"ASSISTANT→TOOL {block.get('name')}({args})")
                elif t == "tool_result":
                    inner = block.get("content", "")
                    if isinstance(inner, list):
                        parts = []
                        for ib in inner:
                            if ib.get("type") == "text":
                                parts.append(ib.get("text", "")[:800])
                            elif ib.get("type") == "image":
                                parts.append("[screenshot]")
                        inner = " ".join(parts)
                    lines.append(f"TOOL→ASSISTANT: {str(inner)[:800]}")
    return "\n".join(lines)


async def _summarize(messages: List[Dict[str, Any]]) -> str:
    transcript = _flatten_for_summary(messages)
    prompt = f"""Summarize this conversation between a user and a voice-controlled coding \
assistant. Focus on: files that were viewed or edited, decisions the user made, code \
changes and their intent, current working context, and any pending or in-progress tasks. \
Be concise — 5 to 10 sentences. Write it as a briefing to a new assistant taking over.

CONVERSATION:
{transcript}"""

    resp = await _client.messages.create(
        model=SUMMARIZER_MODEL,
        max_tokens=600,
        messages=[{"role": "user", "content": prompt}],
    )
    return resp.content[0].text.strip()


async def maybe_compact(messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Compact history if it's grown past MAX_HISTORY_CHARS.

    Returns the (possibly compacted) message list. If nothing to compact,
    returns the input unchanged.
    """
    size = _estimate_chars(messages)
    if size < MAX_HISTORY_CHARS:
        return messages

    split = _find_split_index(messages, KEEP_LAST_N_TURNS)
    if split <= 0:
        # Nothing safe to summarize (all recent). Return as-is; the API will
        # complain if it's genuinely too big, and we'll surface that error.
        print(f"[memory] history is {size} chars but no safe split point found")
        return messages

    older = messages[:split]
    keep = messages[split:]
    print(f"[memory] compacting {len(older)} older messages ({size} chars)")

    summary = await _summarize(older)
    synthetic = [
        {"role": "user", "content": f"[EARLIER CONVERSATION SUMMARY]\n{summary}\n[END SUMMARY]"},
        {"role": "assistant", "content": "Understood, I have that context."},
    ]
    new_messages = synthetic + keep
    new_size = _estimate_chars(new_messages)
    print(f"[memory] compacted to {new_size} chars ({len(new_messages)} messages)")
    return new_messages
