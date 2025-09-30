"""Lightweight API package init.

Avoid importing heavy dependencies (e.g., requests/pytz/schwab) at import time
so submodules like `api.streaming.subscription_manager` can be imported in
isolation for tests.
"""

__all__ = ["Api", "OptionChain"]

def __getattr__(name):
    if name == "Api":
        from .client import Api  # type: ignore
        return Api
    if name == "OptionChain":
        from .option_chain import OptionChain  # type: ignore
        return OptionChain
    raise AttributeError(name)
