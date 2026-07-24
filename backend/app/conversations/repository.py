import uuid

from sqlalchemy import select

from app.conversations.models import Conversation, Message
from app.core.repository import TenantScopedRepository


class ConversationRepository(TenantScopedRepository[Conversation]):
    model = Conversation

    async def get_by_external_contact(
        self, tenant_id: uuid.UUID, channel_id: uuid.UUID, external_contact_id: str
    ) -> Conversation | None:
        stmt = select(Conversation).where(
            Conversation.tenant_id == tenant_id,
            Conversation.channel_id == channel_id,
            Conversation.external_contact_id == external_contact_id,
        )
        return await self.session.scalar(stmt)


class MessageRepository(TenantScopedRepository[Message]):
    model = Message
