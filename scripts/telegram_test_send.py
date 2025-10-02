import argparse
import sys
from typing import Optional
from pathlib import Path
import time

from dotenv import load_dotenv
from os import getenv

# Ensure project root is on sys.path so 'integrations' can be imported when running this file directly
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from integrations.telegram import get_notifier

try:
    from telegram import Bot
except Exception as e:
    Bot = None  # type: ignore


def list_chats(token: str) -> int:
    if Bot is None:
        print("python-telegram-bot is not installed. Please install requirements.")
        return 2
    import asyncio
    async def _run() -> int:
        try:
            bot = Bot(token=token)
            updates = await bot.get_updates(timeout=10)
            if not updates:
                print("No updates found. Send a message to your bot (or in a group with the bot) and rerun.")
                return 0
            printed = set()
            for u in updates:
                m = u.message or u.edited_message or u.channel_post or u.edited_channel_post
                if not m:
                    continue
                chat = m.chat
                key = (chat.id, chat.type)
                if key in printed:
                    continue
                printed.add(key)
                print(
                    f"chat_id: {chat.id} | type: {chat.type} | title: {getattr(chat, 'title', None)} | username: {getattr(chat, 'username', None)}"
                )
            return 0
        except Exception as e:
            print(f"Failed to list chats: {e}")
            return 1
    return asyncio.run(_run())


def send_test(text: str, level: str, chat_id: Optional[str], wait_seconds: float = 1.0) -> int:
    n = get_notifier()
    if not n:
        from pathlib import Path
        enabled = getenv("TELEGRAM_ENABLED")
        token = getenv("TELEGRAM_BOT_TOKEN")
        cid = getenv("TELEGRAM_DEFAULT_CHAT_ID")
        env_path = Path(ROOT, ".env")
        print("Telegram not configured. Ensure TELEGRAM_ENABLED=true, TELEGRAM_BOT_TOKEN, and TELEGRAM_DEFAULT_CHAT_ID in .env")
        print(f"CWD: {Path.cwd()}")
        print(f".env found at {env_path}: {env_path.exists()}")
        print(f"TELEGRAM_ENABLED={enabled}")
        print(f"TELEGRAM_BOT_TOKEN set={bool(token)} length={len(token) if token else 0}")
        print(f"TELEGRAM_DEFAULT_CHAT_ID={cid}")
        return 2
    try:
        n.send(text, level=level, chat_id=chat_id)
        # Give background loop a brief moment (daemon thread) before process exits
        time.sleep(max(0.0, wait_seconds))
        print(f"Sent test message (level={level})")
        return 0
    except Exception as e:
        print(f"Failed to send test message: {e}")
        return 1


def main() -> int:
    parser = argparse.ArgumentParser(description="Test Telegram notifications")
    sub = parser.add_subparsers(dest="cmd")

    s_list = sub.add_parser("list", help="List chat IDs from recent updates (after you message the bot)")

    s_delwh = sub.add_parser("delete-webhook", help="Delete webhook (enables getUpdates for listing chat IDs)")

    s_send = sub.add_parser("send", help="Send a test message")
    s_send.add_argument("--text", default="Test message from OPI bot", help="Message text")
    s_send.add_argument("--level", default="info", choices=["info", "warning", "error"], help="Message level")
    s_send.add_argument("--chat-id", default=None, help="Override chat id (otherwise uses TELEGRAM_DEFAULT_CHAT_ID)")
    s_send.add_argument("--wait", type=float, default=1.0, help="Seconds to wait before exit (allow async send)")

    args = parser.parse_args()

    load_dotenv()

    if args.cmd == "list":
        token = getenv("TELEGRAM_BOT_TOKEN")
        if not token:
            print("Missing TELEGRAM_BOT_TOKEN in .env")
            return 2
        return list_chats(token)

    if args.cmd == "delete-webhook":
        token = getenv("TELEGRAM_BOT_TOKEN")
        if not token:
            print("Missing TELEGRAM_BOT_TOKEN in .env")
            return 2
        if Bot is None:
            print("python-telegram-bot is not installed. Please install requirements.")
"""
Telegram notification test helper
---------------------------------

Usage examples:

1) Discover chat IDs (after you send a message to your bot or a group with your bot):
   python scripts/telegram_test_send.py list

   If you see "No updates found":
   - Open Telegram, DM your bot and send "hi" (or in a group, mention the bot or send /start@YourBot)
   - If a webhook is configured, delete it then retry:
     python scripts/telegram_test_send.py delete-webhook

2) Send a test message (uses TELEGRAM_DEFAULT_CHAT_ID from .env, or override):
   python scripts/telegram_test_send.py send --text "Hello" --level warning
   python scripts/telegram_test_send.py send --text "Hello" --level warning --chat-id -100123...

Requires .env with TELEGRAM_BOT_TOKEN. For send, also set TELEGRAM_ENABLED=true
and TELEGRAM_DEFAULT_CHAT_ID (unless you pass --chat-id).
"""

            return 2
        import asyncio
        async def _run() -> int:
            try:
                bot = Bot(token=token)
                ok = await bot.delete_webhook(drop_pending_updates=False)
                print(f"delete_webhook: {ok}")
                return 0
            except Exception as e:
                print(f"Failed to delete webhook: {e}")
                return 1
        return asyncio.run(_run())

    if args.cmd == "send":
        return send_test(args.text, args.level, args.chat_id, args.wait)

    parser.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
