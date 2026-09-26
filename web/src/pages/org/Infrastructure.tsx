import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, ExternalLink, Factory, FileSearch, MapPin, Pencil, Plus, ShieldCheck } from "lucide-react";
import { motion } from "motion/react";
import { useMemo, useState } from "react";
import { Badge, Bar, Button, Card, Drawer, Empty, ErrorNote, Field, PageHeader, PageSkeleton } from "../../components/ui";
import { useToast } from "../../components/ui/toast";
import { Estimate } from "../../components/ui/Estimate";
import { api, post, put } from "../../lib/api";
import { FdaBadges, SiteDetail } from "../admin/Sites";
import { cn } from "../../lib/cn";
import { titleCase } from "../../lib/format";
import { useOrg, useOrgData } from "./common";

const CERTS = ["WHO_GMP", "EU_GMP", "USFDA", "PICS", "UK_MHRA", "TGA", "HEALTH_CANADA", "PMDA", "ANVISA", "BIOLOGIC_GMP", "CYTOTOXIC_LICENSING", "EU_GMP_ANNEX_1", "COFEPRIS", "DIGEMID"];
const CONTAINMENT = ["standard", "potent", "cytotoxic", "biologic_GMP"];

function PlantEditor({ slug, plant, taxonomy, onClose }: { slug: string; plant: any | null | undefined; taxonomy: any[]; onClose: () => void }) {
  const open = plant !== undefined;
  const isNew = plant === null;
  const [form, setForm] = useState<any>(null);
  const [filter, setFilter] = useState("");
  const [err, setErr] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);
  const qc = useQueryClient();
  const toast = useToast();

  const init = useMemo(() => {
    if (!open) return null;
    return {
      name: plant?.site_name ?? "", city: plant?.city ?? "", state: plant?.state ?? "",
      containment_class: plant?.containment_class ?? "standard",
      certifications: new Set<string>((plant?.certifications_active ?? []).map((c: string) => c.toUpperCase())),
      capabilities: new Set<string>(plant?.capabilities ?? []),
    };
  }, [open, plant]);
  const f = form ?? init;
  if (!f) return <Drawer open={false} onClose={onClose} title="">{null}</Drawer>;
  const set = (patch: any) => setForm({ ...f, ...patch });
  const toggle = (key: "certifications" | "capabilities", v: string) => {
    const s = new Set(f[key]);
    s.has(v) ? s.delete(v) : s.add(v);
    set({ [key]: s });
  };

  const save = async () => {
    setBusy(true);
    setErr(null);
    const body = { name: f.name, city: f.city, state: f.state, containment_class: f.containment_class, certifications: [...f.certifications], capabilities: [...f.capabilities] };
    try {
      if (isNew) await post(`/api/orgs/${slug}/plants`, body);
      else await put(`/api/orgs/${slug}/plants/${plant.asset_id}`, body);
      await qc.invalidateQueries({ queryKey: ["org", slug] });
      toast(isNew ? "Plant added — opportunities and EU checks are recalculated." : "Plant updated.");
      setForm(null);
      onClose();
    } catch (e) {
      setErr(e);
    } finally {
      setBusy(false);
    }
  };

  const close = () => { setForm(null); onClose(); };
  return (
    <Drawer open={open} onClose={close} title={isNew ? "Add a plant" : `Edit ${plant?.site_name}`} subtitle="Capabilities and certifications drive the patent-fit and EU checks." width={820}>
      <div className="space-y-6">
        <div className="grid gap-4 sm:grid-cols-3">
          <Field label="Plant name"><input className="input" value={f.name} onChange={(e) => set({ name: e.target.value })} placeholder="e.g. Baddi OSD Unit 2" /></Field>
          <Field label="City"><input className="input" value={f.city} onChange={(e) => set({ city: e.target.value })} /></Field>
          <Field label="State"><input className="input" value={f.state} onChange={(e) => set({ state: e.target.value })} /></Field>
        </div>
        <Field label="Containment class">
          <div className="flex flex-wrap gap-2">
            {CONTAINMENT.map((c) => <button key={c} type="button" onClick={() => set({ containment_class: c })} className={cn("rounded-full px-3 py-1.5 text-xs font-semibold ring-1 ring-inset transition", f.containment_class === c ? "bg-ink text-white ring-ink" : "bg-white ring-line hover:bg-slate-50")}>{titleCase(c)}</button>)}
          </div>
        </Field>
        <Field label="Active certifications">
          <div className="flex flex-wrap gap-2">
            {CERTS.map((c) => {
              const on = f.certifications.has(c);
              return <button key={c} type="button" onClick={() => toggle("certifications", c)} className={cn("flex items-center gap-1 rounded-full px-3 py-1.5 text-xs font-semibold ring-1 ring-inset transition", on ? "bg-brand-600 text-white ring-brand-600" : "bg-white ring-line hover:bg-slate-50")}>{on && <Check size={12} />}{c.replace(/_/g, " ")}</button>;
            })}
          </div>
        </Field>
        <div>
          <div className="mb-2 flex items-center justify-between"><span className="label">Capabilities · {f.capabilities.size} selected</span><input value={filter} onChange={(e) => setFilter(e.target.value)} placeholder="Filter…" className="input h-8 w-48 text-xs" /></div>
          <div className="space-y-4">
            {taxonomy.map((sec) => {
              const caps = sec.capabilities.filter((c: any) => !filter || c.label.toLowerCase().includes(filter.toLowerCase()));
              if (!caps.length) return null;
              return (
                <div key={sec.id} className="rounded-2xl border border-line p-4">
                  <div className="mb-2.5 text-sm font-semibold">{sec.title}</div>
                  <div className="flex flex-wrap gap-1.5">
                    {caps.map((c: any) => {
                      const on = f.capabilities.has(c.token);
                      return <motion.button whileTap={{ scale: 0.95 }} key={c.token} type="button" onClick={() => toggle("capabilities", c.token)} className={cn("rounded-lg px-2.5 py-1 text-xs ring-1 ring-inset transition", on ? "bg-brand-50 font-semibold text-brand-700 ring-brand-300" : "bg-white text-ink-soft ring-line hover:bg-slate-50")}>{c.label}</motion.button>;
                    })}
                  </div>
                </div>
              );
            })}
          </div>
        </div>
        <ErrorNote error={err} />
        <div className="sticky bottom-0 -mx-6 flex justify-end gap-2 border-t border-line bg-white px-6 py-3">
          <Button variant="secondary" onClick={close}>Cancel</Button>
          <Button loading={busy} onClick={save} disabled={!f.name.trim()}>{isNew ? "Add plant" : "Save changes"}</Button>
        </div>
      </div>
    </Drawer>
  );
}

function CapChip({ label, basis }: { label: string; basis: string }) {
  return (
    <span title={basis === "stated" ? "Stated by the reference site" : basis === "inferred" ? "Inferred from a stated dosage form — not evidenced" : basis === "user" ? "Entered in the app" : "Derived"}
      className={cn("rounded-md px-1.5 py-0.5 text-[11px]", basis === "stated" ? "bg-brand-50 font-medium text-brand-700 ring-1 ring-inset ring-brand-200" : basis === "inferred" ? "border border-dashed border-sky-400 text-sky-700" : "bg-slate-100 text-slate-600")}>
      {label}
    </span>
  );
}

function ReferencePanel({ p }: { p: any }) {
  const ref = p.reference;
  return (
    <div className="border-b border-line bg-slate-50/60 px-5 py-4 text-xs">
      <div className="flex items-center gap-1.5 font-semibold text-ink"><FileSearch size={14} className="text-brand-700" /> Modelled on {ref.company} — {ref.site}</div>
      <p className="mt-1 leading-relaxed text-ink-soft">{ref.summary}</p>
      {p.annual_capacity?.length > 0 && <div className="mt-2"><span className="font-semibold text-ink">Capacity: </span>{p.annual_capacity.join(" · ")}</div>}
      {p.equipment_highlights?.length > 0 && <div className="mt-1"><span className="font-semibold text-ink">Equipment: </span>{p.equipment_highlights.join(" · ")}</div>}
      {Object.keys(p.certification_basis ?? {}).length > 0 && (
        <div className="mt-1"><span className="font-semibold text-ink">Approvals: </span>{Object.entries(p.certification_basis).map(([c, why]: any) => `${c.replace(/_/g, " ")} (${why})`).join(" · ")}</div>
      )}
      {p.certifications_claimed?.length > 0 && (
        <div className="mt-1 flex flex-wrap items-center gap-1"><span className="font-semibold text-ink">Claimed, not verified: </span>{p.certifications_claimed.map((c: string) => c.replace(/_/g, " ")).join(", ")} <Estimate field="certifications_claimed" /></div>
      )}
      {p.inspections?.length > 0 && (
        <div className="mt-1"><span className="font-semibold text-ink">Inspections: </span>{p.inspections.map((i: any, k: number) => <a key={k} href={i.url} target="_blank" rel="noreferrer" className="mr-2 underline decoration-dotted hover:text-brand-700">{i.date} {i.authority}: {i.outcome}</a>)}</div>
      )}
      <div className="mt-2 flex flex-wrap items-center gap-3 text-ink-muted">
        {(ref.sources ?? []).map((s: any) => <a key={s.url} href={s.url} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 font-medium text-brand-700 hover:underline"><ExternalLink size={12} />{s.label}</a>)}
        <span>retrieved {ref.retrieved_at}</span>
      </div>
    </div>
  );
}

function SiteSuggestions({ slug }: { slug: string }) {
  const { data } = useQuery({ queryKey: ["site-suggestions", slug], queryFn: () => api<any>(`/api/orgs/${slug}/site-suggestions`) });
  const [busy, setBusy] = useState<string | null>(null);
  const [open, setOpen] = useState<any | null>(null);
  const toast = useToast();
  const qc = useQueryClient();
  if (!data?.items?.length) return null;
  const add = async (id: string) => {
    setBusy(id);
    try {
      await post(`/api/orgs/${slug}/plants/from-site`, { site_id: id });
      toast("Plant added from public records — review and confirm its capabilities.");
      qc.invalidateQueries({ queryKey: ["site-suggestions", slug] });
      qc.invalidateQueries({ queryKey: ["org", slug] });
      qc.invalidateQueries();
    } catch (e) {
      toast((e as Error).message, "error");
    } finally {
      setBusy(null);
    }
  };
  return (
    <Card delay={0.15} className="mt-5">
      <div className="flex flex-wrap items-center justify-between gap-2 px-5 pt-5">
        <div>
          <div className="flex items-center gap-2 font-display text-[15px] font-bold"><FileSearch size={16} /> Your sites in public records</div>
          <div className="text-xs text-ink-muted">Manufacturing addresses printed on your CDSCO-alerted products, matched with FDA records. Adding one creates a plant whose capabilities are inferred from what was made there.</div>
        </div>
      </div>
      <div className="mt-3 divide-y divide-line/70">
        {data.items.map((s: any) => (
          <div key={s.id} className="flex flex-wrap items-center justify-between gap-3 px-5 py-3">
            <button onClick={() => setOpen(s)} className="min-w-0 text-left">
              <div className="truncate text-sm font-semibold hover:text-brand-700">{s.company} <span className="font-normal text-ink-muted">· {s.city || s.state} {s.pincode}</span></div>
              <div className="mt-1 flex flex-wrap items-center gap-1.5 text-[11px] text-ink-muted">{s.alerts} alerts · {Object.keys(s.forms).join(", ")} <FdaBadges fda={s.fda} /></div>
            </button>
            {s.plant_id ? <Badge tone="brand"><Check size={11} /> added</Badge> : data.can_add && <Button size="sm" loading={busy === s.id} onClick={() => add(s.id)}><Plus size={13} /> Add as plant</Button>}
          </div>
        ))}
      </div>
      <Drawer open={!!open} onClose={() => setOpen(null)} title={open?.company ?? ""} subtitle={open ? <FdaBadges fda={open.fda} /> : undefined} width={680}>
        {open && <SiteDetail site={open} />}
      </Drawer>
    </Card>
  );
}

export function Infrastructure() {
  const { org, slug } = useOrg();
  const { data, isLoading, error } = useOrgData<any>("infrastructure");
  const [editing, setEditing] = useState<any | null | undefined>(undefined);
  if (isLoading || !org) return <PageSkeleton />;
  if (error) return <ErrorNote error={error} />;

  return (
    <>
      <PageHeader eyebrow="Infrastructure" title="Manufacturing footprint" subtitle="Plants, certifications and capabilities — the inputs to the patent-opportunity and EU export analysis."
        actions={data.can_manage && <Button onClick={() => setEditing(null)}><Plus size={16} /> Add plant</Button>} />
      {!data.plants.length && <Empty icon={<Factory />} title="No plants yet">Add a plant profile to see which off-patent molecules you can make and what the EU route needs.</Empty>}
      <div className="grid gap-5 xl:grid-cols-2">
        {data.plants.map((p: any, i: number) => (
          <Card key={p.asset_id} delay={i * 0.06} className="overflow-hidden">
            <div className="relative bg-gradient-to-br from-night-800 to-night-600 px-6 py-5 text-white">
              <div className="absolute right-4 top-4 flex gap-2">
                {p.editable && <button onClick={() => setEditing(p)} className="rounded-lg bg-white/10 p-2 text-white/80 transition hover:bg-white/20"><Pencil size={14} /></button>}
              </div>
              <div className="flex items-center gap-2 text-xs text-slate-300"><MapPin size={13} />{[p.city, p.state, p.country].filter(Boolean).join(", ")}</div>
              <div className="mt-1 font-display text-xl font-bold">{p.site_name}</div>
              <div className="mt-3 flex flex-wrap gap-1.5">
                {p.certifications_active.length ? p.certifications_active.map((c: string) => <span key={c} className="flex items-center gap-1 rounded-full bg-brand-400/15 px-2.5 py-0.5 text-[11px] font-semibold text-brand-200 ring-1 ring-inset ring-brand-400/30"><ShieldCheck size={11} />{c.replace(/_/g, " ")}</span>) : <span className="text-xs text-slate-400">No active certifications</span>}
              </div>
            </div>
            <div className="grid grid-cols-3 divide-x divide-line border-b border-line text-center">
              <div className="px-3 py-3"><div className="label">Containment</div><div className="mt-1 text-sm font-semibold">{titleCase(p.containment_class)}</div></div>
              <div className="px-3 py-3"><div className="label">Forms</div><div className="mt-1 text-sm font-semibold">{p.approved_forms.length}</div></div>
              <div className="px-3 py-3"><div className="label">Capacity</div><div className="mt-1 truncate px-1 text-sm font-semibold" title={(p.annual_capacity ?? []).join(" · ")}>{p.annual_capacity?.[0] ?? (p.batch_capacity_kg ? `${p.batch_capacity_kg} kg batch` : "—")}</div></div>
            </div>
            {p.reference?.company && <ReferencePanel p={p} />}
            <div className="space-y-3 p-5">
              <div className="flex items-center justify-between">
                <div className="label">Capability coverage</div>
                <div className="flex items-center gap-3 text-[11px] text-ink-muted">
                  <span className="flex items-center gap-1"><span className="h-2.5 w-2.5 rounded-sm bg-brand-500" /> stated</span>
                  <span className="flex items-center gap-1"><span className="h-2.5 w-2.5 rounded-sm border border-dashed border-sky-500" /> inferred <Estimate field="capability_inferred" align="right" /></span>
                </div>
              </div>
              {p.sections.map((s: any) => (
                <div key={s.id}>
                  <div className="mb-1 flex justify-between text-xs"><span className="font-medium text-ink-soft">{s.title}</span><span className="tabular-nums text-ink-muted">{s.have.length}/{s.total}</span></div>
                  <Bar value={s.coverage_pct} color={s.coverage_pct > 40 ? "#0a9a7d" : s.coverage_pct > 0 ? "#f59e0b" : "#e2e8f0"} />
                  {s.have.length > 0 && <div className="mt-1.5 flex flex-wrap gap-1">{s.have.map((h: any) => <CapChip key={h.token} label={h.label} basis={h.basis} />)}</div>}
                </div>
              ))}
              {p.other_capabilities?.length > 0 && (
                <div><div className="mb-1 text-xs font-medium text-ink-soft">Other process capabilities</div><div className="flex flex-wrap gap-1">{p.other_capabilities.map((h: any) => <CapChip key={h.token} label={h.label} basis={h.basis} />)}</div></div>
              )}
              {p.approved_forms.length > 0 && <div className="flex flex-wrap gap-1.5 pt-2">{p.approved_forms.map((f: string) => <Badge key={f}>{titleCase(f)}</Badge>)}</div>}
              <div className="flex items-center gap-1.5 pt-1 text-[11px] text-ink-muted">Talent depth used in fit scores is an estimate <Estimate field="talent_depth" /></div>
            </div>
          </Card>
        ))}
      </div>
      <SiteSuggestions slug={slug} />
      <PlantEditor slug={slug} plant={editing} taxonomy={data.taxonomy} onClose={() => setEditing(undefined)} />
    </>
  );
}
