// Sign-in gate — the Figma sign-in screen. Replaces the Streamlit context
// block. Fetches /api/manufacturer/config for the tenant + persona choices,
// renders two Selects, and "Sign in" sets the zustand store + redirects to
// /dashboard. Session-only auth: no token, no server validation — mirrors
// auth.py's mq_* session_state model.

import { useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { MicroscopeIcon, QmarkIcon } from "../components/icons/BioIcon";
import { Button } from "../components/ui/button";
import { Card } from "../components/ui/card";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "../components/ui/select";
import { useConfig } from "../lib/api";
import type { Persona } from "../lib/types";
import { useSession } from "../state/session";

export function SignIn() {
  const navigate = useNavigate();
  const { data, isLoading, error } = useConfig();
  const signIn = useSession((s) => s.signIn);
  const [tenantKey, setTenantKey] = useState<string | null>(null);
  const [persona, setPersona] = useState<Persona | null>(null);
  const [query, setQuery] = useState("");

  // The registry is the whole company ontology now (thousands of entries),
  // not the one-item tuple this screen was built against. A bare Select
  // cannot be used at that size, so filter as the user types and render a
  // bounded slice — the list is pre-sorted by alert count, so an empty query
  // shows the manufacturers that actually have alerts.
  const MAX_RENDERED = 50;
  const tenants = data?.tenants ?? [];
  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    const pool = q
      ? tenants.filter(
          (t) =>
            t.canonical.toLowerCase().includes(q) ||
            t.city.toLowerCase().includes(q) ||
            t.ontology_key.includes(q),
        )
      : tenants;
    return { shown: pool.slice(0, MAX_RENDERED), total: pool.length };
  }, [tenants, query]);

  const selected = tenants.find((t) => t.key === tenantKey) ?? null;
  // More than one raw name that is not simply a spelling variant means the
  // ontology merged separate companies under one key. Show it rather than
  // letting someone sign in to a silently-merged dashboard.
  const mergedNames = selected?.raw_names ?? [];

  const canSubmit = tenantKey && persona && data;

  const onSubmit = () => {
    if (!canSubmit) return;
    const tenant = data!.tenants.find((t) => t.key === tenantKey)!;
    signIn(tenant, persona!);
    navigate("/dashboard");
  };

  return (
    <div className="mx-auto max-w-[460px] pt-[12vh]">
      <Card className="mb-5 p-6">
        <div className="flex items-center gap-2 text-xl font-bold text-foreground">
          <QmarkIcon size={22} className="text-primary" />
          Q-engine
        </div>
        <p className="mt-1.5 text-xs text-muted-foreground">
          Manufacturer quality intelligence — root-cause analysis & CAPA.
        </p>
      </Card>

      <Card className="p-6">
        <div className="mb-4 flex items-center gap-2 text-base font-semibold text-foreground">
          <MicroscopeIcon size={18} className="text-primary" />
          Sign in
        </div>

        {isLoading && <p className="text-sm text-muted-foreground">Loading configuration…</p>}
        {error && (
          <p className="text-sm text-destructive">
            Could not reach the Q-engine API. {String(error.message)}
          </p>
        )}

        {data && (
          <div className="space-y-4">
            <div className="space-y-1.5">
              <label className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
                Manufacturer
                {data.tenant_count ? (
                  <span className="ml-1 font-normal normal-case tracking-normal">
                    ({data.tenant_count.toLocaleString()} registered)
                  </span>
                ) : null}
              </label>
              <input
                type="search"
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                placeholder="Search by name or city…"
                className="h-9 w-full rounded-md border border-input bg-background px-3 text-sm outline-none ring-offset-background placeholder:text-muted-foreground focus-visible:ring-2 focus-visible:ring-ring"
              />
              <Select value={tenantKey ?? undefined} onValueChange={setTenantKey}>
                <SelectTrigger>
                  <SelectValue placeholder="Select manufacturer" />
                </SelectTrigger>
                <SelectContent>
                  {filtered.shown.map((t) => (
                    <SelectItem key={t.key} value={t.key}>
                      {t.canonical} — {t.city}
                      {t.record_count ? ` · ${t.record_count} alerts` : ""}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
              {filtered.total > filtered.shown.length && (
                <p className="text-xs text-muted-foreground">
                  Showing {filtered.shown.length} of {filtered.total.toLocaleString()} matches
                  — keep typing to narrow.
                </p>
              )}
              {filtered.total === 0 && (
                <p className="text-xs text-muted-foreground">No manufacturer matches “{query}”.</p>
              )}
              {mergedNames.length > 1 && (
                <p className="text-xs text-amber-600 dark:text-amber-500">
                  ⚠️ This key covers {mergedNames.length} recorded spellings:{" "}
                  {mergedNames.slice(0, 4).join("; ")}
                  {mergedNames.length > 4 ? "; …" : ""}. If those are different
                  companies, their alerts are combined in this dashboard.
                </p>
              )}
            </div>

            <div className="space-y-1.5">
              <label className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
                Persona
              </label>
              <Select value={persona ?? undefined} onValueChange={(v) => setPersona(v as Persona)}>
                <SelectTrigger>
                  <SelectValue placeholder="Select persona" />
                </SelectTrigger>
                <SelectContent>
                  {data.personas.map((p) => (
                    <SelectItem key={p} value={p}>
                      {p}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>

            <Button className="w-full" disabled={!canSubmit} onClick={onSubmit}>
              Sign in
            </Button>
            <p className="text-xs text-muted-foreground">
              Session-only — no credentials are stored or validated.
            </p>
          </div>
        )}
      </Card>
    </div>
  );
}