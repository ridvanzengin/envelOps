from celery import Celery

from app.core.config import settings

celery_app = Celery("envelops", broker=settings.redis_url, backend=settings.redis_url)
celery_app.autodiscover_tasks(
    ["app.conversations", "app.knowledge", "app.channels", "app.pipeline"]
)

# follow_up_check (docs/ARCHITECTURE.md §4 step 8, app/pipeline/tasks.py)
# runs on a fixed schedule via Celery Beat (`celery -A app.core.celery_app
# beat`, a separate process/container from the worker, see
# docker-compose.yml's `beat` service), not triggered per-message like
# process_incoming_message. The 30-minute scan interval is unrelated to
# settings.follow_up_delay_hours (how long a conversation must be quiet
# before it qualifies) -- this just controls how often the scan itself
# runs, and doesn't need to be that precise.
#
# stream_demo_dm/purge_stale_demo_data (also app/pipeline/tasks.py) are
# the demo-mode-only counterparts (docs/ROADMAP.md) -- both no-op
# immediately unless settings.demo_mode_enabled is True, checked first
# thing in each task, not here. stream_demo_dm ticks hourly and paces
# itself against a 10-15/day target internally (see its own docstring for
# why hourly, not something coarser); purge_stale_demo_data only needs
# day-level precision for a 7-day retention window, so once a day is
# plenty.
celery_app.conf.beat_schedule = {
    "follow-up-check": {
        "task": "follow_up_check",
        "schedule": 30 * 60,
    },
    "stream-demo-dm": {
        "task": "stream_demo_dm",
        "schedule": 60 * 60,
    },
    "purge-stale-demo-data": {
        "task": "purge_stale_demo_data",
        "schedule": 24 * 60 * 60,
    },
}
