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
    proxy: {
      '/auth': 'http://localhost:8000',
      '/channels': 'http://localhost:8000',
      '/knowledge': 'http://localhost:8000',
      '/conversations': 'http://localhost:8000',
      '/leads': 'http://localhost:8000',
      '/escalations': 'http://localhost:8000',
      '/dashboard': 'http://localhost:8000',
      '/test': 'http://localhost:8000',
    },
  },
})
