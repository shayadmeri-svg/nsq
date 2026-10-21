// Plant data (Playground): an organisation's own batch records — files uploaded, or machine readings streamed by the
// edge agent (edge-agent/, OPC UA / Modbus) — control charts against limits, why a batch fell outside a limit, a live
// forecast of the batches running now, and the failure tree calibrated to the plant (core/chem/batch_data.py,
// backend/app/routers/plant_data.py).
import { keepPreviousData, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Activity, AlertTriangle, Beaker, CheckCircle2, ClipboardCopy, Cog, Download, FileSpreadsheet, Flame, Gauge, Layers, ListChecks,
  Microscope, PlayCircle, Plug, Radio, Ruler, Trash2, UploadCloud, Wind,
} from "lucide-react";
import { motion } from "motion/react";
import { useEffect, useMemo, useRef, useState } from "react";
import { useParams, useSearchParams } from "react-router-dom";
import { CartesianGrid, ComposedChart, Line, ReferenceLine, ResponsiveContainer, Scatter, Tooltip, XAxis, YAxis } from "recharts";
import { Badge, Button, Card, CardHeader, Empty, ErrorNote, PageSkeleton, SearchSelect, Segmented, Skeleton, Stat } from "../../components/ui";
import { useToast } from "../../components/ui/toast";
import { api, del, post } from "../../lib/api";
import { cn } from "../../lib/cn";
import { plural } from "../../lib/format";
import { useMe } from "../../lib/session";
import { ProcessTwin } from "./ProcessTwin";

const ICON: Record<string, any> = { batch_summary: ListChecks, rmg: Cog, fbd: Wind, blender: Layers, press: Gauge, ipqc: Ruler, dissolution: Beaker, qc_release: Microscope, api_coa: FileSpreadsheet };
const fmt = (v: number | null | undefined, d = 3) => (v == null || Number.isNaN(v) ? "—" : Math.abs(v) >= 1000 ? Math.round(v).toLocaleString("en-IN") : String(Number(v.toPrecision(d))));
const QC_COLS = ["assay_pct", "av", "dissolution_pct", "disintegration_min", "lod_pct", "tensile_mpa", "friability_pct"];
const TWIN_PARAMS = ["api_potency_pct", "api_d50_um", "weighing_error_pct", "granulation_liquid_pct", "inlet_c", "dew_point_c", "air_m3_h", "drying_min", "blend_min", "pressure_mpa", "weight_rsd_pct"];

// --- formats: what each apparatus file looks like, with a sample to download -----------------------------------
function Formats({ slug, formats, picked, onPick }: { slug: string; formats: any[]; picked: string | null; onPick: (id: string | null) => void }) {
  const [open, setOpen] = useState<string | null>(null);
  const toast = useToast();
  const copy = async (f: any) => {
    try { await navigator.clipboard.writeText(f.columns.map((c: any) => c.id).join(",")); toast("Header row copied: paste it into the first row of your sheet"); }
    catch { toast("Couldn't reach the clipboard", "error"); }
  };
  return (
    <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
      {formats.map((f) => {
        const I = ICON[f.id] ?? FileSpreadsheet;
        const on = picked === f.id;
        return (
          <div key={f.id} className={cn("group rounded-2xl bg-white p-4 shadow-card ring-1 ring-inset transition hover:shadow-hover", on ? "ring-2 ring-gold-400" : "ring-line")}>
            <button className="flex w-full items-start gap-3 text-left" onClick={() => onPick(on ? null : f.id)} title="Use this format for the next upload (otherwise it is detected)">
              <span className={cn("grid h-10 w-10 shrink-0 place-items-center rounded-xl ring-1 ring-inset transition", on ? "bg-gold-500 text-white ring-gold-500" : "bg-gold-50 text-gold-600 ring-gold-100")}><I size={18} /></span>
              <span className="min-w-0">
                <span className="block text-[14px] font-semibold leading-tight">{f.label}</span>
                <span className="mt-0.5 block text-[11px] text-ink-muted">{f.apparatus}</span>
              </span>
            </button>
            <p className="mt-2 text-xs leading-relaxed text-ink-soft">{f.what}</p>
            <div className="mt-3 flex flex-wrap items-center gap-1.5">
              <a href={`/api/plant-data/${slug}/formats/${f.id}/sample.csv`} download className="inline-flex items-center gap-1 rounded-lg bg-ink px-2.5 py-1.5 text-[11px] font-semibold text-white hover:bg-night-700"><Download size={12} /> Sample CSV</a>
              <button onClick={() => copy(f)} className="inline-flex items-center gap-1 rounded-lg px-2.5 py-1.5 text-[11px] font-semibold text-ink-soft ring-1 ring-inset ring-line hover:bg-slate-50"><ClipboardCopy size={12} /> Copy headers</button>
              <button onClick={() => setOpen(open === f.id ? null : f.id)} className="ml-auto text-[11px] font-semibold text-gold-700 hover:underline">{open === f.id ? "Hide columns" : `${f.columns.length} columns`}</button>
            </div>
            {open === f.id && (
              <div className="mt-3 max-h-64 overflow-auto rounded-xl bg-slate-50 p-2">
                <table className="w-full text-[11px]">
                  <tbody>{f.columns.map((c: any) => (
                    <tr key={c.id} className="border-b border-white last:border-0">
                      <td className="py-1 pr-2 font-mono text-[10.5px] text-ink">{c.id}{c.required && <span className="text-rose-500">*</span>}</td>
                      <td className="py-1 pr-2 text-ink-soft">{c.label}{c.unit && <span className="text-ink-faint"> ({c.unit})</span>}</td>
                      <td className="py-1 text-right">{c.twin && <span className="rounded bg-gold-100 px-1.5 py-px text-[9.5px] font-semibold text-gold-700">twin</span>}</td>
                    </tr>))}</tbody>
                </table>
                <div className="mt-1 text-[10px] text-ink-faint">* required · "twin" = feeds the failure tree. Your own header names are matched by meaning, e.g. "Main Compression Force (kN)".</div>
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}

// --- upload: file or pasted table → preview → column mapping → save -------------------------------------------------
function Uploader({ slug, formats, hint, molecules, onSaved }: { slug: string; formats: any[]; hint: string | null; molecules: any[]; onSaved: (molecule: string) => void }) {
  const [file, setFile] = useState<File | null>(null);
  const [text, setText] = useState("");
  const [paste, setPaste] = useState(false);
  const [drag, setDrag] = useState(false);
  const [prev, setPrev] = useState<any>(null);
  const [format, setFormat] = useState<string>("");
  const [mapping, setMapping] = useState<Record<string, string>>({});
  const [name, setName] = useState("");
  const [molecule, setMolecule] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<unknown>(null);
  const input = useRef<HTMLInputElement>(null);
  const toast = useToast();

  const body = (f?: string) => {
    const fd = new FormData();
    if (file) fd.append("file", file); else fd.append("text", text);
    if (f) fd.append("format", f);
    return fd;
  };
  const preview = async (f?: string, fileArg?: File | null) => {
    setBusy(true); setErr(null);
    try {
      const fd = new FormData();
      const src = fileArg !== undefined ? fileArg : file;
      if (src) fd.append("file", src); else fd.append("text", text);
      if (f) fd.append("format", f);
      const r = await api<any>(`/api/plant-data/${slug}/preview`, { method: "POST", body: fd });
      setPrev(r); setFormat(r.format); setMapping(r.mapping);
      if (r.molecule_guess) setMolecule((m) => m || r.molecule_guess);
      setName((n) => n || (r.filename ?? "").replace(/\.[a-z]+$/i, ""));
    } catch (e) { setErr(e); } finally { setBusy(false); }
  };
  const take = (f: File | null) => { setFile(f); setPrev(null); if (f) preview(hint ?? undefined, f); };
  const save = async () => {
    setBusy(true); setErr(null);
    try {
      const fd = body(format);
      fd.set("format", format);
      fd.append("mapping", JSON.stringify(mapping));
      fd.append("name", name);
      fd.append("molecule_key", molecule);
      const r = await api<any>(`/api/plant-data/${slug}/datasets`, { method: "POST", body: fd });
      toast(`${r.name}: ${plural(r.batches, "batch", "batches")} read`);
      setPrev(null); setFile(null); setText(""); setName(""); setPaste(false);
      onSaved(molecule);
    } catch (e) { setErr(e); } finally { setBusy(false); }
  };
  const fm = formats.find((f) => f.id === format);
  const fields: any[] = fm ? [...fm.columns, ...Object.keys(mapping).filter((k) => !fm.columns.some((c: any) => c.id === k)).map((k) => ({ id: k, label: k, extra: true }))] : [];
  const headers: string[] = prev?.headers ?? [];
  const used = new Set(Object.values(mapping));

  return (
    <Card className="overflow-hidden">
      <CardHeader icon={<UploadCloud size={16} />} title="Add your records" subtitle="CSV, TSV or Excel from any apparatus above: the format and the columns are recognised, and you confirm them before anything is saved" />
      <div className="space-y-4 p-5">
        {!prev && (
          <div onDragOver={(e) => { e.preventDefault(); setDrag(true); }} onDragLeave={() => setDrag(false)}
            onDrop={(e) => { e.preventDefault(); setDrag(false); take(e.dataTransfer.files?.[0] ?? null); }}
            className={cn("relative grid place-items-center rounded-2xl border-2 border-dashed px-6 py-10 text-center transition", drag ? "border-gold-400 bg-gold-50" : "border-line bg-slate-50/60")}>
            <motion.div animate={drag ? { scale: 1.08, y: -4 } : { scale: 1, y: 0 }} className="mb-3 grid h-14 w-14 place-items-center rounded-2xl bg-white text-gold-600 shadow-card ring-1 ring-line"><UploadCloud size={24} /></motion.div>
            <div className="text-[15px] font-semibold">Drop a file here, or <button className="text-gold-700 underline-offset-2 hover:underline" onClick={() => input.current?.click()}>browse</button></div>
            <div className="mt-1 text-xs text-ink-muted">.csv · .tsv · .xlsx — up to 8 MB, 50,000 rows{hint && <> · as <b>{formats.find((f) => f.id === hint)?.label}</b></>}</div>
            <button onClick={() => setPaste(!paste)} className="mt-3 text-xs font-semibold text-ink-soft hover:text-ink">{paste ? "Hide" : "Or paste rows from Excel"}</button>
            <input ref={input} type="file" accept=".csv,.tsv,.txt,.xlsx,.xls" className="hidden" onChange={(e) => take(e.target.files?.[0] ?? null)} />
          </div>
        )}
        {paste && !prev && (
          <div className="space-y-2">
            <textarea value={text} onChange={(e) => setText(e.target.value)} rows={6} placeholder={"Copy the cells in Excel (with the header row) and paste here, e.g.\nBatch No.\tAssay %\tDissolution\nB2401\t99.2\t88"}
              className="input h-auto py-2 font-mono text-xs" />
            <Button size="sm" onClick={() => { setFile(null); preview(hint ?? undefined, null); }} disabled={!text.trim()} loading={busy}>Read the table</Button>
          </div>
        )}
        {err != null && <ErrorNote error={err} />}
        {prev && (
          <motion.div initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} className="space-y-4">
            <div className="flex flex-wrap items-end gap-3">
              <div><div className="label mb-1">File</div><div className="text-sm font-semibold">{prev.filename} <span className="font-normal text-ink-muted">· {plural(prev.rows, "row")} · {plural(prev.batches, "batch", "batches")}</span></div></div>
              <div className="w-64"><div className="label mb-1">Read as</div>
                <SearchSelect size="sm" value={format} onChange={(v) => { setFormat(v); preview(v); }} options={formats.map((f) => ({ value: f.id, label: f.label, sub: f.apparatus }))} /></div>
              <div className="w-64"><div className="label mb-1">Molecule (for the failure tree)</div>
                <SearchSelect size="sm" value={molecule} onChange={setMolecule} clearLabel="Not set" placeholder="Choose the molecule" searchPlaceholder="Search a molecule…"
                  options={molecules.map((m) => ({ value: m.key, label: m.name, sub: m.alerts ? `${m.alerts} CDSCO notices` : undefined }))} /></div>
              <div className="w-56"><div className="label mb-1">Name</div><input className="input h-9 text-xs" value={name} onChange={(e) => setName(e.target.value)} /></div>
            </div>

            <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_minmax(0,1.1fr)]">
              <div className="rounded-2xl ring-1 ring-inset ring-line">
                <div className="flex items-center justify-between border-b border-line px-4 py-2.5"><span className="label">Columns</span>
                  <span className="text-[11px] text-ink-muted">{Object.keys(mapping).length} matched{prev.unmapped.length > 0 && ` · ${prev.unmapped.length} not used`}</span></div>
                <div className="max-h-80 divide-y divide-line overflow-auto">
                  {fields.map((c) => (
                    <div key={c.id} className="flex items-center gap-3 px-4 py-2">
                      <div className="min-w-0 flex-1">
                        <div className="flex items-center gap-1.5 text-xs font-medium">{mapping[c.id] ? <CheckCircle2 size={13} className="text-brand-600" /> : <span className="h-[13px] w-[13px] rounded-full ring-1 ring-inset ring-slate-300" />}
                          {c.label}{c.unit && <span className="text-ink-faint">({c.unit})</span>}{c.required && <span className="text-rose-500">*</span>}
                          {c.twin && <span className="rounded bg-gold-100 px-1 text-[9.5px] font-semibold text-gold-700">twin</span>}</div>
                      </div>
                      <div className="w-56 shrink-0">
                        <SearchSelect size="sm" value={mapping[c.id] ?? ""} clearLabel="Not in this file" placeholder="Not in this file"
                          onChange={(v) => setMapping((m) => { const n = { ...m }; if (v) n[c.id] = v; else delete n[c.id]; return n; })}
                          options={headers.map((h) => ({ value: h, label: h, disabled: used.has(h) && mapping[c.id] !== h }))} />
                      </div>
                    </div>
                  ))}
                </div>
                {prev.unmapped.length > 0 && <div className="border-t border-line px-4 py-2 text-[11px] text-ink-muted">Not used: {prev.unmapped.join(", ")}</div>}
              </div>
              <div className="min-w-0 rounded-2xl ring-1 ring-inset ring-line">
                <div className="border-b border-line px-4 py-2.5"><span className="label">First rows</span></div>
                <div className="max-h-80 overflow-auto">
                  <table className="w-full text-[11px]">
                    <thead className="sticky top-0 bg-slate-50"><tr>{headers.map((h) => <th key={h} className={cn("whitespace-nowrap px-2.5 py-1.5 text-left font-semibold", used.has(h) ? "text-ink" : "text-ink-faint")}>{h}</th>)}</tr></thead>
                    <tbody>{prev.preview.map((r: any, i: number) => <tr key={i} className="border-t border-line">{headers.map((h) => <td key={h} className={cn("whitespace-nowrap px-2.5 py-1 tabular-nums", !used.has(h) && "text-ink-faint")}>{String(r[h] ?? "")}</td>)}</tr>)}</tbody>
                  </table>
                </div>
              </div>
            </div>
            <div className="flex flex-wrap items-center gap-2">
              <Button onClick={save} loading={busy} disabled={!mapping.batch_no}><Activity size={15} /> Save and analyse</Button>
              <Button variant="ghost" onClick={() => { setPrev(null); setFile(null); }}>Cancel</Button>
              {!mapping.batch_no && <span className="text-xs text-rose-600">Map a column to "Batch number": files are joined on it.</span>}
            </div>
          </motion.div>
        )}
      </div>
    </Card>
  );
}

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

function Live({ slug, molecule, onReplay }: { slug: string; molecule: string; onReplay: (b: string, params: Record<string, number>) => void }) {
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["plant-live", slug, molecule], queryFn: () => api<any>(`/api/plant-data/${slug}/live${molecule ? `?molecule=${molecule}` : ""}`),
    refetchInterval: 5000, placeholderData: keepPreviousData, enabled: !!slug });
  const d = q.data;
  if (q.error) return <ErrorNote error={q.error} />;
  if (!d) return <Skeleton className="h-64" />;
  return (
    <div className="space-y-5">
      <Connectors slug={slug} conns={d.connectors} onChange={() => qc.invalidateQueries({ queryKey: ["plant-live", slug] })} />
      {d.machines.length > 0 && (
        <>
          <div className="flex items-baseline justify-between"><h3 className="text-[17px] font-semibold tracking-tight">Machines now</h3>
            <span className="flex items-center gap-1.5 text-[11px] text-ink-muted"><span className="h-1.5 w-1.5 animate-pulse rounded-full bg-emerald-500" />refreshing every 5 s</span></div>
          <div className="grid gap-4 lg:grid-cols-2">
            {d.machines.map((m: any) => (
              <Card key={m.dataset_id} className="p-4">
                <div className="flex items-start justify-between gap-2">
                  <div><div className="text-[15px] font-semibold">{m.machine}</div><div className="text-[11px] text-ink-muted">{m.format_label} · {m.ts ? new Date(m.ts).toLocaleTimeString("en-IN") : ""}</div></div>
                  <div className="text-right"><div className="label">Batch</div><div className="font-mono text-[15px] font-semibold text-gold-700">{m.batch_no}</div></div>
                </div>
                <div className="mt-3 grid grid-cols-2 gap-x-4 gap-y-2">
                  {m.fields.map((f: any) => (
                    <div key={f.id} className="flex items-center justify-between gap-2 border-b border-line pb-1.5">
                      <div className="min-w-0"><div className="truncate text-[11px] text-ink-muted">{f.label}{f.twin && <span className="ml-1 rounded bg-gold-100 px-1 text-[9px] font-semibold text-gold-700">twin</span>}</div>
                        <div className="text-[15px] font-semibold tabular-nums">{fmt(m.latest[f.id], 4)} <span className="text-[10px] font-normal text-ink-faint">{f.unit}</span></div></div>
                      <Spark data={m.series[f.id] ?? []} />
                    </div>))}
                </div>
              </Card>))}
          </div>
        </>
      )}
      {d.forecasts?.length > 0 && (
        <>
          <h3 className="text-[17px] font-semibold tracking-tight">Forecast for the batches running now</h3>
          <div className="grid gap-4 lg:grid-cols-2">
            {d.forecasts.map((f: any) => (
              <motion.div key={f.batch_no} layout className="rounded-2xl bg-white p-4 shadow-card ring-1 ring-inset ring-line">
                <div className="flex flex-wrap items-start justify-between gap-2">
                  <div><div className="font-mono text-[17px] font-semibold">{f.batch_no}</div>
                    <div className="text-[11px] text-ink-muted">on {f.machines.join(", ")}{f.drying_in_progress && " · still drying: results if it stopped now"}</div></div>
                  <Button size="sm" variant="secondary" onClick={() => onReplay(f.batch_no, f.live_params)}><PlayCircle size={14} /> Replay in the failure tree</Button>
                </div>
                <div className="mt-3 grid grid-cols-2 gap-2 sm:grid-cols-3">
                  {f.predicted.map((p: any) => (
                    <div key={p.test} className={cn("rounded-xl p-2.5 ring-1 ring-inset transition-colors", p.fails ? "bg-rose-50 ring-rose-200" : "bg-emerald-50/50 ring-emerald-200")}
                      title={p.corrected ? `Model ${fmt(p.model_value, 3)}, corrected by its bias against your ${p.corrected.n} measured batches (${p.corrected.bias > 0 ? "+" : ""}${fmt(p.corrected.bias, 2)})` : "Model value: no measured results of this test uploaded to correct it"}>
                      <div className="truncate text-[10.5px] text-ink-muted">{p.label}</div>
                      <div className={cn("text-[17px] font-semibold tabular-nums", p.fails && "text-rose-700")}>{fmt(p.value, 3)}</div>
                      <div className="text-[9.5px] text-ink-faint">{p.lo != null && p.hi != null ? `${p.lo}–${p.hi}` : p.lo != null ? `≥ ${p.lo}` : `≤ ${p.hi}`}{p.corrected ? " · corrected" : " · model"}</div>
                    </div>))}
                </div>
                <div className="mt-2 text-[10.5px] text-ink-faint">Live settings so far: {Object.keys(f.live_params).length ? Object.entries(f.live_params).map(([k, v]: any) => `${k.replace(/_/g, " ")} ${fmt(v, 3)}`).join(" · ") : "none yet"}; the rest at your medians.</div>
              </motion.div>))}
          </div>
        </>
      )}
      {d.machines.length === 0 && d.connectors.length > 0 && <Empty icon={<Radio size={20} />} title="Waiting for the first readings">Start the agent with the token; machines appear here within a push (15 s by default).</Empty>}
      {d.machines.length > 0 && !molecule && <div className="text-xs text-ink-muted">Choose the molecule above to forecast the running batches.</div>}
    </div>
  );
}

// --- the page ------------------------------------------------------------------------------------------------------------
export function PlantData() {
  const params = useParams();
  const [sp, setSp] = useSearchParams();
  const { data: me } = useMe();
  const qc = useQueryClient();
  const toast = useToast();
  const orgs = useQuery({ queryKey: ["orgs-list"], queryFn: () => api<any>("/api/orgs"), enabled: !!me?.is_platform && !params.slug, staleTime: 300_000 });
  const slug = params.slug ?? me?.org?.slug ?? sp.get("org") ?? orgs.data?.orgs?.[0]?.slug ?? "";
  const src = (sp.get("src") === "scada" ? "scada" : "csv") as "csv" | "scada";
  const molecule = sp.get("m") ?? "";
  const setParam = (k: string, v: string) => { const n = new URLSearchParams(sp); if (v) n.set(k, v); else n.delete(k); setSp(n, { replace: true }); };
  const formats = useQuery({ queryKey: ["pd-formats", slug], queryFn: () => api<any>(`/api/plant-data/${slug}/formats`), enabled: !!slug, staleTime: 3600_000 });
  const mols = useQuery({ queryKey: ["pd-mols", slug], queryFn: () => api<any>(`/api/plant-data/${slug}/molecules`), enabled: !!slug, staleTime: 3600_000 });
  const sets = useQuery({ queryKey: ["pd-sets", slug], queryFn: () => api<any>(`/api/plant-data/${slug}/datasets`), enabled: !!slug, refetchInterval: src === "scada" ? 15000 : false });
  const [hint, setHint] = useState<string | null>(null);
  const [group, setGroup] = useState<"cqa" | "param" | "raw">("cqa");
  const [replay, setReplay] = useState<{ id: string; label: string; set: Record<string, number> } | null>(null);
  const twinRef = useRef<HTMLDivElement>(null);
  const datasets: any[] = sets.data?.datasets ?? [];
  useEffect(() => { if (!molecule) { const m = datasets.find((d) => d.molecule_key)?.molecule_key; if (m) setParam("m", m); } }, [datasets, molecule]); // eslint-disable-line react-hooks/exhaustive-deps
  const ana = useQuery({ queryKey: ["pd-analysis", slug, molecule, datasets.map((d) => `${d.id}:${d.rows}`).join(",")], enabled: !!slug && datasets.length > 0,
    queryFn: () => post<any>(`/api/plant-data/${slug}/analysis`, { molecule_key: molecule || undefined }), placeholderData: keepPreviousData });
  const a = ana.data;
  const charts = useMemo(() => (a?.charts ?? []).filter((c: any) => c.kind === group), [a, group]);
  const worst = useMemo(() => (a?.charts ?? []).filter((c: any) => c.cpk != null).sort((x: any, y: any) => x.cpk - y.cpk)[0], [a]);
  const refresh = (m?: string) => { if (m) setParam("m", m); qc.invalidateQueries({ queryKey: ["pd-sets", slug] }); qc.invalidateQueries({ queryKey: ["pd-analysis", slug] }); };
  const remove = async (d: any) => {
    if (!confirm(`Delete "${d.name}" (${d.batches} batches)? This can't be undone.`)) return;
    try { await del(`/api/plant-data/${slug}/datasets/${d.id}`); toast("Deleted"); refresh(); } catch (e) { toast((e as Error).message, "error"); }
  };
  const replayParams = (label: string, params: Record<string, number>) => {
    setReplay({ id: `${label}:${Date.now()}`, label, set: params });
    setTimeout(() => twinRef.current?.scrollIntoView({ behavior: "smooth", block: "start" }), 60);
  };
  const replayBatch = (b: string) => {
    const row = a?.batches.find((x: any) => x.batch_no === b);
    replayParams(`batch ${b}`, Object.fromEntries(Object.entries(row?.values ?? {}).filter(([k]) => TWIN_PARAMS.includes(k))) as Record<string, number>);
  };

  if (!slug) return me?.is_platform && orgs.isLoading ? <PageSkeleton /> : <Empty icon={<FileSpreadsheet size={20} />} title="No organisation">Plant data belongs to an organisation: create one in Admin → Organisations.</Empty>;
  if (formats.isLoading || sets.isLoading) return <PageSkeleton />;
  if (formats.error) return <ErrorNote error={formats.error} />;
  const twin = (
    <div ref={twinRef} className="scroll-mt-24">
      {molecule ? <ProcessTwin mkey={molecule} endpoint={`/api/plant-data/${slug}/twin`} inject={replay} />
        : <Empty icon={<Beaker size={20} />} title="Choose the molecule to open the failure tree">The tree needs the molecule's dose and solubility; your data supplies the process settings and their spread.</Empty>}
    </div>
  );
  const analysis = a && !a.empty && (
    <>
      <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        <Stat label="Batches" value={a.counts.batches} icon={<Layers size={18} />} hint={`${plural(a.counts.fields, "field")} across ${plural(datasets.length, "file")}`} />
        <Stat label="Outside a limit" value={a.counts.out_of_spec_batches} icon={<AlertTriangle size={18} />} tone={a.counts.out_of_spec_batches ? "rose" : "brand"} delay={0.05} hint="batches with a result beyond its limit" />
        <Stat label="Control-chart signals" value={a.counts.signals} icon={<Activity size={18} />} tone="amber" delay={0.1} hint="Nelson rules 1–3: drift before a failure" />
        <Stat label="Lowest Cpk" value={worst ? worst.cpk : "—"} decimals={2} icon={<Gauge size={18} />} tone="indigo" delay={0.15} hint={worst ? `${worst.label}${worst.cpk_indicative ? " · fewer than 25 batches: indicative" : ""}` : "needs ≥ 5 batches with a limit"} />
      </div>
      <Card className="mt-5 overflow-hidden">
        <CardHeader icon={<ListChecks size={16} />} title="Batches" subtitle="Quality results against their limits; click a batch outside a limit to see why" />
        <div className="mt-3 overflow-x-auto">
          <table className="w-full text-xs">
            <thead className="bg-slate-50 text-[10.5px] uppercase tracking-wide text-ink-muted"><tr>
              <th className="px-4 py-2 text-left">Batch</th><th className="px-3 py-2 text-left">Made</th>
              {QC_COLS.filter((k) => a.batches.some((b: any) => k in b.values)).map((k) => <th key={k} className="px-3 py-2 text-right">{a.charts.find((c: any) => c.field === k)?.label ?? k}</th>)}
            </tr></thead>
            <tbody>{a.batches.map((b: any) => (
              <tr key={b.batch_no} className={cn("border-t border-line", b.out_of_spec.length && "cursor-pointer bg-rose-50/40 hover:bg-rose-50")}
                onClick={() => b.out_of_spec.length && document.getElementById(`diag-${b.batch_no}`)?.scrollIntoView({ behavior: "smooth", block: "center" })}>
                <td className="px-4 py-2 font-semibold">{b.batch_no}</td><td className="px-3 py-2 text-ink-muted">{b.mfg_date ?? ""}</td>
                {QC_COLS.filter((k) => a.batches.some((x: any) => k in x.values)).map((k) => (
                  <td key={k} className={cn("px-3 py-2 text-right tabular-nums", b.out_of_spec.includes(k) ? "font-semibold text-rose-600" : "")}>{fmt(b.values[k], 4)}</td>))}
              </tr>))}</tbody>
          </table>
        </div>
      </Card>
      {a.diagnoses.length > 0 && (
        <div className="mt-5">
          <h3 className="mb-3 text-[17px] font-semibold tracking-tight">Why these batches fell outside a limit</h3>
          <div className="grid gap-4 xl:grid-cols-2">{a.diagnoses.map((d: any) => <div key={d.batch} id={`diag-${d.batch}`}><Diagnosis d={d} hasTwin={!!a.molecule} onReplay={() => replayBatch(d.batch)} /></div>)}</div>
        </div>
      )}
      <div className="mt-6 flex flex-wrap items-center justify-between gap-3">
        <h3 className="text-[17px] font-semibold tracking-tight">Control charts</h3>
        <Segmented value={group} onChange={setGroup} options={[{ value: "cqa", label: "Quality results" }, { value: "param", label: "Process settings" }, { value: "raw", label: "Other readings" }]} />
      </div>
      <div className="mt-3 grid gap-4 md:grid-cols-2 xl:grid-cols-3">
        {charts.map((c: any) => <ControlChart key={c.field} c={c} onBatch={(b) => a.batches.find((x: any) => x.batch_no === b)?.out_of_spec.length && document.getElementById(`diag-${b}`)?.scrollIntoView({ behavior: "smooth", block: "center" })} />)}
        {charts.length === 0 && <div className="text-xs text-ink-muted">None of your data has fields of this kind yet.</div>}
      </div>
      <div className="mt-2 text-[10.5px] text-ink-faint">Individuals charts: control limits = mean ± 3·MR̄/1.128; signals = Nelson rules 1–3. Cpk uses the batch-to-batch σ; * fewer than 25 batches, indicative only. Limits marked "default" are generic: set your own monograph limits.</div>
      {a.molecule && Object.keys(a.model_check ?? {}).length > 0 && (
        <Card className="mt-5 p-5">
          <div className="label mb-2">How well the generic model matches your batches</div>
          <div className="grid gap-2 sm:grid-cols-3 lg:grid-cols-6">
            {Object.entries(a.model_check).map(([k, v]: any) => (
              <div key={k} className="rounded-xl bg-slate-50 p-3 ring-1 ring-inset ring-line">
                <div className="text-[11px] text-ink-muted">{a.charts.find((c: any) => c.field === k)?.label ?? k}</div>
                <div className="text-lg font-semibold tabular-nums">±{fmt(v.mean_abs_error, 2)}</div>
                <div className="text-[10.5px] text-ink-faint">bias {v.bias > 0 ? "+" : ""}{fmt(v.bias, 2)} over {v.n}</div>
              </div>))}
          </div>
          <p className="mt-2 text-[11px] text-ink-muted">The model's prediction from each batch's recorded settings, against the measured result. A large bias means the twin's generic constants don't describe your product yet: the live forecast removes this bias; read the failure tree as a ranking of where to look, not as a forecast.</p>
        </Card>
      )}
    </>
  );

  return (
    <div className="space-y-5">
      <div className="sticky top-16 z-10 -mx-1 flex flex-wrap items-center gap-3 rounded-2xl bg-white/90 px-4 py-3 shadow-card ring-1 ring-inset ring-line backdrop-blur-md">
        <Segmented value={src} onChange={(v) => setParam("src", v === "csv" ? "" : v)} options={[{ value: "csv", label: <span className="flex items-center gap-1.5"><UploadCloud size={13} /> Files (CSV, Excel)</span> }, { value: "scada", label: <span className="flex items-center gap-1.5"><Radio size={13} /> Live (SCADA)</span> }]} />
        {me?.is_platform && !params.slug && (
          <div className="w-56"><SearchSelect size="sm" value={slug} onChange={(v) => setParam("org", v)} searchPlaceholder="Search an organisation…"
            options={(orgs.data?.orgs ?? []).map((o: any) => ({ value: o.slug, label: o.name, sub: o.city }))} /></div>)}
        <div className="w-64"><SearchSelect size="sm" value={molecule} onChange={(v) => setParam("m", v)} clearLabel="No molecule" placeholder="Molecule for the failure tree" searchPlaceholder="Search a molecule…"
          options={(mols.data?.molecules ?? []).map((m: any) => ({ value: m.key, label: m.name, sub: m.alerts ? `${m.alerts} CDSCO notices` : undefined }))} /></div>
        <span className="ml-auto text-[11px] text-ink-muted">{plural(datasets.length, "file")} · {plural(datasets.filter((d) => d.live).length, "live stream")} · private to the organisation</span>
      </div>

      {src === "csv" ? (
        <>
          <div className="flex items-baseline justify-between gap-2"><h2 className="text-[17px] font-semibold tracking-tight">Formats we read</h2>
            <span className="text-[11px] text-ink-muted">{formats.data.note}</span></div>
          <Formats slug={slug} formats={formats.data.formats} picked={hint} onPick={setHint} />
          <Uploader slug={slug} formats={formats.data.formats} hint={hint} molecules={mols.data?.molecules ?? []} onSaved={refresh} />
          {datasets.length > 0 && (
            <Card>
              <CardHeader icon={<FileSpreadsheet size={16} />} title="Your data" subtitle="Joined on batch number; where two sources hold the same value, the newer one's wins" />
              <div className="divide-y divide-line px-5 pb-3 pt-2">
                {datasets.map((d) => (
                  <div key={d.id} className="flex flex-wrap items-center gap-3 py-2.5 text-xs">
                    <span className="grid h-8 w-8 place-items-center rounded-lg bg-slate-50 text-ink-muted ring-1 ring-inset ring-line">{(() => { const I = d.live ? Radio : ICON[d.format] ?? FileSpreadsheet; return <I size={15} />; })()}</span>
                    <div className="min-w-0 flex-1"><div className="truncate text-[13px] font-semibold">{d.name} {d.live && <Badge tone="brand">live</Badge>}</div>
                      <div className="text-ink-muted">{d.format_label} · {plural(d.rows, "row")} · {plural(d.batches, "batch", "batches")} · {plural(d.fields.length, "field")} · {d.uploaded_by} · {new Date(d.created_at).toLocaleDateString("en-IN")}</div></div>
                    <button onClick={() => remove(d)} className="rounded-lg p-2 text-ink-faint hover:bg-rose-50 hover:text-rose-600" title="Delete"><Trash2 size={15} /></button>
                  </div>))}
              </div>
            </Card>
          )}
          {datasets.length === 0 && <Empty icon={<Flame size={20} />} title="No records yet">Download a sample above to see the layout, or drop your own export. Nothing leaves your organisation.</Empty>}
          {ana.error && <ErrorNote error={ana.error} />}
          {analysis}
          {twin}
        </>
      ) : (
        <>
          <Live slug={slug} molecule={molecule} onReplay={(b, p) => replayParams(`live batch ${b}`, p)} />
          {twin}
          {analysis && <><h2 className="pt-2 text-[22px] font-semibold tracking-tight">All batches, files and streams together</h2>{analysis}</>}
        </>
      )}
    </div>
  );
}
