# syntax=docker/dockerfile:1
FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
# Cache mount, not --no-cache-dir -- pip's download cache persists across
# builds in BuildKit's own cache (never committed into an image layer, so
# it doesn't bloat image size the way leaving it in the final image
# would). Without this, any requirements.txt change invalidates this
# layer and pip had nothing to fall back on, re-downloading every
# package from PyPI again, not just the new/changed one -- a real
# bandwidth cost on a metered connection (CLAUDE.md).
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install -r requirements.txt

COPY app ./app
# Never needed before this image ran a real migration -- local/CI dev
# always runs alembic via the host venv (README's documented workflow),
# so this image never had to carry its own copy. The deploy/envelops
# `migrate` service (docker-compose.prod.yml) is the first thing to
# actually invoke `alembic upgrade head` from inside this image; without
# these two, alembic can't find its own config at all ("No
# 'script_location' key found in configuration", not a wrong-path error
# -- it silently falls back to an empty config when alembic.ini isn't
# where it expects, since alembic.ini's own script_location is relative
# to alembic.ini's location, not the invoking CWD).
COPY alembic.ini .
COPY alembic ./alembic
# Same reasoning as alembic above -- `python3 -m scripts.<name>` (README's
# documented invocation for seed_showcase_tenants.py and friends) had
# never been run from inside this image before deploying for real either.
# Without this, ModuleNotFoundError: No module named 'scripts'.
COPY scripts ./scripts

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
