import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { Atom, Beaker, Info } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { CartesianGrid, Line, LineChart, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { Badge, Card, CardHeader, ErrorNote, Segmented, Skeleton } from "../../components/ui";
import { api, post } from "../../lib/api";
import { cn } from "../../lib/cn";
import { ProcessLab } from "./ProcessLab";

type Tab = "molecule" | "dissolution" | "crystal" | "compaction" | "fluidbed" | "legacy";
const tip = { contentStyle: { borderRadius: 10, fontSize: 12 } };

function useDebounced<T>(v: T, ms = 300) {
  const [d, setD] = useState(v);
  useEffect(() => { const t = setTimeout(() => setD(v), ms); return () => clearTimeout(t); }, [v, ms]);
  return d;
}

function Num({ label, value, onChange, step = 1, min, max, unit, hint }: { label: string; value: number; onChange: (v: number) => void; step?: number; min?: number; max?: number; unit?: string; hint?: string }) {
  return (
    <label className="block text-xs" title={hint}>
      <div className="mb-1 flex justify-between"><span className="font-medium text-ink-soft">{label}</span><span className="tabular-nums text-ink">{value}{unit ? ` ${unit}` : ""}</span></div>
      {min != null && max != null
        ? <input type="range" min={min} max={max} step={step} value={value} onChange={(e) => onChange(Number(e.target.value))} className="w-full accent-brand-600" />
        : <input type="number" step={step} value={value} onChange={(e) => onChange(Number(e.target.value))} className="input h-8 w-full text-xs" />}
    </label>
  );
}

function Assumptions({ items, note }: { items?: string[]; note?: string }) {
  if (!items?.length && !note) return null;
  return (
    <div className="space-y-1 border-t border-line px-5 py-3 text-[11px] text-ink-muted">
      {note && <div className="font-medium text-amber-700">{note}</div>}
      {items?.map((a) => <div key={a} className="flex gap-1.5"><Info size={11} className="mt-0.5 shrink-0" />{a}</div>)}
    </div>
  );
}

function Kv({ k, v, sub }: { k: string; v: React.ReactNode; sub?: string }) {
  return <div className="rounded-xl bg-slate-50 p-3"><div className="label">{k}</div><div className="mt-1 font-display text-lg font-bold">{v}</div>{sub && <div className="text-[10.5px] text-ink-muted">{sub}</div>}</div>;
}

function MoleculeTab({ p, list }: { p: any; list: any }) {
  const d = p.descriptors, s = p.solubility;
  return (
    <div className="space-y-5">
      <div className="grid gap-5 xl:grid-cols-[340px_1fr]">
        <Card className="p-4">
          <div className="flex items-start justify-between"><div><div className="font-display text-lg font-bold">{p.name}</div><div className="text-xs text-ink-muted">{d.formula} · {d.mw} g/mol</div></div>
            {p.url ? <a href={p.url} target="_blank" rel="noreferrer"><Badge tone="sky">PubChem CID {p.cid}</Badge></a> : <Badge tone="amber">seed structure</Badge>}</div>
          <div className="mt-2 flex justify-center" dangerouslySetInnerHTML={{ __html: p.svg }} />
          <code className="mt-2 block break-all rounded bg-slate-50 p-2 text-[10px] text-ink-soft">{p.smiles}</code>
        </Card>
        <div className="space-y-4">
          <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
            <Kv k="log P" v={s.logp} sub={s.logp_source} />
            <Kv k="TPSA" v={`${d.tpsa} Å²`} sub={`${d.hbd} donors · ${d.hba} acceptors`} />
            <Kv k="Aqueous solubility, 25 °C" v={`${Number(s.mg_per_ml).toPrecision(2)} mg/mL`} sub={`log S ${s.log_s} · ${s.model}`} />
            <Kv k="Provisional BCS" v={p.bcs.class ?? "—"} sub={p.bcs.class ? `dose number ${Number(p.bcs.dose_number).toPrecision(2)}` : "no strength known"} />
            <Kv k="Melting point" v={p.thermal.mp_c != null ? `${p.thermal.mp_c} °C` : "unknown"} sub={p.thermal.mp_source ?? "run the PubChem job"} />
            <Kv k="Enthalpy of fusion" v={p.thermal.dh_fus ? `${(p.thermal.dh_fus / 1000).toFixed(1)} kJ/mol` : "—"} sub={p.thermal.dh_source ?? ""} />
            <Kv k="Diffusivity, 37 °C" v={`${Number(p.derived.diffusivity_cm2_s).toExponential(2)} cm²/s`} sub="Hayduk-Laudie, McGowan volume" />
            <Kv k="Drug-likeness" v={d.lipinski_violations === 0 ? "Lipinski ✓" : `${d.lipinski_violations} Lipinski flags`} sub={`${d.rotatable_bonds} rotatable bonds · Fsp3 ${d.fraction_csp3}`} />
          </div>
          <Card className="p-4 text-xs">
            <div className="label mb-2">NSQ record for this molecule</div>
            <div className="flex flex-wrap gap-4"><span><b className="text-base">{p.nsq.alerts}</b> alerts</span><span><b className="text-base">{p.nsq.dissolution_pct}%</b> dissolution failures</span>{p.nsq.max_strength_mg && <span>highest strength seen <b>{p.nsq.max_strength_mg} mg</b></span>}</div>
            <div className="mt-2 flex flex-wrap gap-1.5">{p.nsq.categories.map((c: any) => <Badge key={c.name}>{c.name} · {c.count}</Badge>)}</div>
            <p className="mt-2 text-ink-muted">{p.bcs.reason}</p>
          </Card>
        </div>
      </div>
      <Card>
        <CardHeader title="Does structure predict dissolution failures?" subtitle="NSQ dissolution-failure share by computed BCS class, for molecules with a structure and 5+ alerts" />
        <div className="grid gap-3 p-5 md:grid-cols-4">{list.by_bcs.map((c: any) => <Kv key={c.bcs} k={`BCS ${c.bcs}`} v={`${c.dissolution_pct}%`} sub={`${c.molecules} molecules · ${c.alerts} alerts`} />)}</div>
        <Assumptions items={["BCS class computed from structure (solubility model + log P vs metoprolol) and the highest strength in NSQ product names; provisional, not a regulatory classification", "Structures from PubChem where the job has run, otherwise the hand-entered seed; measured log P and melting points sharpen the estimates"]} />
      </Card>
      <Card className="p-4 text-[11px] text-ink-muted"><div className="label mb-1">Where each value comes from</div>{Object.entries(p.provenance).map(([k, v]) => <div key={k}><b className="text-ink-soft">{k.replace(/_/g, " ")}:</b> {String(v)}</div>)}</Card>
    </div>
  );
}

function Dissolution({ mkey, p }: { mkey: string; p: any }) {
  const ion = () => (p.derived.pka_acid != null ? { ionization: "acid", pka: p.derived.pka_acid } : p.derived.pka_base != null ? { ionization: "base", pka: p.derived.pka_base } : { ionization: "none", pka: 4.5 });
  const [f, setF] = useState({ dose_mg: p.derived.dose_mg ?? 100, d50_um: 20, gsd: 1.8, lag_min: 2, volume_ml: 900, q_pct: 75, q_time_min: 45, ph: 6.8, ...ion() });
  useEffect(() => setF((x) => ({ ...x, dose_mg: p.derived.dose_mg ?? 100, ...ion() })), [mkey]); // eslint-disable-line
  const df = useDebounced(f);
  const q = useQuery({ queryKey: ["lab-diss", mkey, df], queryFn: () => post<any>(`/api/lab/molecule/${mkey}/dissolution`, df), placeholderData: keepPreviousData });
  const r = q.data;
  const set = (k: string) => (v: any) => setF({ ...f, [k]: v });
  return (
    <Card>
      <CardHeader title="Dissolution in a USP vessel" subtitle="Noyes-Whitney with a Hintz-Johnson diffusion layer over a particle size distribution, from this molecule's computed solubility and diffusivity" />
      <div className="grid gap-5 p-5 xl:grid-cols-[300px_1fr]">
        <div className="space-y-3">
          <Num label="Dose" unit="mg" value={f.dose_mg} onChange={set("dose_mg")} step={5} />
          <Num label="Particle d50" unit="µm" value={f.d50_um} min={1} max={200} onChange={set("d50_um")} />
          <Num label="Size spread (GSD)" value={f.gsd} min={1.1} max={3} step={0.1} onChange={set("gsd")} />
          <Num label="Disintegration lag" unit="min" value={f.lag_min} min={0} max={20} step={0.5} onChange={set("lag_min")} />
          <Num label="Medium volume" unit="mL" value={f.volume_ml} min={250} max={1000} step={50} onChange={set("volume_ml")} />
          <div className="text-xs"><div className="mb-1 font-medium text-ink-soft">Ionisation</div><Segmented value={f.ionization} onChange={set("ionization")} options={[{ value: "none", label: "Neutral" }, { value: "acid", label: "Weak acid" }, { value: "base", label: "Weak base" }]} /></div>
          {f.ionization !== "none" && <div className="grid grid-cols-2 gap-2"><Num label="pKa" value={f.pka} step={0.1} onChange={set("pka")} /><Num label="Medium pH" value={f.ph} min={1} max={8} step={0.1} onChange={set("ph")} /></div>}
          <div className="grid grid-cols-2 gap-2"><Num label="Q" unit="%" value={f.q_pct} onChange={set("q_pct")} /><Num label="at" unit="min" value={f.q_time_min} onChange={set("q_time_min")} /></div>
        </div>
        <div>
          {q.error ? <ErrorNote error={q.error} /> : !r ? <Skeleton className="h-72" /> : (
            <>
              <div className="mb-3 flex flex-wrap items-center gap-2 text-sm"><Badge tone={r.verdict === "pass" ? "brand" : "rose"}>{r.verdict}</Badge><b>{r.at_q}%</b> dissolved at {r.spec.q_time_min} min (Q {r.spec.q_pct}%)<span className="text-ink-muted">· t85 {r.t85 ?? "not reached"} min · sink index {r.sink_index} · solubility {r.solubility_mg_ml} mg/mL</span></div>
              <ResponsiveContainer width="100%" height={280}>
                <LineChart data={r.times_min.map((t: number, i: number) => ({ t, pct: r.pct[i] }))}><CartesianGrid stroke="#eef2f7" /><XAxis dataKey="t" type="number" fontSize={11} unit=" min" /><YAxis domain={[0, 100]} fontSize={11} unit="%" /><Tooltip {...tip} />
                  <ReferenceLine y={r.spec.q_pct} stroke="#e11d48" strokeDasharray="4 3" /><ReferenceLine x={r.spec.q_time_min} stroke="#e11d48" strokeDasharray="4 3" /><Line dataKey="pct" stroke="#0a9a7d" strokeWidth={2} dot={false} name="% dissolved" /></LineChart>
              </ResponsiveContainer>
              {r.why.map((w: string) => <p key={w} className="mt-2 text-xs text-rose-700">{w}</p>)}
            </>
          )}
        </div>
      </div>
      <Assumptions items={r?.assumptions} />
    </Card>
  );
}

function Crystal({ mkey, solvents, engines }: { mkey: string; solvents: string[]; engines: any }) {
  const [f, setF] = useState({ solvent: "ethanol", gamma: 1, t0_c: 50, t1_c: 5, cool_min: 120, hold_min: 30, seed_pct: 0, seed_um: 50, engine: "auto" });
  const df = useDebounced(f, 500);
  const q = useQuery({ queryKey: ["lab-cryst", mkey, df], queryFn: () => post<any>(`/api/lab/molecule/${mkey}/crystallization`, df), placeholderData: keepPreviousData, retry: false });
  const r = q.data;
  const set = (k: string) => (v: any) => setF({ ...f, [k]: v });
  const pp = engines?.pharmapy;
  const series = r ? r.time_min.map((t: number, i: number) => ({ t, c: r.conc_kg_m3[i], s: r.sat_kg_m3[i], T: r.temp_c[i] })) : [];
  return (
    <Card>
      <CardHeader title="Cooling crystallisation" subtitle="Solubility curve from this molecule's melting point and enthalpy of fusion; population balance in PharmaPy (sim service) or the built-in moments model"
        action={<Badge tone={pp?.available ? "brand" : "amber"}>{pp?.available ? `PharmaPy ${pp.version ?? ""} online` : "PharmaPy offline: built-in engine"}</Badge>} />
      <div className="grid gap-5 p-5 xl:grid-cols-[300px_1fr]">
        <div className="space-y-3">
          <div className="text-xs"><div className="mb-1 font-medium text-ink-soft">Solvent</div><select className="input h-8 w-full text-xs" value={f.solvent} onChange={(e) => set("solvent")(e.target.value)}>{solvents.map((s) => <option key={s}>{s}</option>)}</select></div>
          {f.solvent !== "water" && <Num label="Activity coefficient γ" value={f.gamma} min={0.1} max={10} step={0.1} onChange={set("gamma")} hint="1 = ideal solution; >1 less soluble, <1 more soluble than ideal" />}
          <Num label="Start temperature" unit="°C" value={f.t0_c} min={20} max={78} onChange={set("t0_c")} />
          <Num label="End temperature" unit="°C" value={f.t1_c} min={-5} max={40} onChange={set("t1_c")} />
          <Num label="Cooling time" unit="min" value={f.cool_min} min={10} max={600} step={10} onChange={set("cool_min")} />
          <Num label="Hold" unit="min" value={f.hold_min} min={0} max={240} step={10} onChange={set("hold_min")} />
          <Num label="Seed loading (built-in only)" unit="%" value={f.seed_pct} min={0} max={10} step={0.5} onChange={set("seed_pct")} />
          <div className="text-xs"><div className="mb-1 font-medium text-ink-soft">Engine</div><Segmented value={f.engine} onChange={set("engine")} options={[{ value: "auto", label: "Auto" }, { value: "pharmapy", label: "PharmaPy" }, { value: "builtin", label: "Built-in" }]} /></div>
        </div>
        <div>
          {q.error ? <ErrorNote error={q.error} /> : !r ? <Skeleton className="h-72" /> : (
            <>
              <div className="mb-3 grid grid-cols-2 gap-3 md:grid-cols-5">
                <Kv k="Engine" v={r.engine === "pharmapy" ? "PharmaPy" : "Built-in"} />
                <Kv k="Yield" v={`${r.summary.yield_pct}%`} sub={`max ${r.summary.max_yield_pct}% at end temperature`} />
                <Kv k="Size L4,3" v={`${r.summary.l43_um} µm`} sub={`mean ${r.summary.mean_um} µm`} />
                <Kv k="Spread (CV)" v={r.summary.cv ?? "—"} />
                <Kv k="Peak supersaturation" v={r.summary.peak_supersat} sub="relative, (c − c*)/c*" />
              </div>
              <ResponsiveContainer width="100%" height={260}>
                <LineChart data={series}><CartesianGrid stroke="#eef2f7" /><XAxis dataKey="t" type="number" fontSize={11} unit=" min" /><YAxis yAxisId="c" fontSize={11} width={48} /><YAxis yAxisId="T" orientation="right" fontSize={11} unit="°C" width={44} /><Tooltip {...tip} />
                  <Line yAxisId="c" dataKey="c" name="concentration kg/m³" stroke="#6366f1" dot={false} strokeWidth={2} /><Line yAxisId="c" dataKey="s" name="solubility kg/m³" stroke="#94a3b8" dot={false} strokeDasharray="4 3" /><Line yAxisId="T" dataKey="T" name="temperature" stroke="#f59e0b" dot={false} /></LineChart>
              </ResponsiveContainer>
            </>
          )}
        </div>
      </div>
      <Assumptions items={[...(r?.assumptions ?? []), ...(r ? [`Solubility: ${r.curve.model} in ${r.curve.solvent.name}`] : [])]} note={r?.note} />
    </Card>
  );
}

function Compaction({ materials }: { materials: Record<string, any> }) {
  const [mat, setMat] = useState("plastic");
  const [f, setF] = useState({ ...materials.plastic, d0: 0.4 });
  useEffect(() => setF((x: any) => ({ ...x, ...materials[mat] })), [mat, materials]);
  const df = useDebounced(f);
  const q = useQuery({ queryKey: ["lab-comp", df], queryFn: () => post<any>("/api/lab/compaction", df), placeholderData: keepPreviousData });
  const r = q.data;
  const set = (k: string) => (v: any) => setF({ ...f, [k]: v });
  return (
    <Card>
      <CardHeader title="Tablet compaction" subtitle="Heckel porosity–pressure and Ryshkewitch-Duckworth strength–porosity" />
      <div className="grid gap-5 p-5 xl:grid-cols-[300px_1fr]">
        <div className="space-y-3">
          <select className="input h-8 w-full text-xs" value={mat} onChange={(e) => setMat(e.target.value)}>{Object.entries(materials).map(([k, v]: any) => <option key={k} value={k}>{v.label}</option>)}</select>
          <Num label="Yield pressure Py" unit="MPa" value={f.py_mpa} min={30} max={500} step={5} onChange={set("py_mpa")} />
          <Num label="σ0 (zero-porosity strength)" unit="MPa" value={f.sigma0_mpa} min={2} max={30} step={0.5} onChange={set("sigma0_mpa")} />
          <Num label="b" value={f.b} min={2} max={15} step={0.5} onChange={set("b")} />
          <Num label="Initial relative density" value={f.d0} min={0.2} max={0.7} step={0.01} onChange={set("d0")} />
        </div>
        <div>
          {!r ? <Skeleton className="h-72" /> : (
            <>
              <div className="mb-3 text-sm">{r.p_for_target != null ? <>Reaches <b>{r.target_mpa} MPa</b> at <b>{r.p_for_target} MPa</b> (solid fraction {r.sf_at_target})</> : <span className="text-rose-700">Target strength not reached</span>}</div>
              <ResponsiveContainer width="100%" height={260}>
                <LineChart data={r.pressure_mpa.map((p: number, i: number) => ({ p, ts: r.tensile_mpa[i], sf: r.solid_fraction[i] }))}><CartesianGrid stroke="#eef2f7" /><XAxis dataKey="p" type="number" fontSize={11} unit=" MPa" /><YAxis yAxisId="a" fontSize={11} width={40} /><YAxis yAxisId="b" orientation="right" domain={[0.3, 1]} fontSize={11} width={40} /><Tooltip {...tip} />
                  <ReferenceLine yAxisId="a" y={r.target_mpa} stroke="#e11d48" strokeDasharray="4 3" /><Line yAxisId="a" dataKey="ts" name="tensile MPa" stroke="#0a9a7d" dot={false} strokeWidth={2} /><Line yAxisId="b" dataKey="sf" name="solid fraction" stroke="#6366f1" dot={false} /></LineChart>
              </ResponsiveContainer>
              {r.notes.map((n: string) => <p key={n} className="mt-2 text-xs text-amber-700">{n}</p>)}
            </>
          )}
        </div>
      </div>
      <Assumptions items={r?.assumptions} />
    </Card>
  );
}

function FluidBed() {
  const [f, setF] = useState({ inlet_c: 60, dew_point_c: 10, air_m3_h: 300, spray_g_min: 50, solids_pct: 8, heat_loss_pct: 10 });
  const df = useDebounced(f);
  const q = useQuery({ queryKey: ["lab-fb", df], queryFn: () => post<any>("/api/lab/fluid-bed", df), placeholderData: keepPreviousData, retry: false });
  const r = q.data;
  const set = (k: string) => (v: any) => setF({ ...f, [k]: v });
  const tone = r?.regime === "controlled" ? "brand" : r?.regime === "overwetting" ? "rose" : "amber";
  return (
    <Card>
      <CardHeader title="Fluid-bed granulation: air-side balance" subtitle="Psychrometric mass and energy balance (psychrolib, ASHRAE): outlet temperature, outlet humidity and drying load" />
      <div className="grid gap-5 p-5 xl:grid-cols-[300px_1fr]">
        <div className="space-y-3">
          <Num label="Inlet air" unit="°C" value={f.inlet_c} min={30} max={90} onChange={set("inlet_c")} />
          <Num label="Inlet dew point" unit="°C" value={f.dew_point_c} min={-10} max={25} onChange={set("dew_point_c")} />
          <Num label="Air flow" unit="m³/h" value={f.air_m3_h} min={50} max={2000} step={10} onChange={set("air_m3_h")} />
          <Num label="Binder spray" unit="g/min" value={f.spray_g_min} min={5} max={300} step={5} onChange={set("spray_g_min")} />
          <Num label="Binder solids" unit="%" value={f.solids_pct} min={0} max={30} onChange={set("solids_pct")} />
          <Num label="Heat loss" unit="%" value={f.heat_loss_pct} min={0} max={40} onChange={set("heat_loss_pct")} />
        </div>
        <div>
          {q.error ? <ErrorNote error={q.error} /> : !r ? <Skeleton className="h-60" /> : (
            <>
              <div className={cn("mb-4 rounded-xl p-3 text-sm ring-1 ring-inset", tone === "brand" ? "bg-emerald-50 ring-emerald-200" : tone === "rose" ? "bg-rose-50 ring-rose-200" : "bg-amber-50 ring-amber-200")}><Badge tone={tone as any}>{r.regime}</Badge> <span className="ml-1">{r.message}</span></div>
              <div className="grid grid-cols-2 gap-3 md:grid-cols-3">
                <Kv k="Outlet air" v={`${r.outlet_c} °C`} sub={`wet bulb ${r.wet_bulb_c} °C`} />
                <Kv k="Outlet RH" v={`${r.outlet_rh_pct}%`} sub={`inlet ${r.inlet_rh_pct}%`} />
                <Kv k="Drying load" v={`${r.drying_load_pct}%`} sub="share of the air's evaporation capacity" />
                <Kv k="Water sprayed" v={`${r.water_g_min} g/min`} />
                <Kv k="Evaporation capacity" v={`${r.evaporation_capacity_g_min} g/min`} />
              </div>
            </>
          )}
        </div>
      </div>
      <Assumptions items={r?.assumptions} />
    </Card>
  );
}

export function Lab() {
  const list = useQuery({ queryKey: ["lab-molecules"], queryFn: () => api<any>("/api/lab/molecules"), staleTime: 300_000 });
  const [key, setKey] = useState(() => new URLSearchParams(window.location.search).get("m") ?? "");
  const [tab, setTab] = useState<Tab>("molecule");
  const mols = useMemo(() => (list.data?.molecules ?? []).filter((m: any) => m.has_structure), [list.data]);
  useEffect(() => { if (!key && mols.length) setKey(mols[0].key); }, [mols, key]);
  const prof = useQuery({ queryKey: ["lab-mol", key], queryFn: () => api<any>(`/api/lab/molecule/${key}`), enabled: !!key });
  if (list.error) return <ErrorNote error={list.error} />;
  if (!list.data) return <Skeleton className="h-96" />;
  const needsMol = ["molecule", "dissolution", "crystal"].includes(tab);
  return (
    <div className="space-y-5">
      <Card className="flex flex-wrap items-center gap-3 p-4">
        <Atom size={18} className="text-brand-600" />
        <select className="input h-9 w-72 text-sm" value={key} onChange={(e) => setKey(e.target.value)}>
          {mols.map((m: any) => <option key={m.key} value={m.key}>{m.name}{m.alerts ? ` · ${m.alerts} NSQ alerts` : ""}{m.bcs ? ` · BCS ${m.bcs}` : ""}</option>)}
        </select>
        <Segmented value={tab} onChange={setTab} options={[{ value: "molecule", label: "Molecule" }, { value: "dissolution", label: "Dissolution" }, { value: "crystal", label: "Crystallisation" }, { value: "compaction", label: "Compaction" }, { value: "fluidbed", label: "Fluid bed" }, { value: "legacy", label: "Telmisartan demo (rule-based)" }]} />
        <span className="ml-auto flex items-center gap-1.5 text-[11px] text-ink-muted"><Beaker size={13} />{mols.length} molecules with structures</span>
      </Card>
      {needsMol && (prof.error ? <ErrorNote error={prof.error} /> : !prof.data ? <Skeleton className="h-96" /> : (
        <>
          {tab === "molecule" && <MoleculeTab p={prof.data} list={list.data} />}
          {tab === "dissolution" && <Dissolution mkey={key} p={prof.data} />}
          {tab === "crystal" && <Crystal mkey={key} solvents={list.data.solvents} engines={list.data.engines} />}
        </>
      ))}
      {tab === "compaction" && <Compaction materials={list.data.materials} />}
      {tab === "fluidbed" && <FluidBed />}
      {tab === "legacy" && <><Card className="p-3 text-xs text-amber-800">The original rule-based Telmisartan simulator: thresholds are fixed values from the old prototype, not computed. Kept for comparison.</Card><ProcessLab /></>}
    </div>
  );
}
