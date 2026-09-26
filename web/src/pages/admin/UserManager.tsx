import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Copy, KeyRound, LogOut, MailPlus, MoreHorizontal, Search, UserCheck, UserX } from "lucide-react";
import { AnimatePresence, motion } from "motion/react";
import { useState } from "react";
import { Badge, Button, Card, ErrorNote, Field, Modal, Skeleton } from "../../components/ui";
import { useToast } from "../../components/ui/toast";
import { api, del, patch, post } from "../../lib/api";
import { fmtDate, ROLE_LABEL, timeAgo } from "../../lib/format";
import { useMe } from "../../lib/session";

const ROLE_TONE: Record<string, "rose" | "indigo" | "brand" | "slate"> = { super_admin: "rose", admin: "indigo", org_admin: "brand", member: "slate" };

function InviteModal({ open, onClose, orgSlug, roles, personas }: { open: boolean; onClose: () => void; orgSlug?: string; roles: string[]; personas: string[] }) {
  const { data: me } = useMe();
  const orgs = useQuery({ queryKey: ["my-orgs"], queryFn: () => api<any>("/api/orgs"), enabled: open && !!me?.is_platform });
  const [f, setF] = useState({ email: "", name: "", role: orgSlug ? "member" : "member", persona: "QA", org_slug: orgSlug ?? "", password: "", mode: "invite" });
  const [err, setErr] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);
  const [link, setLink] = useState<string | null>(null);
  const qc = useQueryClient();
  const toast = useToast();
  const needsOrg = f.role === "member" || f.role === "org_admin";

  const submit = async () => {
    setBusy(true);
    setErr(null);
    try {
      const body: any = { email: f.email, name: f.name, role: f.role, persona: f.persona, org_slug: needsOrg ? (f.org_slug || orgSlug) : null };
      if (f.mode === "password") body.password = f.password;
      const r = await post<any>("/api/admin/users", body);
      qc.invalidateQueries({ queryKey: ["users"] });
      qc.invalidateQueries({ queryKey: ["invites"] });
      if (r.invite) setLink(r.invite.link);
      else { toast(`${f.email} can now sign in. They'll be asked to change the password.`); close(); }
    } catch (e) {
      setErr(e);
    } finally {
      setBusy(false);
    }
  };
  const close = () => { setLink(null); setErr(null); setF({ ...f, email: "", name: "", password: "" }); onClose(); };

  return (
    <Modal open={open} onClose={close} title={link ? "Invite ready" : "Add a user"} footer={link ? <Button onClick={close}>Done</Button> : <><Button variant="secondary" onClick={close}>Cancel</Button><Button loading={busy} onClick={submit} disabled={!f.email}>{f.mode === "invite" ? "Create invite" : "Create user"}</Button></>}>
      {link ? (
        <div className="space-y-3">
          <p className="text-sm text-ink-soft">Send this link to <b>{f.email}</b>. It works once and expires in 7 days.</p>
          <div className="flex gap-2"><input readOnly value={link} className="input font-mono text-xs" onFocus={(e) => e.target.select()} /><Button variant="secondary" onClick={() => { navigator.clipboard.writeText(link); toast("Link copied"); }}><Copy size={15} /></Button></div>
        </div>
      ) : (
        <div className="space-y-4">
          <div className="grid gap-4 sm:grid-cols-2">
            <Field label="Email"><input className="input" type="email" value={f.email} onChange={(e) => setF({ ...f, email: e.target.value })} /></Field>
            <Field label="Name"><input className="input" value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} /></Field>
            <Field label="Role"><select className="input" value={f.role} onChange={(e) => setF({ ...f, role: e.target.value })}>{roles.map((r) => <option key={r} value={r}>{ROLE_LABEL[r]}</option>)}</select></Field>
            <Field label="Persona" hint="Orders the diagnosis sections."><select className="input" value={f.persona} onChange={(e) => setF({ ...f, persona: e.target.value })}>{personas.map((p) => <option key={p}>{p}</option>)}</select></Field>
          </div>
          {needsOrg && !orgSlug && me?.is_platform && (
            <Field label="Organisation"><select className="input" value={f.org_slug} onChange={(e) => setF({ ...f, org_slug: e.target.value })}><option value="">Select…</option>{orgs.data?.orgs.map((o: any) => <option key={o.slug} value={o.slug}>{o.name}</option>)}</select></Field>
          )}
          <div className="flex gap-2 rounded-xl bg-slate-100 p-1 text-xs font-semibold">
            {[["invite", "Send invite link"], ["password", "Set a temporary password"]].map(([k, l]) => <button key={k} onClick={() => setF({ ...f, mode: k })} className={`flex-1 rounded-lg py-1.5 transition ${f.mode === k ? "bg-white shadow-sm" : "text-ink-muted"}`}>{l}</button>)}
          </div>
          {f.mode === "password" && <Field label="Temporary password" hint="At least 8 characters; they must change it at first sign-in."><input className="input" type="text" value={f.password} onChange={(e) => setF({ ...f, password: e.target.value })} /></Field>}
          <ErrorNote error={err} />
        </div>
      )}
    </Modal>
  );
}

function RowMenu({ u, roles, onDone }: { u: any; roles: string[]; onDone: () => void }) {
  const [open, setOpen] = useState(false);
  const [temp, setTemp] = useState<string | null>(null);
  const toast = useToast();
  const act = async (fn: () => Promise<any>, msg: string) => {
    setOpen(false);
    try { await fn(); toast(msg); onDone(); } catch (e) { toast((e as Error).message, "error"); }
  };
  return (
    <div className="relative">
      <button onClick={() => setOpen((o) => !o)} className="rounded-lg p-1.5 text-ink-muted hover:bg-slate-100"><MoreHorizontal size={16} /></button>
      {open && <div className="fixed inset-0 z-30" onClick={() => setOpen(false)} />}
      <AnimatePresence>
        {open && (
            <motion.div key="menu" initial={{ opacity: 0, scale: 0.97, y: -4 }} animate={{ opacity: 1, scale: 1, y: 0 }} exit={{ opacity: 0 }} className="absolute right-0 z-40 w-56 rounded-xl bg-white p-1.5 text-sm shadow-lift ring-1 ring-line">
              <div className="px-2.5 pb-1 pt-1.5 text-[11px] font-semibold uppercase tracking-wider text-ink-faint">Change role</div>
              {roles.filter((r) => r !== u.role).map((r) => <button key={r} onClick={() => act(() => patch(`/api/admin/users/${u.id}`, { role: r }), `Role changed to ${ROLE_LABEL[r]}`)} className="block w-full rounded-lg px-2.5 py-1.5 text-left hover:bg-slate-50">{ROLE_LABEL[r]}</button>)}
              <div className="my-1 border-t border-line" />
              <button onClick={async () => { setOpen(false); try { const r = await post<any>(`/api/admin/users/${u.id}/reset-password`); setTemp(r.temporary_password); onDone(); } catch (e) { toast((e as Error).message, "error"); } }} className="flex w-full items-center gap-2 rounded-lg px-2.5 py-1.5 hover:bg-slate-50"><KeyRound size={14} /> Reset password</button>
              <button onClick={() => act(() => post(`/api/admin/users/${u.id}/revoke-sessions`), "Signed out everywhere")} className="flex w-full items-center gap-2 rounded-lg px-2.5 py-1.5 hover:bg-slate-50"><LogOut size={14} /> Sign out everywhere</button>
              <button onClick={() => act(() => patch(`/api/admin/users/${u.id}`, { is_active: !u.is_active }), u.is_active ? "User deactivated" : "User reactivated")} className={`flex w-full items-center gap-2 rounded-lg px-2.5 py-1.5 ${u.is_active ? "text-rose-600 hover:bg-rose-50" : "hover:bg-slate-50"}`}>{u.is_active ? <><UserX size={14} /> Deactivate</> : <><UserCheck size={14} /> Reactivate</>}</button>
            </motion.div>
        )}
      </AnimatePresence>
      <Modal open={!!temp} onClose={() => setTemp(null)} title="Temporary password" footer={<Button onClick={() => setTemp(null)}>Done</Button>}>
        <p className="mb-3 text-sm text-ink-soft">Give this to <b>{u.email}</b>. It is shown once; they must change it at sign-in.</p>
        <div className="flex gap-2"><input readOnly value={temp ?? ""} className="input font-mono" /><Button variant="secondary" onClick={() => { navigator.clipboard.writeText(temp ?? ""); toast("Copied"); }}><Copy size={15} /></Button></div>
      </Modal>
    </div>
  );
}

export function UserManager({ orgSlug }: { orgSlug?: string }) {
  const { data: me } = useMe();
  const [q, setQ] = useState("");
  const [inviting, setInviting] = useState(false);
  const qc = useQueryClient();
  const params = new URLSearchParams({ q, ...(orgSlug ? { org: orgSlug } : {}) });
  const users = useQuery({ queryKey: ["users", orgSlug, q], queryFn: () => api<any>(`/api/admin/users?${params}`) });
  const invites = useQuery({ queryKey: ["invites"], queryFn: () => api<any>("/api/admin/invites") });
  const toast = useToast();
  const refresh = () => qc.invalidateQueries({ queryKey: ["users"] });
  const roles: string[] = users.data?.assignable_roles ?? [];
  const pending = (invites.data?.invites ?? []).filter((i: any) => !orgSlug || i.org?.slug === orgSlug);

  return (
    <>
      <Card className="overflow-hidden">
        <div className="flex flex-wrap items-center justify-between gap-3 px-5 py-4">
          <div className="relative"><Search size={15} className="absolute left-3 top-2.5 text-ink-faint" /><input className="input h-9 w-72 pl-9" placeholder="Search name or email" value={q} onChange={(e) => setQ(e.target.value)} /></div>
          <Button onClick={() => setInviting(true)}><MailPlus size={16} /> Add user</Button>
        </div>
        {users.isLoading ? <div className="space-y-2 p-5">{[0, 1, 2].map((i) => <Skeleton key={i} className="h-12" />)}</div> : (
          <table className="w-full text-sm">
            <thead><tr className="border-y border-line bg-slate-50/70 text-left text-[11px] font-semibold uppercase tracking-wider text-ink-muted">
              <th className="px-5 py-2.5">User</th><th className="px-3 py-2.5">Role</th>{!orgSlug && <th className="px-3 py-2.5">Organisation</th>}<th className="px-3 py-2.5">Persona</th><th className="px-3 py-2.5">Last sign-in</th><th className="w-10 px-5 py-2.5" />
            </tr></thead>
            <tbody>
              {users.data?.users.map((u: any, i: number) => (
                <motion.tr key={u.id} initial={{ opacity: 0 }} animate={{ opacity: 1 }} transition={{ delay: i * 0.02 }} className={`border-b border-line/70 ${u.is_active ? "" : "opacity-50"}`}>
                  <td className="px-5 py-3">
                    <div className="flex items-center gap-3">
                      <span className="grid h-8 w-8 shrink-0 place-items-center rounded-full bg-gradient-to-br from-slate-200 to-slate-300 text-xs font-bold text-slate-700">{(u.name || u.email)[0].toUpperCase()}</span>
                      <div><div className="font-medium">{u.name || "—"}</div><div className="text-xs text-ink-muted">{u.email}</div></div>
                    </div>
                  </td>
                  <td className="px-3 py-3"><Badge tone={ROLE_TONE[u.role]}>{ROLE_LABEL[u.role]}</Badge>{!u.is_active && <Badge className="ml-1">Disabled</Badge>}{u.must_change_password && <Badge tone="amber" className="ml-1">Temp password</Badge>}</td>
                  {!orgSlug && <td className="px-3 py-3 text-xs">{u.org?.name ?? <span className="text-ink-faint">Platform</span>}</td>}
                  <td className="px-3 py-3 text-xs">{u.persona}</td>
                  <td className="px-3 py-3 text-xs text-ink-muted" title={u.last_login_at ?? ""}>{timeAgo(u.last_login_at)}</td>
                  <td className="px-5 py-3 text-right">{u.id !== me?.id && (me?.role === "super_admin" || u.role !== "super_admin") && <RowMenu u={u} roles={roles} onDone={refresh} />}</td>
                </motion.tr>
              ))}
            </tbody>
          </table>
        )}
      </Card>

      {pending.length > 0 && (
        <Card delay={0.1} className="mt-5 p-5">
          <div className="label mb-3">Pending invites</div>
          <ul className="divide-y divide-line text-sm">
            {pending.map((i: any) => (
              <li key={i.id} className="flex items-center justify-between gap-3 py-2.5">
                <div><span className="font-medium">{i.email}</span> <span className="text-xs text-ink-muted">· {ROLE_LABEL[i.role]}{i.org ? ` · ${i.org.name}` : ""} · {i.expired ? "expired" : `expires ${fmtDate(i.expires_at)}`}</span></div>
                <Button size="sm" variant="ghost" onClick={async () => { await del(`/api/admin/invites/${i.id}`); qc.invalidateQueries({ queryKey: ["invites"] }); toast("Invite revoked"); }}>Revoke</Button>
              </li>
            ))}
          </ul>
        </Card>
      )}
      <InviteModal open={inviting} onClose={() => setInviting(false)} orgSlug={orgSlug} roles={roles} personas={users.data?.personas ?? ["QA", "Regulatory", "Executive"]} />
    </>
  );
}
