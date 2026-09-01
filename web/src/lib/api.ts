// Data-fetching wrappers + react-query hooks for the manufacturer_api.
// All requests go through the Vite dev proxy (/api -> :8001) or the nginx
// gateway (same origin in prod), so a relative base is correct.

import { useQuery } from "@tanstack/react-query";
import type {
  ConfigPayload,
  DashboardPayload,
  DiagnosticsPayload,
  Persona,
} from "./types";

const BASE = import.meta.env.VITE_MANUFACTURER_API_URL ?? "";

async function getJSON<T>(path: string): Promise<T> {
  const res = await fetch(`${BASE}${path}`, { headers: { Accept: "application/json" } });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = body.detail ?? detail;
    } catch {
      /* keep statusText */
    }
    throw new Error(`${res.status}: ${detail}`);
  }
  return res.json() as Promise<T>;
}

export function fetchConfig(): Promise<ConfigPayload> {
  return getJSON<ConfigPayload>("/api/manufacturer/config");
}

export function fetchDashboard(tenantKey: string): Promise<DashboardPayload> {
  return getJSON<DashboardPayload>(`/api/manufacturer/${tenantKey}/dashboard`);
}

export function fetchDiagnostics(
  tenantKey: string,
  issueId: string,
  persona: Persona,
): Promise<DiagnosticsPayload> {
  return getJSON<DiagnosticsPayload>(
    `/api/manufacturer/${tenantKey}/diagnostics/${encodeURIComponent(issueId)}?persona=${persona}`,
  );
}

// --- react-query hooks -----------------------------------------------------

export function useConfig() {
  return useQuery({ queryKey: ["config"], queryFn: fetchConfig, staleTime: Infinity });
}

export function useDashboard(tenantKey: string | null) {
  return useQuery({
    queryKey: ["dashboard", tenantKey],
    queryFn: () => fetchDashboard(tenantKey as string),
    enabled: !!tenantKey,
  });
}

export function useDiagnostics(
  tenantKey: string | null,
  issueId: string | null,
  persona: Persona | null,
) {
  return useQuery({
    queryKey: ["diagnostics", tenantKey, issueId, persona],
    queryFn: () => fetchDiagnostics(tenantKey as string, issueId as string, persona as Persona),
    enabled: !!tenantKey && !!issueId && !!persona,
  });
}