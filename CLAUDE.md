# EnvelOps

A demonstration of AI assistant behavior orchestration, safety gating, and
per-tenant configuration. Inbound DMs across channels go through a fixed
pipeline: understand intent → ground in the business's own knowledge (plus
real Gemini tool-calling for live-data-style questions) → score the lead →
decide next step → auto-send (gated by a hard safety check) or escalate to
a human.

**Originally scoped to ship to a real small-business pilot (a friend's
honey business); that pilot is now deprioritized (decided 2026-07-31).**
This is now a solo portfolio project — see `docs/ROADMAP.md` for the full
scope-cut decision and reasoning. Concretely, as of that decision:
- Only **Telegram** is a real channel integration. Instagram/WhatsApp/
  Facebook/Email are **simulated** (`app/channels/simulated_client.py`) —
  same real pipeline, a webhook-shaped entry point, no real platform ever
  contacted.
- Order-status/inventory lookup use **real** Gemini tool-calling (the model
  genuinely decides whether to call a tool) backed by **fake**,
  deterministic connectors (`app/commerce/`), not a real Shopify/
  WooCommerce integration.
- **Turkish/bilingual pipeline support has been cut** — see the Working
  conventions section below.

**Full design docs live in [`docs/`](docs/) — read them before making
product or architecture decisions, don't rely on this file for that:**
- [`docs/REQUIREMENTS.md`](docs/REQUIREMENTS.md) — *what* and *why* (fixed
  reference, product-level)
- [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) — *how*, for Phase 1
  specifically (tech stack, data model, pipeline steps, API surface)
- [`docs/ROADMAP.md`](docs/ROADMAP.md) — *what's next*: current status,
  open bugs, and scoped-but-unbuilt feature work. This one changes every
  session — check it before assuming REQUIREMENTS/ARCHITECTURE's own
  "open items" sections are current, since ROADMAP.md is now the single
  place that gets updated live.

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
  `docs/ARCHITECTURE.md` §2. One deliberate, narrow exception:
  `ChannelRepository.get_by_id_unscoped` — a webhook entry point (§8)
  doesn't know the tenant yet, the channel_id in the URL is how it gets
  discovered. Named to make the exception obvious, not something to
  reach for elsewhere.
- No draft-and-approve queue in Phase 1. The pipeline auto-sends; the only
  pause point is the safety-check escalation gate. Don't reintroduce a
  general approval queue without checking `docs/ARCHITECTURE.md` §5 first.
- **Turkish/bilingual pipeline support is cut, not deferred** (decided
  2026-07-31 — REQUIREMENTS §11, ARCHITECTURE §7 both marked cut).
  Generation/intent prompts no longer instruct the model to detect-and-
  match the incoming message's language; replies are effectively always
  whatever language the model defaults to (English), regardless of input
  language. This was a real, recurring bug source (language-consistency
  issues found live more than once) and stopped being needed once the
  real Turkish-speaking pilot was deprioritized. **Follow-up, same day:
  `escalation/safety_gate.py`'s own Turkish safety-term detection
  patterns were also removed** — originally kept as "a different concern
  from reply-language-matching," but on direct instruction the project is
  now English-only end to end, not English-only-except-one-still-bilingual-
  safety-module. Tenant-added trigger phrases (plain substring match) are
  unaffected — a business owner can still add a non-English phrase, that
  mechanism was never language-specific to begin with. Frontend i18n
  (`react-i18next`, `en.json`/`tr.json`) is untouched — inert, isolated,
  wasn't the source of the problem, not worth the churn to rip out, and
  explicitly out of scope for this backend-only cleanup.
- LLM/embedding provider is Gemini (free tier), both through
  `app.core.llm` (`generate_text` / `embed_text` / `generate_with_tools`,
  the last one added 2026-07-31 for real tool-calling) — pipeline nodes
  and knowledge ingestion should call that module, not the `google-genai`
  SDK directly, so swapping providers later stays contained. Free-tier
  rate limits are a real, unresolved constraint against a pipeline that
  makes up to 4 sequential LLM calls per inbound message needing grounding
  (`understand_intent` → `score_lead` → `call_tools`'s
  `generate_with_tools`, only when the tenant has a fake tool enabled →
  `keep_chatting`) — not yet a problem since there's no real customer
  traffic (the pilot that would have generated it is deprioritized), but
  worth remembering if that ever changes.

## Commands

### Backend (`backend/`)

A venv exists at `backend/.venv` with `requirements.txt` +
`requirements-dev.txt` already installed (FastAPI, SQLAlchemy, LangGraph,
Celery, pytest, ruff, mypy, ...). Activate it: `cd backend && source
.venv/bin/activate`. Adding a *new* package still needs the wifi-install
discipline above; the existing set doesn't need reinstalling.

**`backend/Dockerfile`'s pip install uses a BuildKit cache mount, not
`--no-cache-dir`** (found and fixed 2026-07-29, checked while on wifi
specifically to verify before relying on it off wifi): without this,
adding one package to `requirements.txt` invalidated the whole layer and
pip had no local cache to fall back on, re-downloading every package
from PyPI again, not just the new one — a real cost on a metered
connection. Verified directly: an unrelated one-line `requirements.txt`
touch that forces a layer-cache miss now shows `Using cached ...whl` for
every package, zero `Downloading` lines, and finishes in ~20s instead of
~60s. `backend/.dockerignore` also now excludes `.venv`/cache dirs from
the build context (not a network cost, just wasted local transfer, but
free to fix alongside). Applies to `backend`/`worker`/`beat` alike since
all three share this one Dockerfile.

- Full stack (Postgres+pgvector, Redis, API, Celery worker): `docker
  compose up` from repo root — images are already pulled/built locally, so
  this doesn't re-fetch anything on a hotspot
- API only, without Docker: `cd backend && source .venv/bin/activate &&
  uvicorn app.main:app --reload`
- Celery worker, without Docker: `celery -A app.core.celery_app worker
  --loglevel=info`
- Celery beat (periodic jobs — currently just `follow_up_check`, every 30
  minutes), without Docker: `celery -A app.core.celery_app beat
  --loglevel=info` — a separate process from the worker above, both need
  to be running for `follow_up_check` to actually fire. `docker compose
  up` starts both (`worker` + `beat` services) already.
- Health check once running: `curl localhost:8000/healthz`
- Connecting a real Telegram channel: create a tenant (no API for this
  yet — insert directly or via a script), get a bot token from
  @BotFather, expose the local server publicly (ngrok/cloudflared —
  Telegram needs a real HTTPS URL, localhost doesn't work), then `cd
  backend && source .venv/bin/activate && python3 -m
  scripts.register_telegram_channel --tenant-id <uuid> --bot-token
  <token> --webhook-base-url <your tunnel URL>`. Creates the `Channel`
  row and calls Telegram's `setWebhook` — validates the token via
  `getMe` first, so a typo surfaces immediately, not as silent failures
  later. Not yet tested against a real Telegram round-trip — everything
  up to and including the actual `sendMessage` call is verified for real
  (including a genuine delivery failure with a fake token, handled
  gracefully), but no real bot token has been used end-to-end yet.
- Registering a simulated channel (Instagram/WhatsApp/Facebook/Email —
  decided 2026-07-31, see `docs/ROADMAP.md`): `cd backend && source
  .venv/bin/activate && python3 -m scripts.register_simulated_channel
  --tenant-id <uuid> --channel-type instagram|whatsapp|facebook|email`.
  No real API calls — there's nothing real to call — just creates a
  `Channel` row (`is_test=False`, no `bot_token`) and prints the webhook
  path + secret header value for sending test payloads directly (see the
  script's own docstring for a worked `curl` example).
- One-tenant-at-a-time calibration seeding (the current primary way new
  tenant configs get exercised — decided 2026-07-31): `cd backend &&
  source .venv/bin/activate && python3 -m scripts.seed_calibration_tenant`
  — seeds whatever `TenantSpec`s are in `CALIBRATION_TENANTS` (skips ones
  already seeded, matched by login email) and runs ~28 real Bitext-sampled
  customer-support DMs through the real pipeline per new tenant. Two
  tenants exist so far: Wildroot Apparel Co (Telegram) and Voltage Gadgets
  (Instagram, the first tenant with tool-calling enabled).
- Synthetic conversation validation: `docker compose up -d db` + real
  `ENVELOPS_GEMINI_API_KEY`, then `python3 -m
  scripts.run_synthetic_conversations` from `backend/` — takes ~3 minutes
  (8 messages, English only since the Turkish cut — see below — 20s apart
  to stay under the 15 req/min free-tier cap, see `core/llm.py`). Leaves
  real rows in the DB tagged "Synthetic Test — Honey
  Co" for inspection; doesn't clean up after itself. Originally
  REQUIREMENTS §12 stage 1's pilot-validation gate; that framing no
  longer applies now the pilot is deprioritized, but the script itself is
  still a real, usable smoke test. First full run found two real quality
  gaps (language-inconsistent intent classification, a Turkish-only
  pricing hallucination) — both fixed and re-verified via a second full
  run at the time (prompt-only fixes in `app/pipeline/graph.py`'s
  `understand_intent`/`keep_chatting`). A related language-consistency bug
  in `keep_chatting`'s disclaimer path was later found via Test Console
  usage; **resolved by the Turkish cut above, not by a targeted fix** —
  there's no more language-matching instruction left to be inconsistent.
- Lint: `ruff check app/ tests/ scripts/` — Format-on-save equivalent:
  `ruff format` (not yet run repo-wide, safe to use)
- Type-check: `mypy app/ scripts/`
- Tests: `python -m pytest -q` (pytest is installed now; the older stdlib
  `python3 -m unittest discover -s tests -v` still works with zero installs
  if pytest ever isn't available)
- Migrations: `alembic revision --autogenerate -m "..."` then `alembic
  upgrade head` — needs a reachable Postgres (`docker compose up -d db`).
  Seven migrations exist (initial schema; embedding dim 1536→768 for
  Gemini; tenant closing_action; tenant closing_link; channel telegram
  fields; users.email unique; conversation followed_up_at), all applied,
  all downgrade→upgrade round-trip verified.
- LangGraph's own checkpoint tables (`checkpoints`, `checkpoint_blobs`,
  `checkpoint_writes` — the safety-gate pause/resume state, ARCHITECTURE
  §5) are **not** Alembic-managed. `app/pipeline/runner.get_checkpointer()`
  calls `AsyncPostgresSaver.setup()` itself (idempotent) instead — a
  deliberately separate schema-management path from our own domain tables,
  since these belong to LangGraph, not to our data model.

**Alembic autogenerate gotcha, hit twice now — check for it every time a
migration touches a `Vector(...)` column:** the generated file references
`pgvector.sqlalchemy.vector.VECTOR(...)` but autogenerate doesn't add the
`import pgvector.sqlalchemy` line for it — add it by hand or the migration
fails at import time. A `render_item` hook in `alembic/env.py` would fix
this at the root; hasn't been worth it for two migrations, reconsider if a
third hits the same thing.

**Alembic autogenerate gotcha #2 — check for it any time you run
autogenerate in a dev DB that's had the checkpointer's `.setup()` called
against it:** the `checkpoint*` tables aren't in our SQLAlchemy metadata by
design (they're LangGraph's own, not Alembic-managed — see the checkpointer
bullet above), so autogenerate sees them as "removed" and will generate
`DROP TABLE`/`DROP INDEX` ops for all four of them. Strip those out by hand
before applying — applying them for real would delete the safety-gate
pause/resume state. Always read a freshly generated migration before
running it, don't assume it's only the change you asked for.

**Checkpointer gotcha already hit once — commit before invoking a
checkpointed graph run, don't leave the session's setup writes
uncommitted:** the pipeline's SQLAlchemy session (asyncpg) and the
checkpointer's own connection (psycopg — a different driver, see
`runner.py`'s `_psycopg_conn_string`) hung indefinitely (no error, no
timeout, just stuck) when the session had an open, uncommitted transaction
at the point `interrupt()` tried to write a checkpoint. Committing test-
setup rows (tenant/channel/conversation) before calling `run_pipeline`
fixed it. Root cause not fully isolated — treat "commit before invoking,
don't hold a long-open write transaction across a checkpointed run" as the
working rule either way.

**Celery worker gotcha, hit and fixed 2026-08-03 — never let a Celery task
reuse a pooled asyncpg connection across separate `asyncio.run()` calls:**
`app/pipeline/tasks.py`'s tasks each wrap their body in a fresh
`asyncio.run(...)` — a new event loop per task invocation, in the same
long-running warm worker process across many tasks. A connection checked
out of a normal SQLAlchemy async engine's pool is a real asyncpg
connection bound to whichever loop was running when it was first opened;
reused on a later task's new loop, asyncpg raises `RuntimeError: ... got
Future ... attached to a different loop`, then `InterfaceError: cannot
perform operation: another operation is in progress` on the next attempt.
Reproduced directly in isolation (two sequential `asyncio.run()` calls
against the shared pooled engine, no Celery involved) before touching any
code, then confirmed the fix the same way. Fix: `app/core/db.py` has a
second, `NullPool`-backed engine/sessionmaker (`worker_engine`/
`worker_async_session`) used only by `pipeline/tasks.py` — opens and
closes a real connection per checkout instead of reusing one across loop
boundaries, same "accept per-call connect overhead, stay loop-safe"
tradeoff `app/core/events.py`'s `publish_event()` already made for Redis.
The FastAPI-facing `engine`/`async_session` stay pooled and untouched —
uvicorn's one long-lived loop was never affected by this, no reason to
give up pooling there too. Any *new* async resource shared between
FastAPI and Celery (a client, an engine, a connection) needs this same
"is it reused across a fresh `asyncio.run()` boundary" check before
assuming a module-level singleton is safe — `redis_client.py`'s lazy
singleton is deliberately FastAPI-only for exactly this reason (see its
own docstring), and this db.py fix follows the same shape.

**LangGraph gotcha already hit once — never call `resume_pipeline()`/
`Command(resume=...)` with `None`:** raises `UnboundLocalError:
resume_is_map` from inside langgraph's own `_loop.py` (`resume_is_map` is
only assigned when `resume is not None`, then read unconditionally a few
lines later — a real bug in langgraph 0.2.x, not app code). Only surfaced
running `POST /escalations/{id}/resolve` against a real
`AsyncPostgresSaver` — the unit tests never caught it because they always
passed a dict resume value. `escalate_to_human`'s `interrupt()` doesn't
read the resume value for anything, so any non-None value works; the
resolve endpoint passes `{"resolved_by": <user id>}`. Applies to any future
caller of `resume_pipeline()`, not just this one.

**LangGraph gotcha already hit once — calling `run_pipeline()` again on an
already-interrupted `thread_id` does not resume, does not no-op, and does
not give you a clean slate:** empirically verified (not assumed) by
running the real `AsyncPostgresSaver` twice against the same paused
thread. It silently starts a brand-new run from `load_history` — but
LangGraph's checkpointer *merges* this new run's channel values with the
*previously persisted* ones for that `thread_id` rather than replacing
them. Concretely: a node that only sets a flag (e.g. "skip everything,
nothing to decide this time") and routes straight to `END` will still
return the *previous* run's `draft_text`/`decision` in the result dict,
since nothing in the new run overwrote them. Found building
`check_pending_escalation` (docs/ROADMAP.md's 2026-07-29 changelog entry
on the escalation-cover-message work) — a second message on
an already-escalated conversation re-sent the *first* message's cover
reply verbatim, because the caller trusted `result.get("draft_text")`
without knowing it could be stale. Fixed by having the short-circuiting
node explicitly reset every field it isn't setting itself
(`draft_text`/`decision`/`escalation_reason`/`escalation_logged`) before
returning — not by patching each caller. Any future node that means
"nothing happened this run" needs to make that true of the whole state,
not just of whatever field it's checking.

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

**Both `generate_text` and `embed_text` are confirmed working end to end
against the real API** (`ENVELOPS_GEMINI_API_KEY` is set in `.env`). Getting
here took two real, non-obvious findings — both already fixed in
`core/llm.py`, don't re-break them:

- **Free-tier quota is granted per model, not just per key/project, and a
  given model can sit at a permanent zero quota on a given account** — this
  shows as a 429 `generate_content_free_tier_requests, limit: 0` that never
  recovers on retry, not a transient rate-limit blip (don't mistake it for
  one — a real per-minute rate limit looks the same superficially but
  actually clears after the stated `retryDelay`). `gemini-2.5-flash`,
  `gemini-2.0-flash`, and `gemini-2.0-flash-lite` all hit this on this
  account; `gemini-flash-lite-latest` (current `GENERATION_MODEL`) doesn't.
  IoTOps hit and documented this same issue independently (see
  `../iotops-workspace/IoTOps/deploy/iotops/.env.prod.example`) — if this
  model ever stops working too, check what's actually available via `GET
  https://generativelanguage.googleapis.com/v1beta/models?key=...` rather
  than guessing another name.
- **`text-embedding-004` (the original embedding model choice) is
  retired** — `models.list()` no longer lists it. `gemini-embedding-001`
  replaced it, with configurable output size via `output_dimensionality`
  (current `EMBEDDING_MODEL`, requested at 768 to match the already-migrated
  `knowledge_chunks.embedding` column rather than the model's 3072 default).

Test coverage so far: `escalation/safety_gate.py` (Layer 1 safety floor,
English-only patterns since the Turkish removal above, with a regression
test for a real false positive found in the honey-seller domain —
"guarantee" needing an efficacy word alongside it so shipping/warranty
language doesn't trip it; also covers the tenant-added trigger-phrase
layer, additive-only, plain substring match, language-agnostic), `auth/
security.py` (PBKDF2 password hashing), `knowledge/chunking.py`
(chunk-with-overlap for embedding).

### Frontend (`frontend/`)

Vite + React + TypeScript, `node_modules` already installed. Includes
`react-router-dom` (routing between screens) and `react-i18next` +
`i18next-browser-languagedetector` (English/Turkish UI chrome — this is
just the dashboard's own language switcher, unrelated to the pipeline's
now-cut reply-language-matching above) — both wired up, `App.tsx` has the
nav/routes, `src/i18n/` has the locale files and config. Every page under
`src/pages/` is real, built-out screen content now (Dashboard, Knowledge
sources, Test console, Settings, the conversation rail/panel), not the
early-Phase-1 translated placeholders this line used to describe.

- `npm run dev` — dev server (verified boots and serves)
- `npm run build` — type-check (`tsc -b`) + production build (verified
  clean)
- `npm run lint` — oxlint (verified clean)
