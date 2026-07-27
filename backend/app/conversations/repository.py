import uuid
from datetime import datetime

from sqlalchemy import func, select

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

    async def list_quiet_unscoped(self, cutoff: datetime) -> list[Conversation]:
        """Cross-tenant by design -- follow_up_check (docs/ARCHITECTURE.md
        §4 step 8) is a periodic background job with no per-request tenant
        context, unlike every other query in this codebase; it has to scan
        across all tenants to find quiet conversations, then acts within
        whichever tenant_id each matched row already carries. Same
        reasoning as ChannelRepository.get_by_id_unscoped and
        UserRepository.get_by_email_unscoped -- named to make the exception
        obvious, not something to reach for elsewhere.

        "Quiet" = open, never followed up yet, and the conversation's most
        recent message is outbound and older than `cutoff`.
        """
        latest_message_at = (
            select(func.max(Message.created_at))
            .where(Message.conversation_id == Conversation.id)
            .correlate(Conversation)
            .scalar_subquery()
        )
        stmt = (
            select(Conversation)
            .join(Message, Message.conversation_id == Conversation.id)
            .where(
                Conversation.status == "open",
                Conversation.followed_up_at.is_(None),
                Message.created_at == latest_message_at,
                Message.direction == "outbound",
                Message.created_at < cutoff,
            )
        )
        result = await self.session.scalars(stmt)
        return list(result)


class MessageRepository(TenantScopedRepository[Message]):
    model = Message

    async def get_latest(
        self, tenant_id: uuid.UUID, conversation_id: uuid.UUID
    ) -> Message | None:
        stmt = (
            select(Message)
            .where(Message.tenant_id == tenant_id, Message.conversation_id == conversation_id)
            .order_by(Message.created_at.desc())
            .limit(1)
        )
        return await self.session.scalar(stmt)
