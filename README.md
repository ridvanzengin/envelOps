# EnvelOps

AI-assisted DM-to-lead pipeline for small/mid-size businesses selling over
social DMs. Turns inbound messages into a grounded, lead-scored, safety-gated
conversation pipeline instead of an unmanaged inbox.

Working name — pre-launch, Phase 1 in active development.

## Docs

- [`docs/REQUIREMENTS.md`](docs/REQUIREMENTS.md) — what's being built and why
- [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) — how, for Phase 1
  (tech stack, data model, pipeline, API surface)
- [`docs/ROADMAP.md`](docs/ROADMAP.md) — current status and what's next
- [`CLAUDE.md`](CLAUDE.md) — working conventions for developing this repo
  with Claude Code

## Status

Core pipeline, tenant-isolated data model, auto-send with a hard safety
gate, static knowledge sources, and a Telegram channel are built and
tested (synthetic + live Test Console). See
[`docs/ROADMAP.md`](docs/ROADMAP.md) for current status, open bugs, and
what's next.
