import uuid
from datetime import datetime

from sqlalchemy import select

from app.channels.models import Channel
from app.conversations.models import Conversation
from app.core.repository import TenantScopedRepository
from app.escalation.models import Escalation, TenantTriggerPhrase


class EscalationRepository(TenantScopedRepository[Escalation]):
    model = Escalation

    async def get_pending_by_conversation(
        self, tenant_id: uuid.UUID, conversation_id: uuid.UUID
    ) -> Escalation | None:
        """Only ever returns a *blocking* pending escalation (docs/ROADMAP.md
        §3.1) -- `blocks_pipeline=False` rows (book_or_checkout's missing-
        closing_link fallback) are a tenant-config nag, not a safety pause,
        and must never freeze a conversation's replies the way a real
        safety-floor escalation does."""
        stmt = select(Escalation).where(
            Escalation.tenant_id == tenant_id,
            Escalation.conversation_id == conversation_id,
            Escalation.status == "pending",
            Escalation.blocks_pipeline.is_(True),
        )
        return await self.session.scalar(stmt)

    async def list_with_channel_info(
        self,
        tenant_id: uuid.UUID,
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> list[tuple[Escalation, Channel]]:
        """Two-hop join (Escalation -> Conversation -> Channel) -- lets
        ChannelRail (frontend) show a per-channel-type pending-escalation
        badge instead of one tenant-wide count, now that Test Console
        channels mean more than one channel type can be live at once.

        start/end (both optional, default unfiltered -- the original
        behavior, still what GET /escalations wants) narrow to escalations
        *created* in [start, end) -- app/dashboard/service.py's per-channel
        resolution-rate breakdown."""
        stmt = (
            select(Escalation, Channel)
            .join(Conversation, Conversation.id == Escalation.conversation_id)
            .join(Channel, Channel.id == Conversation.channel_id)
            .where(Escalation.tenant_id == tenant_id)
        )
        if start is not None:
            stmt = stmt.where(Escalation.created_at >= start)
        if end is not None:
            stmt = stmt.where(Escalation.created_at < end)
        result = await self.session.execute(stmt)
        return [(row[0], row[1]) for row in result.all()]


class TenantTriggerPhraseRepository(TenantScopedRepository[TenantTriggerPhrase]):
    model = TenantTriggerPhrase
