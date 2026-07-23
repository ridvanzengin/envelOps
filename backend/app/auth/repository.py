from app.auth.models import User
from app.core.repository import TenantScopedRepository


class UserRepository(TenantScopedRepository[User]):
    model = User
