import { useQueryClient } from "@tanstack/react-query";
import { KeyRound, ShieldAlert } from "lucide-react";
import { useState } from "react";
import { useSearchParams } from "react-router-dom";
import { Button, Card, CardHeader, ErrorNote, Field, PageHeader } from "../components/ui";
import { useToast } from "../components/ui/toast";
import { post } from "../lib/api";
import { fmtDateTime, ROLE_LABEL } from "../lib/format";
import { useMe } from "../lib/session";

export function Account() {
  const { data: me } = useMe();
  const [sp] = useSearchParams();
  const [cur, setCur] = useState("");
  const [pw, setPw] = useState("");
  const [pw2, setPw2] = useState("");
  const [err, setErr] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);
  const toast = useToast();
  const qc = useQueryClient();
  if (!me) return null;

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (pw !== pw2) return setErr(new Error("New passwords do not match."));
    setBusy(true);
    setErr(null);
    try {
      await post("/api/auth/change-password", { current_password: cur, new_password: pw });
      setCur(""); setPw(""); setPw2("");
      toast("Password updated. Other sessions were signed out.");
      qc.invalidateQueries({ queryKey: ["me"] });
    } catch (e) {
      setErr(e);
    } finally {
      setBusy(false);
    }
  };

  return (
    <>
      <PageHeader eyebrow="Account" title={me.name || me.email} subtitle={`${ROLE_LABEL[me.role]}${me.org ? ` · ${me.org.name}` : ""} · last sign-in ${fmtDateTime(me.last_login_at)}`} />
      {(me.must_change_password || sp.get("first")) && (
        <div className="mb-5 flex items-center gap-3 rounded-2xl bg-amber-50 px-4 py-3 text-sm text-amber-800 ring-1 ring-inset ring-amber-200">
          <ShieldAlert size={18} /> Set a new password to continue — your current one was issued by an administrator.
        </div>
      )}
      <div className="grid gap-5 lg:grid-cols-2">
        <Card>
          <CardHeader icon={<KeyRound size={16} />} title="Change password" subtitle="At least 8 characters. Signs out your other sessions." />
          <form onSubmit={submit} className="space-y-4 p-5">
            <Field label="Current password"><input className="input" type="password" autoComplete="current-password" value={cur} onChange={(e) => setCur(e.target.value)} required /></Field>
            <Field label="New password"><input className="input" type="password" autoComplete="new-password" value={pw} onChange={(e) => setPw(e.target.value)} required /></Field>
            <Field label="Confirm new password"><input className="input" type="password" autoComplete="new-password" value={pw2} onChange={(e) => setPw2(e.target.value)} required /></Field>
            <ErrorNote error={err} />
            <Button type="submit" loading={busy}>Update password</Button>
          </form>
        </Card>
        <Card delay={0.05} className="p-5">
          <div className="label">Profile</div>
          <dl className="mt-3 space-y-3 text-sm">
            <div className="flex justify-between"><dt className="text-ink-muted">Email</dt><dd className="font-medium">{me.email}</dd></div>
            <div className="flex justify-between"><dt className="text-ink-muted">Role</dt><dd className="font-medium">{ROLE_LABEL[me.role]}</dd></div>
            <div className="flex justify-between"><dt className="text-ink-muted">Persona</dt><dd className="font-medium">{me.persona}</dd></div>
            <div className="flex justify-between"><dt className="text-ink-muted">Organisation</dt><dd className="font-medium">{me.org?.name ?? "Platform"}</dd></div>
          </dl>
        </Card>
      </div>
    </>
  );
}
