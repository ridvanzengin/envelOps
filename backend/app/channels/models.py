from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.core.models import TenantScopedMixin


class Channel(Base, TenantScopedMixin):
    __tablename__ = "channels"

    type: Mapped[str] = mapped_column(nullable=False)  # beeper | telegram
    external_account_id: Mapped[str] = mapped_column(nullable=False)
    status: Mapped[str] = mapped_column(nullable=False, default="connected")
    # Test Console channels (app/test_console/api.py) -- one per (tenant,
    # type), lazily created on first test message. Lets a conversation's
    # real-vs-test status be derived transitively (Conversation.channel_id
    # -> Channel.is_test) rather than duplicated onto Conversation/Lead/
    # Escalation rows.
    #
    # Three distinct is_test/bot_token combinations exist, not two:
    # Telegram (is_test=False, real bot_token) is the one real integration;
    # a simulated Instagram/WhatsApp/Facebook/Email channel
    # (scripts/register_simulated_channel.py) is also is_test=False but
    # bot_token=None -- a real-shaped, genuinely inbound-DM-flowing
    # conversation, just never actually sent anywhere (app/pipeline/
    # tasks.py's own `if channel.bot_token:` guard already no-ops the
    # send); Test Console channels are the only is_test=True case.
    is_test: Mapped[bool] = mapped_column(nullable=False, default=False)

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
    # Real on/off switch (Channels page, 2026-08-03) -- the pipeline still
    # runs in full either way (intent/lead-score/escalation keep getting
    # computed and logged); this only gates whether the resulting reply
    # actually becomes a customer-facing outbound Message
    # (app/pipeline/tasks.py's _process_incoming_message), and whether
    # the periodic follow-up job (_send_follow_up) sends its nudge.
    # Deliberately a separate field from `status` above, not a new value
    # of it -- `status` is reserved for connection health (currently
    # unread anywhere in the codebase), a different concern from "should
    # the AI reply here."
    ai_enabled: Mapped[bool] = mapped_column(nullable=False, default=True)
