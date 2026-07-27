from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.core.models import TenantScopedMixin


class User(Base, TenantScopedMixin):
    __tablename__ = "users"

    # Globally unique, not per-tenant: login is by email alone (no tenant
    # selector in the request), so two accounts sharing an email would be
    # ambiguous to resolve at login time — see UserRepository.get_by_email_unscoped.
    email: Mapped[str] = mapped_column(nullable=False, unique=True, index=True)
    hashed_password: Mapped[str] = mapped_column(nullable=False)
    role: Mapped[str] = mapped_column(nullable=False, default="owner")
