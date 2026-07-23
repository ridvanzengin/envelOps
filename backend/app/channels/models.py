from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.core.models import TenantScopedMixin


class Channel(Base, TenantScopedMixin):
    __tablename__ = "channels"

    type: Mapped[str] = mapped_column(nullable=False)  # beeper | telegram
    external_account_id: Mapped[str] = mapped_column(nullable=False)
    status: Mapped[str] = mapped_column(nullable=False, default="connected")
