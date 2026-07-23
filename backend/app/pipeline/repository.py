from app.core.repository import TenantScopedRepository
from app.pipeline.models import PipelineTrace


class PipelineTraceRepository(TenantScopedRepository[PipelineTrace]):
    model = PipelineTrace
