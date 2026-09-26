import { useQueryClient } from "@tanstack/react-query";
import { ArrowRight, Lock, Mail } from "lucide-react";
import { useState } from "react";
import { Navigate, useNavigate, useSearchParams } from "react-router-dom";
import { Button, ErrorNote } from "../../components/ui";
import { post } from "../../lib/api";
import { useMe } from "../../lib/session";
import { AuthLayout } from "./AuthLayout";

export function Login() {
  const { data: me } = useMe();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [err, setErr] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);
  const qc = useQueryClient();
  const nav = useNavigate();
  const [sp] = useSearchParams();
  if (me) return <Navigate to={sp.get("next") || "/"} replace />;

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setErr(null);
    try {
      const r = await post<{ user: any }>("/api/auth/login", { email, password });
      qc.setQueryData(["me"], r.user);
      nav(sp.get("next") || "/", { replace: true });
    } catch (e) {
      setErr(e);
    } finally {
      setBusy(false);
    }
  };

  return (
    <AuthLayout>
      <h2 className="font-display text-2xl font-extrabold tracking-tight">Sign in</h2>
      <p className="mt-1.5 text-sm text-ink-muted">Use the email your administrator invited.</p>
      <form onSubmit={submit} className="mt-8 space-y-4">
        <label className="block">
          <span className="label">Email</span>
          <div className="relative mt-1.5">
            <Mail size={16} className="absolute left-3 top-3 text-ink-faint" />
            <input className="input pl-9" type="email" autoComplete="email" required value={email} onChange={(e) => setEmail(e.target.value)} placeholder="you@company.com" />
          </div>
        </label>
        <label className="block">
          <span className="label">Password</span>
          <div className="relative mt-1.5">
            <Lock size={16} className="absolute left-3 top-3 text-ink-faint" />
            <input className="input pl-9" type="password" autoComplete="current-password" required value={password} onChange={(e) => setPassword(e.target.value)} placeholder="••••••••" />
          </div>
        </label>
        <ErrorNote error={err} />
        <Button type="submit" loading={busy} className="h-11 w-full">Continue <ArrowRight size={16} /></Button>
      </form>
      <p className="mt-8 text-xs text-ink-muted">No account? Ask your organisation admin for an invite link.</p>
    </AuthLayout>
  );
}
