import { keepPreviousData, useQuery, useQueryClient } from "@tanstack/react-query";
import { Atom, Beaker, ExternalLink, Info } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { CartesianGrid, Line, LineChart, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { Badge, Button, Card, CardHeader, ErrorNote, Segmented, Skeleton } from "../../components/ui";
import { useToast } from "../../components/ui/toast";
import { api, post } from "../../lib/api";
import { cn } from "../../lib/cn";

// Every number on this page carries where it came from:
//   source     a cited record (PubChem, CDSCO NSQ list, FAERS), linked
//   estimate   a named published method, with its stated uncertainty
//   assumed    a default the user can (and should) replace
//   user       a value the user typed
type Kind = "source" | "estimate" | "assumption" | "assumed" | "user" | null | undefined;
type Tab = "molecule" | "dissolution" | "be" | "safety" | "crystal" | "compaction" | "fluidbed";
const tip = { contentStyle: { borderRadius: 10, fontSize: 12 } };

function useDebounced<T>(v: T, ms = 300) {
  const [d, setD] = useState(v);
  useEffect(() => { const t = setTimeout(() => setD(v), ms); return () => clearTimeout(t); }, [v, ms]);
  return d;
}

function Pill({ kind, label, url }: { kind: Kind; label?: string | null; url?: string | null }) {
  if (!kind) return null;
  const base = "inline-flex items-center gap-0.5 rounded px-1 text-[10px] font-semibold uppercase leading-4";
  if (kind === "source") {
    const body = <span className={cn(base, "bg-brand-50 text-brand-700")} title={label ?? undefined}>source{url && <ExternalLink size={9} />}</span>;
    return url ? <a href={url} target="_blank" rel="noreferrer">{body}</a> : body;
  }
  if (kind === "estimate") return <span className={cn(base, "bg-sky-50 text-sky-700")} title={label ?? undefined}>estimate</span>;
  if (kind === "user") return <span className={cn(base, "bg-indigo-50 text-indigo-700")}>entered</span>;
  return <span className={cn(base, "bg-slate-100 text-ink-muted")} title={label ?? "Default value: replace it with your own"}>assumed</span>;
}

function Num({ label, value, onChange, step = 1, min, max, unit, hint, kind, dflt }: { label: string; value: number | null; onChange: (v: number | null) => void; step?: number; min?: number; max?: number; unit?: string; hint?: string; kind?: Kind; dflt?: number }) {
  // A default the user hasn't touched is "assumed"
  const k: Kind = kind ?? (dflt != null ? (value === dflt ? "assumption" : "user") : undefined);
  return (
    <label className="block text-xs" title={hint}>
      <div className="mb-1 flex items-center justify-between gap-2"><span className="flex items-center gap-1 font-medium text-ink-soft">{label}<Pill kind={k} /></span><span className="tabular-nums text-ink">{value ?? "—"}{unit && value != null ? ` ${unit}` : ""}</span></div>
      {min != null && max != null
        ? <input type="range" min={min} max={max} step={step} value={value ?? min} onChange={(e) => onChange(Number(e.target.value))} className="w-full accent-brand-600" />
        : <input type="number" step={step} value={value ?? ""} placeholder="enter" onChange={(e) => onChange(e.target.value === "" ? null : Number(e.target.value))} className="input h-8 w-full text-xs" />}
    </label>
  );
}

function Assumptions({ items, note }: { items?: (string | null | undefined)[]; note?: string | null }) {
  const list = (items ?? []).filter(Boolean) as string[];
  if (!list.length && !note) return null;
  return (
    <div className="space-y-1 border-t border-line px-5 py-3 text-[11px] text-ink-muted">
      {note && <div className="font-medium text-amber-700">{note}</div>}
      {list.map((a) => <div key={a} className="flex gap-1.5"><Info size={11} className="mt-0.5 shrink-0" />{a}</div>)}
    </div>
  );
}

function Kv({ k, v, sub, kind, label, url, muted }: { k: string; v: React.ReactNode; sub?: React.ReactNode; kind?: Kind; label?: string | null; url?: string | null; muted?: boolean }) {
  return (
    <div className={cn("rounded-xl bg-slate-50 p-3", muted && "opacity-60")}>
      <div className="flex items-center justify-between gap-2"><span className="label">{k}</span><Pill kind={kind} label={label} url={url} /></div>
      <div className="mt-1 font-display text-lg font-bold">{v}</div>
      {sub && <div className="text-[10.5px] text-ink-muted">{sub}</div>}
    </div>
  );
}

const fmt = (x: number | null | undefined, sig = 2) => (x == null ? "—" : Math.abs(x) >= 1e4 || (Math.abs(x) < 1e-3 && x !== 0) ? x.toExponential(sig - 1) : String(Number(x.toPrecision(sig))));

function MoleculeTab({ p }: { p: any }) {
  const d = p.descriptors, s = p.solubility, pv = p.provenance, t = p.thermal;
  const exp = p.experimental ?? {};
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
            <Kv k="log P" v={s.logp} sub={s.logp_source} kind={pv.log_p.kind} label={pv.log_p.label} url={pv.log_p.url} />
            <Kv k="TPSA" v={`${d.tpsa} Å²`} sub={`${d.hbd} donors · ${d.hba} acceptors (RDKit)`} kind="estimate" label="computed from structure (RDKit)" />
            <Kv k="Aqueous solubility, 25 °C" kind={pv.aqueous_solubility.kind} label={pv.aqueous_solubility.label} url={pv.aqueous_solubility.url}
              v={s.in_domain === false ? "out of domain" : `${s.kind === "source" ? "" : "~"}${fmt(s.display_mg_ml, s.kind === "source" ? 2 : 1)} mg/mL`}
              sub={s.kind === "source" ? <span title={s.text}>{s.model}</span> : <>{s.model} · {s.uncertainty}</>} />
            <Kv k="Provisional BCS" v={p.bcs.class ?? "—"} kind={p.bcs.class ? "estimate" : null} label={p.bcs.basis}
              sub={p.bcs.class ? `structure-only guess · dose number ${fmt(p.bcs.dose_number)}` : "not classified"} />
            <Kv k="Melting point" v={t.mp_c != null ? `${t.mp_c} °C` : "unknown"} sub={t.mp_source ?? "no experimental or curated value"} kind={pv.melting_point.kind} label={pv.melting_point.label} url={pv.melting_point.url} />
            <Kv k="Enthalpy of fusion" v={t.dh_fus ? `${(t.dh_fus / 1000).toFixed(0)} kJ/mol` : "—"} sub={t.dh_source ?? ""} kind={pv.enthalpy_of_fusion.kind} label={pv.enthalpy_of_fusion.label} />
            <Kv k="Diffusivity, 37 °C" v={`${Number(p.derived.diffusivity_cm2_s).toExponential(1)} cm²/s`} sub={p.derived.diffusivity_note} kind="estimate" label={p.derived.diffusivity_note} />
            <Kv k="pKa" v={pv.pka.value ?? "unknown"} sub={pv.pka.label} kind={pv.pka.kind} label={pv.pka.text ?? pv.pka.label} url={pv.pka.url} />
          </div>
          {(s.flags?.length > 0) && <Card className="space-y-1 p-3 text-xs text-amber-800">{s.flags.map((f: string) => <div key={f} className="flex gap-1.5"><Info size={12} className="mt-0.5 shrink-0" />Solubility: {f}</div>)}</Card>}
          <Card className="p-4 text-xs">
            <div className="flex items-center justify-between"><div className="label mb-2">NSQ record for this molecule</div><Pill kind="source" label="CDSCO Not of Standard Quality alerts" /></div>
            <div className="flex flex-wrap gap-4"><span><b className="text-base">{p.nsq.alerts}</b> alerts</span><span><b className="text-base">{p.nsq.dissolution_pct}%</b> dissolution failures</span>{p.nsq.max_strength_mg && <span>highest tablet/capsule strength seen <b>{p.nsq.max_strength_mg} mg</b></span>}</div>
            <div className="mt-2 flex flex-wrap gap-1.5">{p.nsq.categories.map((c: any) => <Badge key={c.name}>{c.name} · {c.count}</Badge>)}</div>
            <p className="mt-2 text-ink-muted">{p.bcs.reason}</p>
            <p className="mt-1 text-ink-muted">Drug-likeness: {d.lipinski_violations === 0 ? "no Lipinski flags" : `${d.lipinski_violations} Lipinski flags`} (with the log P above) · {d.rotatable_bonds} rotatable bonds · Fsp3 {d.fraction_csp3}</p>
          </Card>
        </div>
      </div>
      {(exp.solubility_texts?.length > 0 || exp.pka?.length > 0) && (
        <Card className="p-4 text-[11px] text-ink-muted">
          <div className="label mb-1">Published statements (PubChem, as cited)</div>
          {[...(exp.solubility_texts ?? []), ...(exp.pka ?? [])].map((e: any, i: number) => (
            <div key={i} className="flex gap-1.5"><span className="text-ink-soft">“{e.text}”</span>{e.url ? <a href={e.url} target="_blank" rel="noreferrer" className="text-brand-700 underline">{e.source ?? "source"}</a> : <span>{e.source}</span>}</div>
          ))}
        </Card>
      )}
      <Card className="p-4 text-[11px] text-ink-muted"><div className="label mb-1">Where each value comes from</div>
        {Object.entries(p.provenance).map(([k, v]: any) => (
          <div key={k} className="flex flex-wrap items-center gap-1.5"><b className="text-ink-soft">{k.replace(/_/g, " ")}:</b><Pill kind={v.kind} url={v.url} label={v.label} />{v.label}{v.url && <a href={v.url} target="_blank" rel="noreferrer" className="text-brand-700 underline">link</a>}</div>
        ))}
      </Card>
    </div>
  );
}

function VerdictBadge({ verdict }: { verdict: string }) {
  if (verdict === "withheld") return <Badge tone="slate">verdict withheld</Badge>;
  return <Badge tone={verdict === "pass" ? "brand" : "rose"}>model: {verdict}</Badge>;
}

// Ionisation: "auto" lets the server use a sourced pKa; picking acid/base needs a typed pKa (never invented).
type Ion = "auto" | "none" | "acid" | "base";

function IonControls({ f, set, p }: { f: any; set: (k: string) => (v: any) => void; p: any }) {
  const pk = p.derived.pka;
  return (
    <>
      <div className="text-xs"><div className="mb-1 flex items-center gap-1 font-medium text-ink-soft">Ionisation {f.ionization === "auto" && pk?.kind && <Pill kind={pk.kind} url={pk.url} label={pk.source} />}</div>
        <Segmented value={f.ionization} onChange={set("ionization")} options={[{ value: "auto", label: "From data" }, { value: "none", label: "Neutral" }, { value: "acid", label: "Weak acid" }, { value: "base", label: "Weak base" }]} />
        {f.ionization === "auto" && <div className="mt-1 text-[10.5px] text-ink-muted">{p.derived.pka_acid != null ? `acid pKa ${p.derived.pka_acid} (${pk.source})` : p.derived.pka_base != null ? `base pKa ${p.derived.pka_base} (${pk.source})` : p.derived.ionisable?.length ? "ionisable, but no published pKa: choose acid/base and enter it" : "no ionisable group found: neutral"}</div>}
      </div>
      {(f.ionization === "acid" || f.ionization === "base") && <Num label="pKa" value={f.pka} step={0.1} onChange={set("pka")} kind={f.pka == null ? undefined : "user"} hint="Required: enter the literature pKa" />}
      {f.ionization !== "none" && <Num label="Medium pH" value={f.ph} min={1} max={8} step={0.1} onChange={set("ph")} dflt={6.8} />}
    </>
  );
}

function Dissolution({ mkey, p }: { mkey: string; p: any }) {
  const dose0 = p.derived.dose_mg ?? null;
  const init = { dose_mg: dose0 as number | null, d50_um: 20, gsd: 1.8, lag_min: 2, volume_ml: 900, q_pct: 75, q_time_min: 45, ph: 6.8, ionization: "auto" as Ion, pka: null as number | null };
  const [f, setF] = useState(init);
  useEffect(() => setF(init), [mkey]); // eslint-disable-line
  const df = useDebounced(f);
  const q = useQuery({ queryKey: ["lab-diss", mkey, df], queryFn: () => post<any>(`/api/lab/molecule/${mkey}/dissolution`, df), placeholderData: keepPreviousData, retry: false });
  const r = q.data;
  const set = (k: string) => (v: any) => setF({ ...f, [k]: v });
  return (
    <Card>
      <CardHeader title="Dissolution in a USP vessel" subtitle="Noyes-Whitney with a Hintz-Johnson diffusion layer over a log-normal particle size distribution" />
      <div className="grid gap-5 p-5 xl:grid-cols-[300px_1fr]">
        <div className="space-y-3">
          <Num label="Dose" unit="mg" value={f.dose_mg} onChange={set("dose_mg")} step={5} kind={f.dose_mg == null ? undefined : f.dose_mg === dose0 ? "source" : "user"} hint={p.provenance.dose.label} />
          <Num label="Particle d50" unit="µm" value={f.d50_um} min={1} max={200} onChange={set("d50_um")} dflt={20} />
          <Num label="Size spread (GSD)" value={f.gsd} min={1.1} max={3} step={0.1} onChange={set("gsd")} dflt={1.8} />
          <Num label="Disintegration lag" unit="min" value={f.lag_min} min={0} max={20} step={0.5} onChange={set("lag_min")} dflt={2} />
          <Num label="Medium volume" unit="mL" value={f.volume_ml} min={250} max={1000} step={50} onChange={set("volume_ml")} dflt={900} />
          <IonControls f={f} set={set} p={p} />
          <div className="text-[10.5px] text-ink-muted">Generic Q: enter the monograph's</div>
          <div className="grid grid-cols-2 gap-2"><Num label="Q" unit="%" value={f.q_pct} onChange={set("q_pct")} dflt={75} /><Num label="at" unit="min" value={f.q_time_min} onChange={set("q_time_min")} dflt={45} /></div>
        </div>
        <div>
          {q.error ? <ErrorNote error={q.error} /> : !r ? <Skeleton className="h-72" /> : (
            <>
              <div className="mb-1 flex flex-wrap items-center gap-2 text-sm"><VerdictBadge verdict={r.verdict} /><b>{r.at_q}%</b> dissolved at {r.spec.q_time_min} min (Q {r.spec.q_pct}%)<span className="text-ink-muted">· t85 {r.t85 ?? "not reached"} min · sink index {r.sink_index}</span></div>
              <div className="mb-3 flex flex-wrap items-center gap-2 text-[11px] text-ink-muted">
                <span>{r.verdict_basis}</span>
                <span className="flex items-center gap-1">· solubility {fmt(r.inputs.solubility_mg_ml.value)} mg/mL at medium pH <Pill kind={r.inputs.solubility_mg_ml.kind} url={r.inputs.solubility_mg_ml.url} label={r.inputs.solubility_mg_ml.label} /></span>
                {r.inputs.pka.value != null && <span className="flex items-center gap-1">· pKa {r.inputs.pka.value} <Pill kind={r.inputs.pka.kind} url={r.inputs.pka.url} label={r.inputs.pka.label} /></span>}
              </div>
              <ResponsiveContainer width="100%" height={280}>
                <LineChart data={r.times_min.map((t: number, i: number) => ({ t, pct: r.pct[i] }))}><CartesianGrid stroke="#eef2f7" /><XAxis dataKey="t" type="number" fontSize={11} unit=" min" /><YAxis domain={[0, 100]} fontSize={11} unit="%" /><Tooltip {...tip} />
                  <ReferenceLine y={r.spec.q_pct} stroke="#e11d48" strokeDasharray="4 3" /><ReferenceLine x={r.spec.q_time_min} stroke="#e11d48" strokeDasharray="4 3" /><Line dataKey="pct" stroke="#0a9a7d" strokeWidth={2} dot={false} name="% dissolved (model)" /></LineChart>
              </ResponsiveContainer>
              {r.why.map((w: string) => <p key={w} className={cn("mt-2 text-xs", r.verdict === "withheld" ? "text-amber-800" : "text-rose-700")}>{w}</p>)}
            </>
          )}
        </div>
      </div>
      <Assumptions items={r?.assumptions} />
    </Card>
  );
}

const BE_TONE: Record<string, { tone: any; box: string; label: string }> = {
  inside: { tone: "slate", box: "bg-slate-50 ring-slate-200", label: "point estimates inside 80–125%" },
  outside: { tone: "rose", box: "bg-rose-50 ring-rose-200", label: "point estimate outside 80–125%" },
  not_assessable: { tone: "slate", box: "bg-slate-50 ring-slate-200", label: "not assessable" },
  withheld: { tone: "slate", box: "bg-amber-50 ring-amber-200", label: "verdict withheld" },
};

function Bioequivalence({ mkey, p }: { mkey: string; p: any }) {
  const dose0 = p.derived.dose_mg ?? null;
  const init = { dose_mg: dose0 as number | null, d50_um: 60, lag_min: 5, ref_d50_um: 5, cl_l_h: 10, v_l: 50, ka_h: 1, f_abs: 1, window_h: 4, in_vivo_scale: 1, ph: 6.8, ionization: "auto" as Ion, pka: null as number | null };
  const [f, setF] = useState(init);
  useEffect(() => setF(init), [mkey]); // eslint-disable-line
  const df = useDebounced(f, 400);
  const q = useQuery({ queryKey: ["lab-be", mkey, df], queryFn: () => post<any>(`/api/lab/molecule/${mkey}/bioequivalence`, df), placeholderData: keepPreviousData, retry: false });
  const r = q.data;
  const set = (k: string) => (v: any) => setF({ ...f, [k]: v });
  const t = BE_TONE[r?.compare.risk] ?? BE_TONE.not_assessable;
  const pkAssumed = (r?.pk_assumed?.length ?? 0) > 0;
  const conc = r ? r.test.pk.t_h.map((x: number, i: number) => ({ t: x, test: r.test.pk.conc_mg_l[i], ref: r.reference.pk.conc_mg_l[i] })) : [];
  const diss = r ? r.test.dissolution.times_min.map((x: number, i: number) => ({ t: x, test: r.test.dissolution.pct[i], ref: r.reference.dissolution.pct[Math.min(i, r.reference.dissolution.pct.length - 1)] })) : [];
  const pct = (x: number | null) => (x == null ? "—" : `${x}%`);
  return (
    <Card>
      <CardHeader title="Dissolution → plasma exposure → bioequivalence what-if" subtitle="The test dissolution profile and a fast-dissolving reference (same molecule, fine particles), each pushed through a one-compartment oral PK model" />
      <div className="grid gap-5 p-5 xl:grid-cols-[300px_1fr]">
        <div className="space-y-3">
          <div className="label">Test product</div>
          <Num label="Dose" unit="mg" value={f.dose_mg} onChange={set("dose_mg")} step={5} kind={f.dose_mg == null ? undefined : f.dose_mg === dose0 ? "source" : "user"} hint={p.provenance.dose.label} />
          <Num label="Particle d50" unit="µm" value={f.d50_um} min={1} max={250} onChange={set("d50_um")} dflt={60} />
          <Num label="Disintegration lag" unit="min" value={f.lag_min} min={0} max={60} onChange={set("lag_min")} dflt={5} />
          <Num label="Reference d50" unit="µm" value={f.ref_d50_um} min={1} max={50} onChange={set("ref_d50_um")} dflt={5} />
          <IonControls f={f} set={set} p={p} />
          <div className="label pt-2">Pharmacokinetics (enter literature values)</div>
          <div className="grid grid-cols-2 gap-2">
            <Num label="Clearance" unit="L/h" value={f.cl_l_h} step={0.5} onChange={set("cl_l_h")} dflt={10} />
            <Num label="Volume" unit="L" value={f.v_l} step={5} onChange={set("v_l")} dflt={50} />
            <Num label="ka" unit="1/h" value={f.ka_h} step={0.1} onChange={set("ka_h")} dflt={1} />
            <Num label="F (fraction)" value={f.f_abs} step={0.05} onChange={set("f_abs")} dflt={1} />
          </div>
          <Num label="Absorption window" unit="h" value={f.window_h} min={1} max={12} step={0.5} onChange={set("window_h")} dflt={4} hint="Small-intestine transit; drug dissolving after this is not absorbed" />
        </div>
        <div>
          {q.error ? <ErrorNote error={q.error} /> : !r ? <Skeleton className="h-72" /> : (
            <>
              <div className={cn("mb-3 rounded-xl p-3 text-sm ring-1 ring-inset", t.box)}>
                <Badge tone={t.tone}>{t.label}</Badge> <span className="ml-1">{r.compare.message}</span></div>
              <div className="mb-3 grid grid-cols-2 gap-3 md:grid-cols-4">
                <Kv k="Cmax ratio" v={pct(r.compare.cmax_ratio)} sub="test / reference; limits apply to the 90% CI" />
                <Kv k="AUC ratio" v={pct(r.compare.auc_ratio)} sub="test / reference; limits apply to the 90% CI" />
                <Kv k="Tmax" v={`${r.test.pk.tmax_h} h`} sub={pkAssumed ? "from assumed PK (CL, V, ka): enter literature values" : `reference ${r.reference.pk.tmax_h} h`} kind={pkAssumed ? "assumption" : "user"} muted={pkAssumed} />
                <Kv k="Absorbed" v={`${r.test.pk.absorbed_pct}%`} sub={pkAssumed ? `reference ${r.reference.pk.absorbed_pct}% · t½ ${r.test.pk.half_life_h} h from assumed CL/V` : `reference ${r.reference.pk.absorbed_pct}% · t½ ${r.test.pk.half_life_h} h`} kind={pkAssumed ? "assumption" : "user"} muted={pkAssumed} />
              </div>
              <div className="grid gap-4 lg:grid-cols-2">
                <div><div className="label mb-1">Plasma concentration (mg/L){pkAssumed && <span className="ml-1 normal-case text-ink-muted">· assumed PK</span>}</div>
                  <ResponsiveContainer width="100%" height={220}><LineChart data={conc}><CartesianGrid stroke="#eef2f7" /><XAxis dataKey="t" type="number" unit=" h" fontSize={11} /><YAxis fontSize={11} width={44} /><Tooltip {...tip} />
                    <Line dataKey="ref" name="reference" stroke="#94a3b8" strokeDasharray="4 3" dot={false} /><Line dataKey="test" name="test" stroke="#0a9a7d" strokeWidth={2} dot={false} /></LineChart></ResponsiveContainer></div>
                <div><div className="label mb-1">Dissolution (%)</div>
                  <ResponsiveContainer width="100%" height={220}><LineChart data={diss}><CartesianGrid stroke="#eef2f7" /><XAxis dataKey="t" type="number" unit=" min" fontSize={11} /><YAxis domain={[0, 100]} fontSize={11} width={36} /><Tooltip {...tip} />
                    <Line dataKey="ref" name="reference" stroke="#94a3b8" strokeDasharray="4 3" dot={false} /><Line dataKey="test" name="test" stroke="#6366f1" strokeWidth={2} dot={false} /></LineChart></ResponsiveContainer></div>
              </div>
            </>
          )}
        </div>
      </div>
      <Assumptions items={r?.assumptions} />
    </Card>
  );
}

function Safety({ mkey }: { mkey: string }) {
  const q = useQuery({ queryKey: ["lab-safety", mkey], queryFn: () => api<any>(`/api/lab/molecule/${mkey}/safety`), retry: false, staleTime: 3600_000 });
  const r = q.data;
  if (q.error) return <ErrorNote error={q.error} />;
  if (!r) return <Skeleton className="h-72" />;
  if (!r.found) return <Card className="p-6 text-sm text-ink-muted">{r.note} (searched FAERS for “{r.query_name}” as a suspect drug)</Card>;
  return (
    <Card>
      <CardHeader title="Adverse-event signals (FDA FAERS)" subtitle={r.method} action={<Pill kind="source" url={r.source_url} label={r.source} />} />
      <div className="grid grid-cols-2 gap-3 p-5 md:grid-cols-4">
        <Kv k="Reports" v={r.reports.toLocaleString("en-IN")} sub={`as suspect drug, of ${r.all_reports.toLocaleString("en-IN")} in FAERS`} />
        <Kv k="Serious" v={`${r.serious_pct}%`} sub={`${r.serious.toLocaleString("en-IN")} reports`} />
        <Kv k="Signals" v={r.signals} sub={`of the ${r.reactions.length} most-reported reactions`} />
        <Kv k="Death reported" v={r.fatal.toLocaleString("en-IN")} sub="reports flagged seriousnessdeath" />
      </div>
      <div className="grid gap-5 px-5 pb-5 xl:grid-cols-[1.5fr_1fr]">
        <div className="max-h-[420px] overflow-auto scrollbar-thin">
          <table className="w-full text-xs"><thead><tr className="border-b border-line text-left text-[10.5px] uppercase tracking-wider text-ink-muted"><th className="py-2">Reaction</th><th className="text-right">Reports</th><th className="text-right">PRR</th><th className="text-right">ROR (95% CI)</th><th className="text-right">χ²</th><th /></tr></thead>
            <tbody>{r.reactions.map((x: any) => (
              <tr key={x.reaction} className="border-b border-line/60"><td className="py-1.5 font-medium">{x.reaction}</td><td className="text-right tabular-nums">{x.reports}</td><td className="text-right tabular-nums">{x.prr ?? "—"}</td>
                <td className="text-right tabular-nums">{x.ror != null ? `${x.ror} (${x.ror_low}–${x.ror_high})` : "—"}</td><td className="text-right tabular-nums">{x.chi2 ?? "—"}</td>
                <td className="pl-2">{x.signal && <Badge tone="rose">signal</Badge>}</td></tr>
            ))}</tbody></table>
        </div>
        <div><div className="label mb-2">Manufacturers named in reports</div>
          <div className="space-y-1">{r.manufacturers.map((m: any) => <div key={m.name} className="flex justify-between gap-3 text-xs"><span className="truncate">{m.name}</span><span className="tabular-nums text-ink-muted">{m.count}</span></div>)}</div>
        </div>
      </div>
      <Assumptions items={[r.caveat, `openFDA query sent: ${r.query}`, `Searched FAERS for “${r.query_name}” (US name for ${r.local_name}); results cached for 24 h.`]} />
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
  const ill = r?.kinetics_illustrative;
  const series = r ? r.time_min.map((t: number, i: number) => ({ t, c: r.conc_kg_m3[i], s: r.sat_kg_m3[i], T: r.temp_c[i] })) : [];
  return (
    <Card>
      <CardHeader title="Cooling crystallisation" subtitle="Solubility curve from the melting point and enthalpy of fusion; population balance in PharmaPy (sim service) or the built-in moments model"
        action={<Badge tone={pp?.available ? "brand" : "amber"}>{pp?.available ? `PharmaPy ${pp.version ?? ""} online` : "PharmaPy offline: built-in engine"}</Badge>} />
      <div className="grid gap-5 p-5 xl:grid-cols-[300px_1fr]">
        <div className="space-y-3">
          <div className="text-xs"><div className="mb-1 font-medium text-ink-soft">Solvent</div><select className="input h-8 w-full text-xs" value={f.solvent} onChange={(e) => set("solvent")(e.target.value)}>{solvents.map((s) => <option key={s}>{s}</option>)}</select></div>
          {f.solvent !== "water" && <Num label="Activity coefficient γ" value={f.gamma} min={0.1} max={10} step={0.1} onChange={set("gamma")} dflt={1} hint="1 = ideal solution (solvent not modelled); enter a fitted or measured value for this solvent" />}
          <Num label="Start temperature" unit="°C" value={f.t0_c} min={10} max={85} onChange={set("t0_c")} dflt={50} hint="Must be below the solvent's boiling point" />
          <Num label="End temperature" unit="°C" value={f.t1_c} min={-10} max={40} onChange={set("t1_c")} dflt={5} />
          <Num label="Cooling time" unit="min" value={f.cool_min} min={10} max={600} step={10} onChange={set("cool_min")} dflt={120} />
          <Num label="Hold" unit="min" value={f.hold_min} min={0} max={240} step={10} onChange={set("hold_min")} dflt={30} />
          <Num label="Seed loading (built-in engine only)" unit="%" value={f.seed_pct} min={0} max={10} step={0.5} onChange={set("seed_pct")} dflt={0} hint="PharmaPy runs unseeded; with seeds, Auto uses the built-in engine" />
          <div className="text-xs"><div className="mb-1 font-medium text-ink-soft">Engine</div><Segmented value={f.engine} onChange={set("engine")} options={[{ value: "auto", label: "Auto" }, { value: "pharmapy", label: "PharmaPy" }, { value: "builtin", label: "Built-in" }]} /></div>
        </div>
        <div>
          {q.error ? <ErrorNote error={q.error} /> : !r ? <Skeleton className="h-72" /> : (
            <>
              {r.curve?.ideal && <div className="mb-3 rounded-xl bg-amber-50 p-3 text-xs text-amber-800 ring-1 ring-inset ring-amber-200">Ideal solubility (γ = 1): the solvent choice is not modelled, so results are nearly the same in every organic solvent. Enter γ for solvent-specific results.</div>}
              <div className="mb-3 grid grid-cols-2 gap-3 md:grid-cols-5">
                <Kv k="Engine" v={r.engine === "pharmapy" ? "PharmaPy" : "Built-in"} />
                <Kv k="Yield" v={`${r.summary.yield_pct}%`} sub={`max ${r.summary.max_yield_pct}% from the solubility curve`} kind="estimate" label={r.curve.model} />
                <Kv k="Size L4,3" v={`${r.summary.l43_um} µm`} sub={ill ? "illustrative (generic PharmaPy example kinetics)" : `mean ${r.summary.mean_um} µm`} kind={ill ? "assumption" : "user"} muted={ill} />
                <Kv k="Spread (CV)" v={r.summary.cv ?? "—"} sub={ill ? "illustrative kinetics" : undefined} kind={ill ? "assumption" : "user"} muted={ill} />
                <Kv k="Peak supersaturation" v={r.summary.peak_supersat} sub={ill ? "illustrative kinetics · (c − c*)/c*" : "(c − c*)/c*"} kind={ill ? "assumption" : "user"} muted={ill} />
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

function Compaction({ materials, note }: { materials: Record<string, any>; note?: string }) {
  const [mat, setMat] = useState("plastic");
  const [f, setF] = useState({ ...materials.plastic, d0: 0.4 });
  useEffect(() => setF((x: any) => ({ ...x, ...materials[mat] })), [mat, materials]);
  const df = useDebounced(f);
  const q = useQuery({ queryKey: ["lab-comp", df], queryFn: () => post<any>("/api/lab/compaction", df), placeholderData: keepPreviousData });
  const r = q.data;
  const set = (k: string) => (v: any) => setF({ ...f, [k]: v });
  const m = materials[mat];
  return (
    <Card>
      <CardHeader title="Tablet compaction (generic blend, not molecule-specific)" subtitle="Heckel porosity–pressure and Ryshkewitch-Duckworth strength–porosity" />
      <div className="grid gap-5 p-5 xl:grid-cols-[300px_1fr]">
        <div className="space-y-3">
          <div className="text-xs"><div className="mb-1 flex items-center gap-1 font-medium text-ink-soft">Material preset <Pill kind="assumption" label={note} /></div>
            <select className="input h-8 w-full text-xs" value={mat} onChange={(e) => setMat(e.target.value)}>{Object.entries(materials).map(([k, v]: any) => <option key={k} value={k}>{v.label}</option>)}</select></div>
          <Num label="Yield pressure Py" unit="MPa" value={f.py_mpa} min={30} max={600} step={5} onChange={set("py_mpa")} dflt={m?.py_mpa} />
          <Num label="σ0 (zero-porosity strength)" unit="MPa" value={f.sigma0_mpa} min={2} max={30} step={0.5} onChange={set("sigma0_mpa")} dflt={m?.sigma0_mpa} />
          <Num label="b" value={f.b} min={2} max={15} step={0.5} onChange={set("b")} dflt={m?.b} />
          <Num label="Initial relative density" value={f.d0} min={0.2} max={0.7} step={0.01} onChange={set("d0")} dflt={0.4} />
        </div>
        <div>
          {!r ? <Skeleton className="h-72" /> : (
            <>
              <div className="mb-3 text-sm">{r.p_for_target != null ? <>Reaches <b>{r.target_mpa} MPa</b> at <b>{r.p_for_target} MPa</b> (solid fraction {r.sf_at_target}) <span className="text-xs text-ink-muted">for the material parameters on the left</span></> : <span className="text-rose-700">Target strength not reached with these material parameters</span>}</div>
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
  const D = { inlet_c: 60, dew_point_c: 10, air_m3_h: 300, spray_g_min: 50, solids_pct: 8, heat_loss_pct: 10 };
  const [f, setF] = useState(D);
  const df = useDebounced(f);
  const q = useQuery({ queryKey: ["lab-fb", df], queryFn: () => post<any>("/api/lab/fluid-bed", df), placeholderData: keepPreviousData, retry: false });
  const r = q.data;
  const set = (k: string) => (v: any) => setF({ ...f, [k]: v });
  const tone = r?.regime === "controlled" ? "brand" : r?.regime === "overwetting" ? "rose" : "amber";
  return (
    <Card>
      <CardHeader title="Fluid-bed granulation: air-side balance (generic, not molecule-specific)" subtitle="Psychrometric mass and energy balance (psychrolib, ASHRAE): outlet temperature, outlet humidity and drying load" />
      <div className="grid gap-5 p-5 xl:grid-cols-[300px_1fr]">
        <div className="space-y-3">
          <Num label="Inlet air" unit="°C" value={f.inlet_c} min={30} max={90} onChange={set("inlet_c")} dflt={D.inlet_c} />
          <Num label="Inlet dew point" unit="°C" value={f.dew_point_c} min={-10} max={25} onChange={set("dew_point_c")} dflt={D.dew_point_c} />
          <Num label="Air flow" unit="m³/h" value={f.air_m3_h} min={50} max={2000} step={10} onChange={set("air_m3_h")} dflt={D.air_m3_h} />
          <Num label="Binder spray" unit="g/min" value={f.spray_g_min} min={5} max={300} step={5} onChange={set("spray_g_min")} dflt={D.spray_g_min} />
          <Num label="Binder solids" unit="%" value={f.solids_pct} min={0} max={30} onChange={set("solids_pct")} dflt={D.solids_pct} />
          <Num label="Heat loss" unit="%" value={f.heat_loss_pct} min={0} max={40} onChange={set("heat_loss_pct")} dflt={D.heat_loss_pct} />
        </div>
        <div>
          {q.error ? <ErrorNote error={q.error} /> : !r ? <Skeleton className="h-60" /> : (
            <>
              <div className={cn("mb-4 rounded-xl p-3 text-sm ring-1 ring-inset", tone === "brand" ? "bg-emerald-50 ring-emerald-200" : tone === "rose" ? "bg-rose-50 ring-rose-200" : "bg-amber-50 ring-amber-200")}><Badge tone={tone as any}>{r.regime} · rule of thumb</Badge> <span className="ml-1">{r.message}</span></div>
              <div className="grid grid-cols-2 gap-3 md:grid-cols-3">
                <Kv k="Outlet air" v={`${r.outlet_c} °C`} sub={`wet bulb ${r.wet_bulb_c} °C after wall losses`} kind="estimate" label="psychrolib (ASHRAE) energy balance" />
                <Kv k="Outlet RH" v={`${r.outlet_rh_pct}%`} sub={`inlet ${r.inlet_rh_pct}%`} kind="estimate" label="psychrolib (ASHRAE)" />
                <Kv k="Drying load" v={`${r.drying_load_pct}%`} sub="share of the air's evaporation capacity" kind="estimate" label="psychrolib (ASHRAE)" />
                <Kv k="Water sprayed" v={`${r.water_g_min} g/min`} />
                <Kv k="Evaporation capacity" v={`${r.evaporation_capacity_g_min} g/min`} sub="after heat loss" kind="estimate" label="psychrolib (ASHRAE)" />
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
  const mols = useMemo(() => [...(list.data?.molecules ?? [])].sort((a: any, b: any) => Number(b.has_structure) - Number(a.has_structure)), [list.data]);
  const withStructure = mols.filter((m: any) => m.has_structure).length;
  useEffect(() => { if (!key && mols.length) setKey(mols[0].key); }, [mols, key]);
  const current = mols.find((m: any) => m.key === key);
  const prof = useQuery({ queryKey: ["lab-mol", key], queryFn: () => api<any>(`/api/lab/molecule/${key}`), enabled: !!key && !!current?.has_structure });
  const qc = useQueryClient();
  const toast = useToast();
  const [fetching, setFetching] = useState(false);
  const fetchStructure = async () => {
    setFetching(true);
    try {
      const r = await post<any>(`/api/lab/molecule/${key}/fetch-structure`);
      toast(`Structure found (${r.source})`);
      await qc.invalidateQueries({ queryKey: ["lab-molecules"] });
      await qc.invalidateQueries({ queryKey: ["lab-mol", key] });
    } catch (e) { toast((e as Error).message, "error"); } finally { setFetching(false); }
  };
  if (list.error) return <ErrorNote error={list.error} />;
  if (!list.data) return <Skeleton className="h-96" />;
  const needsMol = ["molecule", "dissolution", "be", "safety", "crystal"].includes(tab);
  return (
    <div className="space-y-5">
      <Card className="flex flex-wrap items-center gap-3 p-4">
        <Atom size={18} className="text-brand-600" />
        {needsMol
          ? <select className="input h-9 w-72 text-sm" value={key} onChange={(e) => setKey(e.target.value)}>
              {mols.map((m: any) => <option key={m.key} value={m.key}>{m.name}{m.alerts ? ` · ${m.alerts} NSQ alerts` : ""}{m.has_structure ? "" : " · no structure yet"}</option>)}
            </select>
          : <span className="text-xs text-ink-muted">Generic process model: not tied to a molecule</span>}
        <Segmented value={tab} onChange={setTab} options={[{ value: "molecule", label: "Molecule" }, { value: "dissolution", label: "Dissolution" }, { value: "be", label: "Bioequivalence" }, { value: "safety", label: "Safety" }, { value: "crystal", label: "Crystallisation" }, { value: "compaction", label: "Compaction" }, { value: "fluidbed", label: "Fluid bed" }]} />
        <span className="ml-auto flex items-center gap-2 text-[11px] text-ink-muted"><Beaker size={13} />{withStructure} of {mols.length} molecules have structures
          <span className="hidden items-center gap-1 lg:flex"><Pill kind="source" /> cited <Pill kind="estimate" /> published method <Pill kind="assumption" /> replace me</span></span>
      </Card>
      {needsMol && current && !current.has_structure && (
        <Card className="flex flex-wrap items-center gap-4 p-6">
          <div className="min-w-0 flex-1"><div className="font-display text-base font-bold">{current.name} has no chemical structure yet</div>
            <p className="mt-1 text-xs text-ink-muted">Every model here starts from the structure. It is fetched automatically after each universe build and nightly by the PubChem job; you can also fetch it now from PubChem (falling back to ChEMBL).</p></div>
          <Button onClick={fetchStructure} loading={fetching}><Atom size={14} /> Fetch structure now</Button>
        </Card>
      )}
      {needsMol && current?.has_structure && (prof.error ? <ErrorNote error={prof.error} /> : !prof.data ? <Skeleton className="h-96" /> : (
        <>
          {tab === "molecule" && <MoleculeTab p={prof.data} />}
          {tab === "dissolution" && <Dissolution mkey={key} p={prof.data} />}
          {tab === "be" && <Bioequivalence mkey={key} p={prof.data} />}
          {tab === "safety" && <Safety mkey={key} />}
          {tab === "crystal" && <Crystal mkey={key} solvents={list.data.solvents} engines={list.data.engines} />}
        </>
      ))}
      {tab === "compaction" && <Compaction materials={list.data.materials} note={list.data.materials_note} />}
      {tab === "fluidbed" && <FluidBed />}
    </div>
  );
}
