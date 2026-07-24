from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.core.models import TenantScopedMixin


class Channel(Base, TenantScopedMixin):
    __tablename__ = "channels"

    type: Mapped[str] = mapped_column(nullable=False)  # beeper | telegram
    external_account_id: Mapped[str] = mapped_column(nullable=False)
    status: Mapped[str] = mapped_column(nullable=False, default="connected")

    # Telegram-specific for now (type == "telegram"); null for other channel
    # types. Stored in plaintext -- a real Phase 1 simplification, not a
    # considered security decision: no secrets-manager/encryption-at-rest
    # layer exists yet, and a leaked bot_token lets someone message this
    # tenant's real customers as them. Worth hardening before real DM
    # volume, not before synthetic testing.
    bot_token: Mapped[str | None] = mapped_column(nullable=True)
    # Compared against Telegram's X-Telegram-Bot-Api-Secret-Token header on
    # every webhook call -- the actual authenticity check (Telegram has no
    # request-signing scheme, just this shared secret set via setWebhook's
    # secret_token param). The channel_id in the webhook URL path routes to
    # the right tenant/channel; this is what proves the call really came
    # from Telegram, not just someone who guessed a UUID.
    webhook_secret: Mapped[str | None] = mapped_column(nullable=True)
