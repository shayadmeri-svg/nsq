import { keepPreviousData, useQuery, useQueryClient } from "@tanstack/react-query";
import { ChevronLeft, ChevronRight, EyeOff, FlaskConical, Pencil, Plus, Search, Trash2 } from "lucide-react";
import { useSearchParams } from "react-router-dom";
import { LogViewer } from "../../components/jobs";
import { useMe } from "../../lib/session";
import { MoleculeForm } from "../../components/molecules/MoleculeForm";
import { motion } from "motion/react";
import { useEffect, useState } from "react";
import { Badge, Button, Card, CardHeader, Drawer, ErrorNote, PageHeader, PageSkeleton, Segmented, Stat } from "../../components/ui";
import { useToast } from "../../components/ui/toast";
import { api, del, post } from "../../lib/api";
import { cn } from "../../lib/cn";
import { fmtDate, timeAgo } from "../../lib/format";

export const SOURCE_CHIP: Record<string, { short: string; label: string; cls: string }> = {
  orange_book: { short: "OB", label: "FDA Orange Book", cls: "bg-orange-100 text-orange-800" },
  purple_book: { short: "PB", label: "FDA Purple Book", cls: "bg-violet-100 text-violet-800" },
  ema: { short: "EMA", label: "EMA (EU)", cls: "bg-blue-100 text-blue-800" },
  clinical_trials: { short: "CT", label: "ClinicalTrials.gov", cls: "bg-teal-100 text-teal-800" },
  cdsco: { short: "NSQ", label: "CDSCO NSQ", cls: "bg-rose-100 text-rose-800" },
};
const ORIGIN: Record<string, { tone: any; label: string }> = {
  curated: { tone: "indigo", label: "curated" },
  auto: { tone: "brand", label: "auto" },
  manual: { tone: "amber", label: "added in app" },
};
const PROV_TONE: Record<string, string> = {
  sourced: "bg-emerald-50 text-emerald-700 ring-emerald-200",
  derived: "bg-sky-50 text-sky-700 ring-sky-200",
  estimate: "bg-amber-50 text-amber-700 ring-amber-200",
  unknown: "bg-slate-50 text-slate-500 ring-slate-200",
  entered: "bg-violet-50 text-violet-700 ring-violet-200",
};

export function SourceDots({ sources }: { sources: string[] }) {
  return (
    <div className="flex gap-1">
      {Object.entries(SOURCE_CHIP).map(([k, v]) => (
        <span key={k} title={v.label} className={cn("rounded px-1 py-px text-[9.5px] font-bold tracking-wide", sources.includes(k) ? v.cls : "bg-slate-50 text-slate-300")}>{v.short}</span>
      ))}
    </div>
  );
}

function ProvRow({ field, p }: { field: string; p: any }) {
  return (
    <div className="flex items-start justify-between gap-3 border-b border-line/70 py-2 text-xs last:border-0">
      <div className="min-w-0">
        <div className="font-semibold text-ink">{field.replace(/_/g, " ")}</div>
        {(p.note || p.source) && <div className="mt-0.5 text-ink-muted">{p.source ? <b className="font-medium text-ink-soft">{p.source}. </b> : null}{p.note}</div>}
        {p.source_value != null && <div className="mt-0.5 text-violet-700">Source value kept for comparison: {typeof p.source_value === "object" ? JSON.stringify(p.source_value) : String(p.source_value)}</div>}
      </div>
      <span className={cn("shrink-0 rounded-full px-2 py-0.5 text-[10px] font-bold uppercase tracking-wider ring-1 ring-inset", PROV_TONE[p.status] ?? PROV_TONE.unknown)}>{p.status}</span>
    </div>
  );
}

function MoleculeDrawer({ mkey, onClose, onEdit, canEdit }: { mkey?: string; onClose: () => void; onEdit: (key: string) => void; canEdit: boolean }) {
  const { data, error } = useQuery({ queryKey: ["molecule", mkey], queryFn: () => api<any>(`/api/pipelines/molecules/${mkey}`), enabled: !!mkey });
  const p = data?.patent;
  const sig = p?.signals ?? {};
  const prov = { ...(p?.provenance ?? {}), ...(data?.regulatory?.provenance ?? {}), ...(data?.demand?.provenance ?? {}) };
  return (
    <Drawer open={!!mkey} onClose={onClose} title={p ? p.api_name : mkey} subtitle={p ? <span className="flex items-center gap-2">{p.brand_name || "—"} · {p.originator || "originator unknown"} <Badge tone={ORIGIN[p.origin]?.tone}>{ORIGIN[p.origin]?.label}</Badge></span> : undefined} width={760}>
      {error ? <ErrorNote error={error} /> : !p ? <div className="text-sm text-ink-muted">Loading…</div> : (
        <div className="space-y-5">
          {canEdit && <div className="flex justify-end"><Button size="sm" onClick={() => onEdit(p.molecule_key)}><Pencil size={13} /> Edit values</Button></div>}
          <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
            {[["US LOE", fmtDate(p.estimated_loe_us)], ["EU LOE", fmtDate(p.estimated_loe_eu)], ["India", fmtDate(p.estimated_loe_in)], ["FTO risk", p.fto_risk]].map(([k, v]) => (
              <div key={k} className="rounded-xl bg-slate-50 p-3"><div className="label">{k}</div><div className="mt-1 font-display text-lg font-bold capitalize">{v}</div></div>
            ))}
          </div>
          <div className="grid gap-3 md:grid-cols-2">
            {sig.orange_book && <div className="rounded-xl border border-line p-3 text-xs"><div className="mb-1.5 flex items-center gap-1.5 font-semibold"><span className={cn("rounded px-1 text-[10px] font-bold", SOURCE_CHIP.orange_book.cls)}>OB</span> Orange Book</div>
              <div>{sig.orange_book.anda_active} active ANDAs · {sig.orange_book.nda_active} NDAs</div>
              <div className="text-ink-muted">First generic {fmtDate(sig.orange_book.first_generic_approval)} · forms {(sig.orange_book.dosage_forms ?? []).join(", ")}</div>
              {sig.orange_book.indian_anda_holders?.length > 0 && <div className="mt-1 text-ink-muted">Indian ANDA holders: {sig.orange_book.indian_anda_holders.slice(0, 6).join(", ")}</div>}
            </div>}
            {sig.ema && <div className="rounded-xl border border-line p-3 text-xs"><div className="mb-1.5 flex items-center gap-1.5 font-semibold"><span className={cn("rounded px-1 text-[10px] font-bold", SOURCE_CHIP.ema.cls)}>EMA</span> EU central authorisations</div>
              <div>{sig.ema.authorised} authorised · {sig.ema.generics} generics · {sig.ema.biosimilars} biosimilars{sig.ema.orphan ? " · orphan" : ""}</div>
              <div className="text-ink-muted">{(sig.ema.therapeutic_areas ?? []).join("; ")}</div>
            </div>}
            {sig.purple_book && <div className="rounded-xl border border-line p-3 text-xs"><div className="mb-1.5 font-semibold">Purple Book</div>{sig.purple_book.biosimilars} biosimilars · {sig.purple_book.interchangeables} interchangeable</div>}
            {sig.trials && <div className="rounded-xl border border-line p-3 text-xs"><div className="mb-1.5 flex items-center gap-1.5 font-semibold"><span className={cn("rounded px-1 text-[10px] font-bold", SOURCE_CHIP.clinical_trials.cls)}>CT</span> ClinicalTrials.gov</div>
              <div>{sig.trials.total} trials · {sig.trials.phase3plus} phase 3+ · {sig.trials.recent} started in 3 y · {sig.trials.india} in India</div>
              <div className="text-ink-muted">checked {timeAgo(sig.trials.fetched_at)}</div>
            </div>}
            {sig.nsq && <div className="rounded-xl border border-line p-3 text-xs"><div className="mb-1.5 flex items-center gap-1.5 font-semibold"><span className={cn("rounded px-1 text-[10px] font-bold", SOURCE_CHIP.cdsco.cls)}>NSQ</span> CDSCO alerts</div>
              <div>{sig.nsq.alerts} alerts · {sig.nsq.manufacturers} manufacturers · last {sig.nsq.last}</div>
              <div className="text-ink-muted">{Object.entries(sig.nsq.forms ?? {}).map(([k, v]) => `${k} ${v}`).join(" · ")}</div>
            </div>}
          </div>
          {(p.formulation_patents?.length > 0 || p.secondary_patents?.length > 0) && (
            <div><div className="label mb-2">Patents in force</div>
              <div className="space-y-1">{[...p.formulation_patents, ...p.secondary_patents].map((x: any, i: number) => (
                <div key={i} className="flex justify-between gap-3 rounded-lg bg-slate-50 px-3 py-1.5 text-xs"><span>{x.description}</span><span className="shrink-0 text-ink-muted">{x.jurisdiction} · {fmtDate(x.expiry_date)}</span></div>
              ))}</div>
            </div>
          )}
          <div>
            <div className="label mb-1">Where each value comes from</div>
            <div className="rounded-xl border border-line px-3">{Object.entries(prov).map(([f, v]) => <ProvRow key={f} field={f} p={v} />)}
              {Object.keys(prov).length === 0 && <div className="py-3 text-xs text-ink-muted">Curated seed values; no public source matched yet.</div>}</div>
          </div>
          {p.aliases?.length > 0 && <div className="text-xs text-ink-muted">Also matched as: {p.aliases.join(", ")}</div>}
        </div>
      )}
    </Drawer>
  );
}

function Watchlist({ skipped, onTrack, canEdit }: { skipped: any[]; onTrack: (name: string) => void; canEdit: boolean }) {
  const { data } = useQuery({ queryKey: ["watchlist"], queryFn: () => api<any>("/api/pipelines/watchlist") });
  const [name, setName] = useState("");
  const qc = useQueryClient();
  const toast = useToast();
  const add = async (n: string, exclude = false) => {
    try {
      const r = await post<any>("/api/pipelines/watchlist", { name: n, exclude });
      toast(`${r.name} ${exclude ? "excluded" : "added"} — ${r.hint}`);
      setName("");
      qc.invalidateQueries({ queryKey: ["watchlist"] });
    } catch (e) {
      toast((e as Error).message, "error");
    }
  };
  return (
    <div className="grid gap-5 lg:grid-cols-2">
      <Card delay={0.15}>
        <CardHeader title="Exclusions & quick adds" subtitle={canEdit ? "Keep an auto-discovered molecule out (e.g. an excipient), or add one by name only. Use “Add molecule” to fill in its profile." : "Only the super admin can add or exclude molecules."} />
        {canEdit && <form className="flex gap-2 px-5 pt-4" onSubmit={(e) => { e.preventDefault(); if (name.trim()) add(name.trim()); }}>
          <input className="input h-9 flex-1" value={name} onChange={(e) => setName(e.target.value)} placeholder="e.g. Menthol" />
          <Button size="sm" variant="secondary" type="button" onClick={() => name.trim() && add(name.trim(), true)}><EyeOff size={14} /> Exclude</Button>
          <Button size="sm" type="submit"><Plus size={14} /> Track</Button>
        </form>}
        <div className="max-h-72 space-y-1 overflow-auto px-5 py-4 scrollbar-thin">
          {(data?.items ?? []).map((w: any) => (
            <div key={w.id} className="flex items-center justify-between rounded-lg bg-slate-50 px-3 py-1.5 text-xs">
              <span className="flex items-center gap-2">{w.exclude ? <EyeOff size={13} className="text-rose-500" /> : <Plus size={13} className="text-brand-600" />}<b>{w.name}</b><span className="font-mono text-ink-faint">{w.key}</span></span>
              {canEdit && <button onClick={async () => { await del(`/api/pipelines/watchlist/${w.id}`); qc.invalidateQueries({ queryKey: ["watchlist"] }); }} className="text-ink-faint hover:text-rose-600"><Trash2 size={13} /></button>}
            </div>
          ))}
          {!data?.items?.length && <div className="text-xs text-ink-muted">Empty. Changes apply on the next universe build.</div>}
        </div>
      </Card>
      <Card delay={0.2}>
        <CardHeader title="Not included" subtitle={canEdit ? "NSQ ingredients the builder skipped, and why. Track one to include it anyway." : "NSQ ingredients the builder skipped, and why."} />
        <div className="max-h-[340px] space-y-1 overflow-auto px-5 py-4 scrollbar-thin">
          {skipped.map((s: any) => (
            <div key={s.key + s.name} className="flex items-center justify-between gap-3 rounded-lg px-2 py-1.5 text-xs hover:bg-slate-50">
              <div className="min-w-0"><b className="capitalize">{s.name}</b> <span className="text-ink-muted">· {s.alerts} alerts</span><div className="truncate text-ink-faint">{s.reason}</div></div>
              {canEdit && <Button size="sm" variant="secondary" onClick={() => onTrack(s.name)}><Plus size={12} /> Track</Button>}
            </div>
          ))}
          {!skipped.length && <div className="text-xs text-ink-muted">Nothing skipped.</div>}
        </div>
      </Card>
    </div>
  );
}

export function Molecules() {
  const [q, setQ] = useState("");
  const [dq, setDq] = useState("");
  const [origin, setOrigin] = useState<"" | "curated" | "auto" | "manual">("");
  const [source, setSource] = useState("");
  const [sort, setSort] = useState("alerts");
  const [page, setPage] = useState(1);
  const [open, setOpen] = useState<string | undefined>();
  const [form, setForm] = useState<{ name?: string; key?: string } | null>(null);
  const [runId, setRunId] = useState<number | undefined>();
  const [params, setParams] = useSearchParams();
  const canEdit = !!useMe().data?.permissions.edit_molecules;
  useEffect(() => { const a = params.get("add"); if (a) { if (canEdit) setForm({ name: a }); params.delete("add"); setParams(params, { replace: true }); } }, [params, setParams, canEdit]);
  useEffect(() => { const t = setTimeout(() => { setDq(q); setPage(1); }, 250); return () => clearTimeout(t); }, [q]);
  const { data, isLoading, error, isFetching } = useQuery({
    queryKey: ["universe", dq, origin, source, sort, page],
    queryFn: () => api<any>(`/api/pipelines/molecules?${new URLSearchParams({ q: dq, origin, source, sort, page: String(page), size: "25" })}`),
    placeholderData: keepPreviousData,
  });
  if (isLoading) return <PageSkeleton />;
  if (error) return <ErrorNote error={error} />;
  const c = data.counts ?? {};
  const total = c.molecules || 1;

  return (
    <>
      <PageHeader eyebrow="Platform · Pipelines" title="Molecule universe" subtitle={<>Curated seeds, molecules discovered from NSQ alerts and confirmed by a public source, and molecules added here. Built {timeAgo(data.built_at)}.</>}
        actions={canEdit ? <Button onClick={() => setForm({})}><Plus size={15} /> Add molecule</Button> : <Badge tone="slate">View only · super admin edits</Badge>} />
      <div className="grid grid-cols-2 gap-4 xl:grid-cols-4">
        <Stat label="Molecules" value={c.molecules ?? 0} icon={<FlaskConical size={18} />} />
        <Stat label="Curated" value={c.curated ?? 0} tone="indigo" delay={0.05} hint="hand-built profiles, overlaid with sources" />
        <Stat label="Auto-discovered" value={c.auto ?? 0} tone="brand" delay={0.1} hint={`from ${Number(c.nsq_ingredients ?? 0).toLocaleString("en-IN")} NSQ ingredients`} />
        <Stat label="Added in app / skipped" value={c.manual ?? 0} suffix={` / ${c.skipped ?? 0}`} tone="amber" delay={0.15} hint="typed profiles · no public record, excluded or over the cap" />
      </div>
      <Card delay={0.1} className="mt-5 p-5">
        <div className="label mb-3">Source coverage</div>
        <div className="grid gap-3 md:grid-cols-5">
          {Object.entries(SOURCE_CHIP).map(([k, v]) => {
            const n = data.by_source?.[k] ?? 0;
            return (
              <button key={k} onClick={() => { setSource(source === k ? "" : k); setPage(1); }} className={cn("rounded-xl border p-3 text-left transition", source === k ? "border-brand-500 bg-brand-50/50" : "border-line hover:border-slate-300")}>
                <div className="flex items-center justify-between"><span className={cn("rounded px-1.5 py-px text-[10px] font-bold", v.cls)}>{v.short}</span><span className="font-display text-lg font-bold">{n}</span></div>
                <div className="mt-1 text-[11px] text-ink-muted">{v.label}</div>
                <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-slate-100"><motion.div className="h-full rounded-full bg-brand-500" initial={{ width: 0 }} animate={{ width: `${(100 * n) / total}%` }} transition={{ duration: 0.8 }} /></div>
              </button>
            );
          })}
        </div>
      </Card>

      <Card delay={0.12} className="mt-5">
        <CardHeader title="Molecules" subtitle={`${data.total} shown`} action={
          <div className="flex flex-wrap items-center gap-2">
            <Segmented value={origin} onChange={(v) => { setOrigin(v); setPage(1); }} options={[{ value: "", label: "All" }, { value: "curated", label: "Curated" }, { value: "auto", label: "Auto" }, { value: "manual", label: "Added" }]} />
            <select className="input h-9 w-36" value={sort} onChange={(e) => setSort(e.target.value)}>
              <option value="alerts">Most NSQ alerts</option><option value="loe">Earliest US LOE</option><option value="anda">Most ANDAs</option><option value="trials">Most trials</option><option value="name">Name</option>
            </select>
            <div className="relative"><Search size={15} className="absolute left-3 top-2.5 text-ink-faint" /><input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Molecule or brand…" className="input h-9 w-56 pl-9" /></div>
          </div>
        } />
        <div className="mt-4 overflow-x-auto">
          <table className={cn("w-full text-sm", isFetching && "opacity-60")}>
            <thead><tr className="border-y border-line bg-slate-50/70 text-left text-[11px] font-semibold uppercase tracking-wider text-ink-muted">
              <th className="px-5 py-2.5">Molecule</th><th className="px-3 py-2.5">Sources</th><th className="px-3 py-2.5 text-right">NSQ alerts</th><th className="px-3 py-2.5">US LOE</th><th className="px-3 py-2.5">EU LOE</th><th className="px-3 py-2.5">FTO</th><th className="px-3 py-2.5 text-right">ANDAs</th><th className="px-5 py-2.5 text-right">Trials</th>
            </tr></thead>
            <tbody>
              {data.items.map((m: any) => (
                <tr key={m.key} onClick={() => setOpen(m.key)} className="cursor-pointer border-b border-line/70 hover:bg-slate-50">
                  <td className="px-5 py-2.5"><div className="flex items-center gap-2 font-semibold">{m.name}<Badge tone={ORIGIN[m.origin]?.tone}>{ORIGIN[m.origin]?.label}</Badge>{m.entered?.length > 0 && <span title={`Typed: ${m.entered.join(", ")}${m.edited_by ? ` — ${m.edited_by}` : ""}`} className="rounded-full bg-violet-50 px-1.5 py-0.5 text-[10px] font-bold text-violet-700 ring-1 ring-inset ring-violet-200">{m.entered.length} typed</span>}</div><div className="text-[11px] text-ink-muted">{m.brand || "—"} · {m.area || "area unknown"}{m.modality === "biologic" ? " · biologic" : ""}</div></td>
                  <td className="px-3 py-2.5"><SourceDots sources={m.sources} /></td>
                  <td className="px-3 py-2.5 text-right tabular-nums">{m.alerts || "—"}</td>
                  <td className="px-3 py-2.5 text-xs">{fmtDate(m.loe_us)}</td>
                  <td className="px-3 py-2.5 text-xs">{fmtDate(m.loe_eu)}</td>
                  <td className="px-3 py-2.5"><Badge tone={m.fto === "high" ? "rose" : m.fto === "medium" ? "amber" : "brand"}>{m.fto}</Badge></td>
                  <td className="px-3 py-2.5 text-right tabular-nums">{m.anda ?? "—"}</td>
                  <td className="px-5 py-2.5 text-right tabular-nums">{m.trials || "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <div className="flex items-center justify-between px-5 py-3 text-xs text-ink-muted">
          <span>Page {data.page} of {data.pages}</span>
          <div className="flex gap-1.5"><Button size="sm" variant="secondary" disabled={page <= 1} onClick={() => setPage(page - 1)}><ChevronLeft size={14} /></Button><Button size="sm" variant="secondary" disabled={page >= data.pages} onClick={() => setPage(page + 1)}><ChevronRight size={14} /></Button></div>
        </div>
      </Card>
      <div className="mt-5"><Watchlist canEdit={canEdit} skipped={data.skipped ?? []} onTrack={(name) => setForm({ name })} /></div>
      <MoleculeDrawer canEdit={canEdit} mkey={open} onClose={() => setOpen(undefined)} onEdit={(key) => { setOpen(undefined); setForm({ key }); }} />
      <MoleculeForm open={!!form} name={form?.name} mkey={form?.key} onClose={() => setForm(null)} onSaved={(id) => id && setRunId(id)} />
      <LogViewer runId={runId} onClose={() => setRunId(undefined)} />
    </>
  );
}
