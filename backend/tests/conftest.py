from collections.abc import Iterator

import pytest

from app.core.config import settings


@pytest.fixture(autouse=True)
def _demo_mode_disabled_by_default() -> Iterator[None]:
    """The test suite must not depend on whatever settings.demo_mode_enabled
    happens to be in the developer's own real .env -- found live (2026-08-04):
    turning it on there to view the demo locally silently 403'd 57 unrelated
    tests that assume normal (non-demo) endpoint behavior. Forces it False
    before every test; tests/test_demo_mode.py and friends that actually
    need it True still patch settings.demo_mode_enabled explicitly within
    their own scope, which overrides this for their duration same as any
    other patch."""
    original = settings.demo_mode_enabled
    settings.demo_mode_enabled = False
    yield
    settings.demo_mode_enabled = original
