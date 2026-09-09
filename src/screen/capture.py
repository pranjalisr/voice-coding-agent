"""Screen capture (macOS) via mss.

Detects which physical display contains the focused app's window and
captures from that one — so screenshotting works correctly on multi-monitor
setups where your editor is on the second screen.
"""
import base64
import hashlib
import io
import mss
from PIL import Image
import config


_last_hash = None


def _focused_display_index() -> int:
    """Find which mss monitor index contains the focused app.

    Returns 1 (primary) if detection fails.
    """
    try:
        from Quartz import (
            CGWindowListCopyWindowInfo,
            kCGWindowListOptionOnScreenOnly,
            kCGNullWindowID,
        )
        from AppKit import NSWorkspace

        front = NSWorkspace.sharedWorkspace().frontmostApplication()
        if not front:
            return 1
        target_pid = front.processIdentifier()

        windows = CGWindowListCopyWindowInfo(
            kCGWindowListOptionOnScreenOnly, kCGNullWindowID
        )
        for w in windows:
            if w.get("kCGWindowOwnerPID") != target_pid:
                continue
            bounds = w.get("kCGWindowBounds") or {}
            if not bounds:
                continue
            cx = bounds.get("X", 0) + bounds.get("Width", 0) / 2
            cy = bounds.get("Y", 0) + bounds.get("Height", 0) / 2
            with mss.mss() as sct:
                for i, mon in enumerate(sct.monitors[1:], start=1):
                    if (mon["left"] <= cx < mon["left"] + mon["width"]
                            and mon["top"] <= cy < mon["top"] + mon["height"]):
                        return i
            break
    except Exception as e:
        if config.DEBUG:
            print(f"[screen] display detection failed: {e}")
    return 1


def _hash(png_bytes: bytes) -> str:
    return hashlib.md5(png_bytes).hexdigest()


def grab_screen_b64(force: bool = False):
    """Return (base64_png, changed_bool). changed=False if identical to last grab."""
    global _last_hash
    display_idx = _focused_display_index()
    with mss.mss() as sct:
        monitor = sct.monitors[display_idx]
        raw = sct.grab(monitor)
        img = Image.frombytes("RGB", raw.size, raw.rgb)

        if img.width > config.SCREENSHOT_MAX_WIDTH:
            ratio = config.SCREENSHOT_MAX_WIDTH / img.width
            new_size = (config.SCREENSHOT_MAX_WIDTH, int(img.height * ratio))
            img = img.resize(new_size, Image.LANCZOS)

        buf = io.BytesIO()
        img.save(buf, format="PNG", optimize=True)
        png = buf.getvalue()

    h = _hash(png)
    changed = h != _last_hash
    _last_hash = h

    if not changed and not force:
        return None, False

    return base64.b64encode(png).decode(), True
