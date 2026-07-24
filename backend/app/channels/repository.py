import uuid

from sqlalchemy import select

from app.channels.models import Channel
from app.core.repository import TenantScopedRepository


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
