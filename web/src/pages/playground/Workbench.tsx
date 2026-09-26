import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { ExternalLink, FlaskConical } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { PolarAngleAxis, RadialBar, RadialBarChart, ResponsiveContainer } from "recharts";
import { RankBars, TrendBars } from "../../components/charts";
import { Badge, Card, CardHeader, ErrorNote, Skeleton } from "../../components/ui";
import { Estimate } from "../../components/ui/Estimate";
import { api } from "../../lib/api";
import { cn } from "../../lib/cn";
import { fmtDate, titleCase } from "../../lib/format";

const PILLARS = [["patent", "Patent readiness", "#10b996"], ["regulatory", "Regulatory clarity", "#6366f1"], ["demand", "Demand", "#f59e0b"], ["plant", "Plant fit", "#e11d48"]] as const;

function Field({ k, v }: { k: string; v: any }) {
  return <div className="grid grid-cols-[140px_1fr] gap-2 py-1 text-xs"><span className="text-ink-muted">{k}</span><span className="font-medium text-ink-soft">{v === "" || v == null ? "—" : v}</span></div>;
}

function Slider({ label, value, onChange, color }: { label: string; value: number; onChange: (v: number) => void; color: string }) {
  return (
    <label className="block text-xs">
      <div className="flex justify-between"><span>{label}</span><span className="font-semibold tabular-nums">{value}</span></div>
      <input type="range" min={0} max={100} value={value} onChange={(e) => onChange(Number(e.target.value))} className="w-full" style={{ accentColor: color }} />
    </label>
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
    queryFn: () => api<any>(`/api/playground/molecule/${key}?${new URLSearchParams({ plant_id: plant, w_patent: String(dw.patent), w_regulatory: String(dw.regulatory), w_demand: String(dw.demand), w_plant: String(dw.plant) })}`),
  });
  const d = q.data;
  const radial = useMemo(() => d ? PILLARS.map(([k, , c]) => ({ name: k, value: Math.round(d.score[`${k === "plant" ? "plant_fit" : k === "patent" ? "patent_readiness" : k === "regulatory" ? "regulatory_clarity" : "demand_attractiveness"}_score`]), fill: c })) : [], [d]);

  return (
    <div className="space-y-5">
      <Card className="flex flex-wrap items-center gap-3 p-4">
        <FlaskConical size={18} className="text-brand-700" />
        <select className="input h-10 w-72" value={key} onChange={(e) => setKey(e.target.value)}>{list.data?.molecules.map((m: any) => <option key={m.key} value={m.key}>{m.name}</option>)}</select>
        {d?.plants?.length > 0 && <select className="input h-10 w-72" value={d.plant_id ?? ""} onChange={(e) => setPlant(e.target.value)}>{d.plants.map((p: any) => <option key={p.asset_id} value={p.asset_id}>Scored for: {p.name}</option>)}</select>}
        {d && <span className="text-xs text-ink-muted">{d.patent.origin === "curated" ? "Curated profile" : d.patent.origin === "manual" ? "Added in the app" : "Built from public sources"} · {(d.patent.signals?.sources ?? []).length} sources</span>}
      </Card>
      {q.error && <ErrorNote error={q.error} />}
      {!d ? <Skeleton className="h-96" /> : (
        <div className={cn("space-y-5 transition-opacity", q.isFetching && "opacity-70")}>
          <div className="grid gap-5 xl:grid-cols-[1fr_1.3fr]">
            <Card>
              <CardHeader title="Four-pillar score" subtitle="Drag the weights — the score recomputes on the server" />
              <div className="grid grid-cols-[1fr_1fr] gap-4 p-5">
                <div className="relative">
                  <ResponsiveContainer width="100%" height={220}>
                    <RadialBarChart innerRadius="48%" outerRadius="100%" data={radial} startAngle={90} endAngle={-270}>
                      <PolarAngleAxis type="number" domain={[0, 100]} tick={false} />
                      <RadialBar dataKey="value" background cornerRadius={6} />
                    </RadialBarChart>
                  </ResponsiveContainer>
                  <div className="pointer-events-none absolute inset-0 grid place-items-center text-center"><div><div className="font-display text-3xl font-extrabold">{Math.round(d.score.total_score)}</div><div className="text-[10px] uppercase tracking-wider text-ink-muted">total</div></div></div>
                </div>
                <div className="space-y-3">
                  {PILLARS.map(([k, label, c]) => <Slider key={k} label={`${label} · ${radial.find((r) => r.name === k)?.value}`} value={(w as any)[k]} color={c} onChange={(v) => setW({ ...w, [k]: v })} />)}
                </div>
              </div>
              <div className="space-y-1.5 border-t border-line p-5 text-xs">
                {Object.entries(d.score.explanation ?? {}).map(([k, v]: any) => <div key={k}><b className="capitalize">{k}:</b> <span className="text-ink-soft">{v}</span></div>)}
                {d.score.warnings?.length > 0 && <div className="mt-2 flex flex-wrap gap-1">{d.score.warnings.map((x: string) => <Badge key={x} tone="amber">{x}</Badge>)}</div>}
              </div>
            </Card>

            <Card>
              <CardHeader title="Regulatory passport" subtitle={d.patent.brand_name ? `${d.patent.brand_name} · ${d.patent.originator}` : d.patent.originator} />
              <div className="grid gap-x-6 p-5 md:grid-cols-2">
                <div>
                  <Field k="US LOE" v={<span className="flex items-center gap-1">{fmtDate(d.patent.estimated_loe_us)}<Estimate field="loe" prov={d.patent.provenance?.loe_us} /></span>} />
                  <Field k="EU LOE" v={<span className="flex items-center gap-1">{fmtDate(d.patent.estimated_loe_eu)}<Estimate field="loe" prov={d.patent.provenance?.loe_eu} /></span>} />
                  <Field k="India LOE" v={fmtDate(d.patent.estimated_loe_in)} />
                  <Field k="FTO risk" v={<span className="flex items-center gap-1 capitalize">{d.patent.fto_risk}<Estimate field="fto_risk" prov={d.patent.provenance?.fto_risk} /></span>} />
                  <Field k="Therapeutic area" v={d.patent.therapeutic_area} />
                  <Field k="Market size" v={d.patent.market_size_usd_bn ? `$${d.patent.market_size_usd_bn} bn` : null} />
                </div>
                <div>
                  <Field k="Reference drug (RLD)" v={d.regulatory?.rld} />
                  <Field k="RLD holder" v={d.regulatory?.rld_applicant} />
                  <Field k="TE code" v={d.regulatory?.te_code} />
                  <Field k="Dosage form / strength" v={[d.regulatory?.dosage_form, d.regulatory?.strength].filter(Boolean).join(" · ")} />
                  <Field k="BCS class" v={d.regulatory?.bcs_class} />
                  <Field k="Readiness" v={d.regulatory?.readiness} />
                </div>
              </div>
              <div className="border-t border-line px-5 py-3">
                <div className="label mb-2">Pharmacopoeia monographs</div>
                <div className="grid gap-2 md:grid-cols-3">{[["IP", d.regulatory?.ip_2026_monograph], ["Ph. Eur.", d.regulatory?.ph_eur_monograph], ["USP", d.regulatory?.usp_monograph]].map(([k, v]) => (
                  <div key={k} className={cn("rounded-lg p-2.5 text-[11px]", v ? "bg-emerald-50 text-emerald-900" : "bg-slate-50 text-ink-faint")}><b>{k}</b><div className="line-clamp-3">{v || "not listed"}</div></div>
                ))}</div>
                {(d.regulatory?.exclusivity ?? []).length > 0 && <div className="mt-3 flex flex-wrap gap-1.5">{d.regulatory.exclusivity.map((x: any, i: number) => <Badge key={i} tone={x.expiry_date && new Date(x.expiry_date) > new Date() ? "rose" : "slate"}>{x.type} · {fmtDate(x.expiry_date)}</Badge>)}</div>}
                {(d.regulatory?.analytical_specs ?? []).length > 0 && <div className="mt-3 text-[11px] text-ink-soft"><b>Key tests:</b> {d.regulatory.analytical_specs.join(" · ")}</div>}
              </div>
            </Card>
          </div>

          <div className="grid gap-5 xl:grid-cols-3">
            <Card>
              <CardHeader title="Where it can be sold" subtitle="Per-country patent status" />
              <div className="space-y-1.5 p-5">{(d.patent.geo_coverage ?? []).map((g: any) => (
                <div key={g.country_code} className="flex items-center justify-between rounded-lg bg-slate-50 px-3 py-1.5 text-xs">
                  <span className="font-medium">{g.country_name}</span>
                  <span className="flex items-center gap-2"><span className="text-ink-muted">{g.loe_date ? fmtDate(g.loe_date) : ""}</span><Badge tone={g.market_status === "off_patent" ? "brand" : g.market_status === "loe_pending" ? "amber" : "rose"}>{g.market_status.replace("_", " ")}</Badge></span>
                </div>))}</div>
            </Card>
            <Card>
              <CardHeader title="Demand" subtitle={d.demand?.disease_area} />
              <div className="p-5">
                <Field k="Trials (total / Ph 3+)" v={d.demand ? `${d.demand.trial_count_total} / ${d.demand.trial_count_phase_3_plus}` : null} />
                <Field k="Trend" v={d.demand?.growth_trend} />
                <Field k="Cluster" v={d.demand?.cluster} />
                <Field k="Generic competitors" v={d.demand?.competitor_anda_count} />
                <Field k="Prevalence India / global" v={d.demand && (d.demand.disease_prevalence_india_millions || d.demand.disease_prevalence_global_millions) ? `${d.demand.disease_prevalence_india_millions} M / ${d.demand.disease_prevalence_global_millions} M` : null} />
                <Field k="Buyer activity / momentum" v={d.demand ? `${d.demand.buyer_activity_score} / ${d.demand.market_momentum_score}` : null} />
              </div>
            </Card>
            <Card>
              <CardHeader title="Manufacturing complexity" subtitle={`${titleCase(d.complexity.modality)} · ${titleCase(d.complexity.drug_form)}${d.complexity.sterility_required ? " · sterile" : ""}`} />
              <div className="space-y-2 p-5">
                {[["Process", d.complexity.process_complexity_score], ["Analytical", d.complexity.analytical_complexity_score], ["Biologic", d.complexity.biologic_complexity_score]].map(([k, v]: any) => (
                  <div key={k} className="text-xs"><div className="flex justify-between"><span>{k}</span><b>{v}/10</b></div><div className="mt-1 h-1.5 rounded-full bg-slate-100"><div className="h-full rounded-full bg-brand-500" style={{ width: `${v * 10}%` }} /></div></div>
                ))}
                <div className="flex flex-wrap gap-1 pt-2">{(d.complexity.critical_quality_attributes ?? []).map((c: string) => <Badge key={c}>{c.replace(/_/g, " ")}</Badge>)}</div>
                <div className="flex flex-wrap gap-1 pt-1">{(d.complexity.gmp_pillars ?? []).filter((p: any) => p.applies).map((p: any) => <Badge key={p.pillar_id} tone="indigo">{p.title}</Badge>)}</div>
              </div>
            </Card>
          </div>

          {d.nsq && (
            <Card>
              <CardHeader title="CDSCO NSQ record — all of India" subtitle={`${d.nsq.alerts} alerts across ${d.nsq.manufacturers} manufacturers`} />
              <div className="grid gap-4 p-5 lg:grid-cols-[1.4fr_1fr_1fr]">
                <TrendBars data={d.nsq.trend} height={180} />
                <div><div className="label mb-2">Why it fails</div><RankBars rows={d.nsq.categories} color="#e11d48" /></div>
                <div><div className="label mb-2">Who makes the failing batches</div><RankBars rows={d.nsq.top_manufacturers} color="#f59e0b" /></div>
              </div>
            </Card>
          )}

          {(d.orange_book_curated || d.pharmacopeia) && (
            <div className="grid gap-5 xl:grid-cols-2">
              {d.orange_book_curated && (
                <Card>
                  <CardHeader title="FDA Orange Book (curated record)" subtitle={d.orange_book_curated.provenance?.source_ref} />
                  <div className="p-5">
                    <Field k="TE codes" v={(d.orange_book_curated.te_codes ?? []).join(", ")} />
                    <Field k="RLD applicant" v={d.orange_book_curated.rld_applicant} />
                    <Field k="Application / approval" v={`${d.orange_book_curated.rld_app_number} · ${d.orange_book_curated.rld_approval_date}`} />
                    <Field k="Dosage forms" v={(d.orange_book_curated.dosage_forms ?? []).join(", ")} />
                    <Field k="Strengths" v={(d.orange_book_curated.strengths ?? []).join(", ")} />
                    <Field k="Marketing status" v={(d.orange_book_curated.marketing_statuses ?? []).join(", ")} />
                    {d.orange_book_curated.provenance?.reference_url && <a href={d.orange_book_curated.provenance.reference_url} target="_blank" rel="noreferrer" className="mt-2 inline-flex items-center gap-1 text-xs text-brand-700 hover:underline">Source (retrieved {d.orange_book_curated.provenance.retrieved_at}) <ExternalLink size={11} /></a>}
                  </div>
                </Card>
              )}
              {d.pharmacopeia && (
                <Card>
                  <CardHeader title="IP vs Ph. Eur. vs USP" subtitle="Method-by-method comparison — where an Indian-spec batch may not meet the export spec" />
                  <div className="overflow-x-auto">
                    <table className="w-full text-[11px]"><thead><tr className="border-y border-line bg-slate-50/70 text-left text-[10px] uppercase tracking-wider text-ink-muted"><th className="px-3 py-2">Test</th><th className="px-3 py-2">IP 2026</th><th className="px-3 py-2">Ph. Eur.</th><th className="px-3 py-2">USP</th><th className="px-3 py-2">Verdict</th></tr></thead>
                      <tbody>{d.pharmacopeia.map((r: any) => (
                        <tr key={r.section} className="border-b border-line/60 align-top">
                          <td className="px-3 py-2 font-semibold capitalize">{r.section}</td>
                          {["IP 2026", "Ph. Eur.", "USP"].map((ph) => <td key={ph} className="max-w-[200px] px-3 py-2 text-ink-soft">{r.methods[ph]?.raw_text ?? <span className="text-ink-faint">—</span>}</td>)}
                          <td className="px-3 py-2"><Badge tone={r.significance === "NSQ_RELEVANT" ? "rose" : r.significance === "EQUIVALENT" ? "brand" : "slate"}>{String(r.significance).replace(/_/g, " ").toLowerCase()}</Badge><div className="mt-1 text-ink-muted">{r.rationale}</div></td>
                        </tr>))}</tbody></table>
                  </div>
                </Card>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
