---
name: deploy
description: Deploy EnvelOps to production (https://envelops.site) on the shared Hetzner VM "ringo" — routine updates, fresh-server setup, or health-checking/troubleshooting the live deployment. Use whenever asked to deploy, redeploy, ship to production, update the live site, or check on envelops.site's health.
---

EnvelOps runs in production on the same Hetzner VM as AgriTwin and
IoTOps, reusing its shared `infra` Compose project (nginx, Postgres with
pgvector, Redis) rather than running its own — see `deploy/SERVER_SETUP.md`
for full topology and the first-time setup walkthrough. This skill
assumes that initial setup is done and covers *operating* the live
deployment: routine updates, and the debugging playbook for the failure
modes IoTOps/AgriTwin already hit on this same shared infra (worth
checking here first before rediscovering them independently).

SSH: `ssh iotops-vm` — assumes an `iotops-vm` host alias in your local
`~/.ssh/config` (same VM as IoTOps/AgriTwin, not committed here so the
VM's real IP never ends up in this public repo's history):
```
Host iotops-vm
    HostName <the VM's IP>
    User root
    IdentityFile <path to your private key>
```
Every command below runs on that VM unless noted otherwise.

## Routine update (the common case)

```bash
bash /opt/envelops/deploy/scripts/deploy.sh
```

Pulls `main` (or whatever branch is checked out — check first if you're
mid-feature-branch), rebuilds images, runs `alembic upgrade head` via the
one-shot `migrate` service, restarts `backend`/`worker`/`beat`/`frontend`,
and only touches the shared nginx if `deploy/nginx/envelops.conf`
actually changed (gated by `nginx -t`, never reloads on a routine
unrelated push).

Restart just one affected service after a targeted fix instead of the
whole stack:

```bash
cd /opt/envelops
docker compose -p envelops --env-file deploy/envelops/.env.prod -f deploy/envelops/docker-compose.prod.yml build <service>
docker compose -p envelops --env-file deploy/envelops/.env.prod -f deploy/envelops/docker-compose.prod.yml up -d --no-deps <service>
```

## Fresh server / disaster recovery

Follow `deploy/SERVER_SETUP.md` top to bottom — it's the authoritative,
numbered playbook (DNS → clone → secrets → DB+pgvector → nginx vhost →
build+migrate+start → seed demo data → verify → TLS → systemd → register
Telegram). Don't improvise a different order; the numbering encodes real
dependencies (the DB/extension must exist before `migrate` can run
cleanly, a real cert must exist before the HTTPS nginx block can pass
`nginx -t`, HTTPS must be live before Telegram's `setWebhook` will accept
the callback URL).

## Verifying a deployment actually worked

Don't stop at "containers are Up" — IoTOps's own deploy history shows
exactly why that told nobody anything the day it mattered. Check, in
order:

```bash
# Public reachability
curl -sI https://envelops.site/ | head -3
curl -s https://envelops.site/healthz

# A page route that collides with a backend router prefix still resolves
# to the SPA, not a stray 404/502 -- the one gotcha unique to this app's
# routing (frontend/vite.config.ts's own dev-proxy comment has the full
# story; deploy/nginx/envelops.conf mirrors it)
curl -sI https://envelops.site/knowledge

# IoTOps and AgriTwin unaffected -- check this after ANY shared-nginx touch
curl -sI https://iotops.online/ | head -3
curl -sI https://agritwin.online/ | head -3

# Container health -- names, not just count
docker ps -a --format 'table {{.Names}}\t{{.Status}}' | grep envelops

# Schema actually migrated, not just "container exited 0"
docker exec infra-db-1 psql -U envelops -d envelops -c '\dt'

# Celery beat's scheduled jobs are actually registered (follow-up-check,
# and in demo mode stream-demo-dm/purge-stale-demo-data)
docker logs envelops-beat-1 --tail 20 | grep -i schedule
```

## Known failure modes -- hit for real on this app's own first deploy (2026-08-05)

**`migrate` fails with `permission denied for schema public`** on a
freshly-created database, even though `GRANT ALL PRIVILEGES ON DATABASE`
already ran. Postgres 15+ no longer grants `CREATE` on the `public`
schema to `PUBLIC` (every role) by default -- a database-level grant
doesn't imply a schema-level one. Fix: `GRANT ALL ON SCHEMA public TO
envelops;` as the `postgres` superuser (already folded into
`SERVER_SETUP.md` step 4 -- this only recurs if you're improvising
outside that playbook).

**`migrate`/seed scripts fail with things like `No 'script_location' key
found in configuration` or `ModuleNotFoundError: No module named
'scripts'`** -- the backend `Dockerfile` only ever copied `app/`; nothing
had actually run `alembic` or `python3 -m scripts.<name>` from inside the
image before this app's first real deploy. Already fixed (the Dockerfile
now copies `alembic.ini`/`alembic/`/`scripts/` too) -- only relevant again
if a *new* top-level directory the Dockerfile doesn't know about becomes
runnable-from-container for the first time. Check `docker run --rm
envelops-<service>:latest ls /app` if a similar "file not found"-shaped
error shows up for something new.

**`envelops-beat-1` OOM-crash-loops** (`docker inspect ... .State.OOMKilled`
-> `true`, `RestartCount` climbing fast, empty logs since it dies before
printing anything) if its memory limit ever drops back toward IoTOps's
own 128M starting point. This app's Celery import footprint
(LangGraph/LangChain/google-genai/SQLAlchemy async) is heavier than
IoTOps's -- `backend`/`worker` (same image) sit at ~145-235MB baseline
even at rest. Currently 256M, sized against that observed baseline, not
a guess.

**A calibration/showcase seed script "succeeds" (real tenant + knowledge
base rows, exit code 0) but seeds zero conversations, having burned real
Gemini quota trying.** `scripts/seed_calibration_tenant.py` (and
`seed_showcase_tenants.py`) call `POST /test/conversations/messages` to
run seeded messages through the real pipeline -- but
`app/test_console/api.py`'s `send_test_message` checks
`settings.demo_mode_enabled` directly, not how the caller authenticated,
so with `ENVELOPS_DEMO_MODE_ENABLED=true` (the production default) every
call still runs the real pipeline and then silently discards the result.
The script's own docstring claims immunity from this via its real
(non-bypass) login; that claim doesn't hold against the current code.
See `SERVER_SETUP.md` step 7 for the actual "conversations are optional,
tenants aren't" workaround and the "temporarily flip demo mode off"
procedure if you do want real seeded conversations. **If a seed run gets
killed mid-way or fails partway, delete the resulting empty-shell tenant
before retrying** -- both scripts skip (not retry) a tenant whose owner
email already exists, so a broken half-seeded tenant stays broken forever
otherwise:
```bash
DB_PASS=$(grep "^ENVELOPS_DB_PASSWORD=" /opt/envelops/deploy/envelops/.env.prod | cut -d= -f2-)
docker exec infra-db-1 psql "postgresql://envelops:$DB_PASS@localhost:5432/envelops" -c "SELECT id, name, created_at FROM tenants ORDER BY created_at;"
# then delete the broken one's dependent rows in this order (no CASCADE
# constraints in this schema) before the tenants row itself:
# pipeline_traces, messages, escalations, leads, conversations, channels,
# knowledge_chunks, knowledge_sources, escalation_trigger_phrases,
# fake_commerce_products, users -- all keyed by tenant_id -- then tenants by id.
```

**`seed_calibration_tenant.py` needs `backend/data/bitext_customer_support_27k.csv`
mounted at runtime** (`-v $(pwd)/backend/data:/app/data` on the `docker
compose run` command) -- it's real third-party research data, deliberately
gitignored and not baked into the image. If it isn't already on the VM,
`scp` it from a machine that has it first.

## Known failure modes (inherited from IoTOps/AgriTwin's own incident history on this box — check here before re-diagnosing from scratch)

**Shared `infra-nginx-1` silently stops listening on 80/443** (master +
worker processes alive per `docker exec infra-nginx-1 ps aux`, but
`docker exec infra-nginx-1 ss -tlnp` shows nothing bound) after several
new containers join `infra_proxy` in quick succession. `nginx -s reload`
does *not* fix this — it needs an actual restart:
```bash
docker exec infra-nginx-1 ss -tlnp   # confirm: nothing on 80/443 despite ps showing workers
docker restart infra-nginx-1
docker exec infra-nginx-1 ss -tlnp   # confirm: now listening
curl -sI https://iotops.online/ && curl -sI https://agritwin.online/   # confirm both recovered -- this affects every app on the shared vhost
```
This is a shared-infra action — get explicit confirmation before running
`docker restart infra-nginx-1`, naming it exactly, every time.

**502 after any deploy that recreates `backend`/`frontend`**: check
`deploy/nginx/envelops.conf`'s `proxy_pass` targets are the `set
$upstream http://...; proxy_pass $upstream;` form, never a bare static
`proxy_pass http://host:port;`. A static hostname is resolved once at
nginx startup/reload and cached indefinitely — the `resolver ...
valid=30s` directive only actually takes effect through the variable
form. This already bit IoTOps for real on this exact shared nginx.

**`infra-db-1` connection exhaustion** (`TooManyConnectionsError:
remaining connection slots are reserved for roles with the SUPERUSER
attribute`) — already happened twice on this VM (IoTOps + AgriTwin, both
documented in IoTOps's own CHANGELOG.md). `max_connections=25` total,
shared across three apps now. `app/core/db.py`'s worker engine already
uses `NullPool` (a fresh connection per Celery task, closed after --
deliberate, same reasoning as IoTOps's own query_rule tick), but the
`backend` container's own engine uses SQLAlchemy's default `QueuePool`
(`pool_size=5, max_overflow=10` — up to 15 connections from one process).
If that ever needs tightening, size it small and explicit rather than
waiting to hit this the hard way a third time on this box. Check current
usage:
```bash
docker exec infra-db-1 psql -U postgres -c "SELECT count(*), usename, datname FROM pg_stat_activity GROUP BY usename, datname ORDER BY count(*) DESC;"
```

**A Celery worker with no `--concurrency` set defaults to
`os.cpu_count()`** (4 on this VM) — each prefork process is a near-full
Python interpreter copy, which OOM-killed IoTOps's own memory-capped
celery-worker container for real. `deploy/envelops/docker-compose.prod.yml`
already sets `--concurrency=2` from the start for exactly this reason —
don't remove it without re-sizing the container's memory limit to match.

## Safety rules (non-negotiable, not just style)

- `infra-nginx-1`, `infra-db-1`, `infra-redis-1` are **shared with
  IoTOps and AgriTwin, live**. Any direct mutation (restart, exec into to
  run scripts, raw SQL deletes) needs explicit confirmation naming the
  exact action — a general "yes" or "go ahead" earlier in the
  conversation does not carry forward to a new specific risky action.
- `nginx -t` gates every `nginx -s reload`, no exceptions. Check
  `iotops.online` and `agritwin.online` before and after any
  shared-nginx touch.
- Prefer read-only diagnosis (`docker ps`, `docker logs`, `psql SELECT`)
  before any write/restart/delete — establish what's actually broken
  before acting on it.
- HTTPS vhost changes: edit `deploy/nginx/envelops.conf` in the repo
  (never edit the VM's copy directly), commit, then copy over per
  `SERVER_SETUP.md`/`deploy.sh`'s pattern.
