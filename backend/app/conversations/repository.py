from app.conversations.models import Conversation, Message
from app.core.repository import TenantScopedRepository


class ConversationRepository(TenantScopedRepository[Conversation]):
    model = Conversation


class MessageRepository(TenantScopedRepository[Message]):
    model = Message
