// Reaction lab: run a synthesis step as a batch-reactor kinetic model — anchored to a published route (Open Reaction
// Database), with the yield map over temperature × time, an acceptable operating range, activation-energy sensitivity,
// heat release and Stoessel thermal-safety class. Built-in SciPy engine, cross-checked against PharmaPy's BatchReactor.
import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { LoadingEdge } from "../../components/ui/Loading";
import { BadgeCheck, ChevronDown, FlaskRound, Flame, Info, Target, TriangleAlert } from "lucide-react";
import { useEffect, useMemo, useState, type ReactNode } from "react";
import { CartesianGrid, Legend, Line, LineChart, ReferenceDot, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { Badge, Card, CardHeader, ErrorNote, Skeleton } from "../../components/ui";
import { api, post } from "../../lib/api";
import { cn } from "../../lib/cn";

// Species colours (validated: lightness band, chroma, CVD ≥ 7.3 with dashed reactants + direct labels as secondary encoding)
const SP_COLOR: Record<string, string> = { A: "#0284c7", B: "#a855f7", P: "#0a9a7d", D: "#e11d48", S: "#d97706" };
const SP_ROLE: Record<string, string> = { A: "substrate (limiting)", B: "reagent", P: "product", D: "degradant", S: "by-product" };
const REACTANT = new Set(["A", "B"]);
const GREEN = ["#ecfdf5", "#d1fae5", "#a7f3d0", "#6ee7b7", "#34d399", "#10b981", "#059669", "#047857", "#065f46"];
const CRIT_TONE: Record<number, any> = { 1: "brand", 2: "brand", 3: "amber", 4: "rose", 5: "rose" };

function useDebounced<T>(v: T, ms = 350) {
  const [d, setD] = useState(v);
  useEffect(() => { const t = setTimeout(() => setD(v), ms); return () => clearTimeout(t); }, [v, ms]);
  return d;
}

function Num({ label, value, onChange, step = 1, unit, disabled, hint }: { label: string; value: number | string | null; onChange: (v: string) => void; step?: number; unit?: string; disabled?: boolean; hint?: string }) {
  return (
    <label className="block" title={hint}>
      <span className="text-[10.5px] font-semibold uppercase tracking-wider text-ink-muted">{label}</span>
      <div className="mt-0.5 flex items-center rounded-lg bg-white ring-1 ring-inset ring-line focus-within:ring-brand-400">
        <input type="number" step={step} disabled={disabled} value={value ?? ""} onChange={(e) => onChange(e.target.value)}
          className="h-8 w-full min-w-0 rounded-lg bg-transparent px-2 text-[13px] tabular-nums outline-none disabled:text-ink-faint" />
        {unit && <span className="pr-2 text-[11px] text-ink-faint">{unit}</span>}
      </div>
    </label>
  );
}

function Kpi({ label, value, sub, tone }: { label: string; value: ReactNode; sub?: ReactNode; tone?: string }) {
  return (
    <div className="rounded-xl bg-white p-3 ring-1 ring-inset ring-line">
      <div className="text-[10.5px] font-semibold uppercase tracking-wider text-ink-muted">{label}</div>
      <div className="mt-0.5 font-display text-xl font-bold tabular-nums" style={tone ? { color: tone } : undefined}>{value}</div>
      {sub && <div className="text-[11px] text-ink-muted">{sub}</div>}
    </div>
  );
}

// ------------------------------------------------------------------------------------------ charts

function ConcChart({ res }: { res: any }) {
  const sp: string[] = Object.keys(res.conc);
  const rows = res.time_h.map((t: number, i: number) => ({ t, ...Object.fromEntries(sp.map((s) => [s, res.conc[s][i]])) }));
  const last = rows[rows.length - 1];
  return (
    <ResponsiveContainer width="100%" height={260}>
      <LineChart data={rows} margin={{ top: 8, right: 56, bottom: 4, left: 0 }}>
        <CartesianGrid stroke="#eef2f7" vertical={false} />
        <XAxis dataKey="t" type="number" domain={[0, "dataMax"]} tickFormatter={(v) => `${+v.toFixed(1)} h`} tick={{ fontSize: 11, fill: "#64748b" }} tickLine={false} axisLine={false} />
        <YAxis tick={{ fontSize: 11, fill: "#64748b" }} tickLine={false} axisLine={false} width={44} label={{ value: "mol/L", angle: -90, position: "insideLeft", fontSize: 10, fill: "#94a3b8" }} />
        <Tooltip formatter={(v: any, n: any) => [`${(+v).toFixed(3)} mol/L`, `${n} · ${SP_ROLE[n] ?? ""}`]} labelFormatter={(l) => `${(+l).toFixed(2)} h`} contentStyle={{ fontSize: 12, borderRadius: 10 }} />
        <Legend formatter={(v) => <span className="text-[11px] text-ink-soft">{v} · {SP_ROLE[v] ?? ""}</span>} iconType="plainline" />
        {sp.map((s) => <Line key={s} dataKey={s} stroke={SP_COLOR[s] ?? "#64748b"} strokeWidth={2} dot={false} isAnimationActive={false} strokeDasharray={REACTANT.has(s) ? "6 4" : undefined} />)}
        {sp.map((s) => <ReferenceDot key={`l${s}`} x={last.t} y={last[s]} r={0} label={{ value: s, position: "right", fontSize: 11, fill: "#334155", fontWeight: 600 }} />)}
      </LineChart>
    </ResponsiveContainer>
  );
}

function YieldMap({ map, ok, anchor, op, which }: { map: any; ok: number[][]; anchor: any; op: { t: number; h: number }; which: "yield" | "impurity" }) {
  const [hover, setHover] = useState<{ i: number; j: number } | null>(null);
  const vals: number[][] = which === "yield" ? map.yield_pct : map.impurity_pct ?? [];
  const flat = vals.flat();
  const lo = Math.min(...flat), hi = Math.max(...flat);
  const color = (v: number) => {
    let x = hi > lo ? (v - lo) / (hi - lo) : 1;
    return GREEN[Math.min(GREEN.length - 1, Math.floor(x * (GREEN.length - 1) + 1e-9))];
  };
  const temps: number[] = map.temps_c, hours: number[] = map.hours;
  const rowsTopHot = [...temps.keys()].reverse();
  const near = (arr: number[], v: number) => arr.reduce((b, x, k) => (Math.abs(x - v) < Math.abs(arr[b] - v) ? k : b), 0);
  const ai = anchor ? near(temps, anchor.temp_c) : -1, aj = anchor ? near(hours, anchor.hours) : -1;
  const oi = near(temps, op.t), oj = near(hours, op.h);
  const bi = temps.indexOf(map.best.temp_c), bj = hours.indexOf(map.best.hours);
  return (
    <div>
      <div className="grid gap-[2px]" style={{ gridTemplateColumns: `2.75rem repeat(${hours.length}, minmax(0, 1fr))` }} onMouseLeave={() => setHover(null)}>
        {rowsTopHot.map((i) => [
          <div key={`l${i}`} className="flex h-6 items-center justify-end pr-1 text-[10.5px] tabular-nums text-ink-muted">{temps[i]}°</div>,
          ...hours.map((_, j) => {
            const v = vals[i]?.[j];
            const inPar = ok?.[i]?.[j] === 1;
            return (
              <div key={`${i}-${j}`} onMouseEnter={() => setHover({ i, j })}
                className={cn("relative flex h-6 items-center justify-center rounded-[3px] text-[10px] font-semibold tabular-nums", inPar && "ring-2 ring-inset ring-emerald-900/70")}
                style={{ background: v == null ? "#f1f5f9" : color(v), color: v != null && (v - lo) / (hi - lo || 1) > 0.55 ? "#fff" : "#1e293b" }}>
                {i === bi && j === bj ? "★" : i === ai && j === aj ? "◎" : i === oi && j === oj ? "●" : ""}
              </div>
            );
          }),
        ])}
        <div />
        {hours.map((h) => <div key={h} className="pt-0.5 text-center text-[10px] tabular-nums text-ink-muted">{h < 1 ? +h.toFixed(2) : +h.toFixed(1)}</div>)}
      </div>
      <div className="mt-0.5 text-center text-[10.5px] text-ink-muted">batch time (h) →  ·  temperature ↑</div>
      <div className="mt-2 flex flex-wrap items-center gap-3 text-[11px] text-ink-muted">
        <span className="flex items-center gap-1"><span className="flex h-2.5 w-24 overflow-hidden rounded-full">{GREEN.map((c) => <span key={c} className="flex-1" style={{ background: c }} />)}</span>
          {lo.toFixed(which === "yield" ? 0 : 2)}–{hi.toFixed(which === "yield" ? 0 : 2)}% {which === "yield" ? "yield" : map.impurity}</span>
        <span>★ best · ◎ published example · ● your conditions</span>
        <span className="flex items-center gap-1"><span className="h-3 w-3 rounded-[3px] ring-2 ring-inset ring-emerald-900/70" /> meets the targets</span>
        {hover && vals[hover.i]?.[hover.j] != null && <span className="ml-auto rounded-md bg-night-900 px-2 py-0.5 text-white">
          {temps[hover.i]} °C · {hours[hover.j]} h → yield {map.yield_pct[hover.i][hover.j].toFixed(1)}%{map.impurity_pct ? ` · ${map.impurity} ${map.impurity_pct[hover.i][hover.j].toFixed(2)}%` : ""}</span>}
      </div>
    </div>
  );
}

function EaBand({ band, op }: { band: any; op: number }) {
  const rows = band.temps_c.map((t: number, i: number) => ({ t, low: band.low[i], mid: band.mid[i], high: band.high[i] }));
  return (
    <ResponsiveContainer width="100%" height={220}>
      <LineChart data={rows} margin={{ top: 8, right: 16, bottom: 4, left: 0 }}>
        <CartesianGrid stroke="#eef2f7" vertical={false} />
        <XAxis dataKey="t" type="number" domain={["dataMin", "dataMax"]} tickFormatter={(v) => `${v}°`} tick={{ fontSize: 11, fill: "#64748b" }} tickLine={false} axisLine={false} />
        <YAxis domain={[0, 100]} tickFormatter={(v) => `${v}%`} tick={{ fontSize: 11, fill: "#64748b" }} tickLine={false} axisLine={false} width={40} />
        <Tooltip formatter={(v: any, n: any) => [`${(+v).toFixed(1)}%`, n]} labelFormatter={(l) => `${l} °C, ${band.hours} h`} contentStyle={{ fontSize: 12, borderRadius: 10 }} />
        <Legend iconType="plainline" formatter={(v) => <span className="text-[11px] text-ink-soft">{v}</span>} />
        <ReferenceLine x={op} stroke="#94a3b8" strokeDasharray="3 3" />
        <Line dataKey="low" name={`Ea − ${band.delta_kj}`} stroke="#0284c7" strokeWidth={2} strokeDasharray="6 4" dot={false} isAnimationActive={false} />
        <Line dataKey="mid" name="Ea as entered" stroke="#0a9a7d" strokeWidth={2} dot={false} isAnimationActive={false} />
        <Line dataKey="high" name={`Ea + ${band.delta_kj}`} stroke="#d97706" strokeWidth={2} strokeDasharray="2 3" dot={false} isAnimationActive={false} />
      </LineChart>
    </ResponsiveContainer>
  );
}

function HeatChart({ res }: { res: any }) {
  const rows = res.time_h.map((t: number, i: number) => ({ t, w: +(res.heat_kw_per_l[i] * 1000).toFixed(3), acc: res.acc_k[i] }));
  return (
    <div className="grid gap-3 md:grid-cols-2">
      {[{ k: "w", name: "Heat release", unit: "W/L", color: "#e11d48" }, { k: "acc", name: "Adiabatic rise still stored", unit: "K", color: "#d97706" }].map((c) => (
        <div key={c.k}>
          <div className="mb-1 text-[11px] font-semibold text-ink-soft">{c.name} <span className="font-normal text-ink-muted">({c.unit})</span></div>
          <ResponsiveContainer width="100%" height={150}>
            <LineChart data={rows} margin={{ top: 4, right: 8, bottom: 0, left: 0 }}>
              <CartesianGrid stroke="#eef2f7" vertical={false} />
              <XAxis dataKey="t" type="number" domain={[0, "dataMax"]} tickFormatter={(v) => `${+v.toFixed(1)}h`} tick={{ fontSize: 10, fill: "#64748b" }} tickLine={false} axisLine={false} />
              <YAxis tick={{ fontSize: 10, fill: "#64748b" }} tickLine={false} axisLine={false} width={40} />
              <Tooltip formatter={(v: any) => [`${(+v).toFixed(2)} ${c.unit}`, c.name]} labelFormatter={(l) => `${(+l).toFixed(2)} h`} contentStyle={{ fontSize: 12, borderRadius: 10 }} />
              <Line dataKey={c.k} stroke={c.color} strokeWidth={2} dot={false} isAnimationActive={false} />
            </LineChart>
          </ResponsiveContainer>
        </div>
      ))}
    </div>
  );
}

// ------------------------------------------------------------------------------------------ validation

function Validation() {
  const [open, setOpen] = useState(false);
  const v = useQuery({ queryKey: ["rx-validation"], queryFn: () => api<any>("/api/lab/reactions/validation"), enabled: open, staleTime: 600_000 });
  return (
    <Card className="overflow-hidden">
      <button onClick={() => setOpen(!open)} className="flex w-full items-center gap-2 px-4 py-3 text-left">
        <BadgeCheck size={15} className="text-brand-600" />
        <span className="flex-1 text-[13px] font-semibold">How the engine is checked — exact solutions, and PharmaPy side by side</span>
        <ChevronDown size={15} className={cn("text-ink-faint transition", open && "rotate-180")} />
      </button>
      {open && (
        <div className="border-t border-line p-4 text-xs">
          {!v.data ? <Skeleton className="h-40" /> : (
            <>
              <p className="mb-3 text-ink-soft">Runs now, on this server: every case below is integrated by the same engine you are using and compared with its
                closed-form answer. <b>{v.data.passed} of {v.data.total} pass.</b></p>
              <table className="w-full">
                <thead><tr className="text-left text-[10.5px] uppercase tracking-wider text-ink-muted"><th className="py-1">Case</th><th>Checked against</th><th className="text-right">Max relative error</th><th className="text-right">Result</th></tr></thead>
                <tbody>{v.data.cases.map((c: any) => (
                  <tr key={c.case} className="border-t border-line/70"><td className="py-1.5 font-medium">{c.case}</td><td className="font-mono text-[11px] text-ink-muted">{c.checks}</td>
                    <td className="text-right tabular-nums">{c.max_rel_error.toExponential(1)}</td>
                    <td className="text-right">{c.pass ? <Badge tone="brand">pass</Badge> : <Badge tone="rose">fail</Badge>}</td></tr>))}</tbody>
              </table>
              <div className="mt-3 rounded-lg bg-slate-50 p-3 text-ink-soft">
                <b>PharmaPy (Purdue) cross-check:</b>{" "}
                {v.data.pharmapy ? (v.data.pharmapy.error ? <span className="text-rose-700">{v.data.pharmapy.error}</span>
                  : <>live run of {v.data.pharmapy.case}: yield curves differ by at most <b>{v.data.pharmapy.max_yield_diff_pct} percentage points</b> {v.data.pharmapy.pass ? "✓" : "✗"}</>)
                  : <>the sim service is not running here. During development the two engines were run on six mechanisms (A→P, A+B→P, A→P→D, parallel, competitive-consecutive, and a run 40 °C away from the reference temperature): concentrations agreed within 3×10⁻⁵ mol/L.</>}
              </div>
            </>
          )}
        </div>
      )}
    </Card>
  );
}

// ------------------------------------------------------------------------------------------ page

export function ReactionLab() {
  const mols = useQuery({ queryKey: ["rx-mols"], queryFn: () => api<any>("/api/lab/reactions/molecules"), staleTime: 300_000 });
  const tpls = useQuery({ queryKey: ["rx-tpls"], queryFn: () => api<any>("/api/lab/reactions/templates"), staleTime: Infinity });
  const [mol, setMol] = useState<string>("");
  const routes = useQuery({ queryKey: ["rx-routes", mol], enabled: !!mol, queryFn: () => api<any>(`/api/lab/reactions/routes/${encodeURIComponent(mol)}`) });
  const [anchor, setAnchor] = useState<any | null>(null);
  const [tpl, setTpl] = useState("consecutive");
  const [rx, setRx] = useState<any[]>([]);
  const [c0, setC0] = useState<Record<string, number>>({});
  const [cond, setCond] = useState<any>({ temp_c: 80, hours: 6, t0_c: "", ramp_h: 0, bp_c: 118, rho_kg_l: 0.9, cp_kj_kg_k: 1.9, td24_c: "" });
  const [targets, setTargets] = useState<any>({ min_yield_pct: "", max_impurity_pct: 0.5 });
  const [whichMap, setWhichMap] = useState<"yield" | "impurity">("yield");
  const [solventName, setSolventName] = useState<string | null>(null);

  useEffect(() => { if (!mol && mols.data?.molecules?.length) setMol(mols.data.molecules[0].key); }, [mols.data, mol]);
  const T = tpls.data?.templates?.find((x: any) => x.id === tpl);
  useEffect(() => { if (T) { setRx(T.rxns.map((r: any) => ({ k: r.k, ea: r.ea, dh: r.dh, ...(r.keq ? { keq: r.keq } : {}) }))); setC0(T.c0); } }, [T?.id]); // eslint-disable-line

  const pickRoute = async (r: any) => {
    setAnchor(r.anchor ? { temp_c: r.temp_c, hours: r.hours, yield_pct: r.yield_pct, id: r.id, patent: r.patent } : null);
    setTpl(r.suggested_template);
    setCond((c: any) => ({ ...c, temp_c: r.temp_c ?? c.temp_c, hours: r.hours ?? c.hours }));
    setSolventName(r.solvent);
    if (r.solvent) {
      try {
        const s = await api<any>(`/api/lab/reactions/solvent?name=${encodeURIComponent(r.solvent)}`);
        setCond((c: any) => ({ ...c, bp_c: s.bp_c, rho_kg_l: s.rho_kg_l, cp_kj_kg_k: s.cp_kj_kg_k ?? c.cp_kj_kg_k }));
      } catch { /* unknown solvent: keep what is entered */ }
    }
  };

  const body = useMemo(() => ({
    template: tpl, rxns: rx, c0, anchor, targets: { min_yield_pct: targets.min_yield_pct === "" ? undefined : +targets.min_yield_pct, max_impurity_pct: targets.max_impurity_pct === "" ? undefined : +targets.max_impurity_pct },
    temp_c: +cond.temp_c, hours: +cond.hours, t0_c: cond.t0_c === "" ? undefined : +cond.t0_c, ramp_h: +cond.ramp_h || 0,
    bp_c: cond.bp_c === "" ? undefined : +cond.bp_c, rho_kg_l: +cond.rho_kg_l, cp_kj_kg_k: +cond.cp_kj_kg_k, td24_c: cond.td24_c === "" ? undefined : +cond.td24_c,
  }), [tpl, rx, c0, anchor, targets, cond]);
  const db = useDebounced(body);
  const run = useQuery({ queryKey: ["rx-run", db], enabled: !!T && rx.length > 0, placeholderData: keepPreviousData, queryFn: () => post<any>("/api/lab/reactions/run", db) });
  const d = run.data;
  const s = d?.result?.summary;
  const cal = d?.calibration;

  if (tpls.error) return <ErrorNote error={tpls.error} />;
  if (!tpls.data) return <Skeleton className="h-96" />;
  const setR = (i: number, k: string, v: string) => setRx(rx.map((r, j) => (j === i ? { ...r, [k]: v === "" ? "" : +v } : r)));

  return (
    <div className="space-y-4">
      <div className="rounded-2xl bg-gradient-to-br from-night-900 to-slate-800 p-5 text-white">
        <div className="flex items-center gap-2 text-[11px] font-semibold uppercase tracking-wider text-brand-400"><FlaskRound size={13} /> Reaction lab</div>
        <div className="mt-1 max-w-4xl font-display text-xl font-bold leading-snug">Run a synthesis step before you run it in the plant: conversion, yield and impurities over time, the temperature × time window that meets your spec, and whether a cooling failure could boil or decompose the batch.</div>
        <p className="mt-1.5 max-w-4xl text-[12.5px] text-slate-300">Start from a published route (patents and papers in the Open Reaction Database) — its temperature, time and yield calibrate the model — or enter your own kinetics.
          Engine: {d?.result?.engine === "pharmapy" ? "PharmaPy BatchReactor (Purdue), cross-checked against the built-in solver" : "built-in stiff ODE solver"}{tpls.data.engines?.pharmapy?.available ? " · PharmaPy available" : ""}.</p>
      </div>

      <div className="grid gap-4 xl:grid-cols-[23rem_minmax(0,1fr)]">
        {/* ---------------------------------------------------------------- inputs */}
        <div className="space-y-4">
          <Card className="p-4">
            <div className="label mb-2">1 · Molecule and published route</div>
            <select className="input h-9 w-full" value={mol} onChange={(e) => { setMol(e.target.value); setAnchor(null); }}>
              {(mols.data?.molecules ?? []).map((m: any) => <option key={m.key} value={m.key}>{m.name} — {m.routes} routes, {m.anchors} with T·time·yield</option>)}
            </select>
            <div className="mt-2 max-h-72 space-y-1.5 overflow-y-auto pr-1">
              {routes.data?.routes?.map((r: any) => (
                <button key={r.id} onClick={() => pickRoute(r)} className={cn("w-full rounded-lg p-2 text-left text-[11.5px] ring-1 ring-inset transition hover:bg-slate-50",
                  anchor?.id === r.id ? "bg-emerald-50 ring-emerald-300" : "ring-line")}>
                  <div className="flex items-center gap-1.5 font-semibold">
                    {r.anchor ? <Target size={11} className="text-emerald-600" /> : <span className="h-2.5 w-2.5 rounded-full bg-slate-200" />}
                    {r.temp_c != null ? `${r.temp_c} °C` : "T —"} · {r.hours != null ? `${r.hours} h` : "time —"} · {r.yield_pct != null ? `${r.yield_pct}%` : "yield —"}
                    <span className="ml-auto font-normal text-ink-faint">{r.patent ?? r.doi ?? r.dataset}</span>
                  </div>
                  <div className="mt-0.5 line-clamp-2 text-ink-muted">{r.reactants.slice(0, 3).join(" + ") || "reactants not named"}{r.solvent ? ` · in ${r.solvent}` : ""}{r.catalysts.length ? ` · ${r.catalysts.join(", ")}` : ""}</div>
                </button>
              ))}
              {routes.data && !routes.data.found && <div className="text-xs text-ink-muted">No ORD routes for this molecule.</div>}
            </div>
            <p className="mt-2 text-[10.5px] text-ink-faint"><Target size={10} className="inline" /> = has temperature, time and yield: picking it calibrates the model. Reactions: Open Reaction Database (CC BY-SA).</p>
          </Card>

          <Card className="p-4">
            <div className="label mb-2">2 · Mechanism</div>
            <select className="input h-9 w-full" value={tpl} onChange={(e) => setTpl(e.target.value)}>
              {tpls.data.templates.map((t: any) => <option key={t.id} value={t.id}>{t.label}</option>)}
            </select>
            <p className="mt-1 text-[11px] text-ink-muted">{T?.hint}</p>
            <div className="mt-2 space-y-2">
              {T?.rxns.map((r: any, i: number) => (
                <div key={i} className="rounded-lg bg-slate-50 p-2">
                  <div className="mb-1 font-mono text-[11px] text-ink-soft">{Object.keys(r.r).join(" + ")} → {Object.keys(r.p).join(" + ")}{i === 0 ? " (main)" : ""}</div>
                  <div className="grid grid-cols-3 gap-1.5">
                    <Num label={`k @ Tref`} value={cal?.ok ? +(cal.rxns[i].k).toPrecision(3) : rx[i]?.k} onChange={(v) => setR(i, "k", v)} step={0.01} disabled={!!cal?.ok}
                      hint={cal?.ok ? "set by calibration to the published example" : "1/h (first order) or L/(mol·h) (second order)"} />
                    <Num label="Ea" unit="kJ/mol" value={rx[i]?.ea} onChange={(v) => setR(i, "ea", v)} />
                    <Num label="ΔH" unit="kJ/mol" value={rx[i]?.dh} onChange={(v) => setR(i, "dh", v)} />
                  </div>
                  {r.keq && <div className="mt-1.5 w-1/3"><Num label="K eq" value={rx[i]?.keq} onChange={(v) => setR(i, "keq", v)} step={0.5} /></div>}
                </div>
              ))}
            </div>
            <div className="mt-2 grid grid-cols-3 gap-1.5">
              {Object.keys(c0).map((sp) => <Num key={sp} label={`${sp}₀`} unit="M" step={0.1} value={c0[sp]} onChange={(v) => setC0({ ...c0, [sp]: v === "" ? 0 : +v })} />)}
            </div>
          </Card>

          <Card className="p-4">
            <div className="label mb-2">3 · Conditions and safety inputs</div>
            <div className="grid grid-cols-2 gap-1.5">
              <Num label="Temperature" unit="°C" value={cond.temp_c} onChange={(v) => setCond({ ...cond, temp_c: v })} />
              <Num label="Batch time" unit="h" step={0.5} value={cond.hours} onChange={(v) => setCond({ ...cond, hours: v })} />
              <Num label="Start temp (ramp)" unit="°C" value={cond.t0_c} onChange={(v) => setCond({ ...cond, t0_c: v })} hint="blank = isothermal" />
              <Num label="Ramp time" unit="h" step={0.25} value={cond.ramp_h} onChange={(v) => setCond({ ...cond, ramp_h: v })} />
              <Num label="Boiling point (MTT)" unit="°C" value={cond.bp_c} onChange={(v) => setCond({ ...cond, bp_c: v })} hint={solventName ? `from ${solventName}` : "solvent boiling point"} />
              <Num label="TD24 (DSC/ARC)" unit="°C" value={cond.td24_c} onChange={(v) => setCond({ ...cond, td24_c: v })} hint="optional: completes the Stoessel class" />
              <Num label="Density" unit="kg/L" step={0.05} value={cond.rho_kg_l} onChange={(v) => setCond({ ...cond, rho_kg_l: v })} />
              <Num label="Heat capacity" unit="kJ/kg·K" step={0.1} value={cond.cp_kj_kg_k} onChange={(v) => setCond({ ...cond, cp_kj_kg_k: v })} />
            </div>
            <div className="label mb-1.5 mt-3">Targets for the operating window</div>
            <div className="grid grid-cols-2 gap-1.5">
              <Num label="Min yield" unit="%" value={targets.min_yield_pct} onChange={(v) => setTargets({ ...targets, min_yield_pct: v })} hint="blank = 5 points below the best" />
              <Num label="Max impurity" unit="%" step={0.1} value={targets.max_impurity_pct} onChange={(v) => setTargets({ ...targets, max_impurity_pct: v })} hint="ICH Q3A qualification threshold is often 0.15–0.5%" />
            </div>
          </Card>
        </div>

        {/* ---------------------------------------------------------------- results */}
        <div className="min-w-0 space-y-4">
          {run.error && <ErrorNote error={run.error} />}
          {!d ? <Skeleton className="h-96" /> : (
            <div className={cn("relative space-y-4 transition-opacity", run.isFetching && "opacity-70")}><LoadingEdge active={run.isFetching} className="-top-2" />
              {cal && (cal.ok
                ? <div className="flex items-center gap-2 rounded-xl bg-emerald-50 px-3 py-2 text-xs text-emerald-900 ring-1 ring-inset ring-emerald-200"><Target size={13} />
                    Calibrated to the published example ({anchor?.patent}): {anchor?.yield_pct}% at {anchor?.temp_c} °C, {anchor?.hours} h → main k = {cal.k_ref.toPrecision(3)} at {cal.temp_ref_c} °C. Everything away from that point is prediction.</div>
                : null)}
              {d.notes?.map((n: string, i: number) => <div key={i} className="flex items-start gap-2 rounded-xl bg-amber-50 px-3 py-2 text-xs text-amber-900 ring-1 ring-inset ring-amber-200"><TriangleAlert size={13} className="mt-0.5 shrink-0" />{n}</div>)}

              <div className="grid grid-cols-2 gap-3 md:grid-cols-3 2xl:grid-cols-6">
                <Kpi label="Yield" value={`${s.yield_pct.toFixed(1)}%`} sub={s.peak_yield_pct > s.yield_pct + 0.5 ? `peak ${s.peak_yield_pct.toFixed(1)}% at ${s.peak_yield_h} h` : "at end of batch"} tone="#047857" />
                <Kpi label="Conversion" value={`${s.conversion_pct.toFixed(1)}%`} sub={s.t95_h != null ? `95% by ${s.t95_h} h` : "not 95% in this time"} />
                <Kpi label="Selectivity" value={s.selectivity_pct != null ? `${s.selectivity_pct.toFixed(1)}%` : "—"} sub="product ÷ converted" />
                <Kpi label="Impurity" value={Object.keys(s.impurity_pct).length ? `${Object.values(s.impurity_pct)[0]}%` : "—"} sub={Object.keys(s.impurity_pct)[0] ? `${Object.keys(s.impurity_pct)[0]} · ${SP_ROLE[Object.keys(s.impurity_pct)[0]]}` : "none in this mechanism"} tone={Object.values(s.impurity_pct).some((v: any) => v > (+targets.max_impurity_pct || 1e9)) ? "#be123c" : undefined} />
                <Kpi label="ΔT adiabatic" value={`${s.dt_ad_total_k} K`} sub={`${s.heat_total_kj_l} kJ/L · peak ${s.peak_heat_w_per_l} W/L`} />
                <Kpi label="MTSR" value={`${s.mtsr_c} °C`} sub={s.criticality ? <Badge tone={CRIT_TONE[s.criticality]}>Stoessel class {s.criticality}{s.criticality_partial ? " (partial)" : ""}</Badge> : "add boiling point"} />
              </div>

              <Card><CardHeader title="Concentrations over the batch" subtitle="Dashed = reactants · solid = product and impurities" />
                <div className="px-3 pb-3"><ConcChart res={d.result} /></div></Card>

              <div className="grid gap-4 2xl:grid-cols-[1.25fr_1fr]">
                <Card><CardHeader title={<span className="flex items-center gap-2">Temperature × time map
                    <span className="ml-2 inline-flex rounded-lg bg-slate-100 p-0.5 text-[11px]">{(["yield", "impurity"] as const).map((w) => (
                      <button key={w} disabled={w === "impurity" && !d.map.impurity_pct} onClick={() => setWhichMap(w)} className={cn("rounded-md px-2 py-0.5 font-semibold disabled:opacity-40", whichMap === w ? "bg-white shadow-sm" : "text-ink-muted")}>{w === "yield" ? "Yield" : d.map.impurity ?? "Impurity"}</button>))}</span></span>}
                  subtitle={`Isothermal runs. Best: ${d.map.best.yield_pct.toFixed(1)}% at ${d.map.best.temp_c} °C, ${d.map.best.hours} h`} />
                  <div className="px-4 pb-4">
                    <YieldMap map={d.map} ok={d.acceptable.ok} anchor={anchor} op={{ t: +cond.temp_c, h: +cond.hours }} which={whichMap} />
                    <div className="mt-3 rounded-lg bg-slate-50 p-2.5 text-[11.5px] text-ink-soft">
                      <b>Operating window</b> (yield ≥ {d.acceptable.min_yield_pct}%{d.acceptable.max_impurity_pct != null ? `, ${d.map.impurity ?? "impurity"} ≤ ${d.acceptable.max_impurity_pct}%` : ""}):{" "}
                      {d.acceptable.widest ? <>widest at {d.acceptable.widest.hours} h: <b>{d.acceptable.widest.temp_from_c}–{d.acceptable.widest.temp_to_c} °C</b> · {d.acceptable.share_pct}% of the map meets the targets.</>
                        : <span className="text-rose-700">no temperature and time on the map meets both targets — relax a target or change the mechanism.</span>}
                      <div className="mt-0.5 text-ink-muted">A model-based sketch of a proven acceptable range (ICH Q8): confirm the edges with experiments.</div>
                    </div>
                  </div>
                </Card>
                <Card><CardHeader title="How much the prediction rests on Ea" subtitle={`Yield vs temperature at ${d.ea_band.hours} h, every Ea ± ${d.ea_band.delta_kj} kJ/mol`} />
                  <div className="px-3 pb-3"><EaBand band={d.ea_band} op={+cond.temp_c} />
                    <p className="px-2 text-[11px] text-ink-muted">Where the lines meet (the calibration temperature) the model is pinned by data; the spread elsewhere is what an unknown activation energy costs you. Two published examples at different temperatures would pin Ea.</p></div></Card>
              </div>

              <Card><CardHeader title={<span className="flex items-center gap-2"><Flame size={15} className="text-rose-600" /> Heat and thermal safety</span>} subtitle="Batch mode: everything charged at the start" />
                <div className="px-4 pb-4">
                  <HeatChart res={d.result} />
                  <div className={cn("mt-3 rounded-lg p-2.5 text-[11.5px]", s.criticality >= 4 ? "bg-rose-50 text-rose-900" : s.criticality === 3 ? "bg-amber-50 text-amber-900" : "bg-slate-50 text-ink-soft")}>
                    <b>MTSR {s.mtsr_c} °C</b> (maximum temperature the batch reaches if cooling fails at the worst moment) vs boiling point {cond.bp_c || "—"} °C{cond.td24_c ? ` and TD24 ${cond.td24_c} °C` : ""}: {s.criticality_note}.
                    {s.dt_ad_total_k > 50 && " An adiabatic rise above 50 K usually means dosing one reagent (semi-batch) instead of charging it all at once."}
                  </div>
                </div>
              </Card>

              <Card className="p-4 text-[11.5px] text-ink-soft">
                <div className="label mb-1.5 flex items-center gap-1.5"><Info size={12} /> Assumptions</div>
                <ul className="space-y-0.5">{d.assumptions.map((a: string, i: number) => <li key={i}>● {a}</li>)}</ul>
                {d.cross_check && <div className="mt-2 text-emerald-800">PharmaPy and the built-in solver agree on this run to {d.cross_check.max_yield_diff_pct} percentage points of yield.</div>}
              </Card>
            </div>
          )}
          <Validation />
          <p className="text-[11px] text-ink-faint">Coming next in the lab: stability and shelf-life (Arrhenius and humidity, ICH zone IVb) for formulation pharmacists, then dosing and compounding calculators.</p>
        </div>
      </div>
    </div>
  );
}
