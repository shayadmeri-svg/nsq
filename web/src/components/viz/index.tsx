// Visual building blocks for the Playground: choropleths (India states, world),
// heatmap grid, Sankey, multi-select filter chips.
import { geoMercator, geoNaturalEarth1, geoPath } from "d3-geo";
import type { FeatureCollection, Geometry } from "geojson";
import { AnimatePresence, motion } from "motion/react";
import { Check, ChevronDown, X } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { ResponsiveContainer, Sankey, Tooltip } from "recharts";
import { feature } from "topojson-client";
import worldTopo from "world-atlas/countries-110m.json";
import { cn } from "../../lib/cn";

// --- colour scale ---------------------------------------------------------------
const STOPS = ["#ecfdf8", "#a7f3d9", "#2dd4ae", "#10b996", "#0b7a65", "#073b33"];
export function shade(v: number, max: number, stops = STOPS) {
  if (!v || !max) return "#f1f5f9";
  const t = Math.min(1, Math.log1p(v) / Math.log1p(max));
  const i = Math.min(stops.length - 2, Math.floor(t * (stops.length - 1)));
  return stops[i + 1];
}
const HEAT = ["#fff7ed", "#fed7aa", "#fdba74", "#fb923c", "#ea580c", "#9a3412"];

export function Legend({ max, label, stops = STOPS }: { max: number; label: string; stops?: string[] }) {
  return (
    <div className="flex items-center gap-2 text-[11px] text-ink-muted">
      <span>{label}</span>
      <span className="flex h-2.5 w-32 overflow-hidden rounded-full">{stops.slice(1).map((c) => <span key={c} className="flex-1" style={{ background: c }} />)}</span>
      <span>0 – {max.toLocaleString("en-IN")}</span>
    </div>
  );
}

// --- India map ---------------------------------------------------------------------
// CDSCO spells some states differently from the LGD boundary file.
const STATE_ALIASES: Record<string, string> = {
  "Orissa": "Odisha", "Pondicherry": "Puducherry", "Uttaranchal": "Uttarakhand", "NCT of Delhi": "Delhi",
  "Dadra and Nagar Haveli and Daman and Diu": "Dadra and Nagar Haveli and Daman and Diu",
};
const normState = (s: string) => (STATE_ALIASES[s] ?? s).toLowerCase().replace(/&/g, "and").replace(/[^a-z]/g, "");

export function IndiaMap({ geo, values, selected, onPick, height = 460, metricLabel = "alerts" }: {
  geo: FeatureCollection<Geometry, { name: string }>; values: { name: string; count: number; [k: string]: any }[];
  selected?: string[]; onPick?: (state: string) => void; height?: number; metricLabel?: string;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const [w, setW] = useState(520);
  const [hover, setHover] = useState<{ name: string; x: number; y: number; row?: any } | null>(null);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const ro = new ResizeObserver(() => setW(el.clientWidth));
    ro.observe(el);
    return () => ro.disconnect();
  }, []);
  const byName = useMemo(() => Object.fromEntries(values.map((v) => [normState(v.name), v])), [values]);
  const max = Math.max(1, ...values.filter((v) => v.name !== "Unknown").map((v) => v.count));
  const path = useMemo(() => geoPath(geoMercator().fitSize([w, height], geo as any)), [w, height, geo]);
  const unmapped = values.filter((v) => v.name !== "Unknown" && !geo.features.some((f) => normState(f.properties.name) === normState(v.name)));
  return (
    <div ref={ref} className="relative">
      <svg width={w} height={height} className="block">
        {geo.features.map((f, i) => {
          const row = byName[normState(f.properties.name)];
          const sel = selected?.some((s) => normState(s) === normState(f.properties.name));
          return (
            <motion.path key={f.properties.name + i} d={path(f as any) ?? ""} initial={{ opacity: 0 }} animate={{ opacity: 1 }} transition={{ delay: i * 0.01 }}
              fill={shade(row?.count ?? 0, max)} stroke={sel ? "#0f172a" : "#fff"} strokeWidth={sel ? 1.6 : 0.6}
              className={cn("transition-[fill]", onPick && row && "cursor-pointer hover:brightness-95")}
              onMouseMove={(e) => { const r = ref.current!.getBoundingClientRect(); setHover({ name: f.properties.name, x: e.clientX - r.left, y: e.clientY - r.top, row }); }}
              onMouseLeave={() => setHover(null)} onClick={() => row && onPick?.(row.name)} />
          );
        })}
      </svg>
      {hover && (
        <div className="pointer-events-none absolute z-10 rounded-lg bg-night-900 px-2.5 py-1.5 text-[11px] text-white shadow-lift" style={{ left: hover.x + 12, top: hover.y + 8 }}>
          <div className="font-semibold">{hover.name}</div>
          {hover.row ? <div>{hover.row.count.toLocaleString("en-IN")} {metricLabel}{hover.row.manufacturers != null && ` · ${hover.row.manufacturers} makers`}{hover.row.dissolution_pct != null && ` · ${hover.row.dissolution_pct}% dissolution`}</div> : <div className="text-slate-400">no alerts</div>}
        </div>
      )}
      <div className="mt-2 flex flex-wrap items-center justify-between gap-2"><Legend max={max} label={metricLabel} />
        {unmapped.length > 0 && <span className="text-[10.5px] text-ink-faint">Not on map: {unmapped.map((u) => `${u.name} (${u.count})`).join(", ")}</span>}</div>
    </div>
  );
}

// --- World map ------------------------------------------------------------------------
// world-atlas ids are ISO 3166 numeric; map the ones the reference covers.
export const ISO_NUM: Record<string, string> = {
  "840": "US", "124": "CA", "826": "GB", "392": "JP", "036": "AU", "356": "IN", "076": "BR", "484": "MX", "710": "ZA", "566": "NG",
  "404": "KE", "288": "GH", "818": "EG", "682": "SA", "156": "CN", "040": "AT", "056": "BE", "100": "BG", "191": "HR", "196": "CY",
  "203": "CZ", "208": "DK", "233": "EE", "246": "FI", "250": "FR", "276": "DE", "300": "GR", "348": "HU", "372": "IE", "380": "IT",
  "428": "LV", "440": "LT", "442": "LU", "470": "MT", "528": "NL", "616": "PL", "620": "PT", "642": "RO", "703": "SK", "705": "SI",
  "724": "ES", "752": "SE", "352": "IS", "438": "LI", "578": "NO",
};
const WORLD = feature(worldTopo as any, (worldTopo as any).objects.countries) as unknown as FeatureCollection<Geometry, { name: string }>;

export function WorldMap({ colorFor, isSelected, onPick, tooltip, height = 420 }: {
  colorFor: (code: string | null) => string; isSelected?: (code: string) => boolean; onPick?: (code: string) => void;
  tooltip?: (code: string, name: string) => React.ReactNode; height?: number;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const [w, setW] = useState(800);
  const [hover, setHover] = useState<{ code: string | null; name: string; x: number; y: number } | null>(null);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const ro = new ResizeObserver(() => setW(el.clientWidth));
    ro.observe(el);
    return () => ro.disconnect();
  }, []);
  const feats = useMemo(() => ({ ...WORLD, features: WORLD.features.filter((f) => f.properties.name !== "Antarctica") }), []);
  const path = useMemo(() => geoPath(geoNaturalEarth1().fitSize([w, height], feats as any)), [w, height, feats]);
  return (
    <div ref={ref} className="relative">
      <svg width={w} height={height} className="block">
        {feats.features.map((f: any, i) => {
          const code = ISO_NUM[String(f.id).padStart(3, "0")] ?? null;
          const sel = !!code && !!isSelected?.(code);
          return (
            <path key={i} d={path(f) ?? ""} fill={colorFor(code)} stroke={sel ? "#0f172a" : "#fff"} strokeWidth={sel ? 1.2 : 0.4}
              className={cn(code && onPick && "cursor-pointer hover:brightness-95")}
              onMouseMove={(e) => { const r = ref.current!.getBoundingClientRect(); setHover({ code, name: f.properties.name, x: e.clientX - r.left, y: e.clientY - r.top }); }}
              onMouseLeave={() => setHover(null)} onClick={() => code && onPick?.(code)} />
          );
        })}
      </svg>
      {hover && (
        <div className="pointer-events-none absolute z-10 max-w-[260px] rounded-lg bg-night-900 px-2.5 py-1.5 text-[11px] text-white shadow-lift" style={{ left: Math.min(hover.x + 12, w - 200), top: hover.y + 8 }}>
          <div className="font-semibold">{hover.name}</div>
          {hover.code ? tooltip?.(hover.code, hover.name) : <div className="text-slate-400">not in the reference</div>}
        </div>
      )}
    </div>
  );
}

// --- Heatmap ------------------------------------------------------------------------------
export function Heatmap({ m, rowLabel, onRow, onCol }: { m: { rows: string[]; cols: string[]; values: number[][] }; rowLabel?: string; onRow?: (r: string) => void; onCol?: (c: string) => void }) {
  const max = Math.max(1, ...m.values.flat());
  if (!m.rows.length) return <div className="p-6 text-center text-sm text-ink-muted">No data for this filter.</div>;
  return (
    <div className="overflow-x-auto">
      <table className="border-separate border-spacing-[3px] text-[11px]">
        <thead>
          <tr>
            <th className="sticky left-0 bg-white px-2 text-left font-semibold text-ink-muted">{rowLabel}</th>
            {m.cols.map((c) => <th key={c} onClick={() => onCol?.(c)} className={cn("h-28 w-9 min-w-[36px] align-bottom", onCol && "cursor-pointer")}><div className="w-9 origin-bottom-left translate-x-4 -rotate-45 whitespace-nowrap text-left font-medium text-ink-soft">{c.length > 22 ? c.slice(0, 21) + "…" : c}</div></th>)}
          </tr>
        </thead>
        <tbody>
          {m.rows.map((r, i) => (
            <tr key={r}>
              <td onClick={() => onRow?.(r)} className={cn("sticky left-0 max-w-[220px] truncate bg-white pr-2 font-medium text-ink-soft", onRow && "cursor-pointer hover:text-brand-700")} title={r}>{r}</td>
              {m.values[i].map((v, j) => (
                <td key={j} title={`${r} × ${m.cols[j]}: ${v}`} className="h-7 w-9 rounded-md text-center font-semibold tabular-nums transition hover:ring-2 hover:ring-ink/20"
                  style={{ background: shade(v, max, HEAT), color: v / max > 0.45 ? "#fff" : "#7c2d12" }}>{v || ""}</td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

// --- Sankey ---------------------------------------------------------------------------------
const SANKEY_COLORS = ["#10b996", "#6366f1", "#f59e0b", "#e11d48", "#0ea5e9", "#8b5cf6", "#14b8a6", "#f97316", "#64748b", "#84cc16"];
function SankeyNode({ x, y, width, height, index, payload }: any) {
  const c = SANKEY_COLORS[index % SANKEY_COLORS.length];
  const right = payload.level === 2;
  return (
    <g>
      <rect x={x} y={y} width={width} height={height} fill={c} rx={2} />
      {height > 7 && <text x={right ? x - 6 : x + width + 6} y={y + height / 2} dy="0.35em" textAnchor={right ? "end" : "start"} fontSize={11} fill="#334155">{String(payload.name).slice(0, 26)} · {payload.value}</text>}
    </g>
  );
}
export function SankeyChart({ data, height = 440 }: { data: { nodes: any[]; links: any[] }; height?: number }) {
  if (!data.links.length) return <div className="p-6 text-center text-sm text-ink-muted">No flows for this filter.</div>;
  return (
    <ResponsiveContainer width="100%" height={height}>
      <Sankey data={data} node={<SankeyNode />} nodePadding={14} nodeWidth={10} margin={{ left: 10, right: 10, top: 10, bottom: 10 }} link={{ stroke: "#94a3b8", strokeOpacity: 0.25 }}>
        <Tooltip contentStyle={{ borderRadius: 10, fontSize: 12 }} />
      </Sankey>
    </ResponsiveContainer>
  );
}

// --- Multi-select ------------------------------------------------------------------------------
export function MultiSelect({ label, options, value, onChange }: { label: string; options: { name: string; count?: number }[]; value: string[]; onChange: (v: string[]) => void }) {
  const [open, setOpen] = useState(false);
  const [q, setQ] = useState("");
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    const h = (e: MouseEvent) => { if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false); };
    document.addEventListener("mousedown", h);
    return () => document.removeEventListener("mousedown", h);
  }, [open]);
  const shown = options.filter((o) => o.name.toLowerCase().includes(q.toLowerCase())).slice(0, 80);
  const toggle = (n: string) => onChange(value.includes(n) ? value.filter((x) => x !== n) : [...value, n]);
  return (
    <div ref={ref} className="relative">
      <button type="button" onClick={() => setOpen(!open)} className={cn("flex h-9 items-center gap-1.5 rounded-xl border px-3 text-[13px] transition", value.length ? "border-brand-500 bg-brand-50 text-brand-900" : "border-line bg-white text-ink-soft hover:border-slate-300")}>
        {label}{value.length > 0 && <span className="rounded-full bg-brand-600 px-1.5 text-[10px] font-bold text-white">{value.length}</span>}<ChevronDown size={14} />
      </button>
      <AnimatePresence>
        {open && (
          <motion.div key="menu" initial={{ opacity: 0, y: -4 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -4 }} transition={{ duration: 0.12 }}
            className="absolute left-0 top-10 z-40 w-72 rounded-xl bg-white p-2 shadow-lift ring-1 ring-line">
            <input autoFocus value={q} onChange={(e) => setQ(e.target.value)} placeholder={`Search ${label.toLowerCase()}…`} className="input mb-1.5 h-8 w-full text-xs" />
            <div className="max-h-64 overflow-auto scrollbar-thin">
              {shown.map((o) => (
                <button type="button" key={o.name} onClick={() => toggle(o.name)} className="flex w-full items-center justify-between rounded-lg px-2 py-1.5 text-left text-xs hover:bg-slate-50">
                  <span className="flex items-center gap-2"><span className={cn("grid h-4 w-4 place-items-center rounded border", value.includes(o.name) ? "border-brand-600 bg-brand-600 text-white" : "border-slate-300")}>{value.includes(o.name) && <Check size={11} />}</span>{o.name}</span>
                  {o.count != null && <span className="text-ink-faint">{o.count}</span>}
                </button>
              ))}
            </div>
            {value.length > 0 && <button type="button" onClick={() => onChange([])} className="mt-1 flex w-full items-center justify-center gap-1 rounded-lg py-1 text-[11px] text-ink-muted hover:bg-slate-50"><X size={11} /> Clear</button>}
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}
