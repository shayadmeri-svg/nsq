import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { Button, ErrorNote, Field } from "../../components/ui";
import { api, post } from "../../lib/api";
import { ROLE_LABEL } from "../../lib/format";
import { AuthLayout } from "./AuthLayout";

export function AcceptInvite() {
  const { token = "" } = useParams();
  const { data, error, isLoading } = useQuery({ queryKey: ["invite", token], queryFn: () => api<any>(`/api/auth/invite/${token}`) });
  const [name, setName] = useState("");
  const [pw, setPw] = useState("");
  const [pw2, setPw2] = useState("");
  const [err, setErr] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);
  const qc = useQueryClient();
  const nav = useNavigate();

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (pw !== pw2) return setErr(new Error("Passwords do not match."));
    setBusy(true);
    try {
      const r = await post<{ user: any }>("/api/auth/accept-invite", { token, name: name || data?.name, password: pw });
      qc.setQueryData(["me"], r.user);
      nav("/", { replace: true });
    } catch (e) {
      setErr(e);
    } finally {
      setBusy(false);
    }
  };

  return (
    <AuthLayout>
      {isLoading && <div className="text-sm text-ink-muted">Checking invite…</div>}
      {error && <ErrorNote error={error} />}
      {data && (
        <>
          <h2 className="font-display text-2xl font-extrabold tracking-tight">Join {data.org?.name ?? "NSQ Intelligence"}</h2>
          <p className="mt-1.5 text-sm text-ink-muted">You were invited as <b>{ROLE_LABEL[data.role]}</b> with {data.email}.</p>
          <form onSubmit={submit} className="mt-8 space-y-4">
            <Field label="Your name"><input className="input" value={name || data.name} onChange={(e) => setName(e.target.value)} required /></Field>
            <Field label="Password" hint="At least 8 characters."><input className="input" type="password" autoComplete="new-password" value={pw} onChange={(e) => setPw(e.target.value)} required /></Field>
            <Field label="Confirm password"><input className="input" type="password" autoComplete="new-password" value={pw2} onChange={(e) => setPw2(e.target.value)} required /></Field>
            <ErrorNote error={err} />
            <Button type="submit" loading={busy} className="h-11 w-full">Create account</Button>
          </form>
        </>
      )}
    </AuthLayout>
  );
}
