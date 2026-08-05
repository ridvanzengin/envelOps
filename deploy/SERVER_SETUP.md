# Server Setup — Fresh Clone

Use this when setting up EnvelOps on the shared VM for the first time.
For routine code updates on an already-running server, see
[Deploying Updates](#deploying-updates) below.

This deployment reuses the shared VM's existing `infra` Compose project
(nginx, Postgres/pgvector, Redis) that already runs AgriTwin and IoTOps —
see `~/personal/agritwin/deploy/infra/docker-compose.yml` on the VM at
`/opt/agritwin/deploy/infra/`. EnvelOps never runs its own
nginx/Postgres/Redis in production, the same choice IoTOps already made
on this same box. **Prerequisite: the `infra` project and
`agritwin-infra.service` must already be running before step 5 below** —
they already are, since IoTOps and AgriTwin are both live on this VM.

This app is lighter-weight than IoTOps in one meaningful way worth
calling out up front: it does **not** mount `/var/run/docker.sock` or
manage sibling containers, so it doesn't carry IoTOps's "root-equivalent
control of the whole host Docker daemon" accepted risk. It's a
straightforward FastAPI + Celery + Postgres/pgvector app.

---

## 1 — DNS

Already done — `envelops.site` and `www.envelops.site` both resolve to
this VM's IP (confirmed via `dig`). Nothing to do here; skip straight to
step 2.

---

## 2 — Clone the repo

```bash
git clone -b main https://github.com/ridvanzengin/envelOps.git /opt/envelops
```

No `/opt/envelops-data` host directory needed, unlike IoTOps/AgriTwin —
this app has no local file storage or host-mounted volumes at all
(uploaded knowledge PDFs are parsed/chunked/embedded in-memory, never
persisted to disk; everything durable lives in the shared Postgres).

---

## 3 — Create the secret env file

```bash
cp /opt/envelops/deploy/envelops/.env.prod.example /opt/envelops/deploy/envelops/.env.prod
nano /opt/envelops/deploy/envelops/.env.prod
```

Fill in `ENVELOPS_DB_PASSWORD` (must match step 4 below),
`ENVELOPS_JWT_SECRET`, `ENVELOPS_FAKE_COMMERCE_INTERNAL_TOKEN` (all three:
`python3 -c "import secrets; print(secrets.token_urlsafe(24))"`), and a
real `ENVELOPS_GEMINI_API_KEY` — every pipeline stage (intent, knowledge
grounding, lead scoring, tool-calling) needs it to actually work, not
just SQL generation the way IoTOps's demo degrades without one. Use a key
**dedicated to this deployment**, not the same one local dev uses — they
share one free-tier quota (same warning IoTOps's own `.env.prod.example`
already carries).

---

## 4 — Create the database on the shared Postgres instance

```bash
docker exec -it infra-db-1 psql -U postgres <<'SQL'
  CREATE DATABASE envelops;
  CREATE USER envelops WITH PASSWORD 'CHANGE_ME';  -- match .env.prod ENVELOPS_DB_PASSWORD
  GRANT ALL PRIVILEGES ON DATABASE envelops TO envelops;
  \c envelops
  CREATE EXTENSION IF NOT EXISTS vector;
SQL
```

`infra-db-1` runs `timescale/timescaledb-ha:pg16` — confirmed via
`SELECT * FROM pg_available_extensions WHERE name = 'vector'` that
pgvector (0.8.3) ships in this image already, just not enabled in any
database yet. Created here as the `postgres` superuser rather than
relying on alembic's own `CREATE EXTENSION IF NOT EXISTS vector` (in the
initial migration) to succeed as the less-privileged `envelops` app user
— pgvector's trusted-extension status on this specific image wasn't
worth gambling on for a one-time step. Alembic's own copy of that
statement becomes a harmless no-op once this has already run.

No TimescaleDB hypertables, no PostGIS — this app has no time-series or
spatial data, just relational tables + vector columns via pgvector.

---

## 5 — Add the EnvelOps nginx vhost (HTTP-only for now)

`deploy/nginx/envelops.conf` as checked in has both the HTTP-redirect
block and the final HTTPS block — the HTTPS one references a cert that
doesn't exist yet, and a `listen 443 ssl` block with no matching cert
fails `nginx -t` outright. Deploy only the HTTP block for now:

```bash
# On the VM: copy the file, then comment out the entire second
# (`listen 443 ssl { ... }`) server block in the VM's copy only --
# the repo's own copy stays as the reviewed, final-state source of truth.
cp /opt/envelops/deploy/nginx/envelops.conf \
   /opt/agritwin/deploy/infra/nginx/conf.d/envelops.conf
nano /opt/agritwin/deploy/infra/nginx/conf.d/envelops.conf   # comment out the HTTPS server block

docker exec infra-nginx-1 nginx -t
docker exec infra-nginx-1 nginx -s reload
```

Re-copy the full (both-blocks) repo version back onto the VM in step 9,
once a real cert exists — this mirrors IoTOps's own staged TLS rollout.

---

## 6 — Build and start the app

```bash
cd /opt/envelops

docker compose -p envelops --env-file deploy/envelops/.env.prod \
  -f deploy/envelops/docker-compose.prod.yml build

docker compose -p envelops --env-file deploy/envelops/.env.prod \
  -f deploy/envelops/docker-compose.prod.yml run --rm migrate

docker compose -p envelops --env-file deploy/envelops/.env.prod \
  -f deploy/envelops/docker-compose.prod.yml up -d backend worker beat frontend
```

`migrate` runs once and exits (`restart: "no"`) — don't `up -d` it, it's
not a long-running service. Confirm it actually applied the schema
before moving on:

```bash
docker exec infra-db-1 psql -U envelops -d envelops -c '\dt'
```

Real tables (`tenants`, `channels`, `conversations`, `knowledge_chunks`,
etc.) confirm the migration landed, not just that the container exited
0.

---

## 7 — Seed showcase demo data

```bash
docker compose -p envelops --env-file deploy/envelops/.env.prod \
  -f deploy/envelops/docker-compose.prod.yml run --rm backend \
  python3 -m scripts.seed_showcase_tenants
```

Writes real tenants/knowledge sources/conversations across the four
REQUIREMENTS.md business-model verticals, run through the real pipeline
against the real `ENVELOPS_GEMINI_API_KEY` — this is what makes the
public demo mode's tenant switcher (`GET /auth/demo-tenants`) have
something worth looking at instead of empty state. Not idempotent (see
the script's own docstring) — running it twice creates a second set of
tenants, it doesn't refresh the first. Run once here; re-run later only
if you deliberately want fresh showcase data.

---

## 8 — Verify over plain HTTP (no DNS needed yet, but DNS is already live)

```bash
curl -sI http://envelops.site/
curl -s http://envelops.site/healthz
```

The first should return the frontend's `index.html`; the second
`{"status":"ok"}` — confirming the backend actually reached
`infra-db-1`. Then confirm a real page route survives a hard reload
(the `/auth`, `/channels`, etc. path-collision gotcha
`frontend/vite.config.ts` documents for dev — the same disambiguation
has to hold through the outer nginx too):

```bash
curl -sI http://envelops.site/knowledge   # should be the SPA's index.html, not a backend 404
curl -s http://envelops.site/system/demo-mode   # should be {"enabled":true}
```

---

## 9 — TLS

```bash
certbot certonly --webroot \
  -w /opt/agritwin/deploy/infra/certbot/webroot \
  -d envelops.site -d www.envelops.site \
  --non-interactive --agree-tos -m your@email.com
```

The VM's existing renewal cron already renews *all* certs regardless of
which one's config it was originally set up for — no new cron line
needed. Then:

1. Uncomment the HTTPS `server` block in
   `/opt/envelops/deploy/nginx/envelops.conf` (the repo copy, so it's
   reviewed and versioned).
2. Re-copy it onto the VM (same command as step 5) and reload:
   ```bash
   cp /opt/envelops/deploy/nginx/envelops.conf \
      /opt/agritwin/deploy/infra/nginx/conf.d/envelops.conf
   docker exec infra-nginx-1 nginx -t
   docker exec infra-nginx-1 nginx -s reload
   ```
3. Verify:
   ```bash
   curl -I https://envelops.site/
   curl -N https://envelops.site/events/stream   # should stay open and stream, not hang/buffer -- adjust path to the real one in app/events/api.py if it differs
   ```
4. Confirm IoTOps and AgriTwin are unaffected:
   `curl -I https://iotops.online/ && curl -I https://agritwin.online/`.

---

## 10 — Systemd auto-start

```bash
cp /opt/envelops/deploy/systemd/envelops-app.service /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now envelops-app.service
```

`envelops-app.service` depends on `agritwin-infra.service` by name (a
systemd dependency declaration, not a file this repo owns) — the shared
infra must already be enabled on this box (it is).

---

## 11 — Register the Telegram channel

The one real channel integration — everything else (Instagram/WhatsApp/
Facebook/Email) is simulated and needs no external registration. Once
the app is live over HTTPS:

```bash
docker compose -p envelops --env-file deploy/envelops/.env.prod \
  -f deploy/envelops/docker-compose.prod.yml run --rm backend \
  python3 -m scripts.register_telegram_channel <args — check the script's own --help/docstring>
```

This calls Telegram's `setWebhook` API pointing at
`https://envelops.site/channels/telegram/{channel_id}/webhook` — needs a
real bot token from `@BotFather` and a live HTTPS endpoint, so this must
come after step 9, not before.

---

## Deploying Updates

```bash
bash /opt/envelops/deploy/scripts/deploy.sh
```

Pulls the repo, rebuilds images, runs migrations, restarts app services,
and only touches the shared nginx (`nginx -t` then reload) if
`deploy/nginx/envelops.conf` actually changed since the last deploy —
routine deploys never reload IoTOps/AgriTwin's live serving path on an
unrelated push.

---

## Shared Postgres / Redis notes

- **Postgres**: `envelops` is its own database on `infra-db-1`, alongside
  `iotops` and `agritwin` — no data overlap, standard multi-database
  Postgres isolation. `max_connections=25` total is still shared across
  all three apps (see IoTOps's own SERVER_SETUP.md/CHANGELOG for the
  connection-exhaustion incident this box already had) — if this app
  ever adds its own explicit connection pool sizing (SQLAlchemy's
  `create_async_engine` currently uses library defaults), size it small
  and explicit from the start rather than the library default, the same
  lesson IoTOps had to learn live.
- **Redis**: `infra-redis-1` DB index **2** is this app's own Celery
  broker/backend (`app/core/celery_app.py` uses one URL for both) — DB 0
  is shared between AgriTwin's Celery broker and IoTOps's real-time-rule
  firing keys, DB 1 is IoTOps's own Celery broker. DB 2 was free; picked
  it over doubling up on an already-shared index. **Never run
  `redis-cli -n 2 FLUSHDB` casually** — same rule as IoTOps's own
  warning about DB 0.
