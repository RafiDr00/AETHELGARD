import { useAuthStore } from "@/state/authStore";

export type HttpMethod = "GET" | "POST";

export interface ApiErrorBody {
  detail?: string;
  error?: string;
  message?: string;
  code?: string;
  [key: string]: unknown;
}

export class AuthenticationError extends Error {
  constructor(message = "No API key set. Please start a new session.") {
    super(message);
    this.name = "AuthenticationError";
  }
}

export class ApiClientError<TDetails = ApiErrorBody> extends Error {
  public readonly status: number;
  public readonly statusText: string;
  public readonly method: HttpMethod;
  public readonly url: string;
  public readonly details?: TDetails;

  constructor(params: {
    status: number;
    statusText: string;
    method: HttpMethod;
    url: string;
    message: string;
    details?: TDetails;
  }) {
    super(params.message);
    this.name = "ApiClientError";
    this.status = params.status;
    this.statusText = params.statusText;
    this.method = params.method;
    this.url = params.url;
    this.details = params.details;
  }
}

const API_BASE =
  import.meta.env.VITE_API_BASE_URL ??
  (import.meta.env.DEV ? "" : "http://localhost:8000");

function resolveApiKey(explicitApiKey?: string): string {
  if (explicitApiKey) return explicitApiKey;
  const sessionApiKey = useAuthStore.getState().apiKey;
  if (sessionApiKey) return sessionApiKey;
  throw new AuthenticationError();
}

function buildHeaders(initHeaders?: HeadersInit, apiKey?: string): Headers {
  const headers = new Headers(initHeaders);
  if (!headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }
  const resolvedKey = resolveApiKey(apiKey); // throws AuthenticationError if no key in store
  headers.set("X-API-Key", resolvedKey);
  return headers;
}

async function parseResponseBody(response: Response): Promise<unknown> {
  const contentType = response.headers.get("content-type") ?? "";
  if (contentType.includes("application/json")) {
    return response.json();
  }
  const text = await response.text();
  return text.length > 0 ? text : null;
}

export interface ApiRequestOptions {
  headers?: HeadersInit;
  body?: unknown;
  apiKey?: string;
}

export async function apiRequest<TResponse>(
  method: HttpMethod,
  path: string,
  options: ApiRequestOptions = {},
): Promise<TResponse> {
  const url = `${API_BASE}${path}`;
  const response = await fetch(url, {
    method,
    headers: buildHeaders(options.headers, options.apiKey),
    body: options.body !== undefined ? JSON.stringify(options.body) : undefined,
  });

  const parsedBody = await parseResponseBody(response);

  if (!response.ok) {
    const details = (typeof parsedBody === "object" && parsedBody !== null
      ? (parsedBody as ApiErrorBody)
      : undefined);
    const message =
      details?.detail ?? details?.message ?? details?.error ?? `${response.status} ${response.statusText}`;

    throw new ApiClientError<ApiErrorBody>({
      status: response.status,
      statusText: response.statusText,
      method,
      url,
      message,
      details,
    });
  }

  return parsedBody as TResponse;
}

export function apiGet<TResponse>(path: string, options: Omit<ApiRequestOptions, "body"> = {}) {
  return apiRequest<TResponse>("GET", path, options);
}

export function apiPost<TResponse>(path: string, body?: unknown, options: Omit<ApiRequestOptions, "body"> = {}) {
  return apiRequest<TResponse>("POST", path, { ...options, body });
}
