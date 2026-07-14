import type { Me, RunState, RuntimeConfig } from "./types";

let config: RuntimeConfig = { apiBase: "", envLabel: "local" };
let csrfToken = "";

export async function loadConfig(): Promise<RuntimeConfig> {
  try {
    const res = await fetch("/config.json", { cache: "no-store" });
    if (res.ok) config = await res.json();
  } catch {
    // fall back to defaults (same-origin API)
  }
  return config;
}

export function setCsrfToken(token: string): void {
  csrfToken = token;
}

function url(path: string): string {
  return `${config.apiBase}${path}`;
}

export class Unauthorised extends Error {}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  if (init.method && init.method !== "GET") {
    headers.set("Content-Type", "application/json");
    headers.set("X-CSRF-Token", csrfToken);
  }
  const res = await fetch(url(path), { ...init, headers, credentials: "include" });
  if (res.status === 401) throw new Unauthorised("Not authenticated");
  if (!res.ok) throw new Error(`${res.status}: ${await res.text()}`);
  return (await res.json()) as T;
}

export async function getMe(): Promise<Me> {
  const me = await request<Me>("/api/me");
  setCsrfToken(me.csrf_token);
  return me;
}

export function loginUrl(): string {
  return url("/api/auth/login");
}

export async function logout(): Promise<void> {
  await request("/api/auth/logout", { method: "POST" });
}

export async function submitRequest(query: string): Promise<{ run_id: string }> {
  return request("/api/requests", { method: "POST", body: JSON.stringify({ query }) });
}

export async function getRun(runId: string): Promise<RunState> {
  return request<RunState>(`/api/runs/${runId}`);
}

export async function decideRun(
  runId: string,
  approve: boolean,
  comment: string,
): Promise<void> {
  await request(`/api/runs/${runId}/${approve ? "approve" : "reject"}`, {
    method: "POST",
    body: JSON.stringify({ comment }),
  });
}
