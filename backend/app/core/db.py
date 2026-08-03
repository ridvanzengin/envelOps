from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.pool import NullPool

from app.core.config import settings


class Base(DeclarativeBase):
    pass


engine = create_async_engine(settings.database_url)
async_session = async_sessionmaker(engine, expire_on_commit=False)

# Celery worker tasks (app/pipeline/tasks.py) each wrap their body in a
# fresh asyncio.run() call, once per task -- a new event loop every time,
# reused across many task invocations in the same long-running worker
# process. A connection checked out of `engine`'s pool above is a real
# asyncpg connection bound to whichever loop was running when it was first
# opened; handed to a later task's new loop, asyncpg raises "Future
# attached to a different loop" (found live 2026-08-03, reproduced and
# fixed here -- see CLAUDE.md). NullPool sidesteps this by never reusing a
# raw connection across checkouts -- opens and closes a real one per
# session instead, the same "accept per-call connect overhead to stay
# loop-safe" tradeoff app/core/events.py's publish_event() already makes
# for Redis. Kept as a separate engine rather than applied to `engine`
# above so FastAPI's request handlers (uvicorn's one long-lived loop,
# where reuse is safe and worth keeping) aren't affected.
worker_engine = create_async_engine(settings.database_url, poolclass=NullPool)
worker_async_session = async_sessionmaker(worker_engine, expire_on_commit=False)


async def get_session() -> AsyncIterator[AsyncSession]:
    async with async_session() as session:
        yield session
