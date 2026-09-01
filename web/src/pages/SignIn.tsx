// Sign-in gate — the Figma sign-in screen. Replaces the Streamlit context
// block. Fetches /api/manufacturer/config for the tenant + persona choices,
// renders two Selects, and "Sign in" sets the zustand store + redirects to
// /dashboard. Session-only auth: no token, no server validation — mirrors
// auth.py's mq_* session_state model.

import { useState } from "react";
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
              </label>
              <Select value={tenantKey ?? undefined} onValueChange={setTenantKey}>
                <SelectTrigger>
                  <SelectValue placeholder="Select manufacturer" />
                </SelectTrigger>
                <SelectContent>
                  {data.tenants.map((t) => (
                    <SelectItem key={t.key} value={t.key}>
                      {t.canonical} — {t.city}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
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