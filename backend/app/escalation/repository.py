from app.core.repository import TenantScopedRepository
from app.escalation.models import Escalation, TenantTriggerPhrase


class EscalationRepository(TenantScopedRepository[Escalation]):
    model = Escalation


class TenantTriggerPhraseRepository(TenantScopedRepository[TenantTriggerPhrase]):
    model = TenantTriggerPhrase
