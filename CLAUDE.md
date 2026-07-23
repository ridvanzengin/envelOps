# EnvelOps

AI-assisted DM-to-lead pipeline for small/mid-size businesses (health tourism
clinics, e-commerce sellers, service businesses). Inbound DMs across channels
go through a fixed pipeline: understand intent → ground in the business's own
knowledge → score the lead → decide next step → auto-send (gated by a hard
safety check) or escalate to a human.

**Full design docs live in [`docs/`](docs/) — read them before making
product or architecture decisions, don't rely on this file for that:**
- [`docs/REQUIREMENTS.md`](docs/REQUIREMENTS.md) — *what* and *why* (fixed
  reference, product-level)
- [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) — *how*, for Phase 1
  specifically (tech stack, data model, pipeline steps, API surface)

This file is deliberately short: day-to-day working conventions and things
that would otherwise need repeating every session. When architecture or
requirements change, edit the docs above, not this file.

---

## Environment: limited/metered connection

**The developer is frequently on a phone hotspot with limited data — assume
this every session, not just when told.** It changes how you should work:

- Don't run installs, pulls, or builds speculatively "just to check" — batch
  dependency changes into one install rather than iterating one-package-at-a-
  time.
- Before any command that pulls meaningfully large data (`docker compose
  pull`, `docker build` on a fresh base image, `pip install` / `npm install`
  on a clean environment, cloning a new repo, downloading model weights),
  say what it will fetch and confirm rather than firing it off — cost/time on
  a hotspot is real, not a formality.
- Avoid WebSearch/WebFetch unless the task genuinely needs current external
  information; prefer local docs, code, and existing knowledge first.
- Once dependencies are installed, prefer offline-friendly reruns (cached
  installs, `--no-audit`/`--prefer-offline` equivalents) over fresh resolves.
- If a command times out or stalls, consider a flaky connection before
  assuming a code bug.

**One-time wifi install pass already happened (2026-07-23)** — see Commands
below for exactly what's installed. Don't re-run installs "to be safe" on a
hotspot session; check whether the thing you need is already there first.
New dependencies still need the same install-while-on-wifi discipline going
forward — this pass doesn't cover anything added after it.

## Working conventions

- Domain-module structure per module: `api.py` / `service.py` /
  `repository.py` / `models.py` (see `docs/ARCHITECTURE.md` §1). Keep new
  code inside this pattern rather than introducing a different layering.
- Pydantic models are the single canonical schema — reused across
  API/DB/pipeline state, not redefined per layer.
- Every table and every query gets `tenant_id` scoping. There is no
  code path that reads or writes tenant data without it — see
  `docs/ARCHITECTURE.md` §2.
- No draft-and-approve queue in Phase 1. The pipeline auto-sends; the only
  pause point is the safety-check escalation gate. Don't reintroduce a
  general approval queue without checking `docs/ARCHITECTURE.md` §5 first.
- Turkish + English are both Phase 1, not "English now, i18n later" — the
  pilot tenant's customers DM in Turkish. Generation/intent prompts should
  detect-and-match the incoming message's language, not assume English; any
  embedding provider choice needs real cross-lingual retrieval, not just
  Turkish support. See `docs/ARCHITECTURE.md` §7.
- LLM/embedding provider is Gemini (free tier), both through
  `app.core.llm` (`generate_text` / `embed_text`) — pipeline nodes and
  knowledge ingestion should call that module, not the `google-genai` SDK
  directly, so swapping providers later stays contained. Two caveats to
  keep in mind, not yet resolved: free-tier rate limits against a pipeline
  that makes up to 3 LLM calls per inbound message, and free-tier
  data-usage terms should be checked before routing real customer
  conversations through it (REQUIREMENTS §12 stage 2), not just synthetic
  testing (stage 1).

## Commands

### Backend (`backend/`)

A venv exists at `backend/.venv` with `requirements.txt` +
`requirements-dev.txt` already installed (FastAPI, SQLAlchemy, LangGraph,
Celery, pytest, ruff, mypy, ...). Activate it: `cd backend && source
.venv/bin/activate`. Adding a *new* package still needs the wifi-install
discipline above; the existing set doesn't need reinstalling.

- Full stack (Postgres+pgvector, Redis, API, Celery worker): `docker
  compose up` from repo root — images are already pulled/built locally, so
  this doesn't re-fetch anything on a hotspot
- API only, without Docker: `cd backend && source .venv/bin/activate &&
  uvicorn app.main:app --reload`
- Celery worker, without Docker: `celery -A app.core.celery_app worker
  --loglevel=info`
- Health check once running: `curl localhost:8000/healthz`
- Lint: `ruff check app/ tests/` — Format-on-save equivalent: `ruff format`
  (not yet run repo-wide, safe to use)
- Type-check: `mypy app/`
- Tests: `python -m pytest -q` (pytest is installed now; the older stdlib
  `python3 -m unittest discover -s tests -v` still works with zero installs
  if pytest ever isn't available)
- Migrations: `alembic revision --autogenerate -m "..."` then `alembic
  upgrade head` — needs a reachable Postgres (`docker compose up -d db`).
  Two migrations exist (initial schema; embedding dim 1536→768 for
  Gemini), both applied, both downgrade→upgrade round-trip verified.

**Alembic autogenerate gotcha, hit twice now — check for it every time a
migration touches a `Vector(...)` column:** the generated file references
`pgvector.sqlalchemy.vector.VECTOR(...)` but autogenerate doesn't add the
`import pgvector.sqlalchemy` line for it — add it by hand or the migration
fails at import time. A `render_item` hook in `alembic/env.py` would fix
this at the root; hasn't been worth it for two migrations, reconsider if a
third hits the same thing.

**Docker networking gotcha already hit and fixed once — don't reintroduce
it:** `.env`/`.env.example` use `localhost` for `ENVELOPS_DATABASE_URL`/
`ENVELOPS_REDIS_URL`, which is correct for host/venv dev but wrong inside
the compose network (containers reach each other by service name). The
`backend`/`worker` services in `docker-compose.yml` have explicit
`environment:` overrides (`db`/`redis` instead of `localhost`) for exactly
this reason — if you add a new env var that needs different values in each
context, follow the same pattern rather than editing `.env` itself.

**`config.py` gotcha already hit and fixed once:** `env_file` must be an
absolute path (`Path(__file__).resolve().parents[3] / ".env"`), not the
bare string `".env"` — pydantic-settings resolves a relative path against
cwd, so running the app from `backend/` (the documented no-Docker path)
silently loaded an empty config before this fix. Docker never hit this
since compose injects real env vars directly, bypassing the file lookup.

`ENVELOPS_GEMINI_API_KEY` is set in `.env` now, and `core/llm.py` is
confirmed correct as far as auth/wiring go — the smoke test reaches
Google's servers and gets a real structured response back. But every
model tried (`gemini-2.5-flash`, `gemini-2.0-flash`, `gemini-2.0-flash-lite`)
returns `generate_content_free_tier_requests, limit: 0` — not a rate
limit, a hard zero quota grant for this API key/project. This is an
account/project-level thing on Google's side (free tier not enabled for
this project, regional eligibility, or a billing-link requirement — unclear
which without checking https://aistudio.google.com/apikey directly), not a
code bug. `embed_text` hasn't been tested at all yet since generation was
already blocked the same way — don't assume it works until this is
resolved and it's actually been called.

Test coverage so far: `escalation/safety_gate.py` (Layer 1 safety floor,
Turkish + English patterns, with regression tests for real false positives
found in the honey-seller domain — "şişe" (bottle) vs. "şiş" (swollen),
"garanti"/"guarantee" needing an efficacy word alongside it so shipping/
warranty language doesn't trip it; also covers the tenant-added
trigger-phrase layer, additive-only, plain substring match), `auth/
security.py` (PBKDF2 password hashing), `knowledge/chunking.py`
(chunk-with-overlap for embedding).

### Frontend (`frontend/`)

Vite + React + TypeScript, `node_modules` already installed. Includes
`react-router-dom` (routing between the five §10 screens) and
`react-i18next` + `i18next-browser-languagedetector` (English/Turkish, per
§7) — both wired up already: `App.tsx` has the nav/routes, `src/i18n/`
has the locale files and config, each page under `src/pages/` is a
translated placeholder, not yet the real screen content.

- `npm run dev` — dev server (verified boots and serves)
- `npm run build` — type-check (`tsc -b`) + production build (verified
  clean)
- `npm run lint` — oxlint (verified clean)
