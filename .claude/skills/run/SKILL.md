---
description: Launch and drive envelOps's full stack (backend via docker compose, frontend via Vite) with a headless browser, to visually verify a frontend change or live-update behavior actually works. Use this whenever asked to run/start the app, screenshot it, or confirm a change works end-to-end (not just via lint/typecheck/pytest).
---

# Running envelOps end-to-end

## Backend + frontend

- Backend (API, db, redis, worker, beat): `docker compose up -d` from repo
  root. Health check: `curl localhost:8000/healthz`.
- Frontend: `cd frontend && npm run dev` (Vite). Confirm the port with
  `grep port frontend/vite.config.ts`, or just try `curl -o /dev/null -w
  '%{http_code}' http://localhost:5173/` — 5173 is the default and hasn't
  changed so far. If you edited backend Python and need the container to
  pick it up, `docker compose up -d --build backend` (recreates the
  container; plain `restart` does NOT reload code or env vars).

## Auth for a driven session

`ENVELOPS_DEMO_MODE_ENABLED=true` is set in the local `.env` (never true
outside local dev or an actual public demo deployment — see CLAUDE.md).
This means `App.tsx` skips the Login screen **entirely** and
auto-logs-in as whichever tenant is first in `GET /auth/demo-tenants`,
with zero interaction needed — just `page.goto(...)` and wait for the
app shell to render (e.g. `nav.channel-rail`). There used to be a manual
dropdown on the Login page for this (removed 2026-08-04, along with the
separate `dev_auth_bypass_enabled` flag it depended on) — don't look for
a `<select>` on Login anymore, it's a plain email/password form now and
demo mode never even shows it.

- To drive a **specific** tenant, not just whichever one auto-login
  landed on, use the Dashboard's own tenant dropdown instead (only
  rendered in demo mode, replaces the page's `<h1>`):
  `page.locator(".dashboard__tenant-select select").selectOption("<tenant_id>")`
  — note the option **value** here is `tenant_id`, not `user_id` (a real
  behavior difference from the old Login dropdown, which used
  `user_id` — don't reuse that muscle memory). Fetch the list live from
  `GET /auth/demo-tenants` (`{user_id, tenant_id, tenant_name, email}`)
  if you don't already know the tenant_id.
- Same demo-login flow is also a plain API call if you don't need the
  browser session for it: `POST /auth/demo-login {"user_id": "..."}` →
  `{"access_token": "..."}`, then `Authorization: Bearer <token>` on
  everything else (e.g. `POST /test/conversations/messages` to drive the
  pipeline without going through the Test Console UI at all). This one
  still takes `user_id`, from the same `GET /auth/demo-tenants` list.

## Driving a browser: no `chromium-cli` here

This environment does **not** have `chromium-cli` on `PATH` (checked
2026-07-29, `which chromium-cli` → not found). Don't spend time
re-checking — use the `playwright` npm package directly instead, via a
plain Node script. Two things that cost real time to work out once,
already resolved:

**1. `playwright` isn't a project dependency, but it's already cached
via npx** — no fresh install/download needed (worth checking again if
this ever stops working, since `~/.npm/_npx/*` entries can be pruned):

```bash
for d in ~/.npm/_npx/*/node_modules/playwright; do
  node -e "console.log('$d', require('$d/package.json').version)"
done
```

Point `NODE_PATH` at whichever version's directory when running your
driver script, e.g.:

```bash
NODE_PATH=~/.npm/_npx/e41f203b7505f1fb/node_modules node your_script.js
```

(That specific hash had playwright 1.62.0 as of 2026-07-29 — the hash
itself isn't stable across machines/time, re-run the loop above rather
than hardcoding it blindly, but the *approach* — NODE_PATH into an npx
cache dir — is the reusable part.)

**2. The cached browser binary's revision won't match `chromium.launch()`'s
default (headless_shell) — pass `executablePath` explicitly instead of
letting Playwright auto-resolve.** `~/Library/Caches/ms-playwright/`
had a full `chromium-1228` (regular Chrome for Testing, not the
headless-shell variant) but no matching `chromium_headless_shell-*` for
*any* cached playwright version (tried 1.55.0, 1.56.1, 1.62.0 — each
wanted a different, absent headless_shell revision). `chromium.launch()`
defaults to headless_shell for `headless: true` in newer Playwright, so
it fails with "Executable doesn't exist" even though a perfectly usable
browser *is* on disk. Fix: check what's actually cached first —

```bash
ls ~/Library/Caches/ms-playwright/
find ~/Library/Caches/ms-playwright/chromium-<rev>/chrome-mac-arm64 -iname "*chrome for testing*" -type d
```

— then pass that binary's path straight to `launch()`:

```js
const { chromium } = require("playwright");
const browser = await chromium.launch({
  args: ["--no-sandbox"],
  executablePath:
    "/Users/<you>/Library/Caches/ms-playwright/chromium-1228/chrome-mac-arm64/Google Chrome for Testing.app/Contents/MacOS/Google Chrome for Testing",
});
```

Verify the combination launches before writing the rest of the driver:

```bash
NODE_PATH=~/.npm/_npx/<hash>/node_modules node -e "
const { chromium } = require('playwright');
chromium.launch({ args: ['--no-sandbox'], executablePath: '...' })
  .then(async b => { console.log('LAUNCH_OK'); await b.close(); })
  .catch(e => console.log('LAUNCH_FAIL', e.message));
"
```

## Driver pattern: one self-contained script, not split processes

Don't split "drive the browser" and "trigger a backend event" into two
coordinated processes with signal files — it's fragile (background-task
completion notifications fire on the *shell wrapper* exiting, not on a
detached child you further backgrounded with `&`, which orphans it) and
wastes time debugging synchronization instead of the actual thing under
test. Node 18+'s native `fetch` is available inside the same script —
trigger the backend call from right there, no `curl` in a second
terminal needed. Full working example (login, read a badge, trigger a
real pipeline escalation via the API, confirm the badge updates with
zero clicks — this is docs/ROADMAP.md §3.5's SSE live-update feature):

```js
const { chromium } = require("playwright");

async function main() {
  const browser = await chromium.launch({
    args: ["--no-sandbox"],
    executablePath: "/path/to/cached/Google Chrome for Testing",
  });
  const page = await browser.newPage();
  page.on("pageerror", (e) => console.log("PAGE_ERROR", String(e)));

  await page.goto("http://localhost:5173/");
  // No login step -- demo mode auto-logs in as the first demo-tenants
  // entry the instant the page loads (App.tsx). If you need a specific
  // tenant instead, switch via the Dashboard's own dropdown first:
  // page.locator(".dashboard__tenant-select select").selectOption("<tenant_id>")
  await page.waitForSelector("button.channel-rail__icon--telegram", { timeout: 15000 });
  await page.waitForTimeout(1500); // let the initial GET /escalations settle

  const badge = page.locator("button.channel-rail__icon--telegram .channel-rail__badge");
  const before = (await badge.count()) ? Number(await badge.textContent()) : 0;

  const { access_token } = await (
    await fetch("http://localhost:8000/auth/demo-login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ user_id: "1748dab3-872d-47b6-b08d-724d0b9da17b" }),
    })
  ).json();
  await fetch("http://localhost:8000/test/conversations/messages", {
    method: "POST",
    headers: { "Content-Type": "application/json", Authorization: `Bearer ${access_token}` },
    body: JSON.stringify({
      channel_type: "telegram",
      external_contact_id: `check-${Date.now()}`,
      text: "do you have a physical store I can visit in person?", // reliably hits the knowledge-gap escalation
    }),
  });

  await page.waitForTimeout(4000); // SSE event + 400ms debounce + refetch
  const after = (await badge.count()) ? Number(await badge.textContent()) : 0;
  console.log("BADGE", before, "->", after);
  await page.screenshot({ path: "/tmp/after.png" });
  await browser.close();
}
main();
```

Run it with the `NODE_PATH` prefix from above, in the foreground (no
`run_in_background`, no `&`) — the whole thing takes well under a
minute.

## Other useful selectors

- `nav.channel-rail` — the icon rail itself (persistent on every route,
  `frontend/src/App.tsx` renders it outside `<Routes>`).
- `button.channel-rail__icon--telegram` (Telegram is the one `real:
  true` channel — others are test-only per `ChannelRail.tsx`'s
  `CHANNELS` array) with a `.channel-rail__badge` child span when the
  pending-escalation count is > 0 (absent entirely at 0, not rendered
  as "0").
- Routes: `/` (Dashboard), `/knowledge`, `/test-console`, `/settings` —
  all under one persistent layout with the sidebar nav + `ChannelRail`.
