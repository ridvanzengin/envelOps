from app.channels.models import Channel
from app.core.repository import TenantScopedRepository


class ChannelRepository(TenantScopedRepository[Channel]):
    model = Channel
