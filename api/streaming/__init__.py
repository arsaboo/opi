"""Lightweight streaming package init.

Avoid importing the streaming provider (which depends on `schwab`) at import time
so tests can import `api.streaming.subscription_manager` without the `schwab`
package installed.
"""

__all__ = [
    "StreamingQuoteProvider",
    "ensure_provider",
    "get_provider",
    "get_subscription_manager",
]

def __getattr__(name):
    if name in {"StreamingQuoteProvider", "ensure_provider", "get_provider"}:
        from .provider import StreamingQuoteProvider, ensure_provider, get_provider  # type: ignore
        return {"StreamingQuoteProvider": StreamingQuoteProvider, "ensure_provider": ensure_provider, "get_provider": get_provider}[name]
    if name == "get_subscription_manager":
        from .subscription_manager import get_subscription_manager  # type: ignore
        return get_subscription_manager
    raise AttributeError(name)
