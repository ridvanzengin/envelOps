// Reads a JWT's payload client-side -- safe to do without a signature
// check here, since the token itself isn't trusted for anything (the
// backend re-validates it on every request); this is purely for display,
// currently just Dashboard.tsx's demo-mode tenant dropdown needing to
// know which tenant the current token already belongs to.
export function decodeJwtPayload<T = Record<string, unknown>>(token: string): T | null {
  try {
    const [, payload] = token.split(".");
    const normalized = payload.replace(/-/g, "+").replace(/_/g, "/");
    const padding = (4 - (normalized.length % 4)) % 4;
    return JSON.parse(atob(normalized + "=".repeat(padding))) as T;
  } catch {
    return null;
  }
}
