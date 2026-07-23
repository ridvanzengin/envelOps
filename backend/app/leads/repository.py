from app.core.repository import TenantScopedRepository
from app.leads.models import Lead


class LeadRepository(TenantScopedRepository[Lead]):
    model = Lead
