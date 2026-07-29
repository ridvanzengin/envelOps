import redis.asyncio as async_redis

from app.core.config import settings

# Lazy singleton, safe only because this is used exclusively inside the
# FastAPI process's one long-lived event loop (docs/ROADMAP.md §3.5's SSE
# stream endpoint) -- app/core/events.py's publish_event() deliberately
# does NOT reuse this, since it's also called from the Celery worker,
# which runs each task under a fresh asyncio.run() event loop; a client
# bound to a previous, now-closed loop would break there.
_client: async_redis.Redis | None = None


def get_async_redis_client() -> async_redis.Redis:
    global _client
    if _client is None:
        _client = async_redis.from_url(settings.redis_url)
    return _client
