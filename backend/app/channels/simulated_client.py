"""Payload shapes for the simulated channel webhooks (Instagram, WhatsApp,
Facebook, Email) -- app/channels/api.py's real counterparts, minus any
outbound HTTP functions, since there's no real platform to call. This
project deliberately simulates these integrations rather than building
real ones against Meta's Messaging Platform / a real email inbox: the
showcase here is the pipeline/behavior-orchestration layer, not
third-party API integration work (see app/commerce/connectors.py's
docstring for the same reasoning applied to commerce data).

Deliberately flattened one level below each platform's real webhook
envelope -- e.g. skipping Meta's entry[]/changes[]/value[] wrapper -- just
enough to be recognizably platform-shaped, not full fidelity."""

from pydantic import BaseModel, Field


class MetaSender(BaseModel):
    id: str


class MetaMessage(BaseModel):
    text: str | None = None


class MetaMessagingEvent(BaseModel):
    """Shared by Instagram DMs and Facebook Messenger -- both genuinely
    run on Meta's Messenger Platform with near-identical webhook payload
    shapes in production, so reusing one model for both is intentional,
    not a shortcut."""

    sender: MetaSender
    message: MetaMessage | None = None


class WhatsAppTextBody(BaseModel):
    body: str


class WhatsAppMessage(BaseModel):
    from_: str = Field(alias="from")  # `from` is a Python keyword
    text: WhatsAppTextBody | None = None

    model_config = {"populate_by_name": True}


class EmailWebhookPayload(BaseModel):
    from_address: str
    subject: str | None = None
    text: str
