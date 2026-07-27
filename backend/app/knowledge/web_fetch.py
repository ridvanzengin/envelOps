"""Thin httpx wrapper for crawling a knowledge-source URL (REQUIREMENTS.md
§5) — same "plain HTTP client, not a heavier SDK" reasoning as
app/channels/telegram_client.py, just for an arbitrary business site
instead of Telegram's API.
"""

import httpx


async def fetch_url(url: str) -> str:
    async with httpx.AsyncClient() as client:
        response = await client.get(url, timeout=10.0, follow_redirects=True)
        response.raise_for_status()
        return response.text
