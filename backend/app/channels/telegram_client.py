"""Thin wrapper around Telegram's Bot API — plain HTTP/JSON via httpx,
deliberately not the python-telegram-bot SDK. That SDK's polling/dispatcher
machinery is built for a long-running bot process; we're webhook-based
(receive one POST, respond once), so a raw client is both a better fit and
avoids a heavy dependency neither pattern actually needs.
"""

import httpx
from pydantic import BaseModel

_API_BASE = "https://api.telegram.org"


class TelegramChat(BaseModel):
    id: int


class TelegramMessage(BaseModel):
    chat: TelegramChat
    text: str | None = None


class TelegramUpdate(BaseModel):
    """Only the fields we actually read — Telegram's real Update object has
    many more (edited_message, callback_query, photo, ...). Phase 1 only
    handles plain text messages; everything else comes through as
    `message=None` or `message.text=None` and gets ignored, not rejected."""

    update_id: int
    message: TelegramMessage | None = None


async def send_message(bot_token: str, chat_id: str, text: str) -> None:
    url = f"{_API_BASE}/bot{bot_token}/sendMessage"
    async with httpx.AsyncClient() as client:
        response = await client.post(
            url, json={"chat_id": chat_id, "text": text}, timeout=10.0
        )
        response.raise_for_status()


async def set_webhook(bot_token: str, webhook_url: str, secret_token: str) -> None:
    """Registers our webhook URL with Telegram — a one-time setup call
    (scripts/register_telegram_channel.py), not something that runs on
    every message."""
    url = f"{_API_BASE}/bot{bot_token}/setWebhook"
    async with httpx.AsyncClient() as client:
        response = await client.post(
            url,
            json={"url": webhook_url, "secret_token": secret_token},
            timeout=10.0,
        )
        response.raise_for_status()


async def get_me(bot_token: str) -> dict[str, object]:
    """The bot's own identity (id, username, ...) — used once at channel
    setup time to populate Channel.external_account_id with something real
    rather than a placeholder, and doubles as a token-validity check
    before registering a webhook with a token that might be wrong."""
    url = f"{_API_BASE}/bot{bot_token}/getMe"
    async with httpx.AsyncClient() as client:
        response = await client.get(url, timeout=10.0)
        response.raise_for_status()
        result: dict[str, object] = response.json()["result"]
        return result
