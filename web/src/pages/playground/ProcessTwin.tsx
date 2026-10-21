// Process twin of a wet-granulated tablet: the unit-operation cycle, error injection, and the failure tree
// (batch → quality test → process parameters ranked by Morris sensitivity, each with its tipping point).
// Server: core/chem/process_twin.py via POST /api/lab/molecule/{key}/process-twin.
import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { ChevronDown, ChevronRight, ExternalLink, FileText, FlaskConical, RotateCcw, Zap } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { CartesianGrid, Line, LineChart, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { Badge, Button, Card, CardHeader, ErrorNote, Skeleton } from "../../components/ui";
import { post } from "../../lib/api";
import { cn } from "../../lib/cn";
import { plural } from "../../lib/format";

const BASIS_TONE: Record<string, "brand" | "amber" | "slate"> = { mechanistic: "brand", correlation: "brand", assumed: "amber" };
const fmt = (v: number | null | undefined, d = 2) => (v == null ? "—" : Math.abs(v) >= 100 ? v.toFixed(0) : Number(v.toFixed(d)).toString());

function limitText(id: string, s: any) {
  return ({ assay: `${s.assay_lo}–${s.assay_hi}%`, uniformity: `AV ≤ ${s.av_max}`, dissolution: `≥ ${s.q_pct}% at ${s.q_time_min} min`,
    disintegration: `≤ ${s.dt_max_min} min`, lod: `≤ ${s.lod_max}%`, strength: `≥ ${s.tensile_min} MPa` } as Record<string, string>)[id];
}

const ago = (m?: string | null) => (m ? m : "");
const fda = (d?: string | null) => (d && d.length === 8 ? `${d.slice(0, 4)}-${d.slice(4, 6)}` : d ?? "");

function injLabel(st: any) {
  return `${st.label} ${fmt(st.nominal)} → ${fmt(st.value)} ${st.unit}`;
}

// Error scenarios for this molecule: one per quality test, ordered by how often public records (CDSCO notices,
// FDA recalls) name that test; the injected values are the model's own tipping points, never hand-picked.
function Scenarios({ d, active, onInject }: { d: any; active: string | null; onInject: (id: string, set: Record<string, number>, unitOp: string) => void }) {
  const [open, setOpen] = useState<string | null>(null);
  const r = d.records ?? {};
  return (
    <div>
      <div className="mb-2 flex flex-wrap items-baseline justify-between gap-2">
        <div className="label flex items-center gap-1.5"><Zap size={12} /> Inject an error: scenarios from this molecule's records</div>
        <div className="text-[11px] text-ink-muted">
          <a className="text-brand-700 hover:underline" href={r.cdsco_source?.url} target="_blank" rel="noreferrer">CDSCO</a>: {r.tablet_notices} notice{r.tablet_notices === 1 ? "" : "s"} for immediate-release tablets ·{" "}
          <a className="text-brand-700 hover:underline" href={r.recall_source?.url} target="_blank" rel="noreferrer">FDA recalls</a>:{" "}
          {r.recalls_error ? <span>{r.recalls_error}</span> : <>{r.recalls_ir_tablet} IR-tablet recall{r.recalls_ir_tablet === 1 ? "" : "s"} among the {r.recalls_scanned} latest naming it</>}
        </div>
      </div>
      <div className="grid gap-2.5 md:grid-cols-2 xl:grid-cols-3">
        {d.scenarios.map((s: any) => {
          const quotes = [...s.cdsco_quotes.map((q: any) => ({ src: "CDSCO", text: q.result, who: q.product, when: ago(q.month), url: r.cdsco_source?.url })),
            ...s.recall_quotes.map((q: any) => ({ src: `FDA ${q.recall_number}`, text: q.reason, who: `${q.firm} · ${q.product}`, when: fda(q.date), url: q.url }))];
          return (
            <div key={s.test} className={cn("flex flex-col rounded-2xl p-3.5 ring-1 ring-inset", s.records ? "bg-white ring-line shadow-card" : "bg-slate-50/60 ring-line")}>
              <div className="flex items-start justify-between gap-2">
                <div className="font-display text-[17px] font-semibold leading-tight">{s.label}</div>
                {s.records > 0
                  ? <div className="text-right"><div className="font-display text-2xl font-semibold leading-none text-gold-700">{s.records}</div><div className="text-[10px] text-ink-muted">record{s.records === 1 ? "" : "s"}</div></div>
                  : <span className="text-[10px] text-ink-faint">no public record</span>}
              </div>
              <div className="mt-1 text-[11px] text-ink-muted">{s.cdsco} CDSCO notice{s.cdsco === 1 ? "" : "s"} · {s.recalls} FDA recall{s.recalls === 1 ? "" : "s"}</div>
              {quotes.length > 0 && (
                <div className="mt-2">
                  {(open === s.test ? quotes : quotes.slice(0, 1)).map((q: any, i: number) => (
                    <blockquote key={i} className="mb-1.5 border-l-2 border-gold-400 pl-2 text-[11px] leading-snug text-ink-soft">
                      "{q.text.length > 180 ? q.text.slice(0, 180) + "…" : q.text}"
                      <div className="mt-0.5 text-[10px] text-ink-faint"><a href={q.url} target="_blank" rel="noreferrer" className="font-semibold text-brand-700 hover:underline">{q.src}</a> · {q.who.slice(0, 70)}{q.when && ` · ${q.when}`}</div>
                    </blockquote>))}
                  {quotes.length > 1 && <button onClick={() => setOpen(open === s.test ? null : s.test)} className="text-[10px] font-semibold text-brand-700 hover:underline">{open === s.test ? "fewer" : `all ${quotes.length} quoted records`}</button>}
                </div>
              )}
              <div className="mt-auto space-y-1.5 pt-2.5">
                {s.withheld && <div className="rounded-lg bg-slate-100 p-2 text-[11px] text-ink-muted">Not assessable by the model: {s.withheld}</div>}
                {s.kind === "none" && (
                  <div className="rounded-lg bg-amber-50 p-2 text-[11px] text-ink-soft">
                    <b className="text-amber-800">The model does not reproduce this failure.</b> With {s.worst_params.join(", ")} all at their worse ends it still reaches {fmt(s.worst)} (limit {limitText(s.test, d.specs)}).
                    {s.not_modelled.length > 0 && <> Not in this twin: {s.not_modelled.join(", ")}.</>}
                  </div>)}
                {s.injections.map((step: any[], i: number) => {
                  const id = `${s.test}:${i}`;
                  return (
                    <button key={id} onClick={() => onInject(id, Object.fromEntries(step.map((st) => [st.param, st.value])), step[0].unit_op)}
                      className={cn("w-full rounded-xl px-2.5 py-2 text-left text-[11px] ring-1 ring-inset transition",
                        active === id ? "bg-night-900 text-white ring-night-900" : "bg-white ring-line hover:bg-gold-50 hover:ring-gold-300")}>
                      <div className="flex items-center gap-1.5 font-semibold"><Zap size={11} className={active === id ? "text-gold-400" : "text-rose-500"} />
                        {s.kind === "combined" ? "Inject together" : "Inject"}</div>
                      {step.map((st) => <div key={st.param} className="mt-0.5 tabular-nums">{injLabel(st)}</div>)}
                      <div className={cn("mt-0.5 text-[10px]", active === id ? "text-slate-300" : "text-ink-faint")}>
                        {s.kind === "combined" ? "the first point where the test fails as these drift together (model)" : `fails ${step[0].direction} ${fmt(step[0].tipping)} ${step[0].unit} (model tipping point)`}</div>
                    </button>);
                })}
              </div>
            </div>
          );
        })}
      </div>
      {r.outside?.length > 0 && (
        <div className="mt-2.5 flex flex-wrap items-center gap-1.5 text-[11px] text-ink-muted">Also in this molecule's CDSCO records, outside a tablet process twin:
          {r.outside.map((o: any) => <span key={o.name} className="rounded-full bg-slate-100 px-2 py-0.5">{o.name} · {o.count}</span>)}</div>)}
      {r.label?.inactive_ingredients?.length > 0 && (
        <div className="mt-2 flex flex-wrap items-start gap-1.5 text-[11px] text-ink-muted"><FileText size={12} className="mt-0.5 shrink-0" />
          <span>Excipients on the US label ({r.label.brand}, {r.label.manufacturer}): {r.label.inactive_ingredients.join(", ")}.{" "}
            {r.label.url && <a href={r.label.url} target="_blank" rel="noreferrer" className="inline-flex items-center gap-0.5 text-brand-700 hover:underline">DailyMed <ExternalLink size={10} /></a>}
            {" "}The twin's formulation constants are generic: replace them with your product's.</span>
        </div>)}
    </div>
  );
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
                  {c.national_alerts > 0 && <span className="text-[11px] font-normal text-ink-muted">CDSCO: named in {c.national_alerts} of this molecule's {d.molecule.alerts} IR-tablet notices</span>}
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

            <Scenarios d={d} active={scenario} onInject={(id, set, u) => {
              if (scenario === id) { setScenario(null); setOverrides({}); return; }
              setScenario(id); setOverrides(set); setActive(u);
            }} />
            {Object.keys(overrides).length > 0 && <div><Button size="sm" variant="ghost" onClick={() => { setOverrides({}); setScenario(null); }}><RotateCcw size={13} /> Back to the nominal process</Button></div>}

            <Cycle ops={d.unit_ops} active={active} hot={hot} warm={warm} onPick={(id) => setActive(active === id ? null : id)} />
            {op && op.params.length > 0 && <ParamEditor op={op} overrides={overrides} setOverride={setOverride} />}

            <div className="grid grid-cols-2 gap-2 md:grid-cols-3 xl:grid-cols-6">
              {d.cqas.map((c: any) => {
                const v = d.current.values[c.id], fail = d.current.fails[c.id], wh = d.withheld?.[c.id], mv = d.moved[c.id];
                return (
                  <div key={c.id} className={cn("rounded-xl p-3 ring-1 ring-inset", wh ? "bg-slate-50 ring-line" : fail ? "bg-rose-50 ring-rose-200" : "bg-emerald-50/50 ring-emerald-200")}>
                    <div className="text-[11px] font-medium text-ink-muted">{c.label}</div>
                    <div className="font-display text-lg font-extrabold">{wh ? "n/a" : fmt(v)}</div>
                    <div className="text-[10px] text-ink-muted" title={d.spec_basis?.[c.id]?.text}>{wh ? "not assessable" : <>limit {limitText(c.id, d.specs)} <span className={cn("rounded px-1 font-semibold", d.spec_basis?.[c.id]?.kind === "source" ? "bg-brand-50 text-brand-700" : "bg-amber-50 text-amber-700")}>{d.spec_basis?.[c.id]?.kind === "source" ? "cited" : "default"}</span></>}{!wh && Math.abs(mv) > 1e-3 && <span className={cn("ml-1 font-semibold", fail ? "text-rose-600" : "text-ink")}>({mv > 0 ? "+" : ""}{fmt(mv)})</span>}</div>
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
                <div className="label mb-1 mt-2.5 text-amber-800">Where each limit comes from</div>
                <ul className="space-y-0.5">{d.cqas.map((c: any) => d.spec_basis?.[c.id] && <li key={c.id}><b>{c.label}:</b> {d.spec_basis[c.id].text}
                  {d.spec_basis[c.id].url && <> <a href={d.spec_basis[c.id].url} target="_blank" rel="noreferrer" className="text-brand-700 hover:underline">source</a></>}</li>)}</ul>
                <div className="mt-2">Influence = Morris elementary effects (SALib) over each parameter's normal range; P(fail) = Monte Carlo over {plural(d.mc.n, "batch", "batches")}; tipping points = one-at-a-time sweeps.</div>
              </div>
            </div>
          </>
        )}
      </div>
    </Card>
  );
}
