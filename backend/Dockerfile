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

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
