"""Importing this module registers every model on Base.metadata — the single
place Alembic (and any create_all script) looks to see the full schema."""

from app.auth import models as _auth_models  # noqa: F401
from app.channels import models as _channels_models  # noqa: F401
from app.conversations import models as _conversations_models  # noqa: F401
from app.core.db import Base
from app.escalation import models as _escalation_models  # noqa: F401
from app.knowledge import models as _knowledge_models  # noqa: F401
from app.leads import models as _leads_models  # noqa: F401
from app.pipeline import models as _pipeline_models  # noqa: F401
from app.tenants import models as _tenants_models  # noqa: F401

metadata = Base.metadata
