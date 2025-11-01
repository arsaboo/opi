from integrations.telegram import get_notifier
from status import notify


class BotFailedError(Exception):
    """Custom exception for bot failures."""
    pass


import os


def alert(asset, message, isError: bool = False):
    """Send an alert: logs to status + posts to Telegram if configured.

    - Always logs to console/UI via status.notify
    - Posts to Telegram when TELEGRAM_* env is configured
    - Raises BotFailedError if isError=True
    """
    level = "error" if isError else "info"

    # Sanitize message to prevent exposing sensitive information
    safe_message = _sanitize_message(str(message))
    
    # Log locally to console/UI
    if asset:
        try:
            notify(f"Asset: {asset}")
        except Exception:
            print(f"Asset: {asset}")

    try:
        notify(safe_message, level=level)
    except Exception:
        print(safe_message)

    # Send to Telegram if available, but avoid duplicate sends when
    # status.notify is already routing this level.
    try:
        route_levels = os.getenv("TELEGRAM_ROUTE_LEVELS", "error,warning").lower()
        route_set = {s.strip() for s in route_levels.split(',') if s.strip()}
        should_send_direct = level.lower() not in route_set

        if should_send_direct:
            notifier = get_notifier()
            if notifier is not None:
                parts = []
                if asset:
                    parts.append(f"<b>Asset:</b> {asset}")
                parts.append(safe_message)
                notifier.send("\n".join(parts), level=level)
    except Exception:
        # Best-effort; ignore notifier issues
        pass

    if isError:
        raise BotFailedError(safe_message)

def _sanitize_message(message: str) -> str:
    """Sanitize alert messages to prevent exposure of sensitive information."""
    # Remove potential environment variable values or API keys from messages
    # This is a basic implementation - could be enhanced based on specific needs
    sanitized = message
    
    # Remove potential API keys (typically have specific patterns)
    import re
    # Remove potential API keys that look like long alphanumeric strings
    sanitized = re.sub(r'[A-Z0-9]{20,}', '[REDACTED_API_KEY]', sanitized)
    
    # Remove potential tokens (generic pattern)
    sanitized = re.sub(r'token[^a-z\s][^,\s]+', '[REDACTED_TOKEN]', sanitized, flags=re.IGNORECASE)
    
    return sanitized


def botFailed(asset, message):
    return alert(asset, message, True)
