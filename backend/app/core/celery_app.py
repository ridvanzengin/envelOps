from celery import Celery

from app.core.config import settings

celery_app = Celery("envelops", broker=settings.redis_url, backend=settings.redis_url)
celery_app.autodiscover_tasks(
    ["app.conversations", "app.knowledge", "app.channels", "app.pipeline"]
)

# follow_up_check (docs/ARCHITECTURE.md §4 step 8, app/pipeline/tasks.py)
# is the only periodic job so far -- runs on a fixed schedule via Celery
# Beat (`celery -A app.core.celery_app beat`, a separate process/container
# from the worker, see docker-compose.yml's `beat` service), not triggered
# per-message like process_incoming_message. The 30-minute scan interval
# is unrelated to settings.follow_up_delay_hours (how long a conversation
# must be quiet before it qualifies) -- this just controls how often the
# scan itself runs, and doesn't need to be that precise.
celery_app.conf.beat_schedule = {
    "follow-up-check": {
        "task": "follow_up_check",
        "schedule": 30 * 60,
    },
}
