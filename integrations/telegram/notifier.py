from __future__ import annotations

import asyncio
import os
import threading
from typing import Optional

from telegram import Bot
from telegram.constants import ParseMode


def _env_bool(name: str, default: bool = False) -> bool:
    val = os.getenv(name)
    if val is None:
        return default
    return str(val).strip().lower() in {"1", "true", "yes", "on"}


class TelegramNotifier:
    """Minimal async Telegram sender using python-telegram-bot.

    - Creates a background asyncio loop in a daemon thread
    - Submits send coroutines via run_coroutine_threadsafe
    - Never raises into caller; best-effort sending
    """

    def __init__(
        self,
        token: str,
        default_chat_id: int | str,
        *,
        parse_mode: str = "HTML",
        disable_notifications_default: bool = False,
    ) -> None:
        self.token = token
        self.default_chat_id = int(default_chat_id) if str(default_chat_id).lstrip("-").isdigit() else default_chat_id
        self.parse_mode = parse_mode
        self.disable_notifications_default = disable_notifications_default

        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._loop_thread: Optional[threading.Thread] = None
        self._loop_started = threading.Event()

        self._bot = Bot(token=self.token)

    # --- loop management ---
    def _ensure_loop(self) -> None:
        if self._loop is not None:
            return
        def _run_loop():
            try:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                self._loop = loop
                self._loop_started.set()
                loop.run_forever()
            finally:
                try:
                    if self._loop and not self._loop.is_closed():
                        self._loop.close()
                except Exception:
                    pass

        t = threading.Thread(target=_run_loop, name="telegram-notifier-loop", daemon=True)
        t.start()
        self._loop_thread = t
        self._loop_started.wait(timeout=5)

    def _submit(self, coro: "asyncio.Future | asyncio.coroutines") -> None:
        try:
            self._ensure_loop()
            if self._loop is None:
                return
            asyncio.run_coroutine_threadsafe(coro, self._loop)
        except Exception:
            # Best-effort; never propagate
            pass

    # --- public API ---
    def send(
        self,
        text: str,
        *,
        level: str = "info",
        chat_id: Optional[int | str] = None,
        disable_notification: Optional[bool] = None,
    ) -> None:
        """Queue a Telegram message to be sent."""
        if not text:
            return

        # Escape user content for HTML
        def _esc(s: str) -> str:
            return (
                s.replace("&", "&amp;")
                .replace("<", "&lt;")
                .replace(">", "&gt;")
            )
        safe_text = _esc(str(text))

        emoji = {
            "info": "ℹ️",
            "warning": "⚠️",
            "error": "❌",
        }.get(level, "ℹ️")

        header = {
            "info": "OPI Alert",
            "warning": "OPI Warning",
            "error": "OPI Error",
        }.get(level, "OPI Alert")

        body = f"{emoji} <b>{header}</b>\n{safe_text}"

        # Trim to Telegram message limit (~4096). Keep a safety margin.
        if len(body) > 4000:
            body = body[:3997] + "..."

        target_chat = chat_id or self.default_chat_id
        disable = self.disable_notifications_default if disable_notification is None else disable_notification

        # Normalize parse mode
        pm = None
        try:
            if isinstance(self.parse_mode, str):
                if self.parse_mode.upper() == "HTML":
                    pm = ParseMode.HTML
                elif self.parse_mode.lower() in {"markdown", "md"}:
                    pm = ParseMode.MARKDOWN
                elif self.parse_mode.lower() in {"markdownv2", "mdv2"}:
                    pm = ParseMode.MARKDOWN_V2
                else:
                    pm = None
            else:
                pm = self.parse_mode
        except Exception:
            pm = None

        async def _send():
            try:
                await self._bot.send_message(
                    chat_id=target_chat,
                    text=body,
                    parse_mode=pm,
                    disable_notification=bool(disable),
                )
            except Exception:
                # Best-effort; avoid raising into caller
                pass

        self._submit(_send())

    # --- helpers ---
    @staticmethod
    def from_env() -> Optional["TelegramNotifier"]:
        enabled = _env_bool("TELEGRAM_ENABLED", default=False)
        token = os.getenv("TELEGRAM_BOT_TOKEN")
        chat_id = os.getenv("TELEGRAM_DEFAULT_CHAT_ID")
        parse_mode = os.getenv("TELEGRAM_PARSE_MODE", "HTML")
        disable_notifications = _env_bool("TELEGRAM_DISABLE_NOTIFICATIONS", default=False)

        if not enabled or not token or not chat_id:
            return None
        try:
            return TelegramNotifier(
                token=token,
                default_chat_id=chat_id,
                parse_mode=parse_mode,
                disable_notifications_default=disable_notifications,
            )
        except Exception:
            return None


# Singleton accessor used by callers
_singleton: Optional[TelegramNotifier] = None


def get_notifier() -> Optional[TelegramNotifier]:
    global _singleton
    if _singleton is None:
        _singleton = TelegramNotifier.from_env()
    return _singleton
