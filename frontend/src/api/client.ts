// Relative paths -- Vite's dev-server proxy (vite.config.ts) forwards
// these to the FastAPI backend, so the browser never sees a cross-origin
// request in dev.

export class ApiError extends Error {
  status: number;

  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

async function request<T>(
  path: string,
  options: { method?: string; token?: string | null; body?: unknown } = {},
): Promise<T> {
  const headers: Record<string, string> = {};
  if (options.body !== undefined) {
    headers["Content-Type"] = "application/json";
  }
  if (options.token) {
    headers.Authorization = `Bearer ${options.token}`;
  }

  const response = await fetch(path, {
    method: options.method ?? "GET",
    headers,
    body: options.body !== undefined ? JSON.stringify(options.body) : undefined,
  });

  if (!response.ok) {
    // FastAPI's HTTPException responses are always {"detail": "..."} --
    // fall back to the raw status text if the body isn't that shape (e.g.
    // a proxy/network-level error page, not our own API).
    let detail = response.statusText;
    try {
      const data = (await response.json()) as { detail?: string };
      if (typeof data.detail === "string") {
        detail = data.detail;
      }
    } catch {
      // response body wasn't JSON -- keep the statusText fallback above
    }
    throw new ApiError(response.status, detail);
  }

  if (response.status === 204) {
    return undefined as T;
  }
  return (await response.json()) as T;
}

export function apiGet<T>(path: string, token: string | null): Promise<T> {
  return request<T>(path, { method: "GET", token });
}

export function apiPost<T>(
  path: string,
  body: unknown,
  token: string | null,
): Promise<T> {
  return request<T>(path, { method: "POST", token, body });
}

export function apiDelete(path: string, token: string | null): Promise<void> {
  return request<void>(path, { method: "DELETE", token });
}
