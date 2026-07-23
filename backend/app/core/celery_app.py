from celery import Celery

from app.core.config import settings

celery_app = Celery("envelops", broker=settings.redis_url, backend=settings.redis_url)
celery_app.autodiscover_tasks(
    ["app.conversations", "app.knowledge", "app.channels"]
)
