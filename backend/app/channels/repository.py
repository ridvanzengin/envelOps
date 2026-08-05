import uuid

from sqlalchemy import Select, select

from app.channels.models import Channel
from app.core.repository import TenantScopedRepository


def _build_demo_stream_channel_stmt(
    tenant_id: uuid.UUID, channel_type: str
) -> Select[tuple[Channel]]:
    """Split out from get_demo_stream_channel for testability -- lets a
    plain offline test compile this statement and inspect its SQL without
    a real database, same approach app/commerce/repository.py's
    _build_match_stmt already takes.

    is_test=False (so it shows up on the real Channels page, like a
    genuinely connected platform) -- but bot_token IS NULL is checked too,
    not just is_test: a real Telegram integration is *also* is_test=False,
    and reusing it here would make the demo DM streamer's fake inbound
    messages trigger a REAL send attempt through send_message() with a
    real bot_token, which must never happen."""
    return select(Channel).where(
        Channel.tenant_id == tenant_id,
        Channel.type == channel_type,
        Channel.is_test.is_(False),
        Channel.bot_token.is_(None),
    )


class ChannelRepository(TenantScopedRepository[Channel]):
    model = Channel

    async def get_by_id_unscoped(self, channel_id: uuid.UUID) -> Channel | None:
        """The one legitimate exception to "every query is tenant-scoped"
        (CLAUDE.md): a webhook entry point (app/channels/api.py) doesn't
        know the tenant yet -- channel_id in the URL path is how the
        tenant gets discovered in the first place. Every DB access after
        this point uses the returned channel's own tenant_id; this method
        exists only for that bootstrapping moment, not for general use."""
        return await self.session.scalar(select(Channel).where(Channel.id == channel_id))

    async def get_test_channel(
        self, tenant_id: uuid.UUID, channel_type: str
    ) -> Channel | None:
        """The Test Console's (app/test_console/api.py) one lookup per
        (tenant, type) -- at most one test channel ever exists per type,
        lazily created by the caller via the base .add() if this returns
        None."""
        stmt = select(Channel).where(
            Channel.tenant_id == tenant_id,
            Channel.type == channel_type,
            Channel.is_test.is_(True),
        )
        return await self.session.scalar(stmt)

    async def get_demo_stream_channel(
        self, tenant_id: uuid.UUID, channel_type: str
    ) -> Channel | None:
        """The demo DM streamer's own channel per (tenant, type) --
        app/pipeline/tasks.py's stream_demo_dm. Lazily created by the
        caller via .add() if this returns None, same pattern as
        get_test_channel above. See _build_demo_stream_channel_stmt's own
        docstring for why bot_token IS NULL matters here."""
        return await self.session.scalar(
            _build_demo_stream_channel_stmt(tenant_id, channel_type)
        )

    async def list_non_test(self, tenant_id: uuid.UUID) -> list[Channel]:
        """The Channels page's real channel list (2026-08-03) -- Test
        Console channels (is_test=True) are a separate, always-manual
        mechanism with their own UI and don't belong in a "manage your
        real channels" list. Filtered in the query itself, not
        post-filtered in Python, same reasoning as every other scoped
        query here."""
        stmt = select(Channel).where(
            Channel.tenant_id == tenant_id, Channel.is_test.is_(False)
        )
        result = await self.session.scalars(stmt)
        return list(result)
