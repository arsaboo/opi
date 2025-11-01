from __future__ import annotations

from queue import Queue
from datetime import datetime
import re
import os

from integrations.telegram import get_notifier

# Thread-safe queue for status messages destined for the TUI Status Log.
# Items are simple dicts with keys: time, level, message
# Bound the queue to avoid unbounded memory growth; drop oldest on overflow
status_queue: "Queue[dict]" = Queue(maxsize=1000)

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
    item = {
        "time": datetime.now(),
        "level": level,
        "message": str(message),
    }
    try:
        status_queue.put_nowait(item)
    except Exception:
        # Queue full: drop oldest and enqueue latest to keep UI fresh
        try:
            status_queue.get_nowait()
        except Exception:
            pass
        try:
            status_queue.put_nowait(item)
        except Exception:
            pass


def sanitize_exception_message(exc: Exception) -> str:
    """Create a concise, user-friendly message from an exception.

    - Strips MDN links commonly present in httpx HTTPStatusError messages
    - Extracts status codes when possible
    - Truncates overly long details
    - Sanitizes potential sensitive information
    """
    text = str(exc)

    # Remove MDN docs URL fragments like .../HTTP/Status/400
    text = re.sub(r"https?://developer\.mozilla\.org[^\s]+", "", text).strip()

    # Remove potential sensitive information (API keys, tokens, etc.)
    text = _sanitize_text_for_display(text)

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

def _sanitize_text_for_display(text: str) -> str:
    """Remove potential sensitive information from text before displaying."""
    import re
    
    # Remove potential API keys (generic pattern)
    text = re.sub(r'[A-Z0-9]{20,}', '[REDACTED]', text)
    
    # Remove potential tokens
    text = re.sub(r'token[^a-z\s][^,\s]+', '[REDACTED]', text, flags=re.IGNORECASE)
    
    # Remove potential credentials in URLs
    text = re.sub(r'://[^:]+:[^@]+@', '://[CREDENTIALS_REMOVED]@', text)
    
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

    # Optional: forward warnings/errors to Telegram if configured
    try:
        route_levels = os.getenv("TELEGRAM_ROUTE_LEVELS", "error,warning").lower()
        route_set = {s.strip() for s in route_levels.split(',') if s.strip()}
        if level.lower() in route_set:
            notifier = get_notifier()
            if notifier is not None:
                notifier.send(str(message), level=level)
    except Exception:
        # Never fail due to notifier issues
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
