import uuid

from sqlalchemy import select

from app.auth.models import User
from app.core.repository import TenantScopedRepository


class UserRepository(TenantScopedRepository[User]):
    model = User

    async def get_by_email_unscoped(self, email: str) -> User | None:
        """Login doesn't know the tenant yet — the email is how the tenant
        gets discovered, same reasoning as ChannelRepository.get_by_id_unscoped
        (CLAUDE.md's tenant-scoping section). Not something to reach for
        elsewhere: every other user lookup should go through the scoped
        `get`/`list` methods."""
        stmt = select(User).where(User.email == email)
        return await self.session.scalar(stmt)

    async def get_by_id_unscoped(self, user_id: uuid.UUID) -> User | None:
        """Demo mode's tenant switcher (docs/ROADMAP.md, app/auth/api.py's
        POST /auth/demo-login) -- the caller has a user id from
        GET /auth/demo-tenants but, like login, no tenant to scope by yet.
        Gated at the API layer by settings.demo_mode_enabled, not here;
        not something to reach for outside that one caller."""
        stmt = select(User).where(User.id == user_id)
        return await self.session.scalar(stmt)
