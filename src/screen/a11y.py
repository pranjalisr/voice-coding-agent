"""macOS accessibility-tree extraction.

Requires the running terminal / IDE to have Accessibility permission granted
in System Settings > Privacy & Security > Accessibility.

Returns a compact JSON-serializable dict describing the focused app + focused
element, walked one level of children for context. Fast enough to call per turn.
"""
from typing import Any, Dict, Optional
import json

try:
    from ApplicationServices import (
        AXUIElementCreateSystemWide,
        AXUIElementCopyAttributeValue,
        AXUIElementCopyAttributeNames,
        kAXFocusedApplicationAttribute,
        kAXFocusedUIElementAttribute,
        kAXRoleAttribute,
        kAXTitleAttribute,
        kAXValueAttribute,
        kAXSelectedTextAttribute,
        kAXSelectedTextRangeAttribute,
        kAXNumberOfCharactersAttribute,
        kAXChildrenAttribute,
    )
    from AppKit import NSWorkspace
    MAC_AVAILABLE = True
except ImportError:
    MAC_AVAILABLE = False


MAX_TEXT_CHARS = 4000  # trim gigantic buffers before sending to Claude


def _get(element, attr: str) -> Optional[Any]:
    if element is None:
        return None
    try:
        err, val = AXUIElementCopyAttributeValue(element, attr, None)
        if err == 0:
            return val
    except Exception:
        return None
    return None


def _text_of(element) -> Optional[str]:
    if element is None:
        return None
    val = _get(element, kAXValueAttribute)
    if isinstance(val, str):
        return val
    return None


def _basic_info(element) -> Dict[str, Any]:
    if element is None:
        return {}
    info = {}
    role = _get(element, kAXRoleAttribute)
    title = _get(element, kAXTitleAttribute)
    if role:
        info["role"] = str(role)
    if title:
        info["title"] = str(title)
    text = _text_of(element)
    if text:
        if len(text) > MAX_TEXT_CHARS:
            text = text[: MAX_TEXT_CHARS // 2] + "\n...[TRUNCATED]...\n" + text[-MAX_TEXT_CHARS // 2 :]
        info["text"] = text
    sel = _get(element, kAXSelectedTextAttribute)
    if sel:
        info["selected_text"] = str(sel)[:1000]
    sel_range = _get(element, kAXSelectedTextRangeAttribute)
    if sel_range is not None:
        try:
            info["cursor_range"] = {"loc": sel_range.location, "len": sel_range.length}
        except Exception:
            pass
    return info


def snapshot() -> Dict[str, Any]:
    """Grab a focused-app + focused-element snapshot."""
    if not MAC_AVAILABLE:
        return {"error": "macOS accessibility APIs unavailable"}

    try:
        ws = NSWorkspace.sharedWorkspace()
        front = ws.frontmostApplication()
        app_name = str(front.localizedName()) if front else None
        bundle_id = str(front.bundleIdentifier()) if front else None
    except Exception as e:
        app_name = None
        bundle_id = None

    result: Dict[str, Any] = {
        "app_name": app_name,
        "bundle_id": bundle_id,
    }

    try:
        system = AXUIElementCreateSystemWide()
        focused_app = _get(system, kAXFocusedApplicationAttribute)
        focused_el = _get(focused_app, kAXFocusedUIElementAttribute) if focused_app else None
        if focused_app:
            result["app_title"] = _get(focused_app, kAXTitleAttribute)
        if focused_el:
            result["focused_element"] = _basic_info(focused_el)
        else:
            result["focused_element"] = None
    except Exception as e:
        result["error"] = f"a11y error: {e}"

    return result


def snapshot_text() -> str:
    """Human-readable summary for use in a prompt."""
    snap = snapshot()
    if snap.get("error"):
        return f"[screen unavailable: {snap['error']}]"
    lines = []
    lines.append(f"App: {snap.get('app_name')} ({snap.get('bundle_id')})")
    if snap.get("app_title"):
        lines.append(f"Window: {snap['app_title']}")
    fe = snap.get("focused_element") or {}
    if fe:
        lines.append(f"Focused: role={fe.get('role')} title={fe.get('title')}")
        if fe.get("selected_text"):
            lines.append(f"Selected: {fe['selected_text'][:300]}")
        if fe.get("text"):
            lines.append("--- Visible text ---")
            lines.append(fe["text"])
    return "\n".join(lines)


if __name__ == "__main__":
    print(snapshot_text())
