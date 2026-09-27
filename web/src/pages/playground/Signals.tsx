// Health & trade: regional disease burden (NFHS), outbreaks (IDSP) and India's pharma trade (UN Comtrade).
import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { Activity, HeartPulse, Ship } from "lucide-react";
import { useMemo, useState } from "react";
import { RankBars, TrendBars } from "../../components/charts";
import { Badge, Card, CardHeader, ErrorNote, Segmented, Skeleton, Stat } from "../../components/ui";
import { IndiaMap } from "../../components/viz";
import { api } from "../../lib/api";
import { cn } from "../../lib/cn";
import { ExpandedProvider, type Section } from "../../components/ui/Expanded";

const nf = (n: number | null | undefined, d = 0) => (n == null ? "—" : n.toLocaleString("en-IN", { maximumFractionDigits: d }));

function Missing({ what, how }: { what: string; how: string }) {
  return (
    <div className="m-5 rounded-lg border border-dashed border-line p-4 text-xs text-ink-muted">
      <b className="text-ink-soft">{what} not loaded yet.</b> {how}
    </div>
  );
}

function Change({ v, invert = false }: { v: number | null | undefined; invert?: boolean }) {
  if (v == null) return <span className="text-ink-faint">—</span>;
  const bad = invert ? v < 0 : v > 0;
  return <span className={cn("tabular-nums", v === 0 ? "text-ink-muted" : bad ? "text-rose-700" : "text-emerald-700")}>{v > 0 ? "+" : ""}{v.toFixed(1)}</span>;
}

// ------------------------------------------------------------------------------------ NFHS

function DistrictTable({ d, rows }: { d: any; rows: any[] }) {
  return (
    <table className="w-full text-xs">
      <thead className="sticky top-0 bg-white"><tr className="text-left text-ink-muted"><th className="py-1.5 font-medium">District</th><th className="font-medium">State</th><th className="text-right font-medium">{d.round}</th>{d.previous_round && <th className="text-right font-medium">vs {d.previous_round}</th>}</tr></thead>
      <tbody>{rows.map((r: any) => (
        <tr key={r.state + r.district} className="border-t border-line"><td className="py-1.5">{r.district}</td><td className="text-ink-muted">{r.state}</td>
          <td className="text-right font-semibold tabular-nums">{r.value}%</td>{d.previous_round && <td className="text-right"><Change v={r.change} /></td>}</tr>
      ))}</tbody>
    </table>
  );
}

function Burden({ geo }: { geo: any }) {
  const [openAll, setOpenAll] = useState<string | null>(null);
  const [ind, setInd] = useState("sugar_women");
  const [rnd, setRnd] = useState("");
  const [state, setState] = useState("");
  const q = useQuery({ queryKey: ["sig-nfhs", ind, rnd, state], placeholderData: keepPreviousData,
    queryFn: () => api<any>(`/api/playground/signals/nfhs?${new URLSearchParams({ ind, round: rnd, state })}`) });
  const d = q.data;
  const label = d?.indicators?.find((i: any) => i.key === d.indicator)?.label ?? "";
  const burdenSections: Section[] = d?.available ? [{ id: "districts", title: `${label} — every district`, icon: <HeartPulse size={16} />, subtitle: `${d.round}${d.previous_round ? ` vs ${d.previous_round}` : ""}${state ? ` · ${state}` : ""} · highest first`,
    render: () => <div className="max-w-3xl rounded-2xl bg-white p-4 ring-1 ring-inset ring-line"><DistrictTable d={d} rows={d.districts} /></div> }] : [];
  const groups = useMemo(() => {
    const g: Record<string, any[]> = {};
    for (const i of d?.indicators ?? []) (g[i.group] ??= []).push(i);
    return g;
  }, [d]);
  return (
    <ExpandedProvider sections={burdenSections} active={openAll} onActive={setOpenAll} title="Disease burden">
    <Card>
      <CardHeader icon={<HeartPulse size={16} />} title="Disease burden by district — NFHS"
        subtitle={d?.available ? `${label} · ${d.round}${d.previous_round ? ` vs ${d.previous_round}` : ""}${d.india != null ? ` · India ${d.india}%` : ""}` : "National Family Health Survey fact sheets"} />
      {q.error && <div className="p-5"><ErrorNote error={q.error} /></div>}
      {!d ? <div className="p-5"><Skeleton className="h-72" /></div> : !d.available ? (
        <Missing what="NFHS" how="Run `just fetch-nfhs` (NFHS-5 fact sheets with NFHS-4 alongside; add NFHS-6 with `just fetch-nfhs <file>`), then `just push-signals`." />
      ) : (
        <div className="p-5">
          <div className="mb-4 flex flex-wrap items-center gap-2">
            <select className="input h-9 w-80" value={d.indicator} onChange={(e) => { setInd(e.target.value); setState(""); }}>
              {Object.entries(groups).map(([g, items]) => <optgroup key={g} label={g}>{items.map((i: any) => <option key={i.key} value={i.key}>{i.label}</option>)}</optgroup>)}
            </select>
            {d.rounds.length > 1 && <Segmented value={d.round} onChange={(v: string) => setRnd(v)} options={d.rounds.map((r: string) => ({ value: r, label: r }))} />}
            {state && <button className="text-xs text-brand-700 hover:underline" onClick={() => setState("")}>{state} × — all India</button>}
          </div>
          <div className="grid gap-5 xl:grid-cols-[1.1fr_1fr]">
            <div>
              {geo ? <IndiaMap geo={geo} values={d.states} metricLabel="%" selected={state ? [state] : []} onPick={(s) => setState(s)} height={420} /> : <Skeleton className="h-96" />}
              {d.states.some((s: any) => s.from_districts) && <p className="mt-1 text-[11px] text-ink-faint">Some state values are unweighted means of their districts (no state row loaded).</p>}
            </div>
            <div>
              <div className="label mb-1.5">Highest districts{state ? ` in ${state}` : ""} <span className="font-normal normal-case text-ink-faint">· {nf(d.districts_total)} districts</span></div>
              <DistrictTable d={d} rows={d.districts.slice(0, 12)} />
              {d.districts_total > 12 && <button onClick={() => setOpenAll("districts")} className="mt-2 text-xs font-medium text-brand-700 hover:underline">All {nf(d.districts_total)} districts{state ? ` in ${state}` : ""} ↗</button>}
              {d.risers?.length > 0 && <div className="mt-3"><div className="label mb-1">Biggest rises since {d.previous_round}</div>
                <div className="flex flex-wrap gap-1">{d.risers.map((r: any) => <Badge key={r.state + r.district} tone="rose">{r.district} +{r.change}</Badge>)}</div></div>}
            </div>
          </div>
          <p className="mt-3 text-[11px] text-ink-faint">{d.note}</p>
        </div>
      )}
    </Card>
    </ExpandedProvider>
  );
}

// ------------------------------------------------------------------------------------ IDSP

function Outbreaks({ geo }: { geo: any }) {
  const [openAll, setOpenAll] = useState<string | null>(null);
  const [weeks, setWeeks] = useState<"8" | "13" | "26" | "52">("26");
  const [disease, setDisease] = useState("");
  const [state, setState] = useState("");
  const q = useQuery({ queryKey: ["sig-idsp", weeks, disease, state], placeholderData: keepPreviousData,
    queryFn: () => api<any>(`/api/playground/signals/outbreaks?${new URLSearchParams({ weeks, disease, state })}`) });
  const d = q.data;
  const obSections: Section[] = d?.available ? [{ id: "latest", title: "Latest outbreak reports", icon: <Activity size={16} />, subtitle: `${d.latest.length} most recent in this selection`, render: () => <LatestReports d={d} /> }] : [];
  return (
    <ExpandedProvider sections={obSections} active={openAll} onActive={setOpenAll} title="Outbreaks">
    <Card>
      <CardHeader icon={<Activity size={16} />} title="Outbreaks — IDSP weekly reports"
        subtitle={d?.available ? `${d.weeks.length} weeks (${d.weeks[0]} → ${d.weeks[d.weeks.length - 1]})${disease ? ` · ${disease}` : ""}${state ? ` · ${state}` : ""}` : "Integrated Disease Surveillance Programme"} />
      {q.error && <div className="p-5"><ErrorNote error={q.error} /></div>}
      {!d ? <div className="p-5"><Skeleton className="h-72" /></div> : !d.available ? (
        <Missing what="IDSP outbreak reports" how="Run `just fetch-idsp` (downloads the latest 26 weekly PDFs) or `just fetch-idsp <folder of PDFs>`, then `just push-signals`." />
      ) : (
        <div className="p-5">
          <div className="mb-4 flex flex-wrap items-center gap-2">
            <Segmented value={weeks} onChange={setWeeks} options={[{ value: "8", label: "8 wk" }, { value: "13", label: "13 wk" }, { value: "26", label: "26 wk" }, { value: "52", label: "52 wk" }]} />
            <select className="input h-9 w-64" value={disease} onChange={(e) => setDisease(e.target.value)}>
              <option value="">All diseases</option>{d.diseases_all.map((x: any) => <option key={x.name} value={x.name}>{x.name} ({x.count})</option>)}
            </select>
            {state && <button className="text-xs text-brand-700 hover:underline" onClick={() => setState("")}>{state} × — all India</button>}
          </div>
          <div className="grid gap-5 xl:grid-cols-[1.3fr_1fr]">
            <div>
              <div className="label mb-1.5">Outbreaks per week — top diseases</div>
              {d.series.months.length ? <TrendBars data={d.series} height={240} /> : <div className="text-xs text-ink-muted">No outbreaks in this selection.</div>}
              <div className="mt-4 overflow-x-auto">
                <table className="w-full text-xs">
                  <thead><tr className="text-left text-ink-muted"><th className="py-1 font-medium">Disease</th><th className="text-right font-medium">Outbreaks</th><th className="text-right font-medium">Cases</th><th className="text-right font-medium">Deaths</th><th className="pl-3 font-medium">Medicines it drives</th></tr></thead>
                  <tbody>{d.by_disease.map((r: any) => (
                    <tr key={r.disease} className="cursor-pointer border-t border-line hover:bg-slate-50" onClick={() => setDisease(r.disease === disease ? "" : r.disease)}>
                      <td className="py-1.5 font-medium">{r.disease}</td><td className="text-right tabular-nums">{nf(r.outbreaks)}</td><td className="text-right tabular-nums">{nf(r.cases)}</td>
                      <td className={cn("text-right tabular-nums", r.deaths > 0 && "text-rose-700")}>{nf(r.deaths)}</td>
                      <td className="pl-3"><div className="flex flex-wrap gap-1">{r.medicines.map((m: any) => <Badge key={m.name} tone={m.key ? "brand" : "slate"}>{m.name}{m.key ? " · tracked" : ""}</Badge>)}</div></td>
                    </tr>
                  ))}</tbody>
                </table>
              </div>
            </div>
            <div>
              {geo ? <IndiaMap geo={geo} values={d.states} metricLabel="outbreaks" selected={state ? [state] : []} onPick={(s) => setState(s)} height={360} /> : <Skeleton className="h-80" />}
              <div className="label mb-1 mt-3">Most affected districts</div>
              <RankBars rows={d.districts.map((x: any) => ({ name: `${x.district}, ${x.state}`, count: x.outbreaks }))} color="#e11d48" />
            </div>
          </div>
          <button onClick={() => setOpenAll("latest")} className="mt-4 text-xs font-medium text-brand-700 hover:underline">Latest {d.latest.length} reports ↗</button>
          <p className="mt-3 text-[11px] text-ink-faint">{d.note}</p>
        </div>
      )}
    </Card>
    </ExpandedProvider>
  );
}

function LatestReports({ d }: { d: any }) {
  return (
    <div className="rounded-2xl bg-white p-4 text-xs ring-1 ring-inset ring-line">
            <table className="w-full">
              <tbody>{d.latest.map((r: any, i: number) => (
                <tr key={(r.id ?? "") + i} className="border-t border-line"><td className="py-1 pr-2 tabular-nums text-ink-muted">{r.reported ?? r.start ?? r.week}</td><td className="pr-2">{r.district}, {r.state}</td>
                  <td className="pr-2">{r.disease}</td><td className="pr-2 text-right tabular-nums">{r.cases} cases{r.deaths ? ` · ${r.deaths} deaths` : ""}</td><td className="text-ink-muted">{r.status}</td></tr>
              ))}</tbody>
            </table>
    </div>
  );
}

// ------------------------------------------------------------------------------------ Comtrade

function Trade() {
  const [flow, setFlow] = useState<"export" | "import">("export");
  const [hs, setHs] = useState("");
  const q = useQuery({ queryKey: ["sig-trade", flow, hs], placeholderData: keepPreviousData,
    queryFn: () => api<any>(`/api/playground/signals/trade?${new URLSearchParams({ flow, hs })}`) });
  const d = q.data;
  const yi = d?.years?.length ? d.years.length - 1 : 0;
  return (
    <Card>
      <CardHeader icon={<Ship size={16} />} title="Pharma trade — UN Comtrade"
        subtitle={d?.available ? `India's reported trade, ${d.years[0]}–${d.years[d.years.length - 1]} · US$ million${d.mode === "preview" ? " · public preview data" : ""}` : "India's exports and imports by product class"} />
      {q.error && <div className="p-5"><ErrorNote error={q.error} /></div>}
      {!d ? <div className="p-5"><Skeleton className="h-72" /></div> : !d.available ? (
        <Missing what="UN Comtrade" how="Run `just fetch-comtrade` (set COMTRADE_KEY for the full API; without it the smaller public preview is used), then `just push-signals`." />
      ) : (
        <div className="p-5">
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead><tr className="text-left text-ink-muted"><th className="py-1 font-medium">HS</th><th className="font-medium">Product class</th>
                <th className="text-right font-medium">Exports {d.years[yi]}</th><th className="text-right font-medium">vs {d.years[Math.max(0, yi - 1)]}</th>
                <th className="text-right font-medium">Imports {d.years[yi]}</th><th className="text-right font-medium">Net</th></tr></thead>
              <tbody>{d.codes.map((c: any) => {
                const ex = c.exports_musd[yi], ex0 = c.exports_musd[Math.max(0, yi - 1)], im = c.imports_musd[yi];
                return (
                  <tr key={c.hs} className={cn("cursor-pointer border-t border-line hover:bg-slate-50", hs === c.hs && "bg-brand-50/50")} onClick={() => setHs(hs === c.hs ? "" : c.hs)}>
                    <td className="py-1.5 font-mono text-ink-muted">{c.hs}</td><td>{c.label} {c.group === "api" && <Badge>API</Badge>}</td>
                    <td className="text-right tabular-nums">{nf(ex)}</td><td className="text-right">{ex0 ? <Change v={Math.round((1000 * (ex - ex0)) / ex0) / 10} invert /> : "—"}{ex0 ? <span className="text-ink-faint">%</span> : null}</td>
                    <td className="text-right tabular-nums">{nf(im)}</td><td className={cn("text-right tabular-nums", ex - im < 0 ? "text-rose-700" : "text-emerald-700")}>{nf(ex - im)}</td>
                  </tr>
                );
              })}</tbody>
            </table>
          </div>
          <div className="mt-5 grid gap-5 lg:grid-cols-2">
            <div>
              <div className="mb-2 flex items-center justify-between gap-2">
                <div className="label">{flow === "export" ? "Where India sells" : "Where India buys"} · {hs ? `HS ${hs}` : "all codes"} · {d.latest_year}</div>
                <Segmented value={flow} onChange={setFlow} options={[{ value: "export", label: "Exports" }, { value: "import", label: "Imports" }]} />
              </div>
              <RankBars rows={d.partners.map((p: any) => ({ name: p.name, count: p.count, sub: `${p.share_pct}%` }))} color={flow === "export" ? "#0a9a7d" : "#6366f1"} format={(n) => `$${nf(n)}M`} />
            </div>
            <div>
              <div className="label mb-2">API imports from China — share of India's API-code imports</div>
              <div className="space-y-1.5">{d.china_api_share.map((r: any) => (
                <div key={r.year} className="flex items-center gap-2 text-xs">
                  <span className="w-10 tabular-nums text-ink-muted">{r.year}</span>
                  <div className="h-2 flex-1 rounded-full bg-slate-100"><div className="h-full rounded-full bg-rose-500" style={{ width: `${r.share_pct ?? 0}%` }} /></div>
                  <span className="w-28 text-right tabular-nums">{r.share_pct == null ? "—" : `${r.share_pct}%`} <span className="text-ink-faint">of ${nf(r.imports_musd)}M</span></span>
                </div>
              ))}</div>
            </div>
          </div>
          <p className="mt-3 text-[11px] text-ink-faint">{d.note}</p>
        </div>
      )}
    </Card>
  );
}

export function Signals() {
  const geo = useQuery({ queryKey: ["pg-geo"], queryFn: () => api<any>("/api/playground/geo/india"), staleTime: Infinity, retry: false });
  const m = useQuery({ queryKey: ["sig-meta"], queryFn: () => api<any>("/api/playground/signals/meta") });
  const s = m.data ?? {};
  return (
    <div className="space-y-5">
      <div className="grid gap-4 md:grid-cols-3">
        <Stat label="NFHS indicator values" value={s.nfhs?.records ?? "—"} icon={<HeartPulse size={18} />} tone="rose" hint={s.nfhs ? `retrieved ${s.nfhs.retrieved_at?.slice(0, 10)}` : "not loaded"} />
        <Stat label="IDSP outbreaks" value={s.idsp?.records ?? "—"} icon={<Activity size={18} />} tone="amber" delay={0.05} hint={s.idsp ? `retrieved ${s.idsp.retrieved_at?.slice(0, 10)}` : "not loaded"} />
        <Stat label="Comtrade partner-years" value={s.comtrade?.records ?? "—"} icon={<Ship size={18} />} tone="indigo" delay={0.1} hint={s.comtrade ? `retrieved ${s.comtrade.retrieved_at?.slice(0, 10)}` : "not loaded"} />
      </div>
      <Burden geo={geo.data} />
      <Outbreaks geo={geo.data} />
      <Trade />
    </div>
  );
}
