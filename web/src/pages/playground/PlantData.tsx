// Plant data (Playground): an organisation's own batch records — files uploaded, or machine readings streamed by the
// edge agent (edge-agent/, OPC UA / Modbus) — control charts against limits, why a batch fell outside a limit, a live
// forecast of the batches running now, and the failure tree calibrated to the plant (core/chem/batch_data.py,
// backend/app/routers/plant_data.py).
import { keepPreviousData, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Activity, AlertTriangle, Beaker, CalendarClock, CheckCircle2, ChevronDown, ClipboardCopy, Clock, Cog, Download, FileSpreadsheet, Gauge, Layers, ListChecks, Microscope, Pause, Play, PlayCircle, Plug, Radio, Ruler, Settings2, SlidersHorizontal, Trash2, UploadCloud, Wind,
} from "lucide-react";
import { AnimatePresence, motion } from "motion/react";
import { useEffect, useMemo, useRef, useState } from "react";
import { useParams, useSearchParams } from "react-router-dom";
import { CartesianGrid, ComposedChart, Line, ReferenceArea, ReferenceLine, ResponsiveContainer, Scatter, Tooltip, XAxis, YAxis } from "recharts";
import { Badge, Button, Card, CardHeader, Drawer, Empty, ErrorNote, Modal, PageSkeleton, SearchSelect, Segmented, Skeleton, Stat } from "../../components/ui";
import { useToast } from "../../components/ui/toast";
import { api, del, post } from "../../lib/api";
import { cn } from "../../lib/cn";
import { plural } from "../../lib/format";
import { useMe } from "../../lib/session";
import { ProcessTwin } from "./ProcessTwin";
import { SignalDialog, SimEngine, useSimConfig } from "./SimEngine";

const ICON: Record<string, any> = { batch_summary: ListChecks, rmg: Cog, fbd: Wind, blender: Layers, press: Gauge, ipqc: Ruler, dissolution: Beaker, qc_release: Microscope, api_coa: FileSpreadsheet };
const fmt = (v: number | null | undefined, d = 3) => (v == null || Number.isNaN(v) ? "—" : Math.abs(v) >= 1000 ? Math.round(v).toLocaleString("en-IN") : String(Number(v.toPrecision(d))));
const QC_COLS = ["assay_pct", "av", "dissolution_pct", "disintegration_min", "lod_pct", "tensile_mpa", "friability_pct"];
const TWIN_PARAMS = ["api_potency_pct", "api_d50_um", "weighing_error_pct", "granulation_liquid_pct", "inlet_c", "dew_point_c", "air_m3_h", "drying_min", "blend_min", "pressure_mpa", "weight_rsd_pct"];

// --- one control chart ------------------------------------------------------------------------------------------------
function ControlChart({ c, onBatch }: { c: any; onBatch: (b: string) => void }) {
  const sig = new Set(c.signals.map((s: any) => s.batch));
  const data = c.points.map((p: any, i: number) => ({ i: i + 1, batch: p.batch, v: p.value, oos: c.oos.includes(p.batch) ? p.value : null, sig: sig.has(p.batch) && !c.oos.includes(p.batch) ? p.value : null }));
  const cpkTone = c.cpk == null ? "slate" : c.cpk >= 1.33 ? "brand" : c.cpk >= 1 ? "amber" : "rose";
  const lims = [c.lcl, c.ucl, c.spec?.lo, c.spec?.hi, c.min, c.max].filter((x: any) => x != null) as number[];
  const pad = (Math.max(...lims) - Math.min(...lims)) * 0.08 || 1;
  return (
    <Card className="p-4">
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0"><div className="truncate text-[13px] font-semibold">{c.label}</div>
          <div className="text-[11px] text-ink-muted">n {c.n} · mean {fmt(c.mean)} {c.unit} · SD {fmt(c.sd, 2)}</div></div>
        <div className="flex shrink-0 items-center gap-1.5">
          {c.signals.length > 0 && <Badge tone="amber">{plural(c.signals.length, "signal")}</Badge>}
          {c.cpk != null && <Badge tone={cpkTone as any}>Cpk {c.cpk}{c.cpk_indicative ? "*" : ""}</Badge>}
        </div>
      </div>
      <div className="mt-2 h-36">
        <ResponsiveContainer width="100%" height="100%">
          <ComposedChart data={data} margin={{ top: 6, right: 6, left: -12, bottom: 0 }} onClick={(e: any) => e?.activePayload?.[0] && onBatch(e.activePayload[0].payload.batch)}>
            <CartesianGrid vertical={false} stroke="#eef1f6" />
            <XAxis dataKey="i" tickLine={false} axisLine={false} fontSize={10} />
            <YAxis domain={[Math.min(...lims) - pad, Math.max(...lims) + pad]} tickLine={false} axisLine={false} fontSize={10} width={44} tickFormatter={(v) => fmt(v, 3)} />
            <Tooltip content={({ active, payload }: any) => active && payload?.[0] ? (
              <div className="rounded-lg bg-night-900 px-2.5 py-1.5 text-[11px] text-white shadow-lift">{payload[0].payload.batch}: <b>{fmt(payload[0].payload.v, 4)}</b> {c.unit}</div>) : null} />
            <ReferenceLine y={c.mean} stroke="#94a3b8" />
            <ReferenceLine y={c.ucl} stroke="#94a3b8" strokeDasharray="4 3" />
            <ReferenceLine y={c.lcl} stroke="#94a3b8" strokeDasharray="4 3" />
            {c.spec?.lo != null && <ReferenceLine y={c.spec.lo} stroke="#e11d48" strokeWidth={1.5} />}
            {c.spec?.hi != null && <ReferenceLine y={c.spec.hi} stroke="#e11d48" strokeWidth={1.5} />}
            <Line dataKey="v" stroke="#06a7c4" strokeWidth={2} dot={{ r: 2.5, fill: "#06a7c4" }} isAnimationActive animationDuration={900} />
            <Scatter dataKey="sig" fill="#f59e0b" />
            <Scatter dataKey="oos" fill="#e11d48" />
          </ComposedChart>
        </ResponsiveContainer>
      </div>
      <div className="mt-1 flex flex-wrap gap-x-3 text-[10px] text-ink-faint">
        <span>dashed: control limits (±3σ)</span>{c.spec && <span className="text-rose-500" title={c.spec.text}>red: limit · {c.spec.kind === "source" ? "cited" : c.spec.kind === "yours" ? "yours" : "default"}</span>}
        {c.signals.slice(0, 2).map((s: any, i: number) => <span key={i} className="text-amber-600">{s.batch}: {s.text}</span>)}
      </div>
    </Card>
  );
}

// --- why a batch fell outside a limit -------------------------------------------------------------------------------
function Diagnosis({ d, onReplay, hasTwin }: { d: any; onReplay: () => void; hasTwin: boolean }) {
  return (
    <motion.div initial={{ opacity: 0, y: 10 }} whileInView={{ opacity: 1, y: 0 }} viewport={{ once: true }} className="rounded-2xl bg-white p-4 shadow-card ring-1 ring-inset ring-line">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div><div className="text-[17px] font-semibold tracking-tight">{d.batch}</div><div className="text-[11px] text-ink-muted">{[d.meta.product, d.meta.mfg_date].filter(Boolean).join(" · ")}</div></div>
        {hasTwin && <Button size="sm" variant="secondary" onClick={onReplay}><PlayCircle size={14} /> Replay in the failure tree</Button>}
      </div>
      <div className="mt-3 space-y-1.5">
        {d.failed.map((f: any) => (
          <div key={f.field} className="flex flex-wrap items-baseline gap-x-2 rounded-lg bg-rose-50/70 px-3 py-2 text-xs ring-1 ring-inset ring-rose-100">
            <AlertTriangle size={12} className="translate-y-[1px] text-rose-500" /><b>{f.label}</b>
            <span className="text-[15px] font-semibold tabular-nums text-rose-700">{fmt(f.value, 4)}</span>
            <span className="text-ink-muted">limit {f.lo != null ? `≥ ${f.lo}` : ""}{f.lo != null && f.hi != null ? " and " : ""}{f.hi != null ? `≤ ${f.hi}` : ""}</span>
            {f.predicted != null && <span className="ml-auto text-[11px] text-ink-muted">model, from this batch's settings: <b className="text-ink">{fmt(f.predicted, 3)}</b></span>}
          </div>
        ))}
      </div>
      {d.deviations.length > 0 && (
        <div className="mt-3">
          <div className="label mb-1.5">This batch against your other batches</div>
          <div className="space-y-1">
            {d.deviations.map((x: any) => (
              <div key={x.field} className="grid grid-cols-[minmax(0,1fr)_140px_64px] items-center gap-3 text-xs">
                <div className="flex min-w-0 items-center gap-1.5"><span className="truncate">{x.label}</span>
                  {x.linked && <span className="shrink-0 rounded bg-gold-100 px-1 text-[9.5px] font-semibold text-gold-700" title="The failure tree links this setting to the failed test">linked</span>}
                  <span className="shrink-0 text-ink-faint">{fmt(x.value)} vs {fmt(x.mean)} {x.unit}</span></div>
                <div className="relative h-2 rounded-full bg-slate-100">
                  <div className="absolute left-1/2 top-0 h-2 w-px bg-slate-300" />
                  <motion.div initial={{ width: 0 }} whileInView={{ width: `${Math.min(50, Math.abs(x.z) * 12.5)}%` }} viewport={{ once: true }} transition={{ duration: 0.7 }}
                    className={cn("absolute top-0 h-2 rounded-full", Math.abs(x.z) >= 2 ? "bg-rose-400" : Math.abs(x.z) >= 1 ? "bg-amber-400" : "bg-slate-300")}
                    style={x.z >= 0 ? { left: "50%" } : { right: "50%" }} />
                </div>
                <div className={cn("text-right font-semibold tabular-nums", Math.abs(x.z) >= 2 ? "text-rose-600" : "text-ink-soft")}>{x.z > 0 ? "+" : ""}{x.z} SD</div>
              </div>
            ))}
          </div>
          <div className="mt-2 text-[10.5px] text-ink-faint">Distance from your batches' mean in standard deviations. A large, linked deviation is where to look first; it is not proof of the cause.</div>
        </div>
      )}
    </motion.div>
  );
}

// --- live: connectors, machines, and the twin's forecast for the batches running now -------------------------------
function Spark({ data, color = "#06a7c4" }: { data: (number | null)[]; color?: string }) {
  const v = data.filter((x): x is number => x != null);
  if (v.length < 2) return <div className="h-6" />;
  const lo = Math.min(...v), hi = Math.max(...v), w = 96, h = 24;
  const pts = v.map((y, i) => `${(i / (v.length - 1)) * w},${hi === lo ? h / 2 : h - ((y - lo) / (hi - lo)) * (h - 4) - 2}`).join(" ");
  return <svg width={w} height={h} className="overflow-visible"><polyline points={pts} fill="none" stroke={color} strokeWidth={1.6} strokeLinejoin="round" /></svg>;
}

function Connectors({ slug, conns, onChange }: { slug: string; conns: any[]; onChange: () => void }) {
  const [name, setName] = useState("");
  const [made, setMade] = useState<any>(null);
  const [busy, setBusy] = useState(false);
  const toast = useToast();
  const origin = typeof window !== "undefined" ? window.location.origin : "";
  const add = async () => {
    setBusy(true);
    try { setMade(await post<any>(`/api/plant-data/${slug}/connectors`, { name: name || "Plant agent" })); setName(""); onChange(); }
    catch (e) { toast((e as Error).message, "error"); } finally { setBusy(false); }
  };
  const revoke = async (c: any) => {
    if (!confirm(`Revoke "${c.name}"? Its agent stops being accepted; data already streamed stays.`)) return;
    await del(`/api/plant-data/${slug}/connectors/${c.id}`); onChange();
  };
  const file = (n: string) => `/api/plant-data/${slug}/agent/${n}${n === "config.yaml" ? `?url=${encodeURIComponent(origin)}` : ""}`;
  return (
    <Card>
      <CardHeader icon={<Radio size={16} />} title="Connectors" subtitle="An edge agent at the plant reads your machines over OPC UA or Modbus, read-only, and streams here" />
      <div className="space-y-3 p-5">
        {conns.map((c) => (
          <div key={c.id} className="flex flex-wrap items-center gap-3 rounded-xl px-3 py-2.5 ring-1 ring-inset ring-line">
            <span className="relative flex h-2.5 w-2.5">{c.online && <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-emerald-400 opacity-60" />}
              <span className={cn("relative inline-flex h-2.5 w-2.5 rounded-full", c.online ? "bg-emerald-500" : "bg-slate-300")} /></span>
            <div className="min-w-0 flex-1"><div className="text-[13px] font-semibold">{c.name} <span className="font-mono text-[11px] font-normal text-ink-faint">{c.token_hint}…</span></div>
              <div className="text-[11px] text-ink-muted">{c.online ? "online" : c.last_seen_at ? `last seen ${new Date(c.last_seen_at).toLocaleString("en-IN")}` : "waiting for the agent's first push"}
                {Object.keys(c.machines).length > 0 && ` · ${Object.keys(c.machines).join(", ")}`}{c.agent?.host && ` · on ${c.agent.host}`}</div></div>
            <button onClick={() => revoke(c)} className="rounded-lg p-2 text-ink-faint hover:bg-rose-50 hover:text-rose-600" title="Revoke"><Trash2 size={15} /></button>
          </div>
        ))}
        <div className="flex flex-wrap items-center gap-2">
          <input className="input h-9 w-64 text-xs" placeholder="Name, e.g. Ahmedabad OSD line" value={name} onChange={(e) => setName(e.target.value)} />
          <Button size="sm" onClick={add} loading={busy}><Plug size={14} /> Add a connector</Button>
          <span className="ml-auto flex flex-wrap gap-1.5">
            {["eurveda_agent.py", "config.yaml", "requirements.txt", "simulator.py", "README.md"].map((n) => (
              <a key={n} href={file(n)} download className="inline-flex items-center gap-1 rounded-lg px-2 py-1 text-[11px] font-semibold text-ink-soft ring-1 ring-inset ring-line hover:bg-slate-50"><Download size={11} /> {n}</a>))}
          </span>
        </div>
        {made && (
          <motion.div initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} className="rounded-xl bg-night-900 p-4 text-xs text-slate-300">
            <div className="mb-1 font-semibold text-white">"{made.name}" created. Copy the token now: it is not shown again.</div>
            <div className="flex items-center gap-2"><code className="min-w-0 flex-1 truncate rounded bg-white/10 px-2 py-1.5 font-mono text-[11.5px] text-gold-200">{made.token}</code>
              <Button size="sm" variant="secondary" onClick={() => { navigator.clipboard.writeText(made.token).then(() => toast("Token copied")); }}><ClipboardCopy size={13} /> Copy</Button></div>
            <ol className="mt-3 list-decimal space-y-1 pl-4">
              <li>On a PC on the plant network: download the agent files above, then <code className="text-gold-200">pip install -r requirements.txt</code></li>
              <li>List your machines in <code className="text-gold-200">config.yaml</code>; find OPC UA tags with <code className="text-gold-200">python eurveda_agent.py --browse opc.tcp://&lt;machine-ip&gt;:4840</code></li>
              <li>Check the values match the machine's screen: <code className="text-gold-200">python eurveda_agent.py --config config.yaml --check</code></li>
              <li>Run: <code className="text-gold-200">EURVEDA_TOKEN=&lt;token&gt; python eurveda_agent.py --config config.yaml</code></li>
            </ol>
            <div className="mt-2 text-slate-400">No plant at hand? <code className="text-gold-200">python simulator.py</code> runs a dryer and a press over OPC UA; the downloaded config already points at it.</div>
          </motion.div>
        )}
      </div>
    </Card>
  );
}

// --- how a time series becomes one row per batch -----------------------------------------------------------------------
const BAND = ["#06a7c4", "#10b996", "#6366f1", "#f59e0b", "#a78bfa", "#fb7185"];

function Timeline({ slug, sets }: { slug: string; sets: any[] }) {
  const timed = sets.filter((d) => d.timestamps);
  const [ds, setDs] = useState<string>("");
  const [field, setField] = useState("");
  const [focus, setFocus] = useState<number | null>(0);  // one batch at a time (null = everything)
  const id = ds || String(timed[0]?.id ?? "");
  const q = useQuery({ queryKey: ["pd-timeline", slug, id, field], queryFn: () => api<any>(`/api/plant-data/${slug}/timeline/${id}${field ? `?field=${field}` : ""}`),
    enabled: !!id, placeholderData: keepPreviousData });
  const d = q.data;
  if (!timed.length) return <Empty icon={<Clock size={20} />} title="No time-series data yet">Upload a time-series export or stream from machines; this view then shows how the readings became batches.</Empty>;
  const allWins = (d?.windows ?? []).map((w: any) => ({ ...w, x1: new Date(w.start).getTime(), x2: new Date(w.end).getTime() })).sort((p: any, q: any) => p.x1 - q.x1);
  const f = focus != null && allWins.length ? Math.min(focus, allWins.length - 1) : null;
  const pad = f != null ? Math.max(20 * 60_000, (allWins[f].x2 - allWins[f].x1) * 0.6) : 0;
  const lo = f != null ? allWins[f].x1 - pad : -Infinity, hi = f != null ? allWins[f].x2 + pad : Infinity;
  const pts = (d?.points ?? []).map((p: any) => ({ x: new Date(p.t).getTime(), v: p.v, in: p.batch ? p.v : null, out: p.batch ? null : p.v })).filter((p: any) => p.x >= lo && p.x <= hi);
  const wins = allWins.filter((w: any) => w.x2 >= lo && w.x1 <= hi);
  const colour = Object.fromEntries((d?.per_batch ?? []).map((b: any, i: number) => [b.batch, BAND[i % BAND.length]]));
  const tf = (x: number) => new Date(x).toLocaleString("en-IN", { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" });
  return (
    <Card>
      <CardHeader icon={<Clock size={16} />} title="How your time series becomes batches"
        subtitle="Every reading falls inside the window of the batch that was on its machine at that moment; each batch's readings are then reduced to one value" />
      <div className="space-y-4 p-5">
        <div className="flex flex-wrap items-end gap-3">
          <div className="w-64"><div className="label mb-1">Data</div>
            <SearchSelect size="sm" value={id} onChange={setDs} options={timed.map((t) => ({ value: String(t.id), label: t.name, sub: t.linked_by_time ? "linked by the schedule" : t.live ? "live: batch tag on every reading" : "batch column" }))} /></div>
          <div className="w-56"><div className="label mb-1">Reading</div>
            <SearchSelect size="sm" value={d?.field ?? ""} onChange={setField} options={(d?.fields ?? []).map((f: any) => ({ value: f.id, label: f.label, sub: f.unit }))} /></div>
          {d?.link && <div className="pb-1 text-[11px] text-ink-muted">{plural(d.link.linked, "reading")} in {plural(d.link.batches, "batch", "batches")} · {d.link.outside} idle</div>}
          {allWins.length > 0 && (
            <div className="ml-auto flex items-center gap-1 pb-0.5">
              <Button size="sm" variant="secondary" disabled={f == null || f === 0} onClick={() => setFocus(Math.max(0, (f ?? 0) - 1))}>‹</Button>
              <span className="min-w-[120px] text-center text-[12px] font-semibold">{f == null ? `All ${allWins.length} windows` : `${allWins[f].batch}${allWins[f].machine ? ` · ${allWins[f].machine}` : ""}`}</span>
              <Button size="sm" variant="secondary" disabled={f == null || f >= allWins.length - 1} onClick={() => setFocus((f ?? 0) + 1)}>›</Button>
              <Button size="sm" variant="ghost" onClick={() => setFocus(f == null ? 0 : null)}>{f == null ? "One batch" : "All"}</Button>
            </div>)}
        </div>
        {d?.mode === "none" ? <div className="text-xs text-ink-muted">{d.reason}</div> : (
          <>
            <div className="h-64 rounded-xl bg-slate-50/60 p-2 ring-1 ring-inset ring-line">
              <ResponsiveContainer width="100%" height="100%">
                <ComposedChart data={pts} margin={{ top: 18, right: 10, left: -8, bottom: 0 }}>
                  <CartesianGrid vertical={false} stroke="#eef1f6" />
                  {wins.map((w: any) => <ReferenceArea key={`${w.batch}-${w.machine}`} x1={w.x1} x2={w.x2} fill={colour[w.batch] ?? "#06a7c4"} fillOpacity={0.12} stroke={colour[w.batch]} strokeOpacity={0.35}
                    label={{ value: w.batch, position: "insideTop", fontSize: 10, fill: "#334155" }} />)}
                  <XAxis dataKey="x" type="number" scale="time" domain={["dataMin", "dataMax"]} tickFormatter={tf} fontSize={10} tickLine={false} axisLine={false} minTickGap={40} />
                  <YAxis fontSize={10} tickLine={false} axisLine={false} width={44} />
                  <Tooltip labelFormatter={(x: any) => tf(x)} formatter={(v: any, n: any) => [`${fmt(v, 4)} ${d?.unit ?? ""}`, n === "in" ? "in a batch" : "between batches"]} contentStyle={{ fontSize: 11, borderRadius: 8 }} />
                  <Line dataKey="in" stroke="#0b7a65" strokeWidth={1.8} dot={{ r: 1.6 }} connectNulls={false} isAnimationActive animationDuration={800} />
                  <Scatter dataKey="out" fill="#cbd5e1" />
                </ComposedChart>
              </ResponsiveContainer>
            </div>
            <div className="text-[10.5px] text-ink-faint">Shaded bands: batch windows ({d?.linked_by === "schedule" ? "from your batch schedule" : "from the batch number on each reading"}). Grey dots: readings between batches, left out.</div>
            <div>
              <div className="label mb-1.5">…becomes one value per batch</div>
              <div className="flex gap-2 overflow-x-auto pb-1">
                {(d?.per_batch ?? []).map((b: any) => (
                  <motion.div key={b.batch} initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} className="min-w-[120px] rounded-xl bg-white p-2.5 ring-1 ring-inset ring-line" style={{ borderTop: `3px solid ${colour[b.batch]}` }}>
                    <div className="font-mono text-[11px] font-semibold">{b.batch}</div>
                    <div className="text-[15px] font-semibold tabular-nums">{b.value == null ? "—" : fmt(b.value, 4)} <span className="text-[10px] font-normal text-ink-faint">{d?.unit}</span></div>
                    <div className="text-[9.5px] text-ink-faint">{b.how ?? "value"}</div>
                  </motion.div>))}
              </div>
            </div>
          </>
        )}
      </div>
    </Card>
  );
}

function Fold({ title, sub, children, open: initial = false, icon }: { title: string; sub?: string; children: React.ReactNode; open?: boolean; icon?: React.ReactNode }) {
  const [open, setOpen] = useState(initial);
  return (
    <div className="rounded-2xl bg-white shadow-card ring-1 ring-inset ring-line">
      <button onClick={() => setOpen(!open)} className="flex w-full items-center gap-3 px-5 py-3.5 text-left">
        {icon && <span className="grid h-8 w-8 place-items-center rounded-lg bg-gold-50 text-gold-600 ring-1 ring-inset ring-gold-100">{icon}</span>}
        <span className="min-w-0 flex-1"><span className="block text-[15px] font-semibold">{title}</span>{sub && <span className="block text-[11px] text-ink-muted">{sub}</span>}</span>
        <ChevronDown size={16} className={cn("text-ink-muted transition-transform", open && "rotate-180")} />
      </button>
      <AnimatePresence initial={false}>{open && (
        <motion.div initial={{ height: 0, opacity: 0 }} animate={{ height: "auto", opacity: 1 }} exit={{ height: 0, opacity: 0 }} transition={{ duration: 0.25 }} className="overflow-hidden">
          <div className="border-t border-line p-5">{children}</div>
        </motion.div>)}</AnimatePresence>
    </div>
  );
}

// --- upload: one button, a modal that asks what kind of data, then the right upload -----------------------------------
const KIND_FORMATS: Record<"batch" | "timeseries", string[]> = {
  batch: ["batch_summary", "qc_release", "press", "fbd", "ipqc", "dissolution", "rmg", "blender", "api_coa"],
  timeseries: ["timeseries", "batch_schedule", "fbd", "press"],
};

function UploadModal({ open, onClose, slug, formats, molecules, onDone }: { open: boolean; onClose: () => void; slug: string; formats: any[]; molecules: any[]; onDone: (m?: string) => void }) {
  const [kind, setKind] = useState<"batch" | "timeseries" | null>(null);
  const [file, setFile] = useState<File | null>(null);
  const [prev, setPrev] = useState<any>(null);
  const [format, setFormat] = useState("");
  const [mapping, setMapping] = useState<Record<string, string>>({});
  const [machine, setMachine] = useState("");
  const [molecule, setMolecule] = useState("");
  const [name, setName] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<unknown>(null);
  const [drag, setDrag] = useState(false);
  const input = useRef<HTMLInputElement>(null);
  const toast = useToast();
  const reset = () => { setKind(null); setFile(null); setPrev(null); setFormat(""); setMapping({}); setMachine(""); setName(""); setErr(null); };
  const close = () => { reset(); onClose(); };
  const read = async (f: File, fmt?: string, mach?: string) => {
    setBusy(true); setErr(null);
    try {
      const fd = new FormData();
      fd.append("file", f);
      if (fmt) fd.append("format", fmt);
      fd.append("machine", mach ?? machine);
      const r = await api<any>(`/api/plant-data/${slug}/preview`, { method: "POST", body: fd });
      setPrev(r); setFormat(r.format); setMapping(r.mapping);
      if (r.molecule_guess) setMolecule((m) => m || r.molecule_guess);
      setName((n) => n || f.name.replace(/\.[a-z]+$/i, ""));
    } catch (e) { setErr(e); } finally { setBusy(false); }
  };
  const take = (f: File | null) => { if (!f) return; setFile(f); setPrev(null); read(f); };
  const process = async () => {
    if (!file) return;
    setBusy(true); setErr(null);
    try {
      const fd = new FormData();
      fd.append("file", file); fd.append("format", format); fd.append("mapping", JSON.stringify(mapping));
      fd.append("name", name); fd.append("molecule_key", molecule); fd.append("machine", machine);
      const r = await api<any>(`/api/plant-data/${slug}/datasets`, { method: "POST", body: fd });
      toast(`${r.name}: ${r.format === "batch_schedule" ? "schedule saved, time series re-linked" : `${plural(r.batches, "batch", "batches")} read`}`);
      onDone(molecule || undefined); close();
    } catch (e) { setErr(e); } finally { setBusy(false); }
  };
  const fm = formats.find((f) => f.id === format);
  const fields: any[] = fm ? [...fm.columns, ...Object.keys(mapping).filter((k) => !fm.columns.some((c: any) => c.id === k)).map((k) => ({ id: k, label: k }))] : [];
  const used = new Set(Object.values(mapping));
  const ok = prev && (format === "batch_schedule" ? mapping.batch_no && mapping.batch_start && mapping.batch_end : mapping.batch_no || (mapping.timestamp && prev.link?.linked));
  const samples = kind ? formats.filter((f) => KIND_FORMATS[kind].includes(f.id)) : [];

  return (
    <Modal open={open} onClose={close} width={760} title={!kind ? "Upload data" : kind === "batch" ? "Upload batch data" : "Upload time-series data"}
      footer={<><Button variant="ghost" onClick={close}>Cancel</Button>{kind && <Button onClick={process} loading={busy} disabled={!ok}><Activity size={15} /> Process</Button>}</>}>
      {!kind ? (
        <div className="space-y-3">
          <p className="text-sm text-ink-soft">What does your file look like?</p>
          <div className="grid gap-3 sm:grid-cols-2">
            {([["batch", Layers, "Batch data", "Every row has a batch number.", "BMR summary, QC results / CoA, a press or dryer log with a batch column, a dissolution export"],
              ["timeseries", Clock, "Time-series data", "Rows have a timestamp, no batch number.", "SCADA historian, HMI trend or data-logger export. Needs a batch schedule (which batch ran when), uploaded the same way."]] as const).map(([k, I, t, d, ex]) => (
              <button key={k} onClick={() => setKind(k)} className="group rounded-2xl p-5 text-left ring-1 ring-inset ring-line transition hover:-translate-y-0.5 hover:bg-gold-50/50 hover:shadow-hover hover:ring-gold-300">
                <span className="mb-3 grid h-11 w-11 place-items-center rounded-xl bg-gold-50 text-gold-600 ring-1 ring-inset ring-gold-100 group-hover:bg-gold-500 group-hover:text-white"><I size={20} /></span>
                <span className="block text-[16px] font-semibold">{t}</span>
                <span className="mt-0.5 block text-sm text-ink-soft">{d}</span>
                <span className="mt-2 block text-[11.5px] text-ink-muted">{ex}</span>
              </button>))}
          </div>
        </div>
      ) : (
        <div className="space-y-4">
          <button onClick={reset} className="text-xs font-semibold text-gold-700 hover:underline">← {kind === "batch" ? "Batch data" : "Time-series data"} · change</button>
          {!prev ? (
            <>
              <div onDragOver={(e) => { e.preventDefault(); setDrag(true); }} onDragLeave={() => setDrag(false)} onDrop={(e) => { e.preventDefault(); setDrag(false); take(e.dataTransfer.files?.[0] ?? null); }}
                onClick={() => input.current?.click()}
                className={cn("grid cursor-pointer place-items-center rounded-2xl border-2 border-dashed px-6 py-10 text-center transition", drag ? "border-gold-400 bg-gold-50" : "border-line bg-slate-50/60 hover:border-gold-300 hover:bg-gold-50/40")}>
                <motion.div animate={drag ? { scale: 1.1, y: -4 } : { scale: 1, y: 0 }} className="mb-3 grid h-14 w-14 place-items-center rounded-2xl bg-white text-gold-600 shadow-card ring-1 ring-line">{busy ? <span className="h-5 w-5 animate-spin rounded-full border-2 border-gold-500 border-t-transparent" /> : <UploadCloud size={24} />}</motion.div>
                <div className="text-[15px] font-semibold">Drop the file here, or click to choose</div>
                <div className="mt-1 text-xs text-ink-muted">CSV, TSV or Excel · up to 8 MB · your column names are matched for you</div>
                <input ref={input} type="file" accept=".csv,.tsv,.txt,.xlsx,.xls" className="hidden" onChange={(e) => take(e.target.files?.[0] ?? null)} />
              </div>
              <div className="flex flex-wrap items-center gap-1.5 text-[11px] text-ink-muted">Templates:
                {samples.map((f) => <a key={f.id} href={`/api/plant-data/${slug}/formats/${f.id}/sample.csv`} download className="inline-flex items-center gap-1 rounded-lg px-2 py-1 font-semibold text-ink-soft ring-1 ring-inset ring-line hover:bg-slate-50"><Download size={11} /> {f.label}</a>)}
              </div>
            </>
          ) : (
            <motion.div initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} className="space-y-3">
              <div className="flex flex-wrap items-center gap-3 rounded-xl bg-slate-50 px-4 py-3 ring-1 ring-inset ring-line">
                <FileSpreadsheet size={18} className="text-gold-600" />
                <div className="min-w-0 flex-1"><div className="truncate text-sm font-semibold">{prev.filename}</div>
                  <div className="text-[11px] text-ink-muted">{plural(prev.rows, "row")}{prev.batches ? ` · ${plural(prev.batches, "batch", "batches")}` : ""} · {plural(Object.keys(mapping).length, "column")} recognised</div></div>
                <button onClick={() => { setPrev(null); setFile(null); }} className="text-xs font-semibold text-ink-muted hover:text-ink">Choose another</button>
              </div>
              <div className="grid gap-3 sm:grid-cols-2">
                <div><div className="label mb-1">Read as</div>
                  <SearchSelect size="sm" value={format} onChange={(v) => { setFormat(v); if (file) read(file, v); }} options={formats.filter((f) => KIND_FORMATS[kind].includes(f.id)).map((f) => ({ value: f.id, label: f.label, sub: f.apparatus }))} /></div>
                {prev.link && !mapping.machine && prev.machines?.length > 0 ? (
                  <div><div className="label mb-1">From machine</div>
                    <SearchSelect size="sm" value={machine} onChange={(v) => { setMachine(v); if (file) read(file, format, v); }} clearLabel="Any machine" placeholder="Any machine" options={prev.machines.map((m: string) => ({ value: m, label: m }))} /></div>
                ) : (
                  <div><div className="label mb-1">Molecule (for the failure tree)</div>
                    <SearchSelect size="sm" value={molecule} onChange={setMolecule} clearLabel="Not set" placeholder="Choose the molecule" searchPlaceholder="Search a molecule…" options={molecules.map((m) => ({ value: m.key, label: m.name }))} /></div>)}
              </div>
              {prev.link && (
                <div className={cn("flex items-start gap-2.5 rounded-xl px-4 py-3 text-xs ring-1 ring-inset", prev.link.linked ? "bg-brand-50/60 ring-brand-200" : "bg-amber-50 ring-amber-200")}>
                  <Clock size={15} className="mt-0.5 shrink-0" />
                  {prev.link.windows === 0
                    ? <span><b>No batch schedule yet.</b> Timestamped readings are matched to batches with a schedule (batch, machine, start, end). Upload the schedule first — choose "Batch schedule" under Read as if this file is one.</span>
                    : <span><b>{plural(prev.link.linked, "reading")} matched to {plural(prev.link.batches, "batch", "batches")}</b> by time{prev.link.outside > 0 ? `; ${prev.link.outside} between batches are left out` : ""}.</span>}
                </div>)}
              {format === "batch_schedule" && <div className="rounded-xl bg-indigo-50/60 px-4 py-3 text-xs ring-1 ring-inset ring-indigo-200"><b>Batch schedule:</b> once saved, every time-series file is re-matched to batches with it.</div>}
              <Fold title={`Columns · ${Object.keys(mapping).length} recognised`} sub="Check or change which of your columns is which" icon={<ListChecks size={15} />}>
                <div className="-my-2 max-h-72 divide-y divide-line overflow-auto">
                  {fields.map((c) => (
                    <div key={c.id} className="flex items-center gap-3 py-1.5">
                      <div className="min-w-0 flex-1 text-xs">{mapping[c.id] ? <CheckCircle2 size={12} className="mr-1 inline text-brand-600" /> : null}{c.label}{c.unit && <span className="text-ink-faint"> ({c.unit})</span>}{c.required && <span className="text-rose-500">*</span>}</div>
                      <div className="w-56"><SearchSelect size="sm" value={mapping[c.id] ?? ""} clearLabel="Not in this file" placeholder="Not in this file"
                        onChange={(v) => setMapping((m) => { const n2 = { ...m }; if (v) n2[c.id] = v; else delete n2[c.id]; return n2; })}
                        options={(prev.headers as string[]).map((h) => ({ value: h, label: h, disabled: used.has(h) && mapping[c.id] !== h }))} /></div>
                    </div>))}
                </div>
              </Fold>
            </motion.div>
          )}
          {err != null && <ErrorNote error={err} />}
        </div>
      )}
    </Modal>
  );
}

// --- live line: the machines in order, each batch moving through them -------------------------------------------------
const STATION_ICON: Record<string, any> = { rmg: Cog, fbd: Wind, blender: Layers, press: Gauge };
const STATION_KEY: Record<string, string[]> = { rmg: ["binder_kg", "impeller_kw"], fbd: ["lod_pct", "inlet_c", "elapsed_min"], blender: ["blend_min", "blender_rpm"], press: ["force_kn", "tablet_weight_mg"] };
const SHORT: Record<string, string> = { assay: "Assay", uniformity: "CU", dissolution: "Diss.", disintegration: "DT", lod: "LOD", strength: "Strength" };

function Station({ m, cfg, speed, onTune, tick }: { m: any; cfg: any; speed: number; onTune?: () => void; tick: number }) {
  const I = STATION_ICON[m.format] ?? Radio;
  const keys = (STATION_KEY[m.format] ?? m.fields.map((f: any) => f.id)).filter((k: string) => m.latest[k] != null);
  const main = keys[0];
  const f = (id: string) => m.fields.find((x: any) => x.id === id);
  const dur = cfg ? (m.format === "fbd" ? cfg.signals?.drying_min?.setpoint : m.format === "blender" ? Math.max(cfg.duration_min, cfg.signals?.blend_min?.setpoint ?? 0) : cfg.duration_min) : null;
  const started = m.batch_started ? new Date(m.batch_started).getTime() : null;
  const pr = dur && started ? Math.min(1, ((tick - started) / 1000) * speed / 60 / dur) : null;
  return (
    <motion.button layout onClick={onTune} disabled={!onTune} whileHover={onTune ? { y: -3 } : undefined}
      className={cn("group relative flex min-w-0 flex-col rounded-2xl bg-white p-4 text-left shadow-card ring-1 ring-inset ring-line transition", onTune && "cursor-pointer hover:shadow-hover hover:ring-gold-300")}>
      <div className="flex items-start gap-2.5">
        <span className="grid h-10 w-10 shrink-0 place-items-center rounded-xl bg-gold-50 text-gold-600 ring-1 ring-inset ring-gold-100"><I size={19} /></span>
        <div className="min-w-0 flex-1"><div className="flex items-center gap-1.5 text-[14px] font-semibold">{m.machine}<span className="relative flex h-2 w-2"><span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-emerald-400 opacity-60" /><span className="relative inline-flex h-2 w-2 rounded-full bg-emerald-500" /></span></div>
          <div className="truncate text-[11px] text-ink-muted">{cfg?.label ?? m.format_label}</div></div>
        {onTune && <Settings2 size={15} className="text-ink-faint transition group-hover:text-gold-600" />}
      </div>
      <div className="mt-3 h-7 overflow-hidden">
        <AnimatePresence mode="popLayout" initial={false}>
          <motion.span key={m.batch_no} initial={{ x: -40, opacity: 0 }} animate={{ x: 0, opacity: 1 }} exit={{ x: 40, opacity: 0 }} transition={{ type: "spring", stiffness: 260, damping: 24 }}
            className="inline-flex items-center gap-1.5 rounded-lg bg-night-900 px-2.5 py-1 font-mono text-[12px] font-semibold text-gold-200">{m.batch_no}</motion.span>
        </AnimatePresence>
      </div>
      {pr != null && <div className="mt-2 h-1 overflow-hidden rounded-full bg-slate-100"><motion.div className="h-full rounded-full bg-gradient-to-r from-gold-400 to-brand-500" animate={{ width: `${Math.max(3, pr * 100)}%` }} transition={{ duration: 0.8 }} /></div>}
      {main && (
        <div className="mt-3 flex items-end justify-between gap-2">
          <div><div className="text-[10.5px] text-ink-muted">{f(main)?.label}</div>
            <div className="text-[22px] font-semibold leading-none tabular-nums">{fmt(m.latest[main], 4)} <span className="text-[11px] font-normal text-ink-faint">{f(main)?.unit}</span></div></div>
          <Spark data={m.series[main] ?? []} />
        </div>)}
      <div className="mt-2 space-y-0.5">
        {keys.slice(1, 3).map((k: string) => <div key={k} className="flex justify-between text-[11px]"><span className="text-ink-muted">{f(k)?.label}</span><span className="font-semibold tabular-nums">{fmt(m.latest[k], 4)} {f(k)?.unit}</span></div>)}
      </div>
    </motion.button>
  );
}

function LiveLine({ slug, molecule, onReplay }: { slug: string; molecule: string; onReplay: (b: string, params: Record<string, number>) => void }) {
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["plant-live", slug, molecule], queryFn: () => api<any>(`/api/plant-data/${slug}/live${molecule ? `?molecule=${molecule}` : ""}`),
    refetchInterval: 4000, placeholderData: keepPreviousData, enabled: !!slug });
  const sim = useSimConfig(slug);
  const [edit, setEdit] = useState<string | null>(null);
  const [all, setAll] = useState(false);
  const [tick, setTick] = useState(Date.now());
  useEffect(() => { const t = setInterval(() => setTick(Date.now()), 1000); return () => clearInterval(t); }, []);
  const [speed, setSpeed] = useState<number | null>(null);
  useEffect(() => {
    if (speed == null || !sim.draft || speed === sim.draft.speed) return;
    const t = setTimeout(() => { const c = structuredClone(sim.draft); c.speed = speed; sim.apply(c, true); }, 600);
    return () => clearTimeout(t);
  }, [speed]); // eslint-disable-line react-hooks/exhaustive-deps
  const d = q.data;
  if (q.error) return <ErrorNote error={q.error} />;
  if (!d) return <Skeleton className="h-96" />;
  const simConn = d.connectors.find((c: any) => c.name === "Demo simulator");
  const simOn = !!simConn?.online;
  const cfg = sim.draft;
  const sp = speed ?? cfg?.speed ?? 30;
  return (
    <div className="space-y-5">
      {/* the controls, on the line itself */}
      <div className="flex flex-wrap items-center gap-4 rounded-2xl bg-night-900 px-5 py-4 text-white shadow-lift">
        <div className="flex items-center gap-2.5">
          <span className="relative flex h-3 w-3">{d.machines.length > 0 && <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-emerald-400 opacity-70" />}<span className={cn("relative inline-flex h-3 w-3 rounded-full", d.machines.length ? "bg-emerald-400" : "bg-slate-500")} /></span>
          <div><div className="text-[15px] font-semibold">{d.machines.length ? `Live · ${plural(d.machines.length, "machine")} streaming` : "No machine streaming"}</div>
            <div className="text-[11px] text-slate-400">{simOn ? "Plant simulator · click a machine to tune what it sends" : simConn ? "Plant simulator stopped" : "Connect a plant below, or start the plant simulator"}</div></div>
        </div>
        {cfg && simConn && (
          <div className="flex flex-1 flex-wrap items-center justify-end gap-3">
            <Button size="sm" className={cfg.running ? "bg-white/10 text-white hover:bg-white/20" : "bg-gold-400 text-night-900 hover:bg-gold-300"} onClick={() => { const c = structuredClone(cfg); c.running = !c.running; sim.apply(c, true); }}>
              {cfg.running ? <><Pause size={14} /> Pause</> : <><Play size={14} /> Run</>}</Button>
            <label className="flex w-56 items-center gap-2 text-[11px] text-slate-300">Speed
              <span className="relative h-[18px] flex-1"><span className="pointer-events-none absolute inset-x-0 top-1/2 h-1.5 -translate-y-1/2 rounded-full bg-white/15" />
                <input type="range" min={1} max={120} value={sp} onChange={(e) => setSpeed(Number(e.target.value))} className="range absolute inset-0 w-full" /></span>
              <b className="w-9 text-right text-white">{sp}×</b></label>
            <Button size="sm" className="bg-white/10 text-white hover:bg-white/20" onClick={() => setAll(true)}><SlidersHorizontal size={14} /> All settings</Button>
          </div>)}
      </div>

      {d.machines.length > 0 ? (
        <div className="relative">
          <div className="pointer-events-none absolute left-8 right-8 top-1/2 hidden h-0.5 -translate-y-1/2 bg-gradient-to-r from-gold-200 via-brand-200 to-gold-200 xl:block" />
          <div className="relative grid gap-4 md:grid-cols-2 xl:grid-cols-4">
            {d.machines.map((m: any) => (
              <Station key={m.dataset_id} m={m} cfg={cfg?.apparatus?.[m.machine]} speed={sp} tick={tick} onTune={simOn && cfg?.apparatus?.[m.machine] ? () => setEdit(m.machine) : undefined} />))}
          </div>
        </div>
      ) : <Empty icon={<Radio size={20} />} title="Nothing streaming yet">{simConn ? "The plant simulator is connected but not sending: press Run above." : "Start the plant simulator on the server (docker compose --profile demo up -d plant-sim), or connect a plant's agent below."}</Empty>}

      {d.recent?.length > 0 && (
        <Card>
          <CardHeader icon={<Layers size={16} />} title="Batches on the line" subtitle={molecule ? "Newest first: where each batch is, and what its tests are forecast to give" : "Newest first: where each batch is · choose the molecule above for the forecast"} />
          <div className="divide-y divide-line px-5 pb-3 pt-2">
            <AnimatePresence initial={false}>
              {d.recent.map((b: any) => (
                <motion.div key={b.batch} layout initial={{ opacity: 0, y: -10, backgroundColor: "#ecfeff" }} animate={{ opacity: 1, y: 0, backgroundColor: "#ffffff" }} transition={{ duration: 0.6 }}
                  className="flex flex-wrap items-center gap-x-4 gap-y-2 py-3">
                  <div className="w-36 shrink-0"><div className="font-mono text-[13px] font-semibold">{b.batch}</div>
                    <div className="text-[10.5px] text-ink-muted">{b.complete ? "complete" : `on ${b.stations.find((s: any) => s.status === "running")?.machine ?? "the line"}`}</div></div>
                  <div className="flex items-center gap-1">
                    {b.stations.map((s: any, i: number) => (
                      <span key={s.machine} className="flex items-center gap-1" title={`${s.machine}: ${s.status}`}>
                        <span className={cn("grid h-6 min-w-6 place-items-center rounded-full px-1.5 text-[9.5px] font-bold",
                          s.status === "done" ? "bg-brand-500 text-white" : s.status === "running" ? "animate-pulse bg-gold-400 text-night-900" : "bg-slate-100 text-ink-faint")}>{s.machine.split("-")[0]}</span>
                        {i < b.stations.length - 1 && <span className={cn("h-0.5 w-3", s.status === "done" ? "bg-brand-400" : "bg-slate-200")} />}
                      </span>))}
                  </div>
                  <div className="flex flex-1 flex-wrap justify-end gap-1">
                    {(b.forecast ?? []).map((t: any) => (
                      <span key={t.test} className={cn("rounded-md px-1.5 py-0.5 text-[10.5px] font-semibold tabular-nums ring-1 ring-inset", t.fails ? "bg-rose-50 text-rose-700 ring-rose-200" : "bg-emerald-50 text-emerald-700 ring-emerald-200")}
                        title={`${t.label}: ${t.value}${b.complete ? "" : " (settings so far)"}`}>{SHORT[t.test] ?? t.label} {fmt(t.value, 3)}</span>))}
                  </div>
                  {molecule && Object.keys(b.settings ?? {}).length > 0 && <Button size="sm" variant="ghost" onClick={() => onReplay(b.batch, b.settings)}><PlayCircle size={14} /> Failure tree</Button>}
                </motion.div>))}
            </AnimatePresence>
          </div>
        </Card>)}

      <Fold title="Connect a real plant" sub="An edge agent at the plant reads machines over OPC UA or Modbus, read-only, and streams here" icon={<Plug size={15} />}>
        <Connectors slug={slug} conns={d.connectors} onChange={() => qc.invalidateQueries({ queryKey: ["plant-live", slug] })} />
      </Fold>

      {edit && sim.draft && (
        <SignalDialog m={edit} a={sim.draft.apparatus[edit]} guidance={sim.guidance} patterns={sim.patterns}
          onChange={(f, k, v) => sim.set((c: any) => { c.apparatus[edit].signals[f][k] = v; })} onClose={() => setEdit(null)} onApply={() => sim.apply()} saving={sim.saving} />)}
      <SimEngine slug={slug} open={all} onClose={() => setAll(false)} machines={d.machines} />
    </div>
  );
}

// --- one batch, on click --------------------------------------------------------------------------------------------------
function BatchDrawer({ a, batch, onClose, onReplay }: { a: any; batch: string | null; onClose: () => void; onReplay: (b: string) => void }) {
  const row = a?.batches.find((x: any) => x.batch_no === batch);
  const d = a?.diagnoses.find((x: any) => x.batch === batch);
  const label = (k: string) => a?.charts.find((c: any) => c.field === k)?.label ?? k.replace(/_/g, " ");
  return (
    <Drawer open={!!batch} onClose={onClose} width={640} title={<span className="font-mono">{batch}</span>} subtitle={[row?.product, row?.mfg_date].filter(Boolean).join(" · ")}>
      {row && (
        <div className="space-y-5">
          {d ? <Diagnosis d={d} hasTwin={!!a.molecule} onReplay={() => onReplay(row.batch_no)} />
            : <div className="flex items-center gap-2 rounded-xl bg-emerald-50 px-4 py-3 text-sm text-emerald-800 ring-1 ring-inset ring-emerald-200"><CheckCircle2 size={16} /> Every result of this batch is within its limit.</div>}
          <div>
            <div className="label mb-2">Everything recorded for this batch</div>
            <div className="divide-y divide-line rounded-xl ring-1 ring-inset ring-line">
              {Object.entries(row.values).map(([k, v]: any) => (
                <div key={k} className="flex items-center justify-between gap-3 px-3 py-2 text-xs">
                  <span className="text-ink-soft">{label(k)}{row.derived?.[k] && <span className="block text-[10px] text-ink-faint">{row.derived[k]}</span>}</span>
                  <span className={cn("font-semibold tabular-nums", row.out_of_spec.includes(k) && "text-rose-600")}>{fmt(v, 4)}</span>
                </div>))}
            </div>
          </div>
          {a.molecule && !d && <Button variant="secondary" onClick={() => onReplay(row.batch_no)}><PlayCircle size={14} /> Replay in the failure tree</Button>}
        </div>)}
    </Drawer>
  );
}

// --- the page --------------------------------------------------------------------------------------------------------------
export function PlantData() {
  const params = useParams();
  const [sp, setSp] = useSearchParams();
  const { data: me } = useMe();
  const qc = useQueryClient();
  const toast = useToast();
  const orgs = useQuery({ queryKey: ["orgs-list"], queryFn: () => api<any>("/api/orgs"), enabled: !!me?.is_platform && !params.slug, staleTime: 300_000 });
  // admins land on the plant simulator's organisation (backend DEMO_ORG) when it exists
  const orgList: any[] = orgs.data?.orgs ?? [];
  const slug = params.slug ?? me?.org?.slug ?? sp.get("org") ?? (orgList.find((o) => o.slug === "eurveda-demo") ?? orgList[0])?.slug ?? "";
  const view = (sp.get("view") === "live" || sp.get("src") === "scada" || sp.get("tab") === "live" ? "live" : "batches") as "batches" | "live";
  const molecule = sp.get("m") ?? "";
  const setParam = (k: string, v: string) => { const n2 = new URLSearchParams(sp); if (v) n2.set(k, v); else n2.delete(k); n2.delete("src"); n2.delete("tab"); n2.delete("data"); setSp(n2, { replace: true }); };
  const formats = useQuery({ queryKey: ["pd-formats", slug], queryFn: () => api<any>(`/api/plant-data/${slug}/formats`), enabled: !!slug, staleTime: 3600_000 });
  const mols = useQuery({ queryKey: ["pd-mols", slug], queryFn: () => api<any>(`/api/plant-data/${slug}/molecules`), enabled: !!slug, staleTime: 3600_000 });
  const sets = useQuery({ queryKey: ["pd-sets", slug], queryFn: () => api<any>(`/api/plant-data/${slug}/datasets`), enabled: !!slug, refetchInterval: view === "live" ? 20000 : false });
  const [upload, setUpload] = useState(false);
  const [group, setGroup] = useState<"cqa" | "param" | "raw">("cqa");
  const [sel, setSel] = useState<string | null>(null);
  const [replay, setReplay] = useState<{ id: string; label: string; set: Record<string, number> } | null>(null);
  const treeRef = useRef<HTMLDivElement>(null);
  const datasets: any[] = sets.data?.datasets ?? [];
  useEffect(() => { if (!molecule) { const m = datasets.find((d) => d.molecule_key)?.molecule_key; if (m) setParam("m", m); } }, [datasets, molecule]); // eslint-disable-line react-hooks/exhaustive-deps
  const ana = useQuery({ queryKey: ["pd-analysis", slug, molecule, datasets.map((d) => `${d.id}:${d.rows}:${d.batches}`).join(",")], enabled: !!slug && datasets.length > 0 && view === "batches",
    queryFn: () => post<any>(`/api/plant-data/${slug}/analysis`, { molecule_key: molecule || undefined }), placeholderData: keepPreviousData });
  const a = ana.data;
  const charts = useMemo(() => (a?.charts ?? []).filter((c: any) => c.kind === group), [a, group]);
  const worst = useMemo(() => (a?.charts ?? []).filter((c: any) => c.cpk != null).sort((x: any, y: any) => x.cpk - y.cpk)[0], [a]);
  const refresh = (m?: string) => { if (m && !molecule) setParam("m", m); qc.invalidateQueries({ queryKey: ["pd-sets", slug] }); qc.invalidateQueries({ queryKey: ["pd-analysis", slug] }); qc.invalidateQueries({ queryKey: ["pd-timeline", slug] }); };
  const remove = async (d: any) => {
    if (!confirm(`Delete "${d.name}" (${d.batches} batches)? This can't be undone.`)) return;
    try { await del(`/api/plant-data/${slug}/datasets/${d.id}`); toast("Deleted"); refresh(); } catch (e) { toast((e as Error).message, "error"); }
  };
  const replayParams = (label: string, p: Record<string, number>) => {
    setReplay({ id: `${label}:${Date.now()}`, label, set: p }); setSel(null);
    if (view !== "batches") setParam("view", "");
    setTimeout(() => treeRef.current?.scrollIntoView({ behavior: "smooth", block: "start" }), 250);
  };
  const replayBatch = (b: string) => {
    const row = a?.batches.find((x: any) => x.batch_no === b);
    replayParams(`batch ${b}`, Object.fromEntries(Object.entries(row?.values ?? {}).filter(([k]) => TWIN_PARAMS.includes(k))) as Record<string, number>);
  };

  if (!slug) return me?.is_platform && orgs.isLoading ? <PageSkeleton /> : <Empty icon={<FileSpreadsheet size={20} />} title="No organisation">Plant data belongs to an organisation: create one in Admin → Organisations.</Empty>;
  if (formats.isLoading || sets.isLoading) return <PageSkeleton />;
  if (formats.error) return <ErrorNote error={formats.error} />;
  const cols = a ? QC_COLS.filter((k) => a.batches.some((b: any) => k in b.values)) : [];

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-center gap-3">
        <Segmented value={view} onChange={(v) => setParam("view", v === "batches" ? "" : v)} options={[
          { value: "batches", label: <span className="flex items-center gap-1.5 px-1 text-[13px]"><Layers size={14} /> Batches</span> },
          { value: "live", label: <span className="flex items-center gap-1.5 px-1 text-[13px]"><Radio size={14} /> Live line</span> }]} />
        {me?.is_platform && !params.slug && (
          <div className="w-52"><SearchSelect size="sm" value={slug} onChange={(v) => setParam("org", v)} searchPlaceholder="Search an organisation…"
            options={orgList.map((o: any) => ({ value: o.slug, label: o.name, sub: o.city }))} /></div>)}
        <div className="w-60"><SearchSelect size="sm" value={molecule} onChange={(v) => setParam("m", v)} clearLabel="No molecule" placeholder="Molecule" searchPlaceholder="Search a molecule…"
          options={(mols.data?.molecules ?? []).map((m: any) => ({ value: m.key, label: m.name, sub: m.alerts ? `${m.alerts} CDSCO notices` : undefined }))} /></div>
        <Button className="ml-auto" onClick={() => setUpload(true)}><UploadCloud size={15} /> Upload data</Button>
      </div>

      {view === "live" ? <LiveLine slug={slug} molecule={molecule} onReplay={(b, p) => replayParams(`live batch ${b}`, p)} /> : (
        <>
          {!datasets.length ? (
            <div className="grid place-items-center rounded-3xl bg-gradient-to-br from-gold-50 via-white to-brand-50 px-6 py-16 text-center ring-1 ring-inset ring-line">
              <div className="mb-4 grid h-14 w-14 place-items-center rounded-2xl bg-white text-gold-600 shadow-card ring-1 ring-line"><FileSpreadsheet size={24} /></div>
              <div className="text-[22px] font-semibold tracking-tight">Your batches, against their limits</div>
              <p className="mt-1 max-w-lg text-sm text-ink-muted">Upload batch records or equipment exports, or watch the simulated line stream batches in real time.</p>
              <div className="mt-5 flex gap-2"><Button onClick={() => setUpload(true)}><UploadCloud size={15} /> Upload data</Button>
                <Button variant="secondary" onClick={() => setParam("view", "live")}><Radio size={15} /> Watch the live line</Button></div>
            </div>
          ) : !a ? <div className="space-y-4"><Skeleton className="h-28" /><Skeleton className="h-72" /><div className="text-center text-xs text-ink-muted">Reading your batches…</div></div> : (
            <>
              <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
                <Stat label="Batches" value={a.counts.batches} icon={<Layers size={18} />} hint={`from ${plural(datasets.length, "source")}`} />
                <Stat label="Outside a limit" value={a.counts.out_of_spec_batches} icon={<AlertTriangle size={18} />} tone={a.counts.out_of_spec_batches ? "rose" : "brand"} delay={0.05} hint="click one in the table to see why" />
                <Stat label="Control-chart signals" value={a.counts.signals} icon={<Activity size={18} />} tone="amber" delay={0.1} hint="drift before a failure" />
                <Stat label="Lowest Cpk" value={worst ? worst.cpk : "—"} decimals={2} icon={<Gauge size={18} />} tone="indigo" delay={0.15} hint={worst ? worst.label : "needs ≥ 5 batches with a limit"} />
              </div>

              <Card className="overflow-hidden">
                <CardHeader icon={<ListChecks size={16} />} title="Batches" subtitle="Click a batch to see everything recorded for it, and why it fell outside a limit" />
                <div className="mt-3 max-h-[520px] overflow-auto">
                  <table className="w-full text-xs">
                    <thead className="sticky top-0 bg-slate-50 text-[10.5px] uppercase tracking-wide text-ink-muted"><tr>
                      <th className="px-4 py-2 text-left">Batch</th><th className="px-3 py-2 text-left">Made</th>
                      {cols.map((k) => <th key={k} className="px-3 py-2 text-right">{a.charts.find((c: any) => c.field === k)?.label ?? k}</th>)}<th />
                    </tr></thead>
                    <tbody>{a.batches.map((b: any) => (
                      <tr key={b.batch_no} onClick={() => setSel(b.batch_no)} className={cn("cursor-pointer border-t border-line transition hover:bg-gold-50/50", b.out_of_spec.length && "bg-rose-50/40")}>
                        <td className="px-4 py-2 font-semibold">{b.out_of_spec.length > 0 && <AlertTriangle size={12} className="mr-1 inline text-rose-500" />}{b.batch_no}</td>
                        <td className="px-3 py-2 text-ink-muted">{b.mfg_date ?? ""}</td>
                        {cols.map((k) => <td key={k} className={cn("px-3 py-2 text-right tabular-nums", b.out_of_spec.includes(k) && "font-semibold text-rose-600")}>{fmt(b.values[k], 4)}</td>)}
                        <td className="px-3 text-right text-ink-faint">›</td>
                      </tr>))}</tbody>
                  </table>
                </div>
              </Card>

              <div className="space-y-3">
                <Fold title="Control charts" sub={`${plural(a.charts.length, "chart")} · limits, drift signals and Cpk per field`} icon={<Activity size={15} />}>
                  <div className="mb-3 flex justify-end"><Segmented value={group} onChange={setGroup} options={[{ value: "cqa", label: "Quality results" }, { value: "param", label: "Process settings" }, { value: "raw", label: "Other readings" }]} /></div>
                  <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
                    {charts.map((c: any) => <ControlChart key={c.field} c={c} onBatch={(b) => setSel(b)} />)}
                  </div>
                  {charts.length === 0 && <div className="text-xs text-ink-muted">None of your data has fields of this kind yet.</div>}
                </Fold>
                {datasets.some((d) => d.timestamps && d.format !== "batch_schedule") && (
                  <Fold title="How time-series data became batches" sub="Readings, the batch windows they fell in, and each batch's value" icon={<Clock size={15} />}>
                    <Timeline slug={slug} sets={datasets} />
                  </Fold>)}
                <Fold title="Your files and streams" sub={`${plural(datasets.length, "source")}, joined on batch number`} icon={<FileSpreadsheet size={15} />}>
                  <div className="-my-2 divide-y divide-line">
                    {datasets.map((d) => (
                      <div key={d.id} className="flex flex-wrap items-center gap-3 py-2.5 text-xs">
                        <span className="grid h-8 w-8 place-items-center rounded-lg bg-slate-50 text-ink-muted ring-1 ring-inset ring-line">{(() => { const I = d.live ? Radio : d.format === "batch_schedule" ? CalendarClock : ICON[d.format] ?? FileSpreadsheet; return <I size={15} />; })()}</span>
                        <div className="min-w-0 flex-1"><div className="flex items-center gap-1.5 truncate text-[13px] font-semibold">{d.name}
                          {d.live && <Badge tone="brand">live</Badge>}{d.format === "batch_schedule" && <Badge tone="indigo">schedule</Badge>}{d.linked_by_time && <Badge tone="sky">matched by time</Badge>}</div>
                          <div className="text-ink-muted">{d.format_label} · {plural(d.rows, "row")} · {plural(d.batches, "batch", "batches")} · {d.uploaded_by}</div></div>
                        <button onClick={() => remove(d)} className="rounded-lg p-2 text-ink-faint hover:bg-rose-50 hover:text-rose-600" title="Delete"><Trash2 size={15} /></button>
                      </div>))}
                  </div>
                </Fold>
                {a.molecule && Object.keys(a.model_check ?? {}).length > 0 && (
                  <Fold title="How well the model matches your batches" sub="The model's prediction from each batch's settings, against what was measured" icon={<Gauge size={15} />}>
                    <div className="grid gap-2 sm:grid-cols-3 lg:grid-cols-6">
                      {Object.entries(a.model_check).map(([k, v]: any) => (
                        <div key={k} className="rounded-xl bg-slate-50 p-3 ring-1 ring-inset ring-line">
                          <div className="text-[11px] text-ink-muted">{a.charts.find((c: any) => c.field === k)?.label ?? k}</div>
                          <div className="text-lg font-semibold tabular-nums">±{fmt(v.mean_abs_error, 2)}</div>
                          <div className="text-[10.5px] text-ink-faint">bias {v.bias > 0 ? "+" : ""}{fmt(v.bias, 2)} over {v.n}</div>
                        </div>))}
                    </div>
                  </Fold>)}
              </div>
            </>
          )}
          <div ref={treeRef} className="scroll-mt-24">
            {molecule ? <ProcessTwin mkey={molecule} endpoint={`/api/plant-data/${slug}/twin`} inject={replay} />
              : <Empty icon={<Beaker size={20} />} title="Choose the molecule to open the failure tree">The tree needs the molecule's dose and solubility; your data supplies the process settings and their spread.</Empty>}
          </div>
        </>
      )}

      <UploadModal open={upload} onClose={() => setUpload(false)} slug={slug} formats={formats.data.formats} molecules={mols.data?.molecules ?? []} onDone={refresh} />
      <BatchDrawer a={a} batch={sel} onClose={() => setSel(null)} onReplay={replayBatch} />
    </div>
  );
}
