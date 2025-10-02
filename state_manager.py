import json
import os
from datetime import datetime, timezone
from typing import Iterable, List


CURRENT_VERSION = 1


def _repo_root() -> str:
    # This file lives at repo root; use its directory
    return os.path.dirname(os.path.abspath(__file__))


def state_file_path(account_id: str | int) -> str:
    """Return absolute path to state file for account."""
    return os.path.join(_repo_root(), f"state-{account_id}.json")


def _normalize_symbols(symbols: Iterable[str]) -> List[str]:
    out = []
    seen = set()
    for s in symbols:
        if not s:
            continue
        s2 = str(s).strip()
        if not s2:
            continue
        # Normalize to uppercase for consistency
        s2 = s2.upper()
        if s2 not in seen:
            seen.add(s2)
            out.append(s2)
    return out


def load_symbols(account_id: str | int) -> List[str]:
    """Load tracked symbols for account. On missing/corrupt, start fresh.

    Returns a normalized, deduplicated list. If JSON is corrupt, delete file.
    """
    p = state_file_path(account_id)
    if not os.path.exists(p):
        return []
    try:
        with open(p, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        syms = data.get("symbols", []) if isinstance(data, dict) else []
        return _normalize_symbols(syms)
    except Exception:
        # Corrupt or unreadable; delete and start fresh
        try:
            os.remove(p)
        except Exception:
            pass
        return []


def save_symbols(account_id: str | int, symbols: Iterable[str]) -> None:
    """Atomically save current tracked symbols for account."""
    p = state_file_path(account_id)
    tmp = f"{p}.tmp"
    os.makedirs(os.path.dirname(p), exist_ok=True)
    payload = {
        "version": CURRENT_VERSION,
        "updatedAt": datetime.now(timezone.utc).isoformat(),
        "symbols": _normalize_symbols(symbols),
    }
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, separators=(",", ":"))
    # Replace atomically if possible
    try:
        os.replace(tmp, p)
    except Exception:
        # Best-effort fallback
        try:
            os.remove(p)
        except Exception:
            pass
        os.rename(tmp, p)

