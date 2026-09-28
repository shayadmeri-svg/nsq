import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { ExternalLink, Factory, FlaskConical, Gauge, Globe2, Maximize2, ScrollText, ShieldAlert, TrendingUp, Users } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { PolarAngleAxis, RadialBar, RadialBarChart, ResponsiveContainer } from "recharts";
import { RankBars, TrendBars } from "../../components/charts";
import { Badge, Bar, Card, CardHeader, ErrorNote, Segmented, Skeleton } from "../../components/ui";
import { Estimate } from "../../components/ui/Estimate";
import { ExpandedProvider, Figure, Frame, Tile, type Section } from "../../components/ui/Expanded";
import { api } from "../../lib/api";
import { MakersCard, RegistryBadges } from "./Plants";
import { cn } from "../../lib/cn";
import { fmtDate, titleCase } from "../../lib/format";

const PILLARS = [["patent", "Patent readiness", "#10b996"], ["regulatory", "Regulatory clarity", "#6366f1"], ["demand", "Demand", "#f59e0b"], ["plant", "Plant fit", "#e11d48"]] as const;

function Field({ k, v }: { k: string; v: any }) {
  return <div className="grid grid-cols-[140px_1fr] gap-2 py-1 text-xs"><span className="text-ink-muted">{k}</span><span className="font-medium text-ink-soft">{v === "" || v == null ? "—" : v}</span></div>;
}

function Slider({ label, score, share, value, onChange, color }: { label: string; score?: number; share: number; value: number; onChange: (v: number) => void; color: string }) {
  return (
    <label className="block text-xs">
      <div className="flex items-baseline justify-between gap-2">
        <span>{label} <b className="tabular-nums" style={{ color }}>{score ?? "—"}</b><span className="text-ink-faint">/100</span></span>
        <span className="tabular-nums text-ink-muted" title="This pillar's share of the total">weight {share}%</span>
      </div>
      <input type="range" min={0} max={100} value={value} onChange={(e) => onChange(Number(e.target.value))} className="w-full" style={{ accentColor: color }} />
    </label>
  );
}

// ORD writes USPTO numbers zero-padded and, before 2001, without a kind code ("US05545737", "US07425628B2", "USRE039221E1");
// Google Patents wants "US5545737A/en", "US7425628B2/en", "USRE39221E1/en".
function googlePatent(id: string) {
  const m = /^US(RE)?0*(\d+)([A-Z]\d?)?$/i.exec(id.replace(/[^A-Z0-9]/gi, ""));
  if (!m) return `https://patents.google.com/?q=${encodeURIComponent(id)}`;
  const [, re, num, kind] = m;
  // no kind code: a grant before 2001 ("A"), or a reissue ("E" before RE37,100 in 2001, "E1" after)
  const k = kind || (re ? (Number(num) >= 37100 ? "E1" : "E") : "A");
  return `https://patents.google.com/patent/US${re ? "RE" : ""}${num}${k.toUpperCase()}/en`;
}

const PART_LABEL: Record<string, string> = { form: "Makes the form", capabilities: "Capabilities the form needs", segregation: "Separate block", standing: "Regulatory standing", record: "Track record with this molecule" };

function FitParts({ detail }: { detail?: any }) {
  if (!detail?.parts || detail.method !== "dosage form") return null;
  return (
    <div className="mt-3 rounded-lg bg-slate-50 p-3">
      <div className="mb-1.5 font-semibold text-ink-soft">Plant fit, part by part <span className="font-normal text-ink-muted">· molecule form: {detail.molecule_forms?.join(", ")}{detail.segregated_needed?.length ? ` · needs ${detail.segregated_needed.join(", ")} block` : ""}</span></div>
      <div className="grid gap-x-5 gap-y-1.5 sm:grid-cols-2">{Object.entries(detail.parts).map(([k, v]: any) => (
        <div key={k}><div className="flex justify-between text-[11px]"><span>{PART_LABEL[k] ?? k}</span><span className="tabular-nums">{v}/{detail.max?.[k]}</span></div>
          <Bar value={detail.max?.[k] ? (100 * v) / detail.max[k] : 0} color="#e11d48" /></div>
      ))}</div>
      <div className="mt-2 space-y-0.5 text-[11px] text-ink-muted">
        <div>{detail.capability_match}{detail.inferred_capabilities?.length ? ` · half credit (inferred, not evidenced): ${detail.inferred_capabilities.join(", ")}` : ""}</div>
        <div>{detail.standing} · {detail.record}</div>
      </div>
    </div>
  );
}

const CERT_LABEL: Record<string, string> = { USFDA: "US FDA", EU_GMP: "EU GMP", WHO_GMP: "WHO-GMP", FDA_OAI: "FDA OAI", FDA_IMPORT_ALERT: "FDA import alert",
  EU_NCR: "EU non-compliant", UK_MHRA: "UK MHRA" };
const SHORT_PART: Record<string, string> = { form: "Makes the form", capabilities: "Capabilities", segregation: "Separate block", standing: "Regulatory standing", record: "Track record" };
const certName = (c: string) => CERT_LABEL[c] ?? c.replace(/_/g, " ");
const BAD = new Set(["FDA_OAI", "FDA_IMPORT_ALERT", "EU_NCR"]);

// Up front: what the chosen plant means for this molecule — fit part by part, its rank, gaps, and what its certifications rest on.
function ThisPlant({ sp, onWhy, onRanking }: { sp: any; onWhy: () => void; onRanking: () => void }) {
  const f = sp.fit ?? {};
  const byForm = f.method === "dosage form" && f.parts;
  const pos = sp.position;
  const tone = sp.score >= 80 ? "#0a9a7d" : sp.score >= 60 ? "#0284c7" : sp.score >= 40 ? "#d97706" : "#e11d48";
  const gaps: string[] = [...(f.warnings ?? []), ...(f.missing_capabilities?.length ? [`missing: ${f.missing_capabilities.map((x: string) => x.replace(/_/g, " ")).join(", ")}`] : [])];
  return (
    <Card className="overflow-hidden">
      <div className="grid gap-0 lg:grid-cols-[minmax(0,1.15fr)_auto_minmax(0,1.6fr)]">
        <div className="min-w-0 border-b border-line p-5 lg:border-b-0 lg:border-r">
          <div className="label mb-1.5 flex items-center gap-1.5"><Factory size={12} /> This plant for this molecule</div>
          <div className="flex flex-wrap items-center gap-1.5">
            <span className="font-display text-lg font-bold leading-tight">{sp.name}</span>
            {sp.kind === "registry" ? <Badge>registry</Badge> : sp.kind === "demo" ? <Badge tone="amber">demo</Badge> : <Badge tone="brand">yours</Badge>}
          </div>
          <div className="mt-0.5 text-xs text-ink-muted">{[sp.city, sp.state].filter(Boolean).join(", ")}{sp.company && sp.kind === "demo" ? ` · modelled on ${sp.company}` : ""}
            {sp.registry_plant && <> · <a className="text-brand-700 hover:underline" href={`/playground/plants?plant=${encodeURIComponent(sp.registry_plant)}`}>official record</a></>}</div>
          <div className="mt-3 flex flex-wrap gap-1">
            {(sp.certs ?? []).map((c: string) => <span key={c} title={sp.basis?.[c]}><Badge tone={BAD.has(c) ? "rose" : "brand"}>{certName(c)}</Badge></span>)}
            {(sp.claimed ?? []).map((c: string) => <span key={c} title={sp.basis?.[c]}><Badge tone="amber">{certName(c)} · claimed</Badge></span>)}
            {!(sp.certs?.length || sp.claimed?.length) && <span className="text-xs text-ink-muted">No certification on record</span>}
          </div>
          {(sp.claimed?.length > 0 || (sp.certs ?? []).some((c: string) => BAD.has(c))) && (
            <p className="mt-2 text-[11px] leading-snug text-ink-muted">{(sp.claimed ?? []).concat((sp.certs ?? []).filter((c: string) => BAD.has(c))).map((c: string) => sp.basis?.[c]).filter((x: string | undefined, i: number, a: (string | undefined)[]) => x && a.indexOf(x) === i).slice(0, 2).join(" · ")}</p>
          )}
        </div>
        <button onClick={onWhy} className="flex min-w-[11rem] flex-col items-center justify-center border-b border-line px-6 py-5 text-center transition hover:bg-slate-50 lg:border-b-0 lg:border-r" title="Why this score">
          <div className="font-display text-5xl font-extrabold tabular-nums leading-none" style={{ color: tone }}>{Math.round(sp.score)}</div>
          <div className="mt-1 text-[11px] uppercase tracking-wider text-ink-muted">plant fit / 100</div>
          {pos && <div className="mt-2 text-xs text-ink-soft">#{pos.rank.toLocaleString()} of {pos.of.toLocaleString()} plants{pos.same > 1 ? <span className="text-ink-faint"> · tied with {(pos.same - 1).toLocaleString()}</span> : null}</div>}
          {pos && <div className="text-[11px] text-ink-faint">best in the registry: {Math.round(pos.top)}</div>}
        </button>
        <div className="min-w-0 p-5">
          {byForm ? (
            <>
              <div className="mb-2 flex items-baseline justify-between gap-2 text-[11px] text-ink-muted"><span>Needs: <b className="text-ink-soft">{f.molecule_forms?.join(", ")}</b>{f.segregated_needed?.length ? ` · separate ${f.segregated_needed.join(" / ")} block` : ""}</span>
                <button onClick={onRanking} className="shrink-0 text-brand-700 hover:underline">compare with every plant →</button></div>
              <div className="space-y-1.5">{Object.entries(f.parts).map(([k, v]: any) => {
                const max = f.max?.[k] || 1;
                return (
                  <div key={k} className="grid grid-cols-[9rem_minmax(0,1fr)_3rem] items-center gap-2 text-xs" title={PART_LABEL[k]}>
                    <span className="truncate text-ink-soft">{SHORT_PART[k] ?? k}</span>
                    <Bar value={(100 * v) / max} color={v >= max ? "#0a9a7d" : v > 0 ? "#f59e0b" : "#e11d48"} />
                    <span className="text-right tabular-nums text-ink-muted">{v}/{max}</span>
                  </div>
                );
              })}</div>
              {gaps.length > 0
                ? <div className="mt-3 flex flex-wrap gap-1">{gaps.slice(0, 4).map((g) => <Badge key={g} tone="rose">{g}</Badge>)}</div>
                : <div className="mt-3 text-[11px] text-emerald-700">No gap found for this molecule's form.</div>}
              <div className="mt-2 text-[11px] leading-snug text-ink-muted">{f.standing} · {f.record}</div>
            </>
          ) : (
            <div className="text-sm text-ink-soft">{f.summary || "Plant fit is estimated from the molecule class (its dosage form is not known)."}
              <div className="mt-1 text-xs text-ink-muted">Add the dosage form in the molecule's Regulatory tab to score plants part by part.</div></div>
          )}
        </div>
      </div>
    </Card>
  );
}

// One picker for every plant: your plant profiles (and the demo profiles, marked) first, then any plant in the registry.
function PlantPicker({ plants, current, onPick }: { plants: any[]; current?: string | null; onPick: (id: string) => void }) {
  const [q, setQ] = useState("");
  const [dq, setDq] = useState("");
  const [open, setOpen] = useState(false);
  useEffect(() => { const t = setTimeout(() => setDq(q.trim()), 250); return () => clearTimeout(t); }, [q]);
  const r = useQuery({ queryKey: ["plant-search", dq], enabled: open && dq.length >= 2, queryFn: () => api<any>(`/api/plants?${new URLSearchParams({ q: dq, size: "8", sort: "name" })}`) });
  const cur = plants.find((p) => p.asset_id === current);
  const ql = q.trim().toLowerCase();
  const mine = plants.filter((p) => !ql || `${p.name} ${p.company ?? ""}`.toLowerCase().includes(ql));
  const pick = (id: string) => { onPick(id); setQ(""); setOpen(false); };
  return (
    <div className="relative">
      <input className="input h-10 w-[26rem] max-w-full pr-20" value={open ? q : ""} onChange={(e) => { setQ(e.target.value); setOpen(true); }}
        onFocus={() => setOpen(true)} onBlur={() => setTimeout(() => setOpen(false), 150)}
        placeholder={cur ? `Scored for: ${cur.name}${cur.demo ? " (demo)" : ""}` : "Pick a plant — your plants or any registry plant"} />
      {!open && cur && <span className="pointer-events-none absolute right-3 top-1/2 -translate-y-1/2 text-[10px] font-semibold uppercase tracking-wider text-ink-faint">{cur.kind === "registry" ? "registry" : cur.demo ? "demo" : "yours"}</span>}
      {open && (
        <div className="absolute z-20 mt-1 max-h-96 w-[30rem] overflow-auto rounded-lg border border-line bg-white p-1 shadow-lg">
          {mine.length > 0 && <div className="px-2 pb-1 pt-1.5 text-[10px] font-semibold uppercase tracking-wider text-ink-faint">Plant profiles</div>}
          {mine.map((p) => (
            <button key={p.asset_id} className={cn("block w-full rounded-md px-2 py-1.5 text-left text-xs hover:bg-slate-50", p.asset_id === current && "bg-brand-50")} onMouseDown={() => pick(p.asset_id)}>
              <div className="flex items-center gap-1.5 font-medium">{p.name}
                {p.kind === "registry" ? <Badge>registry</Badge> : p.demo ? <Badge tone="amber">demo</Badge> : <Badge tone="brand">yours</Badge>}</div>
              <div className="text-ink-muted">
                {p.company && <>modelled on {p.company} · </>}
                {p.kind === "registry" ? "picked from the registry" : p.certs?.length ? p.certs.map((c: string) => c.replace(/_/g, " ")).join(", ") : "no certification on record"}
                {p.claimed?.length > 0 && <span className="text-amber-700"> · claimed, not confirmed: {p.claimed.map((c: string) => c.replace(/_/g, " ")).join(", ")}</span>}
              </div>
            </button>
          ))}
          <div className="px-2 pb-1 pt-2 text-[10px] font-semibold uppercase tracking-wider text-ink-faint">Plant registry (CDSCO · EU GMP · US FDA)</div>
          {dq.length < 2 && <div className="px-2 pb-2 text-xs text-ink-muted">Type a company, town or PIN to score any of ~2,850 registry plants.</div>}
          {dq.length >= 2 && r.isLoading && <div className="p-2 text-xs text-ink-muted">Searching…</div>}
          {dq.length >= 2 && r.data?.items?.length === 0 && <div className="p-2 text-xs text-ink-muted">No registry plant matches.</div>}
          {dq.length >= 2 && r.data?.items?.map((p: any) => (
            <button key={p.id} className="block w-full rounded-md px-2 py-1.5 text-left text-xs hover:bg-slate-50" onMouseDown={() => pick(`reg:${p.id}`)}>
              <div className="font-medium">{p.name}</div>
              <div className="text-ink-muted">{[p.district, p.state, p.pin].filter(Boolean).join(" · ")} · {p.dosage_forms.slice(0, 5).join(", ") || "forms not listed"}</div>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

function FitRanking({ moleculeKey, onScore, bare, highlight }: { moleculeKey: string; onScore: (id: string) => void; bare?: boolean; highlight?: string | null }) {
  const [cert, setCert] = useState<"" | "who_gmp" | "eu_gmp" | "us_fda">("");
  const [state, setState] = useState("");
  const [limit, setLimit] = useState(15);
  const r = useQuery({ queryKey: ["fit-rank", moleculeKey, cert, state, limit], enabled: !!moleculeKey, placeholderData: keepPreviousData,
    queryFn: () => api<any>(`/api/playground/molecule/${moleculeKey}/plant-fit?${new URLSearchParams({ cert, state, limit: String(limit) })}`) });
  const f = useQuery({ queryKey: ["plant-facets"], queryFn: () => api<any>("/api/plants/facets") });
  const m = r.data;
  return (
    <Frame bare={bare} title="Plant fit across the registry" subtitle={m ? `Every plant scored for ${m.molecule.dosage_form || m.molecule.forms?.join(", ") || "this molecule"}${m.molecule.segregated?.length ? ` · needs a separate ${m.molecule.segregated.join(" / ")} block` : ""} — ${m.scored?.toLocaleString()} plants` : "Loading…"}>
      {r.error && <div className="p-5"><ErrorNote error={r.error} /></div>}
      {m && !m.molecule.forms?.length ? <div className="p-5 text-xs text-ink-muted">The molecule's dosage form is not known, so plants cannot be scored against it — add it in the molecule's Regulatory tab.</div> : m && (
        <div className="p-5">
          <div className="mb-3 flex flex-wrap items-center gap-2">
            <Segmented value={cert} onChange={setCert} options={[{ value: "", label: "All" }, { value: "us_fda", label: "US FDA" }, { value: "eu_gmp", label: "EU GMP" }, { value: "who_gmp", label: "WHO-GMP" }]} />
            <select className="input h-9 w-48" value={state} onChange={(e) => setState(e.target.value)}><option value="">All states</option>{f.data?.states?.map((s: string) => <option key={s} value={s}>{s}</option>)}</select>
            <span className="ml-auto flex gap-1 text-[11px]">{Object.entries(m.bands).map(([b, n]: any) => <Badge key={b} tone={b === "80+" ? "brand" : b === "60–79" ? "sky" : b === "40–59" ? "amber" : "slate"}>{b}: {n.toLocaleString()}</Badge>)}</span>
          </div>
          {m.tied_at_top > 3 && <p className="mb-2 text-[11px] text-ink-muted">{m.tied_at_top} plants tie at the top score — public records don't separate them further, so they are ordered by most recent EU / FDA inspection.</p>}
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead><tr className="text-left text-ink-muted"><th className="py-1.5 pr-3 font-medium">Fit</th><th className="pr-3 font-medium">Plant</th><th className="pr-3 font-medium">Form · caps · block · standing · record</th><th className="pr-3 font-medium">Why</th><th /></tr></thead>
              <tbody>{m.items.map((p: any) => (
                <tr key={p.id} className={cn("border-t border-line align-top", p.id === highlight && "bg-brand-50/70 ring-1 ring-inset ring-brand-300")}>
                  <td className="py-2 pr-3 font-display text-base font-bold tabular-nums">{Math.round(p.fit)}</td>
                  <td className="py-2 pr-3"><div className="font-medium">{p.name}</div><div className="text-ink-muted">{[p.district, p.state].filter(Boolean).join(", ")}</div><div className="mt-1"><RegistryBadges p={p} /></div></td>
                  <td className="py-2 pr-3 tabular-nums text-ink-soft">{["form", "capabilities", "segregation", "standing", "record"].map((k) => `${Math.round(p.parts[k])}/${m.max[k]}`).join(" · ")}</td>
                  <td className="max-w-md py-2 pr-3 text-ink-muted">{p.fit_record}{p.fit_warnings?.length ? <span className="text-rose-700"> · {p.fit_warnings.join("; ")}</span> : null}</td>
                  <td className="py-2">{p.id === highlight ? <span className="text-[11px] font-semibold text-brand-700">scored ✓</span> : <button className="rounded-md border border-line px-2 py-1 hover:bg-slate-50" onClick={() => onScore(p.id)}>Score</button>}</td>
                </tr>
              ))}</tbody>
            </table>
          </div>
          <div className="mt-2 flex items-center justify-between gap-3 text-[11px] text-ink-faint">
            <span>{m.method}</span>
            {m.total > m.items.length && <button className="shrink-0 text-brand-700 hover:underline" onClick={() => setLimit(limit + 25)}>Show 25 more of {m.total.toLocaleString()}</button>}
          </div>
        </div>
      )}
    </Frame>
  );
}

const NEED_TONE: Record<string, "rose" | "amber" | "indigo" | "sky" | "slate"> = {
  hazardous: "rose", hydrogenation: "amber", cryogenic: "indigo", pressure: "amber", organometallic: "rose",
  high_temperature: "amber", pd_coupling: "sky", chlorinated_solvent: "slate",
};

function Synthesis({ moleculeKey, bare }: { moleculeKey: string; bare?: boolean }) {
  const q = useQuery({ queryKey: ["synthesis", moleculeKey], enabled: !!moleculeKey,
    queryFn: () => api<any>(`/api/playground/molecule/${moleculeKey}/synthesis`) });
  const [all, setAll] = useState(false);
  const s = q.data;
  if (!s || q.error) return null;
  const top = (o: Record<string, number> | undefined) => Object.entries(o ?? {}).map(([k, n]) => `${k} (${n})`).join(" · ") || "—";
  return (
    <Frame bare={bare} title="How it's made — Open Reaction Database"
        subtitle={!s.available ? "Not loaded yet" : !s.found ? "No reaction in the ORD makes this molecule" : `${s.reactions} reactions from ${s.sources} patents / papers${s.yield_median != null ? ` · median yield ${s.yield_median}%` : ""}`}>
      {!s.available ? <div className="p-5 text-xs text-ink-muted">Run <code>just fetch-ord</code> on a laptop (downloads ~1.3 GB once, scans in 10–20 min), then <code>just push-signals</code>.</div>
        : !s.found ? <div className="p-5 text-xs text-ink-muted">Patents and papers in the ORD don't report this molecule as a product (or its structure isn't known yet). Biologics are not covered.</div> : (
          <div className="p-5">
            <div className="label mb-1.5">What the routes ask of an API plant</div>
            {s.needs.length === 0 ? <div className="text-xs text-ink-muted">Nothing special: ambient-pressure reactions between −20 and 150 °C, no flagged reagents.</div> : (
              <div className="grid gap-2 md:grid-cols-2">{s.needs.map((n: any) => (
                <div key={n.key} className="rounded-lg border border-line p-2.5 text-xs">
                  <div className="flex items-center justify-between gap-2"><Badge tone={NEED_TONE[n.key] ?? "slate"}>{n.label}</Badge><span className="tabular-nums text-ink-muted">{n.share_pct}% of reactions</span></div>
                  {n.equipment && <div className="mt-1 text-ink-soft">{n.equipment}</div>}
                </div>
              ))}</div>
            )}
            {Object.keys(s.hazards ?? {}).length > 0 && <div className="mt-2 text-xs"><span className="text-ink-muted">Hazardous reagents seen: </span>{top(s.hazards)}</div>}
            <div className="mt-3 grid gap-x-6 gap-y-1 text-xs md:grid-cols-2">
              <div><span className="text-ink-muted">Temperatures: </span>{s.temp_c ? `${s.temp_c.min} to ${s.temp_c.max} °C (median ${s.temp_c.median}, ${s.temp_c.n} reported)` : "not reported"}</div>
              <div><span className="text-ink-muted">Solvents: </span>{top(s.solvents)}</div>
              <div><span className="text-ink-muted">Catalysts: </span>{top(s.catalysts)}</div>
              <div><span className="text-ink-muted">Reagents: </span>{top(s.reagents)}</div>
            </div>
            <div className="mt-4 overflow-x-auto">
              <table className="w-full text-xs">
                <thead><tr className="text-left text-ink-muted"><th className="py-1 font-medium">From</th><th className="font-medium">Conditions</th><th className="font-medium">Reactants → product</th><th className="font-medium">Needs</th></tr></thead>
                <tbody>{(all ? s.examples : s.examples.slice(0, 8)).map((r: any) => (
                  <tr key={r.id} className="border-t border-line align-top">
                    <td className="py-1.5 pr-3">{r.patent ? <a className="text-brand-700 hover:underline" href={googlePatent(r.patent)} target="_blank" rel="noreferrer">{r.patent}</a>
                      : r.doi ? <a className="text-brand-700 hover:underline" href={`https://doi.org/${r.doi}`} target="_blank" rel="noreferrer">{r.doi}</a> : <span className="text-ink-muted">{r.dataset}</span>}</td>
                    <td className="pr-3 tabular-nums text-ink-soft">{[r.temp_c != null && `${r.temp_c} °C`, r.pressure_bar != null && `${r.pressure_bar} bar`, r.atmosphere && r.atmosphere.toLowerCase(), r.hours != null && `${r.hours} h`, r.yield != null && `${r.yield}% yield`].filter(Boolean).join(" · ") || "—"}{r.solvents?.length ? <div className="text-ink-muted">{r.solvents.join(", ")}</div> : null}</td>
                    <td className="max-w-md pr-3 text-ink-muted"><span className="line-clamp-2 break-all">{[...(r.reactants ?? []), ...(r.reagents ?? []), ...(r.catalysts ?? [])].slice(0, 6).join(" + ")}</span></td>
                    <td className="pr-1"><div className="flex flex-wrap gap-1">{r.needs.map((n: string) => <Badge key={n} tone={NEED_TONE[n] ?? "slate"}>{n.replace("_", " ")}</Badge>)}</div></td>
                  </tr>
                ))}</tbody>
              </table>
              {s.examples.length > 8 && <button className="mt-1 text-xs text-brand-700 hover:underline" onClick={() => setAll(!all)}>{all ? "fewer" : `all ${s.examples.length} examples`}</button>}
            </div>
            <p className="mt-3 text-[11px] text-ink-faint">{s.note} Data: {s.licence}.</p>
          </div>
        )}
    </Frame>
  );
}

// ------------------------------------------------------------------------------ dossier: tiles and their expanded views

const nfx = (n: number | null | undefined) => (n == null ? "—" : n.toLocaleString("en-IN"));
const MARKET_TONE: Record<string, "brand" | "amber" | "rose"> = { off_patent: "brand", loe_pending: "amber" };

function Identity({ d }: { d: any }) {
  const p = d.patent, r = d.regulatory;
  const offNow = (p.geo_coverage ?? []).filter((g: any) => g.market_status === "off_patent").length;
  const chips: [string, string, string?][] = [
    [p.therapeutic_area, "slate"], [[r?.dosage_form, r?.strength].filter(Boolean).join(" · "), "slate"],
    [p.fto_risk ? `FTO ${p.fto_risk}` : "", p.fto_risk === "high" ? "rose" : p.fto_risk === "medium" ? "amber" : "brand"],
    [offNow ? `off-patent in ${offNow} markets` : "", "brand"], [d.nsq ? `${d.nsq.alerts} NSQ alerts` : "", "rose"],
    [r?.te_code ? `TE ${r.te_code}` : "", "indigo"],
  ];
  return (
    <div className="flex flex-wrap items-end justify-between gap-3 px-1">
      <div className="min-w-0">
        <div className="font-display text-2xl font-extrabold tracking-tight">{p.api_name}</div>
        <div className="text-xs text-ink-muted">{[p.brand_name, p.originator].filter(Boolean).join(" · ")}</div>
      </div>
      <div className="flex flex-wrap gap-1.5">{chips.filter(([t]) => t).map(([t, tone]) => <Badge key={t} tone={tone as any}>{t}</Badge>)}</div>
    </div>
  );
}

function ScoreDetail({ d }: { d: any }) {
  return (
    <div className="max-w-4xl space-y-4">
      <div className="grid gap-3 md:grid-cols-2">{Object.entries(d.score.explanation ?? {}).map(([k, v]: any) => (
        <div key={k} className="rounded-xl bg-white p-4 text-sm ring-1 ring-inset ring-line"><div className="label mb-1 capitalize">{k}</div><div className="text-ink-soft">{v}</div></div>
      ))}</div>
      {d.score.warnings?.length > 0 && <div className="flex flex-wrap gap-1">{d.score.warnings.map((x: string) => <Badge key={x} tone="amber">{x}</Badge>)}</div>}
      <div className="rounded-xl bg-white p-4 ring-1 ring-inset ring-line text-xs"><FitParts detail={d.score.plant_fit_detail} /></div>
    </div>
  );
}

function PassportTile({ d }: { d: any }) {
  const r = d.regulatory;
  const mono = [["IP", r?.ip_2026_monograph], ["Ph. Eur.", r?.ph_eur_monograph], ["USP", r?.usp_monograph]];
  return (
    <Tile id="passport" title="Regulatory passport" icon={<ScrollText size={14} />} subtitle={r?.rld ? `RLD ${r.rld}` : "no reference drug on record"} accent="#6366f1">
      <div className="grid grid-cols-3 gap-2">
        <Figure value={r?.te_code || "—"} label="TE code" />
        <Figure value={r?.bcs_class?.replace("BCS ", "") || "—"} label="BCS class" />
        <Figure value={<span className="capitalize">{r?.readiness || "—"}</span>} label="readiness" />
      </div>
      <div className="mt-3 flex gap-1.5">{mono.map(([k, v]) => <span key={k} className={cn("rounded-md px-1.5 py-0.5 text-[11px] font-medium", v ? "bg-emerald-50 text-emerald-800" : "bg-slate-100 text-ink-faint line-through")}>{k}</span>)}</div>
    </Tile>
  );
}

function PassportDetail({ d }: { d: any }) {
  const r = d.regulatory;
  return (
    <div className="space-y-5">
      <div className="grid gap-x-10 rounded-2xl bg-white p-5 ring-1 ring-inset ring-line md:grid-cols-2">
        <div>
          <Field k="US LOE" v={<span className="flex items-center gap-1">{fmtDate(d.patent.estimated_loe_us)}<Estimate field="loe" prov={d.patent.provenance?.loe_us} /></span>} />
          <Field k="EU LOE" v={<span className="flex items-center gap-1">{fmtDate(d.patent.estimated_loe_eu)}<Estimate field="loe" prov={d.patent.provenance?.loe_eu} /></span>} />
          <Field k="India LOE" v={fmtDate(d.patent.estimated_loe_in)} />
          <Field k="FTO risk" v={<span className="flex items-center gap-1 capitalize">{d.patent.fto_risk}<Estimate field="fto_risk" prov={d.patent.provenance?.fto_risk} /></span>} />
          <Field k="Therapeutic area" v={d.patent.therapeutic_area} />
          <Field k="Market size" v={d.patent.market_size_usd_bn ? `$${d.patent.market_size_usd_bn} bn` : null} />
        </div>
        <div>
          <Field k="Reference drug (RLD)" v={r?.rld} />
          <Field k="RLD holder" v={r?.rld_applicant} />
          <Field k="TE code" v={r?.te_code} />
          <Field k="Dosage form / strength" v={[r?.dosage_form, r?.strength].filter(Boolean).join(" · ")} />
          <Field k="BCS class" v={r?.bcs_class} />
          <Field k="Readiness" v={r?.readiness} />
        </div>
      </div>
      <div>
        <div className="label mb-2">Pharmacopoeia monographs</div>
        <div className="grid gap-3 md:grid-cols-3">{[["IP", r?.ip_2026_monograph], ["Ph. Eur.", r?.ph_eur_monograph], ["USP", r?.usp_monograph]].map(([k, v]) => (
          <div key={k} className={cn("rounded-xl p-3 text-xs", v ? "bg-emerald-50 text-emerald-900" : "bg-white text-ink-faint ring-1 ring-inset ring-line")}><b>{k}</b><div className="mt-1">{v || "not listed"}</div></div>
        ))}</div>
        {(r?.exclusivity ?? []).length > 0 && <div className="mt-3 flex flex-wrap gap-1.5">{r.exclusivity.map((x: any, i: number) => <Badge key={i} tone={x.expiry_date && new Date(x.expiry_date) > new Date() ? "rose" : "slate"}>{x.type} · {fmtDate(x.expiry_date)}</Badge>)}</div>}
        {(r?.analytical_specs ?? []).length > 0 && <div className="mt-3 text-xs text-ink-soft"><b>Key tests:</b> {r.analytical_specs.join(" · ")}</div>}
      </div>
      {d.orange_book_curated && (
        <div className="rounded-2xl bg-white p-5 ring-1 ring-inset ring-line">
          <div className="label mb-2">FDA Orange Book (curated record)</div>
          <Field k="TE codes" v={(d.orange_book_curated.te_codes ?? []).join(", ")} />
          <Field k="RLD applicant" v={d.orange_book_curated.rld_applicant} />
          <Field k="Application / approval" v={`${d.orange_book_curated.rld_app_number} · ${d.orange_book_curated.rld_approval_date}`} />
          <Field k="Dosage forms" v={(d.orange_book_curated.dosage_forms ?? []).join(", ")} />
          <Field k="Strengths" v={(d.orange_book_curated.strengths ?? []).join(", ")} />
          <Field k="Marketing status" v={(d.orange_book_curated.marketing_statuses ?? []).join(", ")} />
          {d.orange_book_curated.provenance?.reference_url && <a href={d.orange_book_curated.provenance.reference_url} target="_blank" rel="noreferrer" className="mt-2 inline-flex items-center gap-1 text-xs text-brand-700 hover:underline">Source (retrieved {d.orange_book_curated.provenance.retrieved_at}) <ExternalLink size={11} /></a>}
        </div>
      )}
      {d.pharmacopeia && (
        <div className="overflow-hidden rounded-2xl bg-white ring-1 ring-inset ring-line">
          <div className="px-5 pt-4"><div className="label">IP vs Ph. Eur. vs USP</div><p className="mt-0.5 text-xs text-ink-muted">Method by method — where an Indian-spec batch may not meet the export spec</p></div>
          <div className="mt-3 overflow-x-auto">
            <table className="w-full text-xs"><thead><tr className="border-y border-line bg-slate-50/70 text-left text-[10px] uppercase tracking-wider text-ink-muted"><th className="px-4 py-2">Test</th><th className="px-4 py-2">IP 2026</th><th className="px-4 py-2">Ph. Eur.</th><th className="px-4 py-2">USP</th><th className="px-4 py-2">Verdict</th></tr></thead>
              <tbody>{d.pharmacopeia.map((row: any) => (
                <tr key={row.section} className="border-b border-line/60 align-top">
                  <td className="px-4 py-2.5 font-semibold capitalize">{row.section}</td>
                  {["IP 2026", "Ph. Eur.", "USP"].map((ph) => <td key={ph} className="max-w-[260px] px-4 py-2.5 text-ink-soft">{row.methods[ph]?.raw_text ?? <span className="text-ink-faint">—</span>}</td>)}
                  <td className="px-4 py-2.5"><Badge tone={row.significance === "NSQ_RELEVANT" ? "rose" : row.significance === "EQUIVALENT" ? "brand" : "slate"}>{String(row.significance).replace(/_/g, " ").toLowerCase()}</Badge><div className="mt-1 text-ink-muted">{row.rationale}</div></td>
                </tr>))}</tbody></table>
          </div>
        </div>
      )}
    </div>
  );
}

function MarketsTile({ d }: { d: any }) {
  const g = d.patent.geo_coverage ?? [];
  const c = { off: g.filter((x: any) => x.market_status === "off_patent").length, pend: g.filter((x: any) => x.market_status === "loe_pending").length };
  const blocked = g.length - c.off - c.pend;
  return (
    <Tile id="markets" title="Where it can be sold" icon={<Globe2 size={14} />} subtitle={`${g.length} markets checked`} accent="#10b996">
      <div className="grid grid-cols-3 gap-2">
        <Figure value={c.off} label="off-patent" tone="#0a9a7d" /><Figure value={c.pend} label="LOE pending" tone="#d97706" /><Figure value={blocked} label="blocked" tone={blocked ? "#e11d48" : undefined} />
      </div>
      {g.length > 0 && <div className="mt-3 flex h-2 overflow-hidden rounded-full bg-slate-100">
        <div className="bg-brand-500" style={{ width: `${(100 * c.off) / g.length}%` }} /><div className="bg-amber-400" style={{ width: `${(100 * c.pend) / g.length}%` }} /><div className="bg-rose-400" style={{ width: `${(100 * blocked) / g.length}%` }} />
      </div>}
    </Tile>
  );
}

function MarketsDetail({ d }: { d: any }) {
  return (
    <div className="grid gap-2 md:grid-cols-2 xl:grid-cols-3">{(d.patent.geo_coverage ?? []).map((g: any) => (
      <div key={g.country_code} className="rounded-xl bg-white p-3 text-xs ring-1 ring-inset ring-line">
        <div className="flex items-center justify-between"><span className="font-semibold">{g.country_name}</span><Badge tone={MARKET_TONE[g.market_status] ?? "rose"}>{g.market_status.replace("_", " ")}</Badge></div>
        <div className="mt-1 text-ink-muted">{[g.loe_date && `LOE ${fmtDate(g.loe_date)}`, g.patent_barrier && g.patent_barrier !== "none" && `barrier: ${g.patent_barrier}`, g.export_eligible && "export eligible"].filter(Boolean).join(" · ") || "—"}</div>
        {g.notes && <div className="mt-1 text-ink-faint">{g.notes}</div>}
      </div>
    ))}</div>
  );
}

function DemandTile({ d }: { d: any }) {
  const m = d.demand, cx = d.complexity;
  return (
    <Tile id="demand" title="Demand & complexity" icon={<TrendingUp size={14} />} subtitle={m?.disease_area || "no demand profile"} accent="#f59e0b">
      <div className="grid grid-cols-3 gap-2">
        <Figure value={m ? `${m.trial_count_phase_3_plus}` : "—"} label="Ph 3+ trials" />
        <Figure value={m?.competitor_anda_count ?? "—"} label="generic rivals" />
        <Figure value={`${cx.process_complexity_score}/10`} label="process complexity" />
      </div>
      <div className="mt-3 flex flex-wrap gap-1">{m?.growth_trend && <Badge>{m.growth_trend} trial activity</Badge>}{m?.cluster && <Badge>{m.cluster}</Badge>}{cx.sterility_required && <Badge tone="sky">sterile</Badge>}</div>
    </Tile>
  );
}

function DemandDetail({ d }: { d: any }) {
  const cx = d.complexity;
  return (
    <div className="grid gap-5 lg:grid-cols-2">
      <div className="rounded-2xl bg-white p-5 ring-1 ring-inset ring-line">
        <div className="label mb-2">Demand</div>
        <Field k="Trials (total / Ph 3+)" v={d.demand ? `${d.demand.trial_count_total} / ${d.demand.trial_count_phase_3_plus}` : null} />
        <Field k="Trend" v={d.demand?.growth_trend} />
        <Field k="Cluster" v={d.demand?.cluster} />
        <Field k="Generic competitors" v={d.demand?.competitor_anda_count} />
        <Field k="Prevalence India / global" v={d.demand && (d.demand.disease_prevalence_india_millions || d.demand.disease_prevalence_global_millions) ? `${d.demand.disease_prevalence_india_millions} M / ${d.demand.disease_prevalence_global_millions} M` : null} />
        <Field k="Buyer activity / momentum" v={d.demand ? `${d.demand.buyer_activity_score} / ${d.demand.market_momentum_score}` : null} />
      </div>
      <div className="rounded-2xl bg-white p-5 ring-1 ring-inset ring-line">
        <div className="label mb-2">Manufacturing complexity · {titleCase(cx.modality)} · {titleCase(cx.drug_form)}{cx.sterility_required ? " · sterile" : ""}</div>
        <div className="space-y-2">
          {[["Process", cx.process_complexity_score], ["Analytical", cx.analytical_complexity_score], ["Biologic", cx.biologic_complexity_score]].map(([k, v]: any) => (
            <div key={k} className="text-xs"><div className="flex justify-between"><span>{k}</span><b>{v}/10</b></div><div className="mt-1 h-1.5 rounded-full bg-slate-100"><div className="h-full rounded-full bg-brand-500" style={{ width: `${v * 10}%` }} /></div></div>
          ))}
        </div>
        <div className="mt-3 flex flex-wrap gap-1">{(cx.critical_quality_attributes ?? []).map((c: string) => <Badge key={c}>{c.replace(/_/g, " ")}</Badge>)}</div>
        <div className="mt-2 flex flex-wrap gap-1">{(cx.gmp_pillars ?? []).filter((p: any) => p.applies).map((p: any) => <Badge key={p.pillar_id} tone="indigo">{p.title}</Badge>)}</div>
      </div>
    </div>
  );
}

function NsqTile({ d }: { d: any }) {
  const n = d.nsq;
  if (!n) return (
    <Tile title="NSQ record — all India" icon={<ShieldAlert size={14} />} subtitle="No CDSCO alert names this molecule" accent="#cbd5e1">
      <div className="text-xs text-ink-muted">Nothing failed testing in the alerts since 2021.</div>
    </Tile>
  );
  const vals = n.trend?.series?.[0]?.values ?? [];
  const max = Math.max(1, ...vals);
  return (
    <Tile id="nsq" title="NSQ record — all India" icon={<ShieldAlert size={14} />} subtitle={n.categories?.[0] ? `mostly ${n.categories[0].name.toLowerCase()}` : undefined} accent="#e11d48">
      <div className="grid grid-cols-2 gap-2"><Figure value={n.alerts} label="alerts" tone="#e11d48" /><Figure value={n.manufacturers} label="manufacturers" /></div>
      {vals.length > 1 && <div className="mt-3 flex h-8 items-end gap-px">{vals.slice(-24).map((v: number, i: number) => <div key={i} className="flex-1 rounded-sm bg-rose-300" style={{ height: `${Math.max(4, (100 * v) / max)}%` }} />)}</div>}
    </Tile>
  );
}

function NsqDetail({ d }: { d: any }) {
  const n = d.nsq;
  return (
    <div className="space-y-5">
      <div className="rounded-2xl bg-white p-5 ring-1 ring-inset ring-line"><div className="label mb-2">Alerts per month</div><TrendBars data={n.trend} height={240} /></div>
      <div className="grid gap-5 lg:grid-cols-3">
        <div className="rounded-2xl bg-white p-5 ring-1 ring-inset ring-line"><div className="label mb-2">Why it fails</div><RankBars rows={n.categories} color="#e11d48" /></div>
        <div className="rounded-2xl bg-white p-5 ring-1 ring-inset ring-line"><div className="label mb-2">Who makes the failing batches</div><RankBars rows={n.top_manufacturers} color="#f59e0b" /></div>
        <div className="rounded-2xl bg-white p-5 ring-1 ring-inset ring-line"><div className="label mb-2">Where they are made</div><RankBars rows={n.states} color="#6366f1" /><div className="label mb-2 mt-4">Forms</div><RankBars rows={n.forms} color="#0a9a7d" /></div>
      </div>
    </div>
  );
}

function FitTile({ moleculeKey }: { moleculeKey: string }) {
  const r = useQuery({ queryKey: ["fit-rank", moleculeKey, "", "", 15], enabled: !!moleculeKey, placeholderData: keepPreviousData,
    queryFn: () => api<any>(`/api/playground/molecule/${moleculeKey}/plant-fit?${new URLSearchParams({ cert: "", state: "", limit: "15" })}`) });
  const m = r.data;
  const bands = m?.bands ?? {};
  const tot = Object.values(bands).reduce((a: number, b: any) => a + (b as number), 0) || 1;
  const col: Record<string, string> = { "80+": "#0a9a7d", "60–79": "#38bdf8", "40–59": "#f59e0b", "<40": "#cbd5e1" };
  return (
    <Tile id="fit" title="Plant fit across the registry" icon={<Factory size={14} />} subtitle={m ? `${m.scored?.toLocaleString()} plants scored for ${m.molecule.forms?.join(", ") || "—"}` : "Loading…"}>
      {!m ? <Skeleton className="h-20" /> : !m.molecule.forms?.length ? <div className="text-xs text-ink-muted">Dosage form unknown — can't score plants.</div> : (<>
        <div className="flex h-2 overflow-hidden rounded-full">{Object.entries(bands).map(([b, n]: any) => <div key={b} title={`${b}: ${n}`} style={{ width: `${(100 * n) / tot}%`, background: col[b] }} />)}</div>
        <div className="mt-1 flex justify-between text-[10px] text-ink-muted">{Object.entries(bands).map(([b, n]: any) => <span key={b}>{b} · {nfx(n)}</span>)}</div>
        <ol className="mt-3 space-y-1">{m.items.slice(0, 3).map((p: any) => (
          <li key={p.id} className="flex items-center justify-between gap-2 text-xs"><span className="truncate"><b className="mr-1.5 tabular-nums">{Math.round(p.fit)}</b>{p.name}</span><span className="shrink-0 text-ink-faint">{p.state}</span></li>
        ))}</ol>
      </>)}
    </Tile>
  );
}

function MakersTile({ moleculeKey }: { moleculeKey: string }) {
  const { data: m } = useQuery({ queryKey: ["makers", moleculeKey], queryFn: () => api<any>(`/api/plants/for-molecule/${moleculeKey}`), enabled: !!moleculeKey });
  return (
    <Tile id="makers" title="Who can make it" icon={<Users size={14} />} subtitle="Plant registry · API filings">
      {!m ? <Skeleton className="h-20" /> : (
        <div className="grid grid-cols-3 gap-x-2 gap-y-3">
          <Figure value={nfx(m.api_makers_total + (m.listed_total ?? 0))} label="API makers" />
          <Figure value={nfx(m.made_total)} label="made it (NSQ)" tone={m.made_total ? "#e11d48" : undefined} />
          <Figure value={nfx(m.capable_total)} label="can make the form" />
          <Figure value={nfx(m.capable_fda ?? 0)} label="…US FDA" />
          <Figure value={nfx(m.dmf_total ?? 0)} label="US DMFs" />
          <Figure value={nfx(m.cep_total ?? 0)} label="CEPs" />
        </div>
      )}
    </Tile>
  );
}

function SynthesisTile({ moleculeKey }: { moleculeKey: string }) {
  const { data: s } = useQuery({ queryKey: ["synthesis", moleculeKey], enabled: !!moleculeKey, queryFn: () => api<any>(`/api/playground/molecule/${moleculeKey}/synthesis`) });
  return (
    <Tile id={s?.found ? "synthesis" : undefined} title="How it's made" icon={<FlaskConical size={14} />}
      subtitle={!s ? "Loading…" : !s.available ? "Open Reaction Database not loaded" : !s.found ? "No published reaction makes it" : `${s.reactions} reactions · ${s.sources} patents / papers`}>
      {!s ? <Skeleton className="h-20" /> : !s.found ? <div className="text-xs text-ink-muted">{s.available ? "Biologics and molecules without a known structure are not covered." : "Run just fetch-ord, then just push-signals."}</div> : (
        <div className="space-y-2">
          {s.needs.length === 0 ? <div className="text-xs text-ink-muted">No special equipment in the published routes.</div>
            : <div className="flex flex-wrap gap-1">{s.needs.slice(0, 5).map((n: any) => <Badge key={n.key} tone={NEED_TONE[n.key] ?? "slate"}>{n.label.split(" (")[0]} · {n.share_pct}%</Badge>)}</div>}
          <div className="truncate text-[11px] text-ink-muted">{s.temp_c ? `${s.temp_c.min} to ${s.temp_c.max} °C · ` : ""}{Object.keys(s.solvents ?? {}).slice(0, 3).join(", ")}</div>
        </div>
      )}
    </Tile>
  );
}

export function Workbench({ initial }: { initial?: string }) {
  const list = useQuery({ queryKey: ["pg-world", ""], queryFn: () => api<any>("/api/playground/world") });
  const [key, setKey] = useState(initial ?? "");
  const [plant, setPlant] = useState("");
  const [w, setW] = useState({ patent: 25, regulatory: 20, demand: 25, plant: 30 });
  const [dw, setDw] = useState(w);
  useEffect(() => { const t = setTimeout(() => setDw(w), 250); return () => clearTimeout(t); }, [w]);
  useEffect(() => { if (!key && list.data?.molecules?.length) setKey(list.data.molecules.find((m: any) => m.key === "telmisartan")?.key ?? list.data.molecules[0].key); }, [list.data, key]);
  const q = useQuery({
    queryKey: ["pg-mol", key, plant, dw], enabled: !!key, placeholderData: keepPreviousData,
    queryFn: () => api<any>(`/api/playground/molecule/${key}?${new URLSearchParams(Object.values(dw).some((x) => x > 0)
      ? { plant_id: plant, w_patent: String(dw.patent), w_regulatory: String(dw.regulatory), w_demand: String(dw.demand), w_plant: String(dw.plant) }
      : { plant_id: plant })}`),
  });
  const d = q.data;
  const radial = useMemo(() => d ? PILLARS.map(([k, , c]) => ({ name: k, value: Math.round(d.score[`${k === "plant" ? "plant_fit" : k === "patent" ? "patent_readiness" : k === "regulatory" ? "regulatory_clarity" : "demand_attractiveness"}_score`]), fill: c })) : [], [d]);

  const [active, setActive] = useState<string | null>(null);
  const open = (id: string) => setActive(id);
  useEffect(() => setActive(null), [key]);  // a new molecule starts with the modal closed
  const sections: Section[] = useMemo(() => d ? [
    { id: "score", title: "Why these scores", icon: <Gauge size={16} />, subtitle: "Each pillar's explanation and the plant fit part by part", render: () => <ScoreDetail d={d} /> },
    { id: "passport", title: "Regulatory passport", icon: <ScrollText size={16} />, subtitle: d.patent.brand_name ? `${d.patent.brand_name} · ${d.patent.originator}` : d.patent.originator, render: () => <PassportDetail d={d} /> },
    { id: "markets", title: "Where it can be sold", icon: <Globe2 size={16} />, subtitle: "Patent status per country", render: () => <MarketsDetail d={d} /> },
    { id: "demand", title: "Demand & complexity", icon: <TrendingUp size={16} />, subtitle: d.demand?.disease_area, render: () => <DemandDetail d={d} /> },
    ...(d.nsq ? [{ id: "nsq", title: "NSQ record — all India", icon: <ShieldAlert size={16} />, subtitle: `${d.nsq.alerts} alerts across ${d.nsq.manufacturers} manufacturers`, render: () => <NsqDetail d={d} /> }] : []),
    { id: "fit", title: "Plant fit across the registry", icon: <Factory size={16} />, subtitle: "Every plant scored for this molecule's form", render: () => <FitRanking bare moleculeKey={key} highlight={d.selected_plant?.registry_plant} onScore={(id) => { setPlant(`reg:${id}`); setActive(null); }} /> },
    { id: "makers", title: "Who can make it", icon: <Users size={16} />, subtitle: "API makers, plants that made it, plants permitted to make the form, API filings", render: () => <MakersCard bare moleculeKey={key} highlight={d.selected_plant?.registry_plant} /> },
    { id: "synthesis", title: "How it's made", icon: <FlaskConical size={16} />, subtitle: "Reactions from the Open Reaction Database", render: () => <Synthesis bare moleculeKey={key} /> },
  ] : [], [d, key]);

  return (
    <ExpandedProvider sections={sections} active={active} onActive={setActive} title={d?.patent.api_name ?? "Molecule"} subtitle={d?.patent.therapeutic_area}>
    <div className="space-y-4">
      <Card className="flex flex-wrap items-center gap-3 p-3">
        <FlaskConical size={18} className="ml-1 text-brand-700" />
        <select className="input h-10 w-64" value={key} onChange={(e) => setKey(e.target.value)}>{list.data?.molecules.map((m: any) => <option key={m.key} value={m.key}>{m.name}</option>)}</select>
        <PlantPicker plants={d?.plants ?? []} current={d?.plant_id} onPick={setPlant} />
        {d && <span className="ml-auto text-[11px] text-ink-muted">{d.patent.origin === "curated" ? "Curated profile" : d.patent.origin === "manual" ? "Added in the app" : "Built from public sources"} · {(d.patent.signals?.sources ?? []).length} sources</span>}
      </Card>
      {q.error && <ErrorNote error={q.error} />}
      {!d ? <Skeleton className="h-96" /> : (
        <div className={cn("space-y-4 transition-opacity", q.isFetching && "opacity-70")}>
          <Identity d={d} />
          {d.selected_plant && <ThisPlant sp={d.selected_plant} onWhy={() => open("score")} onRanking={() => open("fit")} />}
          <div className="grid gap-4 xl:grid-cols-[minmax(0,5fr)_minmax(0,7fr)]">
            <Card className="flex flex-col">
              <CardHeader title="Four-pillar score" subtitle="Weighted average of the pillars — the weights move the total only"
                action={<button className="inline-flex items-center gap-1 rounded-lg px-2 py-1 text-xs text-brand-700 hover:bg-brand-50" onClick={() => open("score")}><Maximize2 size={12} /> Why</button>} />
              <div className="grid flex-1 grid-cols-[minmax(0,1fr)_minmax(0,1.1fr)] items-center gap-4 p-5">
                <div className="relative">
                  <ResponsiveContainer width="100%" height={200}>
                    <RadialBarChart innerRadius="48%" outerRadius="100%" data={radial} startAngle={90} endAngle={-270}>
                      <PolarAngleAxis type="number" domain={[0, 100]} tick={false} />
                      <RadialBar dataKey="value" background cornerRadius={6} />
                    </RadialBarChart>
                  </ResponsiveContainer>
                  <div className="pointer-events-none absolute inset-0 grid place-items-center text-center"><div><div className="font-display text-3xl font-extrabold">{Math.round(d.score.total_score)}</div><div className="text-[10px] uppercase tracking-wider text-ink-muted">total</div></div></div>
                </div>
                <div className="space-y-3">
                  {PILLARS.map(([k, label, c]) => {
                    const sum = Object.values(w).reduce((a, b) => a + b, 0);
                    return <Slider key={k} label={label} score={radial.find((r) => r.name === k)?.value} share={sum ? Math.round((100 * (w as any)[k]) / sum) : 0}
                      value={(w as any)[k]} color={c} onChange={(v) => setW({ ...w, [k]: v })} />;
                  })}
                  {Object.values(w).every((x) => x === 0) && <div className="text-[11px] text-amber-700">All weights are 0 — the default weights are used.</div>}
                </div>
              </div>
              {d.score.warnings?.length > 0 && <div className="flex flex-wrap gap-1 border-t border-line px-5 py-3">{d.score.warnings.map((x: string) => <Badge key={x} tone="amber">{x}</Badge>)}</div>}
            </Card>
            <div className="grid gap-4 sm:grid-cols-2">
              <PassportTile d={d} />
              <MarketsTile d={d} />
              <DemandTile d={d} />
              <NsqTile d={d} />
            </div>
          </div>
          <div className="grid gap-4 lg:grid-cols-3">
            <FitTile moleculeKey={key} />
            <MakersTile moleculeKey={key} />
            <SynthesisTile moleculeKey={key} />
          </div>
        </div>
      )}
    </div>
    </ExpandedProvider>
  );
}