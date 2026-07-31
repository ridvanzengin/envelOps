import uuid
from datetime import datetime

from sqlalchemy import func, select

from app.channels.models import Channel
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

    async def list_with_last_message(
        self, tenant_id: uuid.UUID, channel_type: str | None = None
    ) -> list[tuple[Conversation, Message | None, Channel]]:
        """Inbox list view -- one query, not list-then-fetch-per-conversation,
        same reasoning as KnowledgeSourceRepository.list_with_chunk_counts.
        Outer join on Message: a conversation with no messages yet (shouldn't
        happen in practice -- every conversation is created alongside its
        first inbound message, ARCHITECTURE §8) still shows up, just with a
        null preview, rather than silently disappearing from the list. Inner
        join on Channel: every conversation has exactly one, unlike Message.

        channel_type filters to one platform's conversations (ChannelRail/
        ConversationPanel, one rail icon at a time) -- optional so callers
        that genuinely want everything (none currently do, kept for
        parity with how this looked before multiple channel types existed)
        still can.
        """
        latest_message_at = (
            select(func.max(Message.created_at))
            .where(Message.conversation_id == Conversation.id)
            .correlate(Conversation)
            .scalar_subquery()
        )
        stmt = (
            select(Conversation, Message, Channel)
            .join(Channel, Channel.id == Conversation.channel_id)
            .outerjoin(
                Message,
                (Message.conversation_id == Conversation.id)
                & (Message.created_at == latest_message_at),
            )
            .where(Conversation.tenant_id == tenant_id)
            .order_by(Message.created_at.desc())
        )
        if channel_type is not None:
            stmt = stmt.where(Channel.type == channel_type)
        result = await self.session.execute(stmt)
        return [(row[0], row[1], row[2]) for row in result.all()]

    async def list_in_range_with_channel(
        self, tenant_id: uuid.UUID, start: datetime, end: datetime
    ) -> list[tuple[Conversation, Channel]]:
        """Dashboard aggregates (app/dashboard/service.py) -- conversations
        created in [start, end), joined to their channel for the per-channel
        breakdown. Inner join on Channel is safe here (unlike
        list_with_last_message's outer join on Message above): every
        conversation always has exactly one channel."""
        stmt = (
            select(Conversation, Channel)
            .join(Channel, Channel.id == Conversation.channel_id)
            .where(
                Conversation.tenant_id == tenant_id,
                Conversation.created_at >= start,
                Conversation.created_at < end,
            )
        )
        result = await self.session.execute(stmt)
        return [(row[0], row[1]) for row in result.all()]


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

    async def list_by_conversation(
        self, tenant_id: uuid.UUID, conversation_id: uuid.UUID
    ) -> list[Message]:
        stmt = (
            select(Message)
            .where(Message.tenant_id == tenant_id, Message.conversation_id == conversation_id)
            .order_by(Message.created_at.asc())
        )
        result = await self.session.scalars(stmt)
        return list(result)

    async def list_in_range(
        self, tenant_id: uuid.UUID, start: datetime, end: datetime
    ) -> list[Message]:
        """Dashboard aggregates (app/dashboard/service.py) -- messages sent
        in [start, end) across every conversation, used for the outbound-
        count stat tile and the inbound->outbound response-time estimate.
        Not scoped to one conversation, unlike list_by_conversation above."""
        stmt = select(Message).where(
            Message.tenant_id == tenant_id,
            Message.created_at >= start,
            Message.created_at < end,
        )
        result = await self.session.scalars(stmt)
        return list(result)
