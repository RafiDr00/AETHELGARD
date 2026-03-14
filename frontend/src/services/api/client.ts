// Base API client — reads VITE_API_BASE_URL from env or defaults to same origin
// (Vite's dev proxy forwards /api /health /metrics /pipeline to localhost:8000)
import { useAuthStore } from "@/state/authStore";

const API_BASE =
  import.meta.env.VITE_API_BASE_URL ??
  (import.meta.env.DEV ? "" : "http://localhost:8000");

export class ApiError extends Error {
  constructor(
    public readonly status: number,
    public readonly statusText: string,
    message?: string,
  ) {
    super(message ?? `${status} ${statusText}`);
    this.name = "ApiError";
  }
}

export async function apiFetch<T>(
  path: string,
  init?: RequestInit,
): Promise<T> {
  const url = `${API_BASE}${path}`;
  const res = await fetch(url, {
    headers: { "Content-Type": "application/json", ...init?.headers },
    ...init,
  });
  if (!res.ok) {
    throw new ApiError(res.status, res.statusText);
  }
  return res.json() as Promise<T>;
}

export async function apiPost<T>(
  path: string,
  body?: unknown,
): Promise<T> {
  const apiKey = useAuthStore.getState().apiKey;
  if (!apiKey) {
    throw new Error("No API key set. Please start a new session.");
  }
  return apiFetch<T>(path, {
    method: "POST",
    headers: { "X-API-Key": apiKey },
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });
}

/** Helper to produce WebSocket URL with same host as API */
export function wsUrl(path: string): string {
  const base = API_BASE || window.location.origin;
  const u = new URL(base);
  u.protocol = u.protocol === "https:" ? "wss:" : "ws:";
  u.pathname = path;
  return u.toString();
}
