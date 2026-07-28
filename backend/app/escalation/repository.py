import uuid

from sqlalchemy import select

from app.channels.models import Channel
from app.conversations.models import Conversation
from app.core.repository import TenantScopedRepository
from app.escalation.models import Escalation, TenantTriggerPhrase


class EscalationRepository(TenantScopedRepository[Escalation]):
    model = Escalation

    async def list_with_channel_info(
        self, tenant_id: uuid.UUID
    ) -> list[tuple[Escalation, Channel]]:
        """Two-hop join (Escalation -> Conversation -> Channel) -- lets
        ChannelRail (frontend) show a per-channel-type pending-escalation
        badge instead of one tenant-wide count, now that Test Console
        channels mean more than one channel type can be live at once."""
        stmt = (
            select(Escalation, Channel)
            .join(Conversation, Conversation.id == Escalation.conversation_id)
            .join(Channel, Channel.id == Conversation.channel_id)
            .where(Escalation.tenant_id == tenant_id)
        )
        result = await self.session.execute(stmt)
        return [(row[0], row[1]) for row in result.all()]


class TenantTriggerPhraseRepository(TenantScopedRepository[TenantTriggerPhrase]):
    model = TenantTriggerPhrase
