import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Building2, Check, ExternalLink, Pencil, Plus, Search, X } from "lucide-react";
import { motion } from "motion/react";
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { Badge, Button, Drawer, Empty, ErrorNote, Field, itemVariants, listVariants, PageHeader, PageSkeleton } from "../../components/ui";
import { useToast } from "../../components/ui/toast";
import { api, patch, post } from "../../lib/api";
import { cn } from "../../lib/cn";

function ManufacturerPicker({ value, onChange }: { value: string[]; onChange: (v: string[]) => void }) {
  const [q, setQ] = useState("");
  const [dq, setDq] = useState("");
  useEffect(() => { const t = setTimeout(() => setDq(q), 250); return () => clearTimeout(t); }, [q]);
  const { data, isFetching } = useQuery({ queryKey: ["mfg", dq], queryFn: () => api<any>(`/api/admin/manufacturers?q=${encodeURIComponent(dq)}&limit=12`) });
  const toggle = (k: string) => onChange(value.includes(k) ? value.filter((x) => x !== k) : [...value, k]);
  return (
    <div>
      {value.length > 0 && <div className="mb-2 flex flex-wrap gap-1.5">{value.map((k) => <button key={k} onClick={() => toggle(k)} className="flex items-center gap-1 rounded-full bg-brand-600 px-2.5 py-1 text-xs font-semibold text-white">{k}<X size={12} /></button>)}</div>}
      <div className="relative"><Search size={15} className="absolute left-3 top-3 text-ink-faint" /><input className="input pl-9" placeholder="Search CDSCO manufacturer names…" value={q} onChange={(e) => setQ(e.target.value)} /></div>
      <div className={cn("mt-2 max-h-72 overflow-y-auto rounded-xl border border-line scrollbar-thin", isFetching && "opacity-60")}>
        {data?.manufacturers.map((m: any) => {
          const on = value.includes(m.key);
          return (
            <button key={m.key} onClick={() => toggle(m.key)} className={cn("flex w-full items-start justify-between gap-3 border-b border-line/60 px-3 py-2.5 text-left last:border-0 hover:bg-slate-50", on && "bg-brand-50/60")}>
              <div className="min-w-0">
                <div className="text-sm font-medium">{m.name} <span className="text-xs text-ink-faint">· {m.city || m.state}</span></div>
                <div className="truncate text-[11px] text-ink-muted" title={m.raw_names.join(" | ")}>key “{m.key}” · {m.raw_names.length} spelling(s)</div>
                {m.raw_names.length > 1 && <div className="truncate text-[11px] text-amber-700">{m.raw_names.slice(0, 3).join(" | ")}</div>}
              </div>
              <div className="flex shrink-0 items-center gap-2"><Badge tone="rose">{m.alerts}</Badge>{on && <Check size={16} className="text-brand-600" />}</div>
            </button>
          );
        })}
      </div>
      <p className="mt-1.5 text-xs text-ink-muted">Check the spellings: one key can merge different companies with similar names.</p>
    </div>
  );
}

function OrgEditor({ org, onClose }: { org: any | null | undefined; onClose: () => void }) {
  const open = org !== undefined;
  const plants = useQuery({ queryKey: ["all-plants"], queryFn: () => api<any>("/api/admin/plants"), enabled: open });
  const [f, setF] = useState<any>({});
  const [err, setErr] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);
  const qc = useQueryClient();
  const toast = useToast();
  useEffect(() => {
    if (open) setF({ name: org?.name ?? "", city: org?.city ?? "", country: org?.country ?? "India", notes: org?.notes ?? "", ontology_keys: org?.ontology_keys ?? [], plant_ids: org?.plant_ids ?? [], is_active: org?.is_active ?? true });
    setErr(null);
  }, [open, org]);

  const save = async () => {
    setBusy(true);
    setErr(null);
    try {
      if (org) await patch(`/api/admin/orgs/${org.slug}`, f);
      else await post("/api/admin/orgs", f);
      qc.invalidateQueries({ queryKey: ["admin-orgs"] });
      qc.invalidateQueries({ queryKey: ["my-orgs"] });
      qc.invalidateQueries({ queryKey: ["org"] });
      toast(org ? "Organisation updated" : "Organisation created");
      onClose();
    } catch (e) {
      setErr(e);
    } finally {
      setBusy(false);
    }
  };
  const togglePlant = (id: string) => setF({ ...f, plant_ids: f.plant_ids.includes(id) ? f.plant_ids.filter((x: string) => x !== id) : [...f.plant_ids, id] });

  return (
    <Drawer open={open} onClose={onClose} title={org ? `Edit ${org.name}` : "New organisation"} subtitle="Link the CDSCO manufacturer identities and the plants this organisation operates." width={780}>
      <div className="space-y-6">
        <div className="grid gap-4 sm:grid-cols-3">
          <Field label="Name"><input className="input" value={f.name ?? ""} onChange={(e) => setF({ ...f, name: e.target.value })} /></Field>
          <Field label="City"><input className="input" value={f.city ?? ""} onChange={(e) => setF({ ...f, city: e.target.value })} /></Field>
          <Field label="Country"><input className="input" value={f.country ?? ""} onChange={(e) => setF({ ...f, country: e.target.value })} /></Field>
        </div>
        <Field label="CDSCO manufacturer identities"><ManufacturerPicker value={f.ontology_keys ?? []} onChange={(v) => setF({ ...f, ontology_keys: v })} /></Field>
        <Field label="Plants">
          <div className="grid gap-2 sm:grid-cols-2">
            {plants.data?.plants.map((p: any) => {
              const on = f.plant_ids?.includes(p.asset_id);
              const taken = p.org && p.org !== org?.slug;
              return (
                <button key={p.asset_id} onClick={() => togglePlant(p.asset_id)} className={cn("rounded-xl border p-3 text-left transition", on ? "border-brand-400 bg-brand-50/60" : "border-line hover:bg-slate-50")}>
                  <div className="flex items-center justify-between gap-2"><span className="text-sm font-medium">{p.name}</span>{on && <Check size={15} className="text-brand-600" />}</div>
                  <div className="mt-0.5 text-[11px] text-ink-muted">{p.city} · {p.certifications.join(", ") || "no certs"} · {p.capabilities} caps{p.custom ? " · custom" : ""}{taken ? ` · also on ${p.org}` : ""}</div>
                </button>
              );
            })}
          </div>
        </Field>
        <Field label="Notes"><textarea className="input h-20 py-2" value={f.notes ?? ""} onChange={(e) => setF({ ...f, notes: e.target.value })} /></Field>
        {org && <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={!!f.is_active} onChange={(e) => setF({ ...f, is_active: e.target.checked })} /> Active (members can sign in and view)</label>}
        <ErrorNote error={err} />
        <div className="sticky bottom-0 -mx-6 flex justify-end gap-2 border-t border-line bg-white px-6 py-3">
          <Button variant="secondary" onClick={onClose}>Cancel</Button>
          <Button loading={busy} onClick={save} disabled={!f.name?.trim()}>{org ? "Save" : "Create organisation"}</Button>
        </div>
      </div>
    </Drawer>
  );
}

export function Orgs() {
  const { data, isLoading, error } = useQuery({ queryKey: ["admin-orgs"], queryFn: () => api<any>("/api/admin/orgs") });
  const [editing, setEditing] = useState<any | null | undefined>(undefined);
  if (isLoading) return <PageSkeleton />;
  if (error) return <ErrorNote error={error} />;
  return (
    <>
      <PageHeader eyebrow="Platform" title="Organisations" subtitle="Each pharma company you demo to: its CDSCO manufacturer identities, its plants and its people." actions={<Button onClick={() => setEditing(null)}><Plus size={16} /> New organisation</Button>} />
      {data.orgs.length === 0 && <Empty icon={<Building2 />} title="No organisations yet">Create one, link its manufacturer names from the CDSCO data, attach its plants, then invite its users.</Empty>}
      <motion.div variants={listVariants} initial="hidden" animate="show" className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
        {data.orgs.map((o: any) => (
          <motion.div variants={itemVariants} key={o.slug} className="card group p-5">
            <div className="flex items-start justify-between gap-3">
              <div>
                <div className="font-display text-base font-bold">{o.name}</div>
                <div className="text-xs text-ink-muted">{[o.city, o.country].filter(Boolean).join(", ")} · /{o.slug}</div>
              </div>
              {!o.is_active && <Badge tone="rose">Disabled</Badge>}
            </div>
            <div className="mt-4 grid grid-cols-3 gap-2 text-center">
              {[["Alerts", o.stats.alerts], ["Plants", o.stats.plants], ["Users", o.stats.users]].map(([l, v]) => <div key={l as string} className="rounded-xl bg-slate-50 py-2"><div className="font-display text-lg font-extrabold">{v}</div><div className="text-[11px] text-ink-muted">{l}</div></div>)}
            </div>
            <div className="mt-3 flex flex-wrap gap-1">{o.ontology_keys.slice(0, 4).map((k: string) => <Badge key={k}>{k}</Badge>)}{o.ontology_keys.length > 4 && <Badge>+{o.ontology_keys.length - 4}</Badge>}</div>
            <div className="mt-4 flex gap-2">
              <Link to={`/o/${o.slug}`} className="inline-flex h-8 items-center gap-1.5 rounded-xl bg-ink px-3 text-xs font-medium text-white"><ExternalLink size={13} /> Open dashboard</Link>
              <Button size="sm" variant="secondary" onClick={() => setEditing(o)}><Pencil size={13} /> Edit</Button>
              <Link to={`/o/${o.slug}/team`} className="inline-flex h-8 items-center rounded-xl px-3 text-xs font-medium text-ink-soft hover:bg-slate-100">Team</Link>
            </div>
          </motion.div>
        ))}
      </motion.div>
      <OrgEditor org={editing} onClose={() => setEditing(undefined)} />
    </>
  );
}
