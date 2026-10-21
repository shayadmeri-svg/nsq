// Sim engine: tune what the plant simulator (edge-agent/simulator.py) sends — run/pause, speed, and per machine each
// signal's setpoint, noise, instrument range and pattern. Saved to /api/plant-data/{org}/sim-config; the simulator
// reads it every 5 s with its connector token. Guidance = the process twin's normal operating range in the signal's unit.
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowRight, Pause, Play, RotateCcw, Settings2 } from "lucide-react";
import { motion } from "motion/react";
import { useEffect, useMemo, useState } from "react";
import { Badge, Button, Drawer, ErrorNote, Modal, Skeleton } from "../../components/ui";
import { useToast } from "../../components/ui/toast";
import { api } from "../../lib/api";
import { cn } from "../../lib/cn";

const ORDER = ["RMG-1", "FBD-1", "BLENDER-1", "PRESS-1"];
const PATTERN_HELP: Record<string, string> = {
  steady: "setpoint ± noise",
  drift: "+ amplitude per batch (e.g. force creeping up as punches wear)",
  sine: "+ amplitude · sin(2π · minutes / period)",
  step: "+ amplitude on every N-th batch (a recurring fault)",
  spikes: "+ amplitude on about one in N readings",
  ramp: "rises by amplitude over each batch to the setpoint",
};
const n = (v: any) => (v === "" || v == null || Number.isNaN(Number(v)) ? 0 : Number(v));
const fmtv = (v: number) => (Math.abs(v) >= 1000 ? Math.round(v).toLocaleString("en-IN") : String(Number(v.toPrecision(3))));

// the same formula the simulator uses, seeded, for the preview
function preview(s: any, count = 48): number[] {
  let seed = 11;
  const rnd = () => { seed = (seed * 16807) % 2147483647; return seed / 2147483647; };
  const gauss = () => Math.sqrt(-2 * Math.log(rnd() || 1e-9)) * Math.cos(2 * Math.PI * rnd());
  const perBatch = s.per === "batch";
  return Array.from({ length: count }, (_, i) => {
    const b = perBatch ? i + 1 : Math.floor(i / 12) + 1, pr = perBatch ? 1 : (i % 12) / 11;
    let v = n(s.setpoint);
    if (s.pattern === "drift") v += n(s.amplitude) * (b - 1);
    else if (s.pattern === "sine") v += n(s.amplitude) * Math.sin((2 * Math.PI * i * (perBatch ? 65 : 5)) / Math.max(1, n(s.period_min)));
    else if (s.pattern === "step" && b % Math.max(1, n(s.every)) === 0) v += n(s.amplitude);
    else if (s.pattern === "ramp") v -= n(s.amplitude) * (1 - pr);
    else if (s.pattern === "spikes" && rnd() < 1 / Math.max(1, n(s.every))) v += n(s.amplitude);
    v += gauss() * n(s.noise);
    return Math.min(n(s.max), Math.max(n(s.min), v));
  });
}

function Spark({ s, g }: { s: any; g?: any }) {
  const v = preview(s);
  const lo = Math.min(...v, g?.lo ?? Infinity), hi = Math.max(...v, g?.hi ?? -Infinity), w = 150, h = 34;
  const y = (x: number) => (hi === lo ? h / 2 : h - ((x - lo) / (hi - lo)) * (h - 4) - 2);
  return (
    <svg width={w} height={h} className="overflow-visible">
      {g && <rect x={0} width={w} y={y(g.hi)} height={Math.max(1, y(g.lo) - y(g.hi))} fill="#10b996" opacity={0.12} />}
      <polyline points={v.map((x, i) => `${(i / (v.length - 1)) * w},${y(x)}`).join(" ")} fill="none" stroke="#06a7c4" strokeWidth={1.5} />
    </svg>
  );
}

function Num({ value, onChange, step = "any", className }: { value: number; onChange: (v: number) => void; step?: string; className?: string }) {
  const [t, setT] = useState(String(value));
  useEffect(() => setT(String(value)), [value]);
  return <input type="number" step={step} value={t} onChange={(e) => { setT(e.target.value); if (e.target.value !== "" && !Number.isNaN(Number(e.target.value))) onChange(Number(e.target.value)); }}
    className={cn("input h-8 w-[84px] px-2 text-right text-xs tabular-nums", className)} />;
}

export function SignalDialog({ m, a, guidance, patterns, onChange, onClose, onApply, saving }: {
  m: string; a: any; guidance: Record<string, any>; patterns: string[]; onChange: (f: string, k: string, v: any) => void; onClose: () => void; onApply: () => void; saving: boolean;
}) {
  return (
    <Modal open onClose={onClose} width={1040} title={<span className="flex items-center gap-2"><Settings2 size={18} /> {m} · {a.label}</span>}
      footer={<><Button variant="ghost" onClick={onClose}>Done</Button><Button onClick={onApply} loading={saving}>Apply to simulator</Button></>}>
      <p className="mb-3 text-xs text-ink-muted">Each reading = setpoint + pattern + noise, clamped to the instrument range (min–max). Per-batch signals are drawn once when a batch starts.
        The green band is the range the process twin treats as normal for that setting: stay inside it for good batches, push outside to make failures.</p>
      <div className="-mx-6 overflow-x-auto px-6">
        <table className="w-full min-w-[960px] text-xs">
          <thead className="text-[10.5px] uppercase tracking-wide text-ink-muted">
            <tr><th className="py-2 pr-3 text-left">Signal</th><th className="px-1 text-right">Setpoint</th><th className="px-1 text-right">Noise (SD)</th><th className="px-1 text-right">Min</th><th className="px-1 text-right">Max</th>
              <th className="px-2 text-left">Pattern</th><th className="px-1 text-right">Amplitude</th><th className="px-1 text-right">Every N / period</th><th className="pl-3 text-left">Preview</th></tr>
          </thead>
          <tbody>
            {Object.entries(a.signals).map(([f, s]: any) => {
              const g = guidance[`${m}.${f}`];
              return (
                <tr key={f} className="border-t border-line align-top">
                  <td className="min-w-[200px] py-2.5 pr-3"><div className="font-semibold">{s.label ?? f}</div>
                    <div className="text-[10.5px] text-ink-muted">{s.unit} · per {s.per === "batch" ? "batch" : "reading"}</div>
                    {g && <div className="mt-0.5 max-w-[220px] text-[10px] text-brand-700">{fmtv(g.lo)}–{fmtv(g.hi)} {s.unit}: {g.text}</div>}</td>
                  <td className="px-1 py-2.5 text-right"><Num value={s.setpoint} onChange={(v) => onChange(f, "setpoint", v)} className={g && (s.setpoint < g.lo || s.setpoint > g.hi) ? "ring-2 ring-amber-300" : ""} /></td>
                  <td className="px-1 py-2.5 text-right"><Num value={s.noise} onChange={(v) => onChange(f, "noise", v)} /></td>
                  <td className="px-1 py-2.5 text-right"><Num value={s.min} onChange={(v) => onChange(f, "min", v)} /></td>
                  <td className="px-1 py-2.5 text-right"><Num value={s.max} onChange={(v) => onChange(f, "max", v)} /></td>
                  <td className="px-2 py-2.5"><select className="input h-8 w-28 px-2 text-xs" value={s.pattern} onChange={(e) => onChange(f, "pattern", e.target.value)}>
                    {patterns.map((p) => <option key={p} value={p}>{p}</option>)}</select>
                    <div className="mt-0.5 max-w-[150px] text-[10px] text-ink-faint">{PATTERN_HELP[s.pattern]}</div></td>
                  <td className="px-1 py-2.5 text-right"><Num value={s.amplitude} onChange={(v) => onChange(f, "amplitude", v)} className={s.pattern === "steady" ? "opacity-40" : ""} /></td>
                  <td className="px-1 py-2.5 text-right">{s.pattern === "sine"
                    ? <Num value={s.period_min} onChange={(v) => onChange(f, "period_min", v)} />
                    : <Num value={s.every} step="1" onChange={(v) => onChange(f, "every", Math.max(1, Math.round(v)))} className={["step", "spikes"].includes(s.pattern) ? "" : "opacity-40"} />}</td>
                  <td className="py-2.5 pl-3"><Spark s={s} g={g} /></td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </Modal>
  );
}

/** The simulator's settings for an organisation: the saved config, a local draft, and apply (PUT). */
export function useSimConfig(slug: string, enabled = true) {
  const qc = useQueryClient();
  const toast = useToast();
  const q = useQuery({ queryKey: ["sim-config", slug], queryFn: () => api<any>(`/api/plant-data/${slug}/sim-config`), enabled: enabled && !!slug, refetchInterval: 15000 });
  const [draft, setDraft] = useState<any>(null);
  const [dirty, setDirty] = useState(false);
  const [saving, setSaving] = useState(false);
  useEffect(() => { if (q.data && !dirty) setDraft(q.data.config); }, [q.data, dirty]);
  const set = (fn: (c: any) => void) => { setDraft((c: any) => { const n2 = structuredClone(c); fn(n2); return n2; }); setDirty(true); };
  const apply = async (cfg?: any, quiet = false) => {
    setSaving(true);
    try {
      const r = await api<any>(`/api/plant-data/${slug}/sim-config`, { method: "PUT", json: { config: cfg ?? draft } });
      setDraft(r.config); setDirty(false);
      qc.setQueryData(["sim-config", slug], (old: any) => ({ ...old, config: r.config, guidance: r.guidance }));
      if (!quiet) toast("Applied: the simulator picks it up within 5 seconds");
    } catch (e) { toast((e as Error).message, "error"); } finally { setSaving(false); }
  };
  return { q, draft, setDraft, dirty, setDirty, saving, set, apply, guidance: q.data?.guidance ?? {}, patterns: q.data?.patterns ?? Object.keys(PATTERN_HELP) };
}

export function SimEngine({ slug, open, onClose, machines }: { slug: string; open: boolean; onClose: () => void; machines: any[] }) {
  const qc = useQueryClient();
  const toast = useToast();
  const q = useQuery({ queryKey: ["sim-config", slug], queryFn: () => api<any>(`/api/plant-data/${slug}/sim-config`), enabled: open && !!slug, refetchInterval: open ? 10000 : false });
  const [draft, setDraft] = useState<any>(null);
  const [dirty, setDirty] = useState(false);
  const [edit, setEdit] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  useEffect(() => { if (q.data && !dirty) setDraft(q.data.config); }, [q.data, dirty]);
  const guidance = q.data?.guidance ?? {};
  const batchOn = useMemo(() => Object.fromEntries(machines.map((m) => [m.machine, m.batch_no])), [machines]);
  const set = (fn: (c: any) => void) => { setDraft((c: any) => { const n2 = structuredClone(c); fn(n2); return n2; }); setDirty(true); };
  const setSig = (m: string, f: string, k: string, v: any) => set((c) => { c.apparatus[m].signals[f][k] = v; });
  const apply = async (cfg = draft) => {
    setSaving(true);
    try {
      const r = await api<any>(`/api/plant-data/${slug}/sim-config`, { method: "PUT", json: { config: cfg } });
      setDraft(r.config); setDirty(false);
      qc.setQueryData(["sim-config", slug], (old: any) => ({ ...old, config: r.config, guidance: r.guidance }));
      toast("Applied: the simulator picks it up within 5 seconds");
    } catch (e) { toast((e as Error).message, "error"); } finally { setSaving(false); }
  };
  const sim = q.data?.simulator;
  return (
    <Drawer open={open} onClose={onClose} width={600} title="Sim engine" subtitle="What the simulated machines send. The simulator reads these settings every 5 seconds.">
      {q.error ? <ErrorNote error={q.error} /> : !draft ? <Skeleton className="h-96" /> : (
        <div className="space-y-4 pb-20">
          <div className={cn("flex items-center gap-2 rounded-xl px-3 py-2.5 text-xs ring-1 ring-inset", sim?.online ? "bg-emerald-50/60 ring-emerald-200" : "bg-amber-50 ring-amber-200")}>
            <span className={cn("h-2 w-2 rounded-full", sim?.online ? "animate-pulse bg-emerald-500" : "bg-amber-500")} />
            {sim?.online ? <span><b>Simulator connected</b> · {Object.keys(sim.machines ?? {}).length} machines streaming</span>
              : <span><b>Simulator not running.</b> On the server: <code className="text-[11px]">docker compose --profile demo up -d plant-sim</code> (needs PLANT_SIM_TOKEN in .env). Settings saved here apply when it starts.</span>}
          </div>

          <div className="flex flex-wrap items-center gap-3 rounded-2xl p-4 ring-1 ring-inset ring-line">
            <Button size="sm" variant={draft.running ? "secondary" : "primary"} onClick={() => { const c = structuredClone(draft); c.running = !c.running; setDraft(c); apply(c); }}>
              {draft.running ? <><Pause size={14} /> Pause</> : <><Play size={14} /> Run</>}</Button>
            <label className="flex min-w-[220px] flex-1 items-center gap-2 text-xs">
              <span className="w-12 shrink-0 font-medium text-ink-soft">Speed</span>
              <span className="relative h-[18px] w-full"><span className="pointer-events-none absolute inset-x-0 top-1/2 h-1.5 -translate-y-1/2 rounded-full bg-slate-200" />
                <input type="range" min={1} max={120} step={1} value={draft.speed} onChange={(e) => set((c) => { c.speed = Number(e.target.value); })} className="range absolute inset-0 w-full" /></span>
              <span className="w-12 text-right font-semibold tabular-nums">{draft.speed}×</span>
            </label>
            <div className="w-full text-[10.5px] text-ink-faint">{draft.speed}× = one plant minute every {fmtv(60 / draft.speed)} s of real time; a 60-minute drying takes {60 / draft.speed >= 2 ? `${fmtv(60 / draft.speed)} min` : `${fmtv(3600 / draft.speed)} s`}.</div>
          </div>

          <div className="flex items-center justify-between gap-1 overflow-x-auto px-1 text-[11px] font-semibold text-ink-soft">
            {ORDER.map((m, i) => (
              <span key={m} className="flex items-center gap-1">
                <span className={cn("rounded-full px-2 py-1 ring-1 ring-inset", draft.apparatus[m]?.enabled ? "bg-gold-50 text-gold-700 ring-gold-200" : "bg-slate-50 text-ink-faint ring-line line-through")}>{m}</span>
                {i < ORDER.length - 1 && <ArrowRight size={12} className="text-ink-faint" />}
              </span>))}
          </div>

          {ORDER.map((m) => {
            const a = draft.apparatus[m];
            if (!a) return null;
            const quick = Object.entries(a.signals).filter(([, s]: any) => s.noise > 0 || s.pattern !== "steady").slice(0, 4);
            return (
              <motion.div key={m} layout className={cn("rounded-2xl p-4 ring-1 ring-inset transition", a.enabled ? "bg-white ring-line" : "bg-slate-50 ring-line opacity-70")}>
                <div className="flex items-center gap-3">
                  <button role="switch" aria-checked={a.enabled} onClick={() => set((c) => { c.apparatus[m].enabled = !c.apparatus[m].enabled; })}
                    className={cn("relative h-5 w-9 shrink-0 rounded-full transition", a.enabled ? "bg-brand-500" : "bg-slate-300")}>
                    <span className={cn("absolute top-0.5 h-4 w-4 rounded-full bg-white shadow transition-all", a.enabled ? "left-[18px]" : "left-0.5")} /></button>
                  <div className="min-w-0 flex-1"><div className="text-[14px] font-semibold">{m} <span className="font-normal text-ink-muted">· {a.label}</span></div>
                    <div className="text-[11px] text-ink-muted">{batchOn[m] ? <>running <b className="font-mono text-gold-700">{batchOn[m]}</b></> : "idle or waiting for its first batch"}
                      {m !== "FBD-1" && <> · runs {a.duration_min} min per batch</>}</div></div>
                  <button onClick={() => setEdit(m)} className="rounded-lg p-2 text-ink-muted ring-1 ring-inset ring-line hover:bg-gold-50 hover:text-gold-700" title="All signals: setpoint, noise, range, pattern"><Settings2 size={16} /></button>
                </div>
                {a.enabled && (
                  <div className="mt-3 space-y-2.5">
                    {quick.map(([f, s]: any) => {
                      const g = guidance[`${m}.${f}`];
                      const pct = (x: number) => `${Math.max(0, Math.min(100, ((x - s.min) / (s.max - s.min || 1)) * 100))}%`;
                      return (
                        <label key={f} className="block text-xs">
                          <div className="flex items-center justify-between"><span className="font-medium text-ink-soft">{s.label}{s.pattern !== "steady" && <Badge tone="indigo" className="ml-1.5">{s.pattern}</Badge>}</span>
                            <span className={cn("font-semibold tabular-nums", g && (s.setpoint < g.lo || s.setpoint > g.hi) && "text-amber-600")}>{fmtv(s.setpoint)} {s.unit}</span></div>
                          <div className="relative mt-1 h-[18px]">
                            <div className="pointer-events-none absolute inset-x-0 top-1/2 h-1.5 -translate-y-1/2 rounded-full bg-slate-200" />
                            {g && <div className="pointer-events-none absolute top-1/2 h-1.5 -translate-y-1/2 rounded-full bg-brand-400/70" style={{ left: pct(Math.max(s.min, g.lo)), width: `calc(${pct(Math.min(s.max, g.hi))} - ${pct(Math.max(s.min, g.lo))})` }} />}
                            <input type="range" min={s.min} max={s.max} step={(s.max - s.min) / 200} value={s.setpoint} onChange={(e) => setSig(m, f, "setpoint", Number(e.target.value))} className="range absolute inset-0 w-full" />
                          </div>
                          {g && <div className="text-[10px] text-ink-faint">green: {fmtv(g.lo)}–{fmtv(g.hi)} {s.unit} — {g.text}</div>}
                        </label>);
                    })}
                    {m !== "FBD-1" && (
                      <label className="flex items-center justify-between text-xs"><span className="font-medium text-ink-soft">Minutes per batch</span>
                        <Num value={a.duration_min} onChange={(v) => set((c) => { c.apparatus[m].duration_min = v; })} /></label>)}
                  </div>)}
              </motion.div>
            );
          })}

          <div className="sticky bottom-0 -mx-6 flex items-center gap-2 border-t border-line bg-white/95 px-6 py-3 backdrop-blur">
            <Button onClick={() => apply()} loading={saving} disabled={!dirty}>Apply to simulator</Button>
            <Button variant="ghost" onClick={() => { setDraft(q.data.defaults); setDirty(true); }}><RotateCcw size={14} /> Defaults</Button>
            <span className="ml-auto text-[11px] text-ink-muted">{dirty ? "unsaved changes" : q.data?.updated_by ? `saved by ${q.data.updated_by}` : "defaults"}</span>
          </div>
        </div>
      )}
      {edit && draft && (
        <SignalDialog m={edit} a={draft.apparatus[edit]} guidance={guidance} patterns={q.data?.patterns ?? Object.keys(PATTERN_HELP)}
          onChange={(f, k, v) => setSig(edit, f, k, v)} onClose={() => setEdit(null)} onApply={() => apply()} saving={saving} />
      )}
    </Drawer>
  );
}
