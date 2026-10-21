// Process twin of a wet-granulated tablet: the unit-operation cycle, error injection, and the failure tree
// (batch → quality test → process parameters ranked by Morris sensitivity, each with its tipping point).
// Server: core/chem/process_twin.py via POST /api/lab/molecule/{key}/process-twin.
import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { ChevronDown, ChevronRight, FlaskConical, RotateCcw, Zap } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { CartesianGrid, Line, LineChart, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { Badge, Button, Card, CardHeader, ErrorNote, Skeleton } from "../../components/ui";
import { post } from "../../lib/api";
import { cn } from "../../lib/cn";

const SCENARIOS: { id: string; label: string; set: Record<string, number>; why: string }[] = [
  { id: "overcompress", label: "Over-compression", set: { pressure_mpa: 260 }, why: "Press set too high: low porosity, strong bonds" },
  { id: "overlube", label: "Over-lubrication", set: { blend_min: 20 }, why: "Blend left running: lubricant film makes the tablet hydrophobic" },
  { id: "shortdry", label: "Short drying", set: { drying_min: 40 }, why: "Dryer stopped early" },
  { id: "monsoon", label: "Humid inlet air", set: { dew_point_c: 24 }, why: "Monsoon air without dehumidification: less drying capacity" },
  { id: "wetgran", label: "Over-wet granulation", set: { granulation_liquid_pct: 38 }, why: "Too much binder liquid: dense granules, more water to dry" },
  { id: "coarse", label: "Coarse API lot", set: { api_d50_um: 90 }, why: "API lot milled coarser than the spec" },
  { id: "subpotent", label: "Sub-potent API lot", set: { api_potency_pct: 94 }, why: "API assay below its CoA claim" },
  { id: "weight", label: "Weight variation", set: { weight_rsd_pct: 4 }, why: "Poor die fill (flow, hopper level)" },
];

const BASIS_TONE: Record<string, "brand" | "amber" | "slate"> = { mechanistic: "brand", correlation: "brand", assumed: "amber" };
const fmt = (v: number | null | undefined, d = 2) => (v == null ? "—" : Math.abs(v) >= 100 ? v.toFixed(0) : Number(v.toFixed(d)).toString());

function limitText(id: string, s: any) {
  return ({ assay: `${s.assay_lo}–${s.assay_hi}%`, uniformity: `AV ≤ ${s.av_max}`, dissolution: `≥ ${s.q_pct}% at ${s.q_time_min} min`,
    disintegration: `≤ ${s.dt_max_min} min`, lod: `≤ ${s.lod_max}%`, strength: `≥ ${s.tensile_min} MPa` } as Record<string, string>)[id];
}

function Cycle({ ops, active, hot, warm, onPick }: { ops: any[]; active: string | null; hot: Set<string>; warm: Set<string>; onPick: (id: string) => void }) {
  return (
    <div className="relative overflow-x-auto pb-6">
      <div className="flex min-w-[760px] items-stretch gap-0">
        {ops.map((u, i) => (
          <div key={u.id} className="flex flex-1 items-center">
            <button onClick={() => onPick(u.id)}
              className={cn("relative flex-1 rounded-xl p-3 text-left ring-1 ring-inset transition",
                active === u.id ? "bg-night-900 text-white ring-night-900" : hot.has(u.id) ? "bg-rose-50 ring-rose-300" : warm.has(u.id) ? "bg-amber-50 ring-amber-300" : "bg-white ring-line hover:bg-slate-50")}>
              <div className="text-[10px] font-semibold uppercase tracking-wider opacity-60">{i + 1}</div>
              <div className="text-sm font-bold">{u.label}</div>
              <div className={cn("mt-0.5 text-[11px]", active === u.id ? "text-slate-300" : "text-ink-muted")}>{u.what}</div>
              {u.params?.some((p: any) => p.injected) && <Zap size={13} className="absolute right-2 top-2 text-rose-500" />}
            </button>
            {i < ops.length - 1 && <ChevronRight size={18} className="mx-1 shrink-0 text-ink-faint" />}
          </div>
        ))}
      </div>
      {/* the loop back: test results feed the next batch's settings */}
      <svg className="pointer-events-none absolute bottom-0 left-0 h-6 w-full min-w-[760px]" preserveAspectRatio="none" viewBox="0 0 100 10">
        <path d="M 96 0 Q 96 9 50 9 Q 4 9 4 0" fill="none" stroke="#cbd5e1" strokeWidth="0.4" strokeDasharray="1 1" vectorEffect="non-scaling-stroke" />
      </svg>
      <div className="absolute bottom-0 left-1/2 -translate-x-1/2 bg-white px-2 text-[10px] text-ink-faint">results feed the next batch</div>
    </div>
  );
}

function ParamEditor({ op, overrides, setOverride }: { op: any; overrides: Record<string, number>; setOverride: (id: string, v: number | null) => void }) {
  return (
    <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
      {op.params.map((p: any) => {
        const v = overrides[p.id] ?? p.nominal;
        const out = v < p.lo || v > p.hi;
        return (
          <label key={p.id} className={cn("block rounded-xl p-3 text-xs ring-1 ring-inset", p.id in overrides ? "bg-rose-50/60 ring-rose-200" : "bg-white ring-line")} title={p.note}>
            <div className="flex items-center justify-between gap-2"><span className="font-medium">{p.label}</span><Badge tone={BASIS_TONE[p.basis] ?? "slate"}>{p.basis}</Badge></div>
            <div className="mt-1 flex items-center gap-2">
              <input type="range" min={p.sweep[0]} max={p.sweep[1]} step={(p.sweep[1] - p.sweep[0]) / 200} value={v}
                onChange={(e) => setOverride(p.id, Number(e.target.value))} className="w-full accent-brand-600" />
              <span className={cn("w-20 text-right font-semibold tabular-nums", out && "text-rose-600")}>{fmt(v)} {p.unit}</span>
            </div>
            <div className="mt-0.5 flex justify-between text-[10px] text-ink-faint"><span>normal range {fmt(p.lo)}–{fmt(p.hi)}</span>
              {p.id in overrides && <button type="button" onClick={() => setOverride(p.id, null)} className="text-brand-700 hover:underline">reset</button>}</div>
          </label>
        );
      })}
    </div>
  );
}

function Sweep({ tip, param, limitLabel, current }: { tip: any; param: any; limitLabel: string; current: number }) {
  if (!tip?.sweep) return null;
  const data = tip.sweep.map((x: number, i: number) => ({ x, y: tip.values[i] }));
  return (
    <div className="mt-2 rounded-lg bg-slate-50 p-2">
      <ResponsiveContainer width="100%" height={150}>
        <LineChart data={data} margin={{ left: 0, right: 8, top: 6, bottom: 0 }}><CartesianGrid stroke="#e2e8f0" />
          <XAxis dataKey="x" type="number" fontSize={10} domain={["dataMin", "dataMax"]} unit={` ${param.unit}`} /><YAxis fontSize={10} width={40} /><Tooltip contentStyle={{ fontSize: 11, borderRadius: 8 }} />
          {(tip.crossings ?? []).map((c: any, i: number) => <ReferenceLine key={i} y={c.limit} stroke="#e11d48" strokeDasharray="4 3" />)}
          <ReferenceLine x={current} stroke="#0f172a" />
          <ReferenceLine x={param.lo} stroke="#94a3b8" strokeDasharray="2 2" /><ReferenceLine x={param.hi} stroke="#94a3b8" strokeDasharray="2 2" />
          <Line dataKey="y" stroke="#0a9a7d" strokeWidth={2} dot={false} />
        </LineChart>
      </ResponsiveContainer>
      <div className="px-1 text-[10px] text-ink-muted">Test value as this parameter is swept (others held). Red: the limit ({limitLabel}); black: current; grey: normal range.</div>
    </div>
  );
}

function Tree({ d, onPick, picked }: { d: any; onPick: (unitOp: string, key: string) => void; picked: string | null }) {
  const [open, setOpen] = useState<Record<string, boolean>>({});
  const t = d.tree;
  const params = useMemo(() => Object.fromEntries(d.unit_ops.flatMap((u: any) => u.params.map((p: any) => [p.id, p]))), [d]);
  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between rounded-xl bg-night-900 px-4 py-3 text-white">
        <div><div className="text-sm font-bold">{t.label}</div><div className="text-[11px] text-slate-300">Probability over {d.mc.n} simulated batches run inside the normal ranges around the current settings</div></div>
        <div className="font-display text-2xl font-extrabold">{(100 * t.p_fail).toFixed(1)}%</div>
      </div>
      {t.children.map((c: any) => {
        const isOpen = open[c.id] ?? (c.fails_now || (c.p_fail ?? 0) > 0);
        return (
          <div key={c.id} className="ml-4 border-l-2 border-line pl-3">
            <button onClick={() => setOpen({ ...open, [c.id]: !isOpen })} className="flex w-full items-center gap-3 rounded-xl bg-white px-3 py-2.5 text-left ring-1 ring-inset ring-line hover:bg-slate-50">
              {isOpen ? <ChevronDown size={15} /> : <ChevronRight size={15} />}
              <div className="min-w-0 flex-1">
                <div className="flex flex-wrap items-center gap-2 text-sm font-semibold">{c.label}
                  {c.withheld ? <Badge>not assessable</Badge> : c.fails_now ? <Badge tone="rose">fails now</Badge> : <Badge tone="brand">passes now</Badge>}
                  {c.national_share_pct != null && c.cdsco.length > 0 && <span className="text-[11px] font-normal text-ink-muted">CDSCO: {c.national_share_pct}% of this molecule's {d.molecule.alerts} alerts</span>}
                </div>
                <div className="text-[11px] text-ink-muted">{c.withheld ? c.withheld : <>now {fmt(c.value)} · limit {limitText(c.id, d.specs)}</>}</div>
              </div>
              <div className="w-36 shrink-0">
                {c.p_fail == null ? <span className="text-[11px] text-ink-faint">—</span> : <>
                  <div className="h-1.5 overflow-hidden rounded-full bg-slate-100"><div className="h-full bg-rose-500" style={{ width: `${Math.max(2, 100 * c.p_fail)}%` }} /></div>
                  <div className="mt-0.5 text-right text-[11px] tabular-nums text-ink-muted">P(fail) {(100 * c.p_fail).toFixed(1)}%</div></>}
              </div>
            </button>
            {isOpen && (
              <div className="ml-5 mt-1.5 space-y-1.5 border-l-2 border-dashed border-line pl-3">
                {c.children.map((k: any) => {
                  const key = `${c.id}:${k.param}`;
                  const tp = k.tipping;
                  return (
                    <div key={key}>
                      <button onClick={() => onPick(k.unit_op, picked === key ? "" : key)}
                        className={cn("flex w-full items-center gap-3 rounded-lg px-3 py-2 text-left text-xs ring-1 ring-inset", picked === key ? "bg-brand-50 ring-brand-200" : "bg-white ring-line hover:bg-slate-50")}>
                        <div className="min-w-0 flex-1">
                          <div className="flex flex-wrap items-center gap-1.5 font-medium">{k.label}
                            <span className="rounded bg-slate-100 px-1.5 py-px text-[10px] text-ink-muted">{d.unit_ops.find((u: any) => u.id === k.unit_op)?.label}</span>
                            <Badge tone={BASIS_TONE[k.basis] ?? "slate"}>{k.basis}</Badge></div>
                          <div className="mt-0.5 text-ink-muted">
                            now {fmt(k.current)} {params[k.param]?.unit} ·{" "}
                            {tp ? <>fails if it goes <b>{tp.direction}</b> {fmt(tp.at)} {params[k.param]?.unit}{k.margin_nor != null && <> · margin <b className={cn(k.margin_nor < 1 && "text-rose-600")}>{k.margin_nor}×</b> the normal half-range</>}</>
                              : "no tipping point within the searched range"}
                          </div>
                        </div>
                        <div className="w-28 shrink-0">
                          <div className="h-1.5 overflow-hidden rounded-full bg-slate-100"><div className="h-full bg-indigo-500" style={{ width: `${Math.max(2, 100 * k.influence)}%` }} /></div>
                          <div className="mt-0.5 text-right text-[10px] text-ink-muted">influence {k.mu_star === 0 ? "none" : `${(100 * k.influence).toFixed(0)}%`}</div>
                        </div>
                      </button>
                      {picked === key && <Sweep tip={d.tipping[k.param]?.[c.id]} param={params[k.param]} limitLabel={limitText(c.id, d.specs)} current={k.current} />}
                    </div>
                  );
                })}
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}

export function ProcessTwin({ mkey }: { mkey: string }) {
  const [overrides, setOverrides] = useState<Record<string, number>>({});
  const [active, setActive] = useState<string | null>("compression");
  const [picked, setPicked] = useState<string | null>(null);
  const [scenario, setScenario] = useState<string | null>(null);
  useEffect(() => { setOverrides({}); setScenario(null); setPicked(null); }, [mkey]);
  const [debounced, setDebounced] = useState(overrides);
  useEffect(() => { const t = setTimeout(() => setDebounced(overrides), 450); return () => clearTimeout(t); }, [overrides]);
  const q = useQuery({ queryKey: ["twin", mkey, debounced], queryFn: () => post<any>(`/api/lab/molecule/${mkey}/process-twin`, { overrides: debounced }),
    placeholderData: keepPreviousData, retry: false, staleTime: 5 * 60_000 });
  const d = q.data;
  const setOverride = (id: string, v: number | null) => { setScenario(null); setOverrides((o) => { const n = { ...o }; if (v == null) delete n[id]; else n[id] = v; return n; }); };
  const { hot, warm } = useMemo(() => {
    const hot = new Set<string>(), warm = new Set<string>();
    if (!d) return { hot, warm };
    for (const c of d.tree.children) for (const k of c.children) {
      if (c.fails_now && k.influence > 0.3) hot.add(k.unit_op);
      else if (k.margin_nor != null && k.margin_nor < 1) warm.add(k.unit_op);
    }
    for (const u of d.unit_ops) if (u.params.some((p: any) => p.injected)) hot.add(u.id);
    return { hot, warm };
  }, [d]);
  const op = d?.unit_ops.find((u: any) => u.id === active);
  return (
    <Card>
      <CardHeader icon={<FlaskConical size={16} />} title="Process twin and failure tree"
        subtitle="A wet-granulated tablet of this molecule, unit operation by unit operation: inject an error, watch it travel to the quality tests, and see which parameters tip each test" />
      <div className="space-y-5 p-5">
        {q.error && <ErrorNote error={q.error} />}
        {!d ? <Skeleton className="h-96" /> : (
          <>
            <div className="flex flex-wrap items-center gap-2 text-[11px] text-ink-muted">
              <span><b className="text-ink">{d.molecule.name}</b> {d.molecule.dose_mg} mg</span>
              <span>· solubility {fmt(d.molecule.solubility_mg_ml, 4)} mg/mL in the dissolution medium</span>
              <span>· {d.molecule.medium}</span>
              {q.isFetching && <span className="text-brand-700">· recalculating…</span>}
            </div>

            <div>
              <div className="label mb-2 flex items-center gap-1.5"><Zap size={12} /> Inject an error</div>
              <div className="flex flex-wrap gap-1.5">
                {SCENARIOS.map((s) => (
                  <button key={s.id} title={s.why} onClick={() => { setScenario(s.id); setOverrides(s.set); setActive(d.unit_ops.find((u: any) => u.params.some((p: any) => p.id in s.set))?.id ?? active); }}
                    className={cn("rounded-full px-3 py-1 text-xs font-medium ring-1 ring-inset transition", scenario === s.id ? "bg-rose-600 text-white ring-rose-600" : "bg-white ring-line hover:bg-rose-50")}>{s.label}</button>
                ))}
                {Object.keys(overrides).length > 0 && <Button size="sm" variant="ghost" onClick={() => { setOverrides({}); setScenario(null); }}><RotateCcw size={13} /> Nominal process</Button>}
              </div>
              {scenario && <div className="mt-1.5 text-[11px] text-ink-muted">{SCENARIOS.find((s) => s.id === scenario)?.why}</div>}
            </div>

            <Cycle ops={d.unit_ops} active={active} hot={hot} warm={warm} onPick={(id) => setActive(active === id ? null : id)} />
            {op && op.params.length > 0 && <ParamEditor op={op} overrides={overrides} setOverride={setOverride} />}

            <div className="grid grid-cols-2 gap-2 md:grid-cols-3 xl:grid-cols-6">
              {d.cqas.map((c: any) => {
                const v = d.current.values[c.id], fail = d.current.fails[c.id], wh = d.withheld?.[c.id], mv = d.moved[c.id];
                return (
                  <div key={c.id} className={cn("rounded-xl p-3 ring-1 ring-inset", wh ? "bg-slate-50 ring-line" : fail ? "bg-rose-50 ring-rose-200" : "bg-emerald-50/50 ring-emerald-200")}>
                    <div className="text-[11px] font-medium text-ink-muted">{c.label}</div>
                    <div className="font-display text-lg font-extrabold">{wh ? "n/a" : fmt(v)}</div>
                    <div className="text-[10px] text-ink-muted">{wh ? "not assessable" : `limit ${limitText(c.id, d.specs)}`}{!wh && Math.abs(mv) > 1e-3 && <span className={cn("ml-1 font-semibold", fail ? "text-rose-600" : "text-ink")}>({mv > 0 ? "+" : ""}{fmt(mv)})</span>}</div>
                  </div>
                );
              })}
            </div>

            <Tree d={d} picked={picked} onPick={(u, key) => { setActive(u); setPicked(key || null); }} />

            <div className="grid gap-4 lg:grid-cols-2">
              <div className="rounded-xl bg-slate-50 p-3 text-[11px]">
                <div className="label mb-1.5">How each link is modelled</div>
                <ul className="space-y-1">{d.links.map((l: any, i: number) => <li key={i} className="flex gap-2"><Badge tone={BASIS_TONE[l.basis] ?? "slate"}>{l.basis}</Badge><span><b>{d.cqas.find((c: any) => c.id === l.to)?.label}:</b> {l.what}</span></li>)}</ul>
              </div>
              <div className="rounded-xl bg-amber-50/60 p-3 text-[11px] text-ink-soft">
                <div className="label mb-1.5 text-amber-800">Read this first</div>
                <ul className="list-disc space-y-1 pl-4">{d.assumptions.map((a: string) => <li key={a}>{a}</li>)}</ul>
                <div className="mt-2">Influence = Morris elementary effects (SALib) over each parameter's normal range; P(fail) = Monte Carlo over {d.mc.n} batches; tipping points = one-at-a-time sweeps.</div>
              </div>
            </div>
          </>
        )}
      </div>
    </Card>
  );
}
