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
