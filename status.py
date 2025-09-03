from __future__ import annotations

from queue import Queue, Empty
from datetime import datetime
import re

# Thread-safe queue for status messages destined for the TUI Status Log.
# Items are simple dicts with keys: time, level, message
status_queue: "Queue[dict]" = Queue()

# Indicates whether the Textual UI has been mounted.
_ui_active: bool = False


def set_ui_active(active: bool = True) -> None:
    global _ui_active
    _ui_active = bool(active)


def publish(message: str, level: str = "info") -> None:
    """Publish a message to the global status queue.

    Safe to call from any thread or non-UI code. The Textual UI drains this
    queue periodically and renders messages in the Status Log widget.
    """
    try:
        status_queue.put_nowait({
            "time": datetime.now(),
            "level": level,
            "message": str(message),
        })
    except Exception:
        # Never raise from a logging pathway
        pass


def sanitize_exception_message(exc: Exception) -> str:
    """Create a concise, user-friendly message from an exception.

    - Strips MDN links commonly present in httpx HTTPStatusError messages
    - Extracts status codes when possible
    - Truncates overly long details
    """
    text = str(exc)

    # Remove MDN docs URL fragments like .../HTTP/Status/400
    text = re.sub(r"https?://developer\.mozilla\.org[^\s]+", "", text).strip()

    # Try to surface an HTTP status code if present
    m = re.search(r"\b(\d{3})\b", text)
    if m and m.group(1) in {"400", "401", "403", "404", "408", "429", "500", "502", "503", "504"}:
        code = m.group(1)
        # Prefer a compact standard phrase
        phrases = {
            "400": "Bad Request",
            "401": "Unauthorized",
            "403": "Forbidden",
            "404": "Not Found",
            "408": "Request Timeout",
            "429": "Too Many Requests",
            "500": "Internal Server Error",
            "502": "Bad Gateway",
            "503": "Service Unavailable",
            "504": "Gateway Timeout",
        }
        phrase = phrases.get(code, "HTTP Error")
        # Remove noisy prefixes like "Client error" messages
        text = re.sub(r"^.*?error.*?:\s*", "", text, flags=re.IGNORECASE)
        text = text.strip(" -:")
        base = f"HTTP {code} {phrase}"
        if text and code not in text:
            text = f"{base}: {text}"
        else:
            text = base

    # Truncate very long messages to keep the status bar readable
    if len(text) > 220:
        text = text[:217] + "..."

    return text


def publish_exception(exc: Exception, *, prefix: str | None = None, level: str = "error") -> None:
    """Publish a sanitized exception message to the status queue."""
    msg = sanitize_exception_message(exc)
    if prefix:
        msg = f"{prefix}: {msg}"
    publish(msg, level=level)


def notify(message: str, level: str = "info") -> None:
    """User-facing message: prints before UI; routes to Status Log after UI."""
    if _ui_active:
        publish(message, level=level)
    else:
        try:
            print(message)
        except Exception:
            pass


def notify_exception(exc: Exception, *, prefix: str | None = None, level: str = "error") -> None:
    if _ui_active:
        publish_exception(exc, prefix=prefix, level=level)
    else:
        # Keep CLI output compact before UI starts
        msg = sanitize_exception_message(exc)
        if prefix:
            msg = f"{prefix}: {msg}"
        try:
            print(msg)
        except Exception:
            pass
