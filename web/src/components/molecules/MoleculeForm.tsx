// Add / edit a tracked molecule. Starts from what the curated seed and the
// public sources say; only the fields you type are stored, and they win over
// the sources on every rebuild (the source value stays visible next to them).
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { CheckCircle2, FlaskConical, Plus, RotateCcw, Search, Trash2 } from "lucide-react";
import { AnimatePresence, motion } from "motion/react";
import { useEffect, useMemo, useState } from "react";
import { Badge, Button, Drawer, ErrorNote, Segmented } from "../ui";
import { useToast } from "../ui/toast";
import { api, del, post } from "../../lib/api";
import { cn } from "../../lib/cn";

type Field = { key: string; group: string; label: string; type: string; options?: string[]; help?: string; required?: boolean; min?: number; max?: number };
type Schema = { groups: { id: string; title: string; hint: string }[]; fields: Field[] };

const SRC_SHORT: Record<string, string> = { orange_book: "Orange Book", purple_book: "Purple Book", ema: "EMA", clinical_trials: "ClinicalTrials.gov", cdsco: "CDSCO NSQ" };
const STATUS_CHIP: Record<string, string> = {
  sourced: "bg-emerald-50 text-emerald-700 ring-emerald-200",
  derived: "bg-sky-50 text-sky-700 ring-sky-200",
  estimate: "bg-amber-50 text-amber-700 ring-amber-200",
  unknown: "bg-slate-50 text-slate-500 ring-slate-200",
  entered: "bg-violet-50 text-violet-700 ring-violet-200",
};

const empty = (v: any) => v == null || v === "" || (Array.isArray(v) && v.length === 0);
const show = (v: any) => (empty(v) ? "—" : Array.isArray(v) ? (typeof v[0] === "object" ? `${v.length} item(s)` : v.join(", ")) : String(v));

function RowsEditor({ value, onChange, kind }: { value: any[]; onChange: (v: any[]) => void; kind: "patents" | "exclusivity" }) {
  const rows = value ?? [];
  const set = (i: number, patch: any) => onChange(rows.map((r, j) => (j === i ? { ...r, ...patch } : r)));
  const blank = kind === "patents" ? { kind: "formulation", description: "", jurisdiction: "US", expiry_date: "", risk_level: "medium" } : { type: "", expiry_date: "", description: "" };
  return (
    <div className="space-y-2">
      {rows.map((r, i) => (
        <div key={i} className="flex flex-wrap items-center gap-1.5 rounded-lg bg-slate-50 p-2">
          {kind === "patents" ? (
            <>
              <select className="input h-8 w-28 text-xs" value={r.kind} onChange={(e) => set(i, { kind: e.target.value })}>{["formulation", "process", "secondary"].map((o) => <option key={o}>{o}</option>)}</select>
              <input className="input h-8 min-w-[180px] flex-1 text-xs" placeholder="Description" value={r.description ?? ""} onChange={(e) => set(i, { description: e.target.value })} />
              <select className="input h-8 w-20 text-xs" value={r.jurisdiction} onChange={(e) => set(i, { jurisdiction: e.target.value })}>{["US", "EU", "IN", "global"].map((o) => <option key={o}>{o}</option>)}</select>
              <input type="date" className="input h-8 w-36 text-xs" value={(r.expiry_date ?? "").slice(0, 10)} onChange={(e) => set(i, { expiry_date: e.target.value })} />
              <select className="input h-8 w-24 text-xs" value={r.risk_level} onChange={(e) => set(i, { risk_level: e.target.value })}>{["low", "medium", "high"].map((o) => <option key={o}>{o}</option>)}</select>
            </>
          ) : (
            <>
              <input className="input h-8 w-24 text-xs" placeholder="Type (NCE…)" value={r.type ?? ""} onChange={(e) => set(i, { type: e.target.value })} />
              <input type="date" className="input h-8 w-36 text-xs" value={(r.expiry_date ?? "").slice(0, 10)} onChange={(e) => set(i, { expiry_date: e.target.value })} />
              <input className="input h-8 min-w-[180px] flex-1 text-xs" placeholder="Description" value={r.description ?? ""} onChange={(e) => set(i, { description: e.target.value })} />
            </>
          )}
          <button type="button" onClick={() => onChange(rows.filter((_, j) => j !== i))} className="p-1 text-ink-faint hover:text-rose-600"><Trash2 size={13} /></button>
        </div>
      ))}
      <Button type="button" size="sm" variant="secondary" onClick={() => onChange([...rows, blank])}><Plus size={13} /> Add {kind === "patents" ? "patent" : "exclusivity"}</Button>
    </div>
  );
}

function Input({ f, value, onChange }: { f: Field; value: any; onChange: (v: any) => void }) {
  const cls = "input h-9 w-full";
  switch (f.type) {
    case "textarea":
      return <textarea className="input min-h-[72px] w-full py-2" value={value ?? ""} onChange={(e) => onChange(e.target.value)} />;
    case "select":
      return <select className={cls} value={value ?? ""} onChange={(e) => onChange(e.target.value)}>{!f.options?.includes("") && <option value="">—</option>}{f.options?.map((o) => <option key={o} value={o}>{o || "—"}</option>)}</select>;
    case "date":
      return <input type="date" className={cls} value={(value ?? "").slice(0, 10)} onChange={(e) => onChange(e.target.value)} />;
    case "number":
    case "int":
      return <input type="number" step={f.type === "int" ? 1 : "any"} min={f.min} max={f.max} className={cls} value={value ?? ""} onChange={(e) => onChange(e.target.value === "" ? "" : Number(e.target.value))} />;
    case "list":
      return <textarea className="input min-h-[64px] w-full py-2" value={Array.isArray(value) ? value.join("\n") : value ?? ""} onChange={(e) => onChange(e.target.value.split("\n"))} />;
    case "patents":
    case "exclusivity":
      return <RowsEditor kind={f.type as any} value={value ?? []} onChange={onChange} />;
    default:
      return <input className={cls} value={value ?? ""} onChange={(e) => onChange(e.target.value)} />;
  }
}

export function MoleculeForm({ open, name: initialName, mkey, onClose, onSaved }: {
  open: boolean; name?: string; mkey?: string; onClose: () => void; onSaved?: (runId: number | null) => void;
}) {
  const schema = useQuery({ queryKey: ["molecule-schema"], queryFn: () => api<Schema>("/api/molecules/schema"), staleTime: Infinity, enabled: open });
  const [query, setQuery] = useState("");
  const [target, setTarget] = useState<{ name?: string; key?: string } | null>(null);
  const [group, setGroup] = useState("identity");
  const [typed, setTyped] = useState<Record<string, any>>({});
  const [reverted, setReverted] = useState<Set<string>>(new Set());
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<unknown>(null);
  const toast = useToast();
  const qc = useQueryClient();

  useEffect(() => {
    if (!open) return;
    setQuery(initialName ?? "");
    setTarget(mkey || initialName ? { name: initialName, key: mkey } : null);
    setGroup("identity");
    setErr(null);
  }, [open, initialName, mkey]);

  const look = useQuery({
    queryKey: ["molecule-lookup", target?.key, target?.name],
    queryFn: () => api<any>(`/api/molecules/lookup?${new URLSearchParams({ name: target?.name ?? "", key: target?.key ?? "" })}`),
    enabled: open && !!target,
  });
  useEffect(() => { if (look.data) { setTyped({ ...look.data.entered }); setReverted(new Set()); } }, [look.data]);

  const d = look.data;
  const fields = schema.data?.fields ?? [];
  const isNew = d && !d.tracked && !d.entry;
  const value = (k: string) => (k in typed ? typed[k] : d?.values?.[k]);
  const set = (k: string, v: any) => { setTyped((t) => ({ ...t, [k]: v })); setReverted((r) => { const n = new Set(r); n.delete(k); return n; }); };
  const revert = (k: string) => { setTyped((t) => { const n = { ...t }; delete n[k]; return n; }); if (d?.entered && k in d.entered) setReverted((r) => new Set(r).add(k)); };
  const counts = useMemo(() => Object.fromEntries((schema.data?.groups ?? []).map((g) => [g.id, fields.filter((f) => f.group === g.id && f.key in typed).length])), [typed, fields, schema.data]);

  const save = async () => {
    setBusy(true);
    setErr(null);
    const values: Record<string, any> = {};
    for (const [k, v] of Object.entries(typed)) {
      const f = fields.find((x) => x.key === k);
      if (!f) continue;
      values[k] = f.type === "list" && Array.isArray(v) ? v.filter((x: string) => x.trim()) : v;
    }
    for (const k of reverted) values[k] = null;
    try {
      const r = await post<any>("/api/molecules", { name: typed.api_name || d?.name || target?.name || query, key: d?.key, values });
      toast(r.message);
      qc.invalidateQueries({ queryKey: ["universe"] });
      qc.invalidateQueries({ queryKey: ["molecule-lookup"] });
      onSaved?.(r.run_id);
      onClose();
    } catch (e) {
      setErr(e);
    } finally {
      setBusy(false);
    }
  };

  const untrack = async () => {
    if (!d?.key) return;
    setBusy(true);
    try {
      const r = await del<any>(`/api/molecules/${d.key}`);
      toast(r.untracked ? "Removed from the tracked set — rebuilding." : "Typed values cleared — back to the sources.");
      qc.invalidateQueries({ queryKey: ["universe"] });
      onSaved?.(r.run_id);
      onClose();
    } catch (e) {
      setErr(e);
    } finally {
      setBusy(false);
    }
  };

  return (
    <Drawer open={open} onClose={onClose} width={820}
      title={d ? (value("api_name") || d.name) : "Track a molecule"}
      subtitle={d ? (
        <span className="flex flex-wrap items-center gap-1.5">
          <span className="font-mono text-[11px]">{d.key}</span>
          {isNew ? <Badge tone="amber">new — will be tracked</Badge> : d.curated ? <Badge tone="indigo">curated</Badge> : <Badge tone="brand">{d.origin === "manual" ? "added in app" : "tracked"}</Badge>}
          {d.sources.map((s: string) => <Badge key={s} tone="slate">{SRC_SHORT[s] ?? s}</Badge>)}
          {d.nsq.alerts > 0 && <Badge tone="rose">{d.nsq.alerts} NSQ alerts · {d.nsq.manufacturers} makers</Badge>}
        </span>
      ) : "Search by name. The form fills from the curated seed and the public sources."}>
      {!target || !d ? (
        <form onSubmit={(e) => { e.preventDefault(); if (query.trim().length > 1) setTarget({ name: query.trim() }); }} className="space-y-3">
          <div className="flex gap-2">
            <div className="relative flex-1"><Search size={15} className="absolute left-3 top-3 text-ink-faint" />
              <input autoFocus className="input h-10 w-full pl-9" value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Molecule name, e.g. Empagliflozin or Salbutamol" /></div>
            <Button type="submit" loading={look.isFetching}><FlaskConical size={15} /> Look up</Button>
          </div>
          <ErrorNote error={look.error} />
          <p className="text-xs text-ink-muted">We check the Orange Book, Purple Book, EMA, ClinicalTrials.gov and the CDSCO alerts for this name and pre-fill every field they cover. You only type what is missing or what you know better — typed values always win, and the source value stays visible beside them.</p>
        </form>
      ) : (
        <div className="space-y-4">
          {isNew && !d.confirmed && <div className="rounded-xl bg-amber-50 p-3 text-xs text-amber-900 ring-1 ring-inset ring-amber-200">No public source (Orange Book, Purple Book, EMA) matched <b>{d.name}</b>. It will still be tracked because you are adding it by hand — fill in the name, dosage form and loss-of-exclusivity dates so it can be scored.</div>}
          <div className="flex flex-wrap items-center justify-between gap-2">
            <Segmented value={group} onChange={setGroup} options={(schema.data?.groups ?? []).map((g) => ({ value: g.id, label: <span className="flex items-center gap-1">{g.title}{counts[g.id] ? <span className="rounded-full bg-violet-100 px-1.5 text-[10px] font-bold text-violet-700">{counts[g.id]}</span> : null}</span> }))} />
            <span className="flex items-center gap-2 text-[11px] text-ink-muted"><span className="h-2.5 w-2.5 rounded-sm bg-violet-400" /> typed by you — wins over sources</span>
          </div>
          <p className="text-xs text-ink-muted">{schema.data?.groups.find((g) => g.id === group)?.hint}</p>
          <AnimatePresence mode="wait">
            <motion.div key={group} initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0 }} transition={{ duration: 0.15 }} className="space-y-3">
              {fields.filter((f) => f.group === group).map((f) => {
                const isTyped = f.key in typed;
                const prov = d.provenance?.[f.key];
                const base = d.values?.[f.key];
                const wide = ["patents", "exclusivity", "textarea", "list"].includes(f.type);
                return (
                  <div key={f.key} className={cn("rounded-xl border p-3 transition", isTyped ? "border-violet-300 bg-violet-50/30" : "border-line")}>
                    <div className="mb-1.5 flex flex-wrap items-center justify-between gap-2">
                      <label className="text-[13px] font-semibold">{f.label}{f.required && isNew ? <span className="text-rose-500"> *</span> : null}</label>
                      <div className="flex items-center gap-1.5">
                        {isTyped ? (
                          <>
                            <span className={cn("rounded-full px-2 py-0.5 text-[10px] font-bold uppercase ring-1 ring-inset", STATUS_CHIP.entered)}>typed</span>
                            <button type="button" onClick={() => revert(f.key)} className="flex items-center gap-1 text-[11px] text-ink-muted hover:text-ink" title="Use the source / seed value again"><RotateCcw size={11} /> use source</button>
                          </>
                        ) : prov ? (
                          <span title={[prov.source, prov.note].filter(Boolean).join(" — ")} className={cn("rounded-full px-2 py-0.5 text-[10px] font-bold uppercase ring-1 ring-inset", STATUS_CHIP[prov.status] ?? STATUS_CHIP.unknown)}>{prov.status}{prov.source ? ` · ${prov.source}` : ""}</span>
                        ) : empty(base) ? <span className="text-[10px] font-semibold uppercase text-ink-faint">empty</span> : null}
                      </div>
                    </div>
                    <div className={wide ? "" : "max-w-md"}><Input f={f} value={value(f.key)} onChange={(v) => set(f.key, v)} /></div>
                    {isTyped && !empty(base) && JSON.stringify(base) !== JSON.stringify(typed[f.key]) && (
                      <div className="mt-1.5 text-[11px] text-ink-muted">Source / seed value: <span className="font-medium text-ink-soft">{show(base)}</span>{prov?.source ? ` (${prov.source})` : ""}</div>
                    )}
                    {f.help && <div className="mt-1 text-[11px] text-ink-faint">{f.help}</div>}
                  </div>
                );
              })}
            </motion.div>
          </AnimatePresence>
          <ErrorNote error={err} />
          <div className="sticky bottom-0 -mx-6 flex items-center justify-between gap-3 border-t border-line bg-white/95 px-6 py-3 backdrop-blur">
            <div className="text-xs text-ink-muted">
              {Object.keys(typed).length} typed field(s){reverted.size ? ` · ${reverted.size} back to source` : ""}
              {d.entry && <> · last edited by {d.entry.updated_by}</>}
            </div>
            <div className="flex gap-2">
              {d.entry && <Button variant="secondary" onClick={untrack} disabled={busy}>{d.entry.added ? "Stop tracking" : "Clear typed values"}</Button>}
              <Button onClick={save} loading={busy} disabled={isNew && !(value("api_name") || d.name)}><CheckCircle2 size={15} /> {isNew ? "Start tracking" : "Save"}</Button>
            </div>
          </div>
        </div>
      )}
    </Drawer>
  );
}
