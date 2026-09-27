import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { ChevronLeft, ChevronRight, Columns3, Download, Factory, FlaskConical, Grid3x3, Package, Pill, Search, ShieldAlert, SlidersHorizontal, Stethoscope, Waypoints, X } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { Legendary, RankBars, TrendArea } from "../../components/charts";
import { Badge, Button, Card, CardHeader, ErrorNote, Segmented, Skeleton, Stat } from "../../components/ui";
import { Heatmap, IndiaMap, MultiSelect, SankeyChart } from "../../components/viz";
import { api } from "../../lib/api";
import { cn } from "../../lib/cn";
import { fmtMonth } from "../../lib/format";
import { ExpandedProvider, Tile, type Section } from "../../components/ui/Expanded";

export type Filters = { focus: string; drug_type: string[]; form: string[]; category: string[]; state: string[]; source: string[]; since: string; until: string; q: string; authenticity: string };
export const EMPTY: Filters = { focus: "all", drug_type: [], form: [], category: [], state: [], source: [], since: "", until: "", q: "", authenticity: "" };

export function qs(f: Filters, extra: Record<string, string | string[] | number | boolean> = {}) {
  const p = new URLSearchParams();
  p.set("focus", f.focus);
  for (const k of ["drug_type", "form", "category", "state", "source"] as const) f[k].forEach((v) => p.append(k, v));
  if (f.since) p.set("since", f.since);
  if (f.until) p.set("until", f.until);
  if (f.q) p.set("q", f.q);
  if (f.authenticity) p.set("authenticity", f.authenticity);
  for (const [k, v] of Object.entries(extra)) (Array.isArray(v) ? v : [v]).forEach((x) => p.append(k, String(x)));
  return p.toString();
}

export function FilterBar({ f, set }: { f: Filters; set: (f: Filters) => void }) {
  const { data } = useQuery({ queryKey: ["pg-facets"], queryFn: () => api<any>("/api/playground/facets"), staleTime: 300_000 });
  const [q, setQ] = useState(f.q);
  useEffect(() => { const t = setTimeout(() => q !== f.q && set({ ...f, q }), 350); return () => clearTimeout(t); }, [q]); // eslint-disable-line
  const active = f.drug_type.length + f.form.length + f.category.length + f.state.length + f.source.length + (f.since ? 1 : 0) + (f.until ? 1 : 0) + (f.q ? 1 : 0) + (f.focus !== "all" ? 1 : 0) + (f.authenticity ? 1 : 0);
  return (
    <Card className="sticky top-2 z-30 p-3">
      <div className="flex flex-wrap items-center gap-2">
        <SlidersHorizontal size={15} className="text-ink-muted" />
        <Segmented value={f.focus} onChange={(v) => set({ ...f, focus: v })} options={[{ value: "all", label: "All" }, { value: "dissolution", label: "Dissolution only" }, { value: "non_dissolution", label: "Excl. dissolution" }]} />
        <MultiSelect label="Drug type" options={data?.drug_type ?? []} value={f.drug_type} onChange={(v) => set({ ...f, drug_type: v })} />
        <MultiSelect label="Form" options={data?.form ?? []} value={f.form} onChange={(v) => set({ ...f, form: v })} />
        <MultiSelect label="Failure" options={data?.category ?? []} value={f.category} onChange={(v) => set({ ...f, category: v })} />
        <MultiSelect label="State" options={data?.state ?? []} value={f.state} onChange={(v) => set({ ...f, state: v })} />
        <MultiSelect label="Lab type" options={data?.source ?? []} value={f.source} onChange={(v) => set({ ...f, source: v })} />
        <select className="input h-9 w-28 text-xs" value={f.since} onChange={(e) => set({ ...f, since: e.target.value })}>
          <option value="">From</option>{(data?.months ?? []).map((m: string) => <option key={m} value={m}>{fmtMonth(m)}</option>)}
        </select>
        <select className="input h-9 w-28 text-xs" value={f.until} onChange={(e) => set({ ...f, until: e.target.value })}>
          <option value="">To</option>{(data?.months ?? []).map((m: string) => <option key={m} value={m}>{fmtMonth(m)}</option>)}
        </select>
        <select className="input h-9 w-36 text-xs" value={f.authenticity ?? ""} onChange={(e) => set({ ...f, authenticity: e.target.value })} title="Spurious = declared spurious; the maker on the label may not be the real maker">
          <option value="">All batches</option><option value="genuine">Exclude spurious</option><option value="spurious">Spurious only</option>
        </select>
        <div className="relative"><Search size={14} className="absolute left-2.5 top-2.5 text-ink-faint" /><input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Product or manufacturer…" className="input h-9 w-56 pl-8 text-xs" /></div>
        {active > 0 && <button onClick={() => { setQ(""); set(EMPTY); }} className="flex items-center gap-1 text-xs text-ink-muted hover:text-ink"><X size={12} /> Clear {active}</button>}
      </div>
    </Card>
  );
}

const toggle = (arr: string[], v: string) => (arr.includes(v) ? arr.filter((x) => x !== v) : [...arr, v]);

export function Explorer({ f, set }: { f: Filters; set: (f: Filters) => void }) {
  const [topMfr, setTopMfr] = useState(15);
  const [heat, setHeat] = useState<"mfr_reason" | "mfr_molecule" | "form_lab">("mfr_reason");
  const [flow, setFlow] = useState<"state" | "molecule">("state");
  const [mapMetric, setMapMetric] = useState<"alerts" | "intensity">("intensity");
  const [active, setActive] = useState<string | null>(null);
  const cube = useQuery({ queryKey: ["pg-cube", f, topMfr], queryFn: () => api<any>(`/api/playground/cube?${qs(f, { top_mfr: topMfr })}`), placeholderData: keepPreviousData });
  const geo = useQuery({ queryKey: ["pg-geo"], queryFn: () => api<any>("/api/playground/geo/india"), staleTime: Infinity, retry: false });
  const d = cube.data;

  // All hooks must run on every render regardless of loading/error/empty state
  // (Rules of Hooks) — so the memos below guard internally with `d &&` rather
  // than living after an early return, and calls that need `d` fall back to
  // safe defaults when it isn't loaded yet.
  const breakdowns = useMemo(() => !d || d.empty ? [] : [
    { id: "categories", title: "Failure categories", hint: "Click to filter", icon: <ShieldAlert size={14} />, rows: d.categories, color: "#e11d48", onClick: (n: string) => set({ ...f, category: toggle(f.category, n) }) },
    { id: "forms", title: "Dosage forms", hint: "Click to filter", icon: <Pill size={14} />, rows: d.forms, color: "#f59e0b", onClick: (n: string) => set({ ...f, form: toggle(f.form, n) }) },
    { id: "classes", title: "Therapeutic class", hint: "Click to filter", icon: <Stethoscope size={14} />, rows: d.drug_types, color: "#10b996", onClick: (n: string) => set({ ...f, drug_type: toggle(f.drug_type, n) }) },
    { id: "makers", title: "Most-flagged manufacturers", hint: "Click to search", icon: <Factory size={14} />, rows: d.top_manufacturers, color: "#f59e0b", onClick: (n: string) => set({ ...f, q: n }) },
    { id: "products", title: "Most-flagged products", hint: "Brand and strength as labelled", icon: <Package size={14} />, rows: d.top_products, color: "#8b5cf6", onClick: undefined },
    { id: "labs", title: "Testing labs", hint: "Who found them", icon: <FlaskConical size={14} />, rows: d.labs, color: "#0ea5e9", onClick: undefined },
  ], [d, f, set]);

  const { hot, hmPreview, hmMax } = useMemo(() => {
    if (!d || d.empty) return { hot: undefined as { row: string; col: string; v: number } | undefined, hmPreview: [] as number[], hmMax: 1 };
    const cells: { row: string; col: string; v: number }[] = [];
    (d.heat_mfr_reason?.rows ?? []).forEach((r: string, i: number) => (d.heat_mfr_reason.cols ?? []).forEach((c: string, j: number) => cells.push({ row: r, col: c, v: d.heat_mfr_reason.values[i][j] })));
    const hot = cells.sort((a, b2) => b2.v - a.v)[0];
    const hmPreview: number[] = (d.heat_mfr_reason?.values ?? []).slice(0, 6).flatMap((r: number[]) => r.slice(0, 12).concat(Array(Math.max(0, 12 - r.length)).fill(0)));
    const hmMax = Math.max(1, ...hmPreview);
    return { hot, hmPreview, hmMax };
  }, [d]);

  const hm = d && !d.empty ? (heat === "mfr_reason" ? d.heat_mfr_reason : heat === "mfr_molecule" ? d.heat_mfr_molecule : d.heat_form_lab) : undefined;

  const sections: Section[] = useMemo(() => !d || d.empty ? [] : [
    ...breakdowns.map((b) => ({ id: b.id, title: b.title, icon: b.icon, subtitle: b.hint, render: () => <div className="max-w-3xl"><RankBars rows={b.rows} color={b.color} onClick={b.onClick ? (n: string) => { b.onClick!(n); setActive(null); } : undefined} /></div> })),
    { id: "heatmap", title: "Heatmap", icon: <Grid3x3 size={16} />, subtitle: "Where problems concentrate — darker = more alerts", render: () => (
      <div>
        <div className="mb-4 flex flex-wrap items-center gap-2">
          <Segmented value={heat} onChange={setHeat} options={[{ value: "mfr_reason", label: "Maker × failure" }, { value: "mfr_molecule", label: "Maker × molecule" }, { value: "form_lab", label: "Form × testing lab" }]} />
          {heat === "mfr_reason" && <select className="input h-9 w-28 text-xs" value={topMfr} onChange={(e) => setTopMfr(Number(e.target.value))}>{[10, 15, 20, 25, 30].map((n) => <option key={n} value={n}>Top {n}</option>)}</select>}
        </div>
        <div className="rounded-2xl bg-white p-5 ring-1 ring-inset ring-line"><Heatmap m={hm} rowLabel={heat === "form_lab" ? "Form" : "Manufacturer"} onCol={heat === "mfr_reason" ? (c) => { set({ ...f, category: toggle(f.category, c) }); setActive(null); } : undefined} onRow={heat !== "form_lab" ? (r) => { set({ ...f, q: r }); setActive(null); } : undefined} /></div>
      </div>
    ) },
    { id: "flow", title: "How alerts flow", icon: <Waypoints size={16} />, subtitle: flow === "state" ? "Manufacturing state → therapeutic class → failure" : "Therapeutic class → molecule → failure", render: () => (
      <div>
        <div className="mb-4"><Segmented value={flow} onChange={setFlow} options={[{ value: "state", label: "State flow" }, { value: "molecule", label: "Molecule flow" }]} /></div>
        <div className="rounded-2xl bg-white p-4 ring-1 ring-inset ring-line"><SankeyChart data={flow === "state" ? d.sankey_state : d.sankey_molecule} height={620} /></div>
      </div>
    ) },
    // eslint-disable-next-line react-hooks/exhaustive-deps
  ], [breakdowns, heat, topMfr, flow, hm, d, f, set]);

  if (cube.error) return <ErrorNote error={cube.error} />;
  if (!d) return <div className="space-y-4"><Skeleton className="h-28" /><Skeleton className="h-96" /></div>;
  if (d.empty) return <Card className="p-10 text-center text-sm text-ink-muted">No alerts match these filters.</Card>;
  const k = d.kpis;

  return (
    <ExpandedProvider sections={sections} active={active} onActive={setActive} title="NSQ explorer" subtitle={`${k.alerts.toLocaleString("en-IN")} alerts in view`}>
    <div className={cn("space-y-5 transition-opacity", cube.isFetching && "opacity-70")}>
      <div className="grid grid-cols-2 gap-4 xl:grid-cols-5">
        <Stat label="Alerts" value={k.alerts} hint={`${fmtMonth(d.period.first)} – ${fmtMonth(d.period.last)}`} />
        <Stat label="Manufacturers" value={k.manufacturers} tone="indigo" delay={0.03} hint={`${k.products.toLocaleString("en-IN")} products${k.spurious ? ` · ${k.spurious} spurious not attributed` : ""}`} />
        <Stat label="States" value={k.states} tone="amber" delay={0.06} hint={`${k.labs} testing labs`} />
        <Stat label="Dissolution share" value={k.dissolution_share} decimals={1} suffix="%" tone="rose" delay={0.09} />
        <Stat label="Found by CDSCO labs" value={k.cdsco_share} decimals={1} suffix="%" tone="brand" delay={0.12} hint="rest by state labs" />
      </div>

      <div className="grid gap-5 xl:grid-cols-[1.15fr_1fr]">
        <Card delay={0.05}>
          <CardHeader title="Where the failing batches were made"
            subtitle={mapMetric === "alerts" ? "Raw alert count by manufacturing state. Click a state to filter everything." : `Alerts per flagged maker vs the national average (${d.national_per_maker}). 1.0 = average; states with fewer than 20 alerts are grey.`}
            action={<Segmented value={mapMetric} onChange={setMapMetric} options={[{ value: "intensity", label: "Per maker" }, { value: "alerts", label: "Raw count" }]} />} />
          <div className="p-4">{geo.data ? <IndiaMap geo={geo.data} metricLabel={mapMetric === "alerts" ? "alerts" : "× national rate"}
            values={mapMetric === "alerts" ? d.states : d.states.map((s: any) => ({ ...s, count: s.intensity ?? 0 }))} selected={f.state} onPick={(s) => set({ ...f, state: toggle(f.state, s) })} /> : geo.error ? <div className="p-6 text-sm text-ink-muted">State boundaries not loaded in Redis.</div> : <Skeleton className="h-[460px]" />}
            <p className="mt-2 text-[11px] leading-relaxed text-ink-muted">NSQ alerts follow where regulators draw samples and how many plants a state has, so raw counts are not failure rates. "Per maker" compares states on repeat intensity instead. No public count of licensed units per state is loaded, so neither view is a true rate.</p></div>
        </Card>
        <Card delay={0.08}>
          <CardHeader title="Alerts per month" subtitle="By failure category" />
          <div className="px-3 pb-3 pt-3"><TrendArea data={d.trend} height={250} /><div className="px-3 pt-2"><Legendary items={d.trend.series} /></div></div>
          <div className="grid grid-cols-2 gap-4 border-t border-line p-4">
            <div><div className="label mb-2">States</div><RankBars rows={d.states.filter((s: any) => s.name !== "Unknown").slice(0, 8).map((s: any) => ({ name: s.name, count: s.count, sub: `${s.manufacturers} makers` }))} color="#6366f1" onClick={(n) => set({ ...f, state: toggle(f.state, n) })} /></div>
            <div><div className="label mb-2">Lab type</div><RankBars rows={d.sources} color="#0ea5e9" onClick={(n) => set({ ...f, source: toggle(f.source, n) })} /></div>
          </div>
        </Card>
      </div>

      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
        {breakdowns.map((b) => (
          <Tile key={b.id} id={b.id} clickable={false} title={b.title} subtitle={b.hint} icon={b.icon}>
            <RankBars rows={b.rows.slice(0, 5)} color={b.color} onClick={b.onClick} />
            {b.rows.length > 5 && <button onClick={() => setActive(b.id)} className="mt-2 text-xs font-medium text-brand-700 hover:underline">All {b.rows.length} ↗</button>}
          </Tile>
        ))}
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <Tile id="heatmap" title="Heatmap — where problems concentrate" icon={<Grid3x3 size={14} />} subtitle="Maker × failure, maker × molecule, form × testing lab">
          <div className="text-xs text-ink-muted">Hottest cell</div>
          <div className="mt-0.5 text-sm font-semibold">{hot ? `${hot.row} × ${hot.col}` : "—"} <span className="font-display text-lg font-extrabold text-rose-600">{hot?.v ?? ""}</span></div>
          <div className="mt-3 grid grid-cols-12 gap-0.5">{hmPreview.map((v, i) => <div key={i} className="aspect-square rounded-[3px]" style={{ background: v ? `rgba(225,29,72,${0.12 + 0.88 * (v / hmMax)})` : "#f1f5f9" }} />)}</div>
        </Tile>
        <Tile id="flow" title="How alerts flow" icon={<Waypoints size={14} />} subtitle="State → therapeutic class → failure, or class → molecule → failure">
          <div className="space-y-1.5">{(d.sankey_state?.links ?? []).slice().sort((x: any, y: any) => y.value - x.value).slice(0, 4).map((l: any, i: number) => (
            <div key={i} className="flex items-center justify-between gap-2 text-xs"><span className="truncate">{d.sankey_state.nodes[l.source]?.name} → {d.sankey_state.nodes[l.target]?.name}</span><b className="tabular-nums">{l.value}</b></div>
          ))}</div>
        </Tile>
      </div>
    </div>
    </ExpandedProvider>
  );
}

export function Ledger({ f }: { f: Filters }) {
  const [cols, setCols] = useState<string[]>([]);
  const [sort, setSort] = useState("month");
  const [desc, setDesc] = useState(true);
  const [page, setPage] = useState(1);
  const [pick, setPick] = useState(false);
  useEffect(() => setPage(1), [f]);
  const q = useQuery({ queryKey: ["pg-ledger", f, cols, sort, desc, page], queryFn: () => api<any>(`/api/playground/ledger?${qs(f, { cols, sort, desc, page, size: 50 })}`), placeholderData: keepPreviousData });
  const d = q.data;
  const current = useMemo(() => (d?.cols ?? []).map((c: any) => c.key), [d]);
  if (q.error) return <ErrorNote error={q.error} />;
  return (
    <Card>
      <CardHeader title="Alert ledger" subtitle={`${d?.total?.toLocaleString("en-IN") ?? "…"} alerts · sort by any column, choose columns, export the filtered set`}
        action={<div className="flex gap-2">
          <Button size="sm" variant="secondary" onClick={() => setPick(!pick)}><Columns3 size={14} /> Columns</Button>
          <a href={`/api/playground/ledger.csv?${qs(f, { cols: current, sort, desc })}`} className="inline-flex h-8 items-center gap-1.5 rounded-lg bg-ink px-3 text-xs font-medium text-white"><Download size={13} /> CSV</a>
        </div>} />
      {pick && d && (
        <div className="flex flex-wrap gap-1.5 border-b border-line px-5 py-3">
          {d.all_cols.map((c: any) => {
            const on = current.includes(c.key);
            return <button key={c.key} onClick={() => setCols(on ? current.filter((x: string) => x !== c.key) : [...current, c.key])} className={cn("rounded-full px-2.5 py-1 text-[11px] font-medium ring-1 ring-inset", on ? "bg-brand-600 text-white ring-brand-600" : "text-ink-soft ring-line hover:bg-slate-50")}>{c.label}</button>;
          })}
        </div>
      )}
      <div className="overflow-x-auto">
        <table className={cn("w-full text-xs", q.isFetching && "opacity-60")}>
          <thead><tr className="border-b border-line bg-slate-50/70 text-left">
            {d?.cols.map((c: any) => (
              <th key={c.key} onClick={() => { if (sort === c.key) setDesc(!desc); else { setSort(c.key); setDesc(false); } }} className="cursor-pointer whitespace-nowrap px-3 py-2.5 text-[11px] font-semibold uppercase tracking-wider text-ink-muted hover:text-ink">
                {c.label}{sort === c.key && (desc ? " ↓" : " ↑")}
              </th>
            ))}
          </tr></thead>
          <tbody>
            {d?.rows.map((r: any, i: number) => (
              <tr key={i} className="border-b border-line/60 align-top hover:bg-slate-50">
                {d.cols.map((c: any) => <td key={c.key} className={cn("px-3 py-2", ["manufacturer", "reason"].includes(c.key) ? "min-w-[260px] max-w-[420px]" : "max-w-[240px] truncate")} title={r[c.key]}>{c.key === "category" ? <Badge tone="rose">{r[c.key]}</Badge> : c.key === "flag" ? (r.flag ? <Badge tone="indigo">Spurious</Badge> : <span className="text-ink-faint">—</span>) : r[c.key] || "—"}</td>)}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {d && <div className="flex items-center justify-between px-5 py-3 text-xs text-ink-muted"><span>Page {d.page} of {d.pages}</span>
        <div className="flex gap-1.5"><Button size="sm" variant="secondary" disabled={page <= 1} onClick={() => setPage(page - 1)}><ChevronLeft size={14} /></Button><Button size="sm" variant="secondary" disabled={page >= d.pages} onClick={() => setPage(page + 1)}><ChevronRight size={14} /></Button></div></div>}
    </Card>
  );
}