import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    // Dev-only proxy to the FastAPI backend (docker compose / uvicorn on
    // :8000, docs/ARCHITECTURE.md §9's router prefixes) -- lets the
    // frontend call relative paths (fetch("/auth/login")) without the
    // browser treating it as cross-origin, so no CORS middleware is
    // needed on the backend for local dev. Frontend deployment/production
    // origin setup isn't designed yet (ARCHITECTURE has no §10 note on
    // this), so this is deliberately dev-only, not a production answer.
    //
    // Keys are regexes anchored to a path-segment boundary, not
    // plain-string prefixes -- vite's proxy does a bare
    // `url.startsWith(key)` for string keys, which silently matched a
    // frontend page route too (a hard reload on `/knowledge` was being
    // sent to this proxy and 404ing, since the page path is the exact
    // same string as the API prefix). Found via live testing
    // (docs/ROADMAP.md §3.4's verification pass), not something the
    // plain-string form ever surfaced before.
    //
    // Two different boundary rules, matching each router's actual shape
    // (backend/app/*/api.py): `/conversations` and `/escalations` each
    // have a real bare `@router.get("")` (docs/ARCHITECTURE.md §9), so
    // those must still match with nothing after the prefix but a query
    // string -- safe for them specifically because neither is also a
    // frontend page route. `/channels` deliberately avoids a bare
    // collection-root GET for exactly that reason: it's now also a real
    // page route (Channels.tsx, 2026-08-03), so its real-channel-list
    // endpoint lives at `/channels/connected` instead (same reasoning
    // `/knowledge/sources` already established for `/knowledge`'s own
    // page-route collision) -- a plain trailing-slash requirement is
    // enough, no special-casing needed here. `/auth`, `/channels`,
    // `/knowledge`, `/leads`, `/dashboard`, `/test` are all always called
    // with a further path segment, so those require a trailing slash,
    // which is what keeps a frontend page route of the same bare name
    // from colliding with the proxy.
    proxy: {
      '^/auth(/|\\?)': 'http://localhost:8000',
      '^/channels(/|\\?)': 'http://localhost:8000',
      '^/knowledge(/|\\?)': 'http://localhost:8000',
      '^/conversations(/|$|\\?)': 'http://localhost:8000',
      '^/leads(/|\\?)': 'http://localhost:8000',
      '^/escalations(/|$|\\?)': 'http://localhost:8000',
      '^/dashboard(/|\\?)': 'http://localhost:8000',
      '^/test(/|\\?)': 'http://localhost:8000',
      '^/events(/|\\?)': 'http://localhost:8000',
      '^/tenants(/|\\?)': 'http://localhost:8000',
      '^/system(/|\\?)': 'http://localhost:8000',
    },
  },
})
