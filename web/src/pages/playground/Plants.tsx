// Plant registry: India's manufacturing plants from CDSCO's official lists (WHO-GMP
// certified units + SUGAM approved sites), what each is permitted to make, and the NSQ
// alerts linked to each plant. The "rates" card is the denominator view: how many plants
// can make X, and how many of them had NSQ alerts.

import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { AlertTriangle, BadgeCheck, ChevronLeft, ChevronRight, ExternalLink, Factory, FlaskConical, KeyRound, MapPin, Search, ShieldAlert, Syringe } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { Badge, Button, Card, CardHeader, Drawer, Empty, ErrorNote, PageSkeleton, Segmented, Skeleton, Stat } from "../../components/ui";
import { api } from "../../lib/api";
import { BasisLegend, CoverageSections } from "../../components/capabilities";
import { cn } from "../../lib/cn";
import { fmtMonth } from "../../lib/format";
import { ExpandedProvider, Frame, type Section } from "../../components/ui/Expanded";

type Rate = { key: string; label: string; plants: number; plants_with_nsq: number; alerts: number; share_with_nsq: number | null; alerts_per_100_plants: number | null };
type Labels = { capabilities: Record<string, string>; segregated: Record<string, string> };

const SEG_TONE: Record<string, string> = {
  beta_lactam: "bg-amber-50 text-amber-800 ring-amber-200", cephalosporin: "bg-orange-50 text-orange-800 ring-orange-200",
  carbapenem: "bg-yellow-50 text-yellow-800 ring-yellow-200", hormone: "bg-pink-50 text-pink-800 ring-pink-200",
  steroid: "bg-fuchsia-50 text-fuchsia-800 ring-fuchsia-200", cytotoxic: "bg-rose-50 text-rose-800 ring-rose-200",
  immunosuppressant: "bg-violet-50 text-violet-800 ring-violet-200", potent_other: "bg-red-50 text-red-800 ring-red-200",
};
const MATCH_WORD: Record<string, string> = { site: "same company + PIN", site_fuzzy: "same PIN, similar name", company: "same company, same town or only plant in the state (no shared PIN)" };
const nf = (n: number | null | undefined, d = 0) => (n == null ? "—" : n.toLocaleString("en-IN", { maximumFractionDigits: d, minimumFractionDigits: d }));

function FormChip({ k, labels, dim }: { k: string; labels?: Labels; dim?: boolean }) {
  return <span className={cn("rounded-md px-1.5 py-0.5 text-[10.5px]", dim ? "bg-slate-50 text-ink-muted" : "bg-slate-100 text-ink-soft")}>{labels?.capabilities[k] ?? k.replace(/_/g, " ")}</span>;
}

function SegChip({ k, forms, labels }: { k: string; forms?: string[]; labels?: Labels }) {
  const f = (forms ?? []).filter((x) => x !== "unspecified");
  return (
    <span className={cn("rounded-md px-1.5 py-0.5 text-[10.5px] font-medium ring-1 ring-inset", SEG_TONE[k] ?? "bg-slate-50 text-ink-soft ring-line")}
      title={f.length ? `Separate ${labels?.segregated[k] ?? k} block for: ${f.map((x) => labels?.capabilities[x] ?? x).join(", ")}` : undefined}>
      {labels?.segregated[k] ?? k.replace(/_/g, " ")}{f.length ? ` · ${f.length}` : ""}
    </span>
  );
}

export function RegistryBadges({ p }: { p: any }) {
  return (
    <div className="flex flex-wrap gap-1">
      {p.who_gmp && <Badge tone="brand"><BadgeCheck size={11} /> WHO-GMP</Badge>}
      {p.eu_status === "non_compliant" ? <span title={`EU statement of non-compliance ${p.eu_ncr ?? ""}`}><Badge tone="rose"><ShieldAlert size={11} /> EU non-compliant</Badge></span>
        : p.eu_gmp ? <span title={`EU GMP certificate, last inspected ${p.eu_last}`}><Badge tone="indigo"><BadgeCheck size={11} /> EU GMP</Badge></span>
          : p.eu_status === "compliant" ? <span title={`EU GMP inspection ${p.eu_last} — older than 3 years`}><Badge>EU GMP (old)</Badge></span> : null}
      {p.fda_import_alert ? <span title="On FDA Import Alert 66-40 (drug GMP red list)"><Badge tone="rose"><ShieldAlert size={11} /> FDA import alert</Badge></span>
        : p.fda_oai ? <span title={`FDA inspection ${p.fda_last} classified OAI (Official Action Indicated)`}><Badge tone="rose"><ShieldAlert size={11} /> FDA OAI</Badge></span>
          : p.fda_ok ? <span title={`FDA inspection ${p.fda_last} classified ${p.fda_code}`}><Badge tone="sky"><BadgeCheck size={11} /> US FDA</Badge></span>
            : p.fda_code ? <span title={`FDA inspection ${p.fda_last} classified ${p.fda_code} — older than 5 years`}><Badge>US FDA (old)</Badge></span> : null}
      {p.schedule_c && <Badge tone="indigo"><Syringe size={11} /> Schedule C</Badge>}
      {p.sterile && !p.schedule_c && <Badge tone="sky">Sterile</Badge>}
      {p.api && <Badge><FlaskConical size={11} /> API</Badge>}
      {p.loan_licensees?.length > 0 && <Badge tone="amber"><KeyRound size={11} /> Loan licence ×{p.loan_licensees.length}</Badge>}
    </div>
  );
}

// ---------------------------------------------------------------------------------- rates

function RatesCard({ s: all, onPick, limit, onExpand, bare }: { s: any; onPick: (dim: string, key: string) => void; limit?: number; onExpand?: () => void; bare?: boolean }) {
  const [finished, setFinished] = useState(false);
  const fin = useQuery({ queryKey: ["plants-summary", "finished"], queryFn: () => api<any>("/api/plants/summary?exclude_api_only=true"), enabled: finished });
  const s = finished && fin.data ? fin.data : all;
  const [dim, setDim] = useState<"capabilities" | "segregated" | "states" | "tiers" | "breadth">("capabilities");
  const [metric, setMetric] = useState<"share" | "per100">("share");
  const rows: Rate[] = useMemo(() => (s[dim] as Rate[]).filter((r) => r.plants >= (dim === "states" ? 5 : 3)), [s, dim]);
  const val = (r: Rate) => (metric === "share" ? r.share_with_nsq ?? 0 : r.alerts_per_100_plants ?? 0);
  const max = Math.max(1, ...rows.map(val));
  const overall = s.plants ? (100 * s.with_nsq) / s.plants : 0;
  return (
    <Frame bare={bare} title="Who fails, per plant that can make it"
        subtitle={<span>Registry plants grouped by what they are permitted to make, and how many had NSQ alerts. Dashed line: all registry plants ({nf(overall, 1)}% with alerts). Click a row to list those plants.</span>}>
      <div className="px-5 pb-5 pt-3">
        <div className="mb-4 flex flex-wrap gap-2">
          <Segmented value={dim} onChange={setDim} options={[{ value: "capabilities", label: "Dosage form" }, { value: "segregated", label: "Segregated block" }, { value: "states", label: "State" }, { value: "tiers", label: "Certification" }, { value: "breadth", label: "Breadth" }]} />
          <Segmented value={metric} onChange={setMetric} options={[{ value: "share", label: "% plants with NSQ" }, { value: "per100", label: "Alerts / 100 plants" }]} />
          <label className="flex cursor-pointer items-center gap-2 rounded-xl bg-slate-50 px-3 text-xs text-ink-soft ring-1 ring-inset ring-line" title={`NSQ tests finished medicines, so plants that make only APIs can never appear in it (${all.api_only_plants ?? "?"} such plants). Leave them out for a fair comparison.`}>
            <input type="checkbox" checked={finished} onChange={(e) => setFinished(e.target.checked)} className="accent-brand-600" />
            Finished-dose plants only{finished && fin.isFetching ? " …" : ""}
          </label>
        </div>
        <div className="mb-2 grid grid-cols-[minmax(0,1.7fr)_60px_minmax(0,1.6fr)_72px] gap-3 text-[10.5px] font-semibold uppercase tracking-wider text-ink-muted">
          <span>{dim === "capabilities" ? "Permitted to make" : dim === "segregated" ? "Separate block" : dim === "states" ? "State" : dim === "tiers" ? "Listed as" : "Dosage forms per plant"}</span>
          <span className="text-right">Plants</span><span /><span className="text-right">{metric === "share" ? "With NSQ" : "Alerts/100"}</span>
        </div>
        <div className="space-y-1.5">
          {rows.slice(0, limit ?? rows.length).map((r) => (
            <button key={r.key} onClick={() => onPick(dim, r.key)} disabled={dim === "tiers" || dim === "breadth"}
              className="grid w-full grid-cols-[minmax(0,1.7fr)_60px_minmax(0,1.6fr)_72px] items-center gap-3 rounded-lg px-1 py-1 text-left text-[13px] hover:bg-slate-50 disabled:cursor-default disabled:hover:bg-transparent">
              <span className="font-medium leading-snug text-ink-soft" title={r.label}>{r.label}</span>
              <span className="text-right tabular-nums text-ink-muted">{nf(r.plants)}</span>
              <span className="relative h-2.5 overflow-hidden rounded-full bg-slate-100">
                <span className="absolute inset-y-0 left-0 rounded-full bg-rose-400/80" style={{ width: `${(100 * val(r)) / max}%` }} />
                {metric === "share" && <span className="absolute inset-y-[-2px] w-px border-l border-dashed border-ink-muted" style={{ left: `${(100 * overall) / max}%` }} />}
              </span>
              <span className="text-right tabular-nums font-semibold" title={`${r.plants_with_nsq} of ${r.plants} plants · ${r.alerts} alerts`}>
                {metric === "share" ? `${nf(r.share_with_nsq, 1)}%` : nf(r.alerts_per_100_plants, 0)}
              </span>
            </button>
          ))}
        </div>
        {limit && rows.length > limit && onExpand && <button onClick={onExpand} className="mt-2 w-full rounded-lg py-2 text-center text-xs font-medium text-brand-700 hover:bg-brand-50">All {rows.length} rows ↗</button>}
        <p className="mt-4 text-[11.5px] leading-relaxed text-ink-muted">{finished ? `Leaving out ${s.api_only_plants} API-only plants. ` : ""}{s.caveat} Small groups swing a lot: read rates on fewer than ~30 plants as hints.</p>
      </div>
    </Frame>
  );
}

// ---------------------------------------------------------------------------------- detail

const FDA_CODE: Record<string, [string, string]> = {
  NAI: ["No Action Indicated", "brand"], VAI: ["Voluntary Action Indicated", "amber"], OAI: ["Official Action Indicated", "rose"],
};

function FdaPanel({ fda, records }: { fda: any; records?: any[] }) {
  const recs = records?.length ? records : [fda];
  return (
    <div>
      <div className="label mb-1.5 flex items-center gap-2">US FDA — inspection classifications
        {fda.import_alert ? <Badge tone="rose">Import Alert 66-40</Badge> : fda.acceptable ? <Badge tone="sky">acceptable · {fda.last_code} {fda.last_inspection}</Badge>
          : fda.last_code ? <Badge tone={(FDA_CODE[fda.last_code]?.[1] ?? "slate") as any}>{fda.last_code} {fda.last_inspection}</Badge> : null}
      </div>
      {recs.map((r: any) => (
        <div key={r.fei} className="mb-2 rounded-lg border border-line p-2.5 text-xs">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <span className="font-medium">{r.name} <span className="font-normal text-ink-muted">· FEI {r.fei}{r.address ? ` · ${r.address}` : ""}</span></span>
            {r.profile && <a href={r.profile} target="_blank" rel="noreferrer" className="text-brand-700 hover:underline">FDA firm profile</a>}
          </div>
          <ul className="mt-1.5 space-y-0.5">{(r.inspections ?? []).slice(0, 6).map((i: any, n: number) => (
            <li key={(i.id ?? "") + n} className="flex flex-wrap items-center gap-2">
              <span className="w-20 tabular-nums text-ink-muted">{i.date ?? "—"}</span>
              <Badge tone={(FDA_CODE[i.code]?.[1] ?? "slate") as any}>{i.code || "?"}</Badge>
              <span className="text-ink-soft">{FDA_CODE[i.code]?.[0] ?? ""}{i.project_area ? ` · ${i.project_area}` : ""}{i.citations ? " · citations posted" : ""}</span>
            </li>
          ))}</ul>
          {r.oai_count > 0 && <div className="mt-1 text-rose-700">{r.oai_count} OAI outcome{r.oai_count > 1 ? "s" : ""} on record</div>}
        </div>
      ))}
    </div>
  );
}

function EuPanel({ eu }: { eu: any }) {
  const [all, setAll] = useState(false);
  const leaf = (eu.scope ?? []).filter((c: any) => c.code.split(".").length >= 3 || c.code.startsWith("1.6") || c.code.startsWith("3."));
  const ncr = (eu.documents ?? []).filter((d: any) => d.type === "NCR");
  return (
    <div>
      <div className="label mb-1.5 flex items-center gap-2">EU GMP — EudraGMDP
        {eu.status === "non_compliant" ? <Badge tone="rose">non-compliant since {eu.last_ncr}</Badge> : eu.certified ? <Badge tone="indigo">certified · inspected {eu.last_gmp_inspection}</Badge>
          : eu.last_gmp_inspection ? <Badge>last certificate {eu.last_gmp_inspection} (&gt; 3 years)</Badge> : null}
      </div>
      {ncr.map((d: any) => (
        <div key={d.number} className="mb-2 rounded-lg bg-rose-50 p-3 text-xs text-rose-900">
          <div className="font-semibold">Statement of non-compliance {d.number} · {d.authority} · inspected {d.inspection_date}</div>
          {d.ncr?.nature && <p className="mt-1 leading-relaxed">{d.ncr.nature}</p>}
          {d.ncr?.action && <p className="mt-1"><b>Action:</b> {d.ncr.action}</p>}
        </div>
      ))}
      {leaf.length > 0 && (
        <div className="rounded-lg border border-line p-2.5 text-xs">
          <div className="mb-1 text-ink-muted">Approved operations (certificate Part 2)</div>
          <ul className="space-y-0.5">{(all ? leaf : leaf.slice(0, 12)).map((c: any) => (
            <li key={c.code + c.label}><span className="mr-1.5 font-mono text-ink-faint">{c.code}</span>{c.label}{c.details?.length ? <span className="text-ink-muted"> — {c.details.join("; ")}</span> : null}</li>
          ))}</ul>
          {leaf.length > 12 && <button className="mt-1 text-brand-700 hover:underline" onClick={() => setAll(!all)}>{all ? "fewer" : `all ${leaf.length}`}</button>}
        </div>
      )}
      {eu.substances?.length > 0 && <div className="mt-2 text-xs"><span className="text-ink-muted">Active substances inspected: </span>{eu.substances.slice(0, 30).join(", ")}{eu.substances.length > 30 ? ` +${eu.substances.length - 30}` : ""}</div>}
      <div className="mt-2 text-[11px] text-ink-muted">{(eu.documents ?? []).map((d: any) => `${d.type} ${d.number} (${d.authority ?? "?"}, ${d.inspection_date ?? "?"})`).join(" · ")}</div>
    </div>
  );
}

function PlantDrawer({ id, labels, onClose }: { id?: string; labels?: Labels; onClose: () => void }) {
  const { data: p, error } = useQuery({ queryKey: ["plant", id], queryFn: () => api<any>(`/api/plants/${encodeURIComponent(id!)}`), enabled: !!id });
  const c = p?.capabilities;
  return (
    <Drawer open={!!id} onClose={onClose} title={p?.name ?? "Plant"} subtitle={p ? <RegistryBadges p={p.brief} /> : undefined} width={760}>
      {error ? <ErrorNote error={error} /> : !p ? <div className="text-sm text-ink-muted">Loading…</div> : (
        <div className="space-y-5 text-sm">
          <div className="flex items-start gap-2 text-ink-soft"><MapPin size={15} className="mt-0.5 shrink-0" />
            <div>{p.address || "—"}<div className="text-xs text-ink-muted">{[p.district, p.state, p.pin].filter(Boolean).join(" · ") || "no location parsed"}</div></div>
          </div>
          {p.aliases?.length > 0 && <div className="text-xs text-ink-muted">Also listed as: {p.aliases.join(" · ")}</div>}

          <div className="grid grid-cols-3 gap-3">
            <div className="rounded-xl bg-slate-50 p-3"><div className="label">NSQ alerts linked</div><div className="mt-1 font-display text-xl font-bold">{p.nsq?.alerts ?? 0}</div>
              <div className="text-[11px] text-ink-muted">{p.nsq ? `${fmtMonth(p.nsq.first)} – ${fmtMonth(p.nsq.last)}` : "none on record"}</div></div>
            <div className="rounded-xl bg-slate-50 p-3"><div className="label">Dosage forms</div><div className="mt-1 font-display text-xl font-bold">{c.dosage_forms.length}</div>
              <div className="text-[11px] text-ink-muted">{Object.keys(c.segregated).length} segregated block(s)</div></div>
            <div className="rounded-xl bg-slate-50 p-3"><div className="label">WHO-GMP</div><div className="mt-1 font-semibold">{p.who_gmp_certified ? "Certified" : "Not in the list"}</div>
              <div className="text-[11px] text-ink-muted">{p.who_gmp_valid_until ? `valid until ${p.who_gmp_valid_until}` : p.who_gmp_certified ? "validity not stated" : ""}</div></div>
          </div>

          <div>
            <div className="label mb-1.5">Permitted to make</div>
            <div className="flex flex-wrap gap-1.5">{c.dosage_forms.length ? c.dosage_forms.map((f: string) => <Badge key={f}>{labels?.capabilities[f] ?? f}</Badge>) : <span className="text-xs text-ink-muted">No dosage form in CDSCO's wording{c.therapeutic.length ? " — therapeutic classes only" : ""}.</span>}</div>
            {Object.keys(c.segregated).length > 0 && (
              <div className="mt-3 space-y-1.5">
                {Object.entries(c.segregated).map(([k, forms]: any) => (
                  <div key={k} className="flex flex-wrap items-center gap-1.5 text-xs"><SegChip k={k} labels={labels} /><span className="text-ink-muted">block for</span>
                    {forms.map((f: string) => <FormChip key={f} k={f} labels={labels} />)}</div>
                ))}
              </div>
            )}
            {c.therapeutic.length > 0 && <div className="mt-2 text-xs text-ink-muted">Therapeutic classes: {c.therapeutic.map((t: string) => t.replace(/_/g, " ")).join(", ")}</div>}
          </div>

          <div>
            <div className="mb-1.5 flex items-center justify-between"><span className="label">Capability coverage implied by this listing</span><BasisLegend /></div>
            <p className="mb-2.5 text-[11.5px] text-ink-muted">What Schedule M / WHO-GMP require for the products CDSCO lists ({p.catalog.required}), and what is usual for them ({p.catalog.inferred}). Hover a chip for the rule. Equipment-level detail needs a source (EU GMP certificate, inspection report) or the company.</p>
            <CoverageSections sections={p.catalog.sections} other={p.catalog.other} />
          </div>

          <div>
            <div className="label mb-1.5">Evidence — CDSCO's own words</div>
            <div className="space-y-1.5">
              {c.evidence.map((e: any, i: number) => (
                <div key={i} className="rounded-lg border border-line p-2.5 text-xs">
                  <div className="text-ink">{e.text}</div>
                  <div className="mt-1 flex flex-wrap items-center gap-1 text-ink-faint">
                    <span>{e.source === "cdsco_sugam" ? "SUGAM licence" : "WHO-GMP list"}{e.ref ? ` · ${e.ref}` : ""}</span>
                    {e.issued && <span>· issued {e.issued}</span>}{e.valid_until && <span>· valid until {e.valid_until}</span>}
                    {e.forms?.map((f: string) => <FormChip key={f} k={f} labels={labels} dim />)}
                    {e.segregated?.map((s: string) => <SegChip key={s} k={s} labels={labels} />)}
                  </div>
                </div>
              ))}
            </div>
          </div>

          {p.eu && <EuPanel eu={p.eu} />}
          {p.fda && <FdaPanel fda={p.fda} records={p.fda_records} />}

          {p.licences?.length > 0 && (
            <div>
              <div className="label mb-1.5">Manufacturing licences (SUGAM)</div>
              <table className="w-full text-xs">
                <thead><tr className="border-b border-line text-left text-[10.5px] uppercase tracking-wider text-ink-muted"><th className="py-1.5">Licence</th><th>Form</th><th>Covers</th><th>Site</th><th>Valid</th></tr></thead>
                <tbody>{p.licences.map((l: any) => (
                  <tr key={`${l.number}-${l.form}`} className="border-b border-line/60">
                    <td className="py-1.5 font-mono">{l.number}</td><td>{l.form}</td><td className="max-w-[240px] text-ink-muted">{l.covers}</td><td>{l.site_type}</td>
                    <td className={cn("tabular-nums", l.expires && l.expires < new Date().toISOString().slice(0, 10) && "text-rose-700")}>{l.issued} → {l.expires}</td>
                  </tr>
                ))}</tbody>
              </table>
              {p.loan_licensees?.length > 0 && <div className="mt-2 rounded-lg bg-amber-50 p-2.5 text-xs text-amber-900"><b>Loan licensees made here:</b> {p.loan_licensees.join(" · ")} — brands sold under these names are manufactured at this plant.</div>}
            </div>
          )}

          <div>
            <div className="label mb-1.5">NSQ alerts at this plant</div>
            {!p.nsq ? <div className="text-xs text-ink-muted">No site in the NSQ directory matched this plant (company name + PIN / state).</div> : (
              <>
                <div className="mb-2 flex flex-wrap gap-1.5">{Object.entries(p.nsq.forms).map(([f, n]: any) => <Badge key={f}>{f} · {n}</Badge>)}</div>
                {p.nsq.outside_capabilities?.length > 0 && (
                  <div className="mb-2 flex items-start gap-2 rounded-lg bg-rose-50 p-2.5 text-xs text-rose-900"><AlertTriangle size={14} className="mt-0.5 shrink-0" />
                    <span>Alerted in <b>{p.nsq.outside_capabilities.join(", ")}</b>, which this plant's WHO-GMP listing does not cover — made under a non-WHO-GMP licence, on loan elsewhere, or a mislabelled maker.</span></div>
                )}
                {p.nsq.sites.map((s: any) => (
                  <div key={s.id} className="mb-1 flex items-center justify-between rounded-lg border border-line px-3 py-2 text-xs">
                    <span><b>{s.company}</b> <span className="text-ink-muted">· {s.pincode || "no PIN"} · matched on {MATCH_WORD[s.match] ?? s.match}</span></span>
                    <span className="tabular-nums">{s.alerts} alerts · last {fmtMonth(s.last)}</span>
                  </div>
                ))}
              </>
            )}
          </div>

          <div className="flex flex-wrap gap-3 text-xs">
            {p.source_links?.map((s: any) => s.url && <a key={s.key} href={s.url} target="_blank" rel="noreferrer" className="flex items-center gap-1 text-brand-700 hover:underline"><ExternalLink size={12} />{s.key === "cdsco_sugam" ? "CDSCO approved manufacturing sites" : s.key === "eudragmdp" ? "EudraGMDP (search this site)" : "CDSCO WHO-GMP certified units"}</a>)}
          </div>
        </div>
      )}
    </Drawer>
  );
}

// ---------------------------------------------------------------------------------- page

function AboutDetail({ s }: { s: any }) {
  return (
    <div className="max-w-3xl space-y-4 text-[13.5px] leading-relaxed text-ink-soft">
      <p><b>WHO-GMP certified units</b> ({nf(s.who_gmp)}): CDSCO's list of plants certified for export certificates (COPP), with the "category of drugs permitted" for each — dosage forms, separate blocks for beta-lactams, cephalosporins, hormones or cytotoxics, and certificate dates.</p>
      <p><b>Approved manufacturing sites</b> (SUGAM, {nf(s.sugam)}): licence number, form (Form 28 = Schedule C: sterile and biological products), own or loan licence, and the brand owner making there on loan.</p>
      <p><b>EU GMP (EudraGMDP)</b>{s.meta?.eudragmdp ? ` — ${nf(s.meta.eudragmdp.eu_sites)} Indian sites, ${nf(s.meta.eudragmdp.eu_added)} not on CDSCO's lists` : " — not fetched yet"}: certificates from EU / EEA inspections, each listing the approved operations in the EU's coded format (e.g. 1.1.1.2 lyophilisates, 1.6.1 sterility testing, 3.1 API synthesis) — marked "stated" on the plant — and statements of non-compliance with what failed. Sites of one company at one PIN are kept apart when their plot numbers differ.</p>
      <p><b>US FDA inspections</b>{s.meta?.fda_inspections ? ` — ${nf(s.meta.fda_inspections.fda_sites)} Indian drug sites, ${nf(s.meta.fda_inspections.fda_added)} not on the other lists` : " — not fetched yet"}: FDA's classification of each inspection — NAI (clean), VAI (observations, fixed voluntarily), OAI (official action: warning letter or import alert). "US FDA" on a plant means its latest GMP inspection was NAI or VAI within 5 years and it is not on Import Alert 66-40. Clinical / bioequivalence study inspections are left out{s.meta?.fda_inspections?.fda_clinical_only ? ` (${nf(s.meta.fda_inspections.fda_clinical_only)} study-only sites)` : ""}. FDA's inspection records have no postcode, so the site's FDA registration supplies it where one exists; import-alert firms are matched by name and place. FDA does not state dosage forms, so FDA-only plants list none.</p>
      <p><b>NSQ link</b>: an NSQ "Manufactured By" site is joined to a plant on company name and PIN code ({nf(s.match_kinds?.site ?? 0)} exact, {nf(s.match_kinds?.site_fuzzy ?? 0)} near-identical names), or on company and state when either side has no PIN ({nf(s.match_kinds?.company ?? 0)}).</p>
    </div>
  );
}

export function Plants() {
  const [params, setParams] = useSearchParams();
  const summary = useQuery({ queryKey: ["plants-summary"], queryFn: () => api<any>("/api/plants/summary") });
  const facets = useQuery({ queryKey: ["plants-facets"], queryFn: () => api<any>("/api/plants/facets") });
  const [q, setQ] = useState("");
  const [dq, setDq] = useState("");
  const [state, setState] = useState("");
  const [capability, setCapability] = useState(params.get("capability") ?? "");
  const [segregated, setSegregated] = useState(params.get("segregated") ?? "");
  const [cert, setCert] = useState<"" | "who_gmp" | "eu_gmp" | "eu_ncr" | "us_fda" | "fda_oai" | "schedule_c" | "loan">("");
  const [nsq, setNsq] = useState<"" | "yes" | "no">("");
  const [sort, setSort] = useState<"nsq" | "forms" | "name">("nsq");
  const [page, setPage] = useState(1);
  const [active, setActive] = useState<string | null>(null);
  const open = params.get("plant") ?? undefined;
  const setOpen = (id?: string) => { const n = new URLSearchParams(params); if (id) n.set("plant", id); else n.delete("plant"); setParams(n, { replace: true }); };
  useEffect(() => { const t = setTimeout(() => { setDq(q); setPage(1); }, 250); return () => clearTimeout(t); }, [q]);
  const list = useQuery({
    queryKey: ["plants", dq, state, capability, segregated, cert, nsq, sort, page],
    queryFn: () => api<any>(`/api/plants?${new URLSearchParams({ q: dq, state, capability, segregated, cert, nsq, sort, page: String(page), size: "15" })}`),
    placeholderData: keepPreviousData,
  });
  if (summary.isLoading) return <PageSkeleton />;
  if (summary.error) return <ErrorNote error={summary.error} />;
  const s = summary.data;
  const labels: Labels | undefined = s.labels;
  if (!s.plants) {
    return <Card><Empty icon={<Factory size={22} />} title="The plant registry has not been built yet">
      Run <b>CDSCO plant registry</b> under Admin → Jobs (Sources), or run <code>fetch_source.py cdsco_plants</code> on a machine that can reach CDSCO and copy <code>data/sources/cdsco_plants.json</code> to the server.
    </Empty></Card>;
  }
  const pick = (dim: string, key: string) => {
    if (dim === "capabilities") setCapability(capability === key ? "" : key);
    if (dim === "segregated") setSegregated(segregated === key ? "" : key);
    if (dim === "states") setState(state === key ? "" : key);
    setPage(1);
  };
  const chips = [state, capability && (capability === "sterile" ? "Sterile (any)" : labels?.capabilities[capability]), segregated && labels?.segregated[segregated]].filter(Boolean);
  const sections: Section[] = [
    { id: "rates", title: "Who fails, per plant that can make it", icon: <Factory size={16} />, subtitle: "Every group — click a row to list those plants",
      render: () => <RatesCard bare s={s} onPick={(d, k) => { pick(d, k); setActive(null); }} /> },
    { id: "about", title: "How the registry is built", icon: <FlaskConical size={16} />, subtitle: "Sources, what each contributes, and how NSQ alerts are joined", render: () => <AboutDetail s={s} /> },
  ];

  return (
    <ExpandedProvider sections={sections} active={active} onActive={setActive} title="Plant registry" subtitle={`${nf(s.plants)} plants`}>
      <div className="grid grid-cols-2 gap-4 xl:grid-cols-5">
        <Stat label="Plants in the registry" value={s.plants} icon={<Factory size={18} />} hint={`${nf(s.who_gmp)} WHO-GMP · ${nf(s.eu_gmp)} EU GMP · ${nf(s.us_fda ?? 0)} US FDA · ${nf(s.sugam)} in SUGAM${s.eu_ncr ? ` · ${nf(s.eu_ncr)} under EU non-compliance` : ""}${s.fda_oai ? ` · ${nf(s.fda_oai)} FDA OAI / import alert` : ""}`} />
        <Stat label="Sterile-capable" value={s.sterile} tone="indigo" delay={0.04} hint="Injectables, ophthalmics or a Schedule C licence" />
        <Stat label="API makers" value={s.api} tone="amber" delay={0.08} hint="Bulk drugs / raw materials" />
        <Stat label="Plants with NSQ alerts" value={s.with_nsq} tone="rose" delay={0.12} hint={`${nf(s.nsq_sites_linked)} of ${nf(s.nsq_sites)} NSQ sites linked`} />
        <Stat label="NSQ alerts from listed plants" value={s.nsq_alerts_linked_pct} decimals={1} suffix="%" tone="rose" delay={0.16}
          hint="The rest come from makers on neither CDSCO list" />
      </div>

      <div className="mt-5 grid gap-5 xl:grid-cols-[minmax(0,3fr)_minmax(0,2fr)]">
        <RatesCard s={s} onPick={pick} limit={10} onExpand={() => setActive("rates")} />
        <Card delay={0.15} className="min-w-0">
          <CardHeader title="Where the registry comes from" subtitle={`Retrieved ${s.meta?.retrieved_at?.slice(0, 10) ?? "—"}`}
            action={<button onClick={() => setActive("about")} className="inline-flex items-center gap-1 whitespace-nowrap rounded-lg px-2 py-1 text-xs text-brand-700 hover:bg-brand-50">How it's built ↗</button>} />
          <div className="grid grid-cols-2 gap-3 p-5">
            {[
              ["CDSCO WHO-GMP", s.who_gmp, "certified units, with what each may make", "#0a9a7d"],
              ["CDSCO SUGAM", s.sugam, "approved sites and licences", "#64748b"],
              ["EU GMP", s.meta?.eudragmdp?.eu_sites, `Indian sites · ${nf(s.eu_gmp)} certified now`, "#6366f1"],
              ["US FDA", s.meta?.fda_inspections?.fda_sites, `inspected sites · ${nf(s.us_fda ?? 0)} acceptable`, "#0ea5e9"],
            ].map(([k, v, sub, c]: any) => (
              <div key={k} className="rounded-xl p-3 ring-1 ring-inset ring-line">
                <div className="flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-wider text-ink-muted"><span className="h-2 w-2 rounded-full" style={{ background: c }} />{k}</div>
                <div className="mt-1 font-display text-xl font-extrabold tabular-nums">{v != null ? nf(v) : "—"}</div>
                <div className="text-[11px] text-ink-muted">{v != null ? sub : "not fetched yet"}</div>
              </div>
            ))}
            <div className="col-span-2 rounded-xl bg-slate-50 p-3 text-xs text-ink-soft">NSQ alerts are joined to plants on company name and PIN code: {nf(s.match_kinds?.site ?? 0)} exact, {nf(s.match_kinds?.site_fuzzy ?? 0)} near-identical, {nf(s.match_kinds?.company ?? 0)} on company and state.</div>
            {s.outside_capabilities?.length > 0 && <p className="col-span-2 flex items-start gap-2 rounded-lg bg-rose-50 p-2.5 text-xs text-rose-900"><ShieldAlert size={14} className="mt-0.5 shrink-0" />
              <span>WHO-GMP plants with NSQ alerts in a form their listing doesn't cover: {s.outside_capabilities.map((o: any) => `${o.form} (${o.plants})`).join(", ")}.</span></p>}
          </div>
        </Card>
      </div>

      <Card delay={0.2} className="mt-5">
        <CardHeader title="Plants" subtitle={`${list.data?.total?.toLocaleString("en-IN") ?? "…"} plants`} action={
          <div className="flex flex-wrap items-center gap-2">
            {chips.length > 0 && <button onClick={() => { setState(""); setCapability(""); setSegregated(""); setPage(1); }}><Badge tone="indigo">{chips.join(" · ")} ✕</Badge></button>}
            <select className="input h-9 w-36 text-xs" value={state} onChange={(e) => { setState(e.target.value); setPage(1); }}>
              <option value="">All states</option>{facets.data?.states.map((x: string) => <option key={x}>{x}</option>)}
            </select>
            <select className="input h-9 w-44 text-xs" value={capability} onChange={(e) => { setCapability(e.target.value); setPage(1); }}>
              <option value="">Any dosage form</option><option value="sterile">Sterile (any)</option>
              {facets.data?.capabilities.map((x: any) => <option key={x.key} value={x.key}>{x.label}</option>)}
            </select>
            <select className="input h-9 w-40 text-xs" value={segregated} onChange={(e) => { setSegregated(e.target.value); setPage(1); }}>
              <option value="">Any block</option>{facets.data?.segregated.map((x: any) => <option key={x.key} value={x.key}>{x.label}</option>)}
            </select>
            <Segmented value={cert} onChange={(v) => { setCert(v); setPage(1); }} options={[{ value: "", label: "All" }, { value: "who_gmp", label: "WHO-GMP" }, { value: "eu_gmp", label: "EU GMP" }, { value: "eu_ncr", label: "EU NCR" }, { value: "us_fda", label: "US FDA" }, { value: "fda_oai", label: "FDA OAI" }, { value: "schedule_c", label: "Sched. C" }, { value: "loan", label: "Loan" }]} />
            <Segmented value={nsq} onChange={(v) => { setNsq(v); setPage(1); }} options={[{ value: "", label: "Any" }, { value: "yes", label: "With NSQ" }, { value: "no", label: "Clean" }]} />
            <select className="input h-9 w-32 text-xs" value={sort} onChange={(e) => setSort(e.target.value as any)}>
              <option value="nsq">Most alerts</option><option value="forms">Most forms</option><option value="name">Name</option>
            </select>
            <div className="relative"><Search size={15} className="absolute left-3 top-2.5 text-ink-faint" /><input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Company, town, PIN, loan licensee…" className="input h-9 w-60 pl-9" /></div>
          </div>
        } />
        <div className="mt-4 overflow-x-auto">
          <table className={cn("w-full text-sm", list.isFetching && "opacity-60")}>
            <thead><tr className="border-y border-line bg-slate-50/70 text-left text-[11px] font-semibold uppercase tracking-wider text-ink-muted">
              <th className="px-5 py-2.5">Plant</th><th className="px-3 py-2.5">Where</th><th className="px-3 py-2.5">Permitted to make</th><th className="px-3 py-2.5">Blocks</th><th className="px-3 py-2.5">Listing</th><th className="px-5 py-2.5 text-right">NSQ</th>
            </tr></thead>
            <tbody>
              {list.data?.items.map((x: any) => (
                <tr key={x.id} onClick={() => setOpen(x.id)} className="cursor-pointer border-b border-line/70 align-top hover:bg-slate-50">
                  <td className="max-w-[300px] px-5 py-2.5"><div className="truncate font-semibold" title={x.name}>{x.name}</div>
                    {x.therapeutic?.length > 0 && <div className="truncate text-[11px] text-ink-muted">{x.therapeutic.map((t: string) => t.replace(/_/g, " ")).join(", ")}</div>}</td>
                  <td className="px-3 py-2.5 text-xs">{x.state || "—"}<div className="text-ink-faint">{[x.district, x.pin].filter(Boolean).join(" · ")}</div></td>
                  <td className="px-3 py-2.5"><div className="flex max-w-[280px] flex-wrap gap-1">{x.dosage_forms.slice(0, 3).map((f: string) => <FormChip key={f} k={f} labels={labels} />)}
                    {x.dosage_forms.length === 0 && x.licence_forms?.map((f: string) => <span key={f} className="rounded-md border border-dashed border-line px-1.5 py-0.5 text-[10.5px] text-ink-muted" title="Licence form only — CDSCO lists no dosage forms for this site">{f}</span>)}
                    {x.dosage_forms.length > 3 && <span className="text-[10.5px] text-ink-faint">+{x.dosage_forms.length - 3}</span>}</div></td>
                  <td className="px-3 py-2.5"><div className="flex max-w-[200px] flex-wrap gap-1">{Object.entries(x.segregated).map(([k, f]: any) => <SegChip key={k} k={k} forms={f} labels={labels} />)}</div></td>
                  <td className="px-3 py-2.5"><RegistryBadges p={x} /></td>
                  <td className="px-5 py-2.5 text-right tabular-nums">{x.nsq_alerts ? <span className="font-semibold text-rose-700">{x.nsq_alerts}</span> : <span className="text-ink-faint">0</span>}
                    {x.nsq_last && <div className="text-[11px] text-ink-muted">{fmtMonth(x.nsq_last)}</div>}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {list.data?.items.length === 0 && <div className="p-8 text-center text-sm text-ink-muted">No plant matches these filters.</div>}
        </div>
        {list.data && (
          <div className="flex items-center justify-between px-5 py-3 text-xs text-ink-muted">
            <span>Page {list.data.page} of {list.data.pages}</span>
            <div className="flex gap-1.5"><Button size="sm" variant="secondary" disabled={page <= 1} onClick={() => setPage(page - 1)}><ChevronLeft size={14} /></Button><Button size="sm" variant="secondary" disabled={page >= list.data.pages} onClick={() => setPage(page + 1)}><ChevronRight size={14} /></Button></div>
          </div>
        )}
      </Card>
      <PlantDrawer id={open} labels={labels} onClose={() => setOpen(undefined)} />
    </ExpandedProvider>
  );
}

// Registry section for the NSQ site drawer (admin site directory, org infrastructure).
export function SiteRegistryLink({ cdsco }: { cdsco: any }) {
  if (!cdsco) return <div className="text-xs text-ink-muted">Not found in CDSCO's WHO-GMP or approved-site lists (matched on company name and PIN).</div>;
  return (
    <div className="space-y-1.5">
      {cdsco.plants.map((p: any) => (
        <Link key={p.id} to={`/playground/plants?plant=${encodeURIComponent(p.id)}`} className="block rounded-lg border border-line p-2.5 text-xs hover:bg-slate-50">
          <div className="flex items-center justify-between gap-2"><span className="font-semibold">{p.name}</span><RegistryBadges p={p} /></div>
          <div className="mt-1 flex flex-wrap gap-1">{p.dosage_forms.map((f: string) => <FormChip key={f} k={f} />)}{Object.entries(p.segregated).map(([k, f]: any) => <SegChip key={k} k={k} forms={f} />)}</div>
          <div className="mt-1 text-ink-faint">Matched on {MATCH_WORD[cdsco.match] ?? cdsco.match}{p.who_gmp_valid_until ? ` · WHO-GMP valid until ${p.who_gmp_valid_until}` : ""}</div>
        </Link>
      ))}
    </div>
  );
}


// "Who can make it" — for the Molecule workbench.
function MakerRow({ p, right, sub, highlight }: { p: any; right?: React.ReactNode; sub?: React.ReactNode; highlight?: string | null }) {
  // name on its own line (never squeezed by the badges), place under it, badges last
  const where = [p.district, p.state, p.pin].filter(Boolean).join(" · ").replace(/\uFFFD/g, "");
  return (
    <Link to={`/playground/plants?plant=${encodeURIComponent(p.id)}`} className={cn("block rounded-lg border-b border-line/60 px-2 py-2 text-xs last:border-0 hover:bg-slate-50", p.id === highlight && "bg-brand-50 ring-1 ring-inset ring-brand-300")}>
      <span className="flex items-start justify-between gap-2">
        <span className="line-clamp-2 min-w-0 font-semibold leading-snug text-ink" title={p.name}>{p.name}</span>
        {right && <span className="shrink-0">{right}</span>}
      </span>
      {(where || sub) && <span className="mt-0.5 block truncate text-ink-muted">{where}{where && sub ? " · " : ""}{sub}</span>}
      <span className="mt-1 block"><RegistryBadges p={p} /></span>
    </Link>
  );
}

function FilingsRow({ m }: { m: any }) {
  const [all, setAll] = useState(false);
  if (m.dmf_total == null) return null;
  const none = !m.filings_at?.dmf && !m.filings_at?.cep;
  const rows = [...(m.dmf ?? []), ...(m.cep ?? [])].sort((a: any, b: any) => (b.plants.length ? 1 : 0) - (a.plants.length ? 1 : 0));
  return (
    <div className="border-t border-line px-5 py-4">
      <div className="label mb-1.5">API filings <span className="font-normal normal-case text-ink-faint">· {m.dmf_total} active US DMFs ({m.dmf_in_registry} holders in the registry) · {m.cep_total} valid CEPs ({m.cep_in_registry} in the registry)</span></div>
      {none ? <div className="text-xs text-ink-muted">FDA's DMF list and EDQM's CEP file are not fetched yet (Data jobs → FDA Drug Master Files / EDQM CEPs).</div>
        : rows.length === 0 ? <div className="text-xs text-ink-muted">No active US DMF or valid CEP names this API.</div> : (
          <>
            <div className="grid gap-x-6 gap-y-1 md:grid-cols-2">{(all ? rows : rows.slice(0, 10)).map((r: any) => (
              <div key={r.kind + r.number} className="flex flex-wrap items-center gap-1.5 text-xs">
                <Badge tone={r.kind === "CEP" ? "indigo" : "sky"}>{r.kind}</Badge>
                <span className="font-medium">{r.holder}</span>
                <span className="text-ink-faint">{r.number}{r.date ? ` · ${r.date.slice(0, 4)}` : ""}</span>
                {r.country && r.country !== "IN" && <span className="text-[11px] text-ink-faint">{r.country}</span>}
                {r.plants.map((p: any) => <Link key={p.id} to={`/playground/plants?plant=${encodeURIComponent(p.id)}`} title={r.level === "site" ? "Site named on the certificate (SPOR location = EudraGMDP site)" : "Same company, matched by name"} className={`rounded px-1.5 py-0.5 text-[11px] hover:underline ${r.level === "site" ? "bg-indigo-50 text-indigo-700" : "bg-slate-100 text-brand-700"}`}>{p.state ?? p.name}{r.level === "site" ? " · site" : ""}</Link>)}
                {r.plants_total > r.plants.length && <span className="text-[11px] text-ink-faint">+{r.plants_total - r.plants.length}</span>}
              </div>
            ))}</div>
            {rows.length > 10 && <button className="mt-1 text-xs text-brand-700 hover:underline" onClick={() => setAll(!all)}>{all ? "fewer" : `all ${rows.length}`}</button>}
            <p className="mt-2 text-[11px] text-ink-faint">DMFs name only the holder company: the chips are that company's plants, matched by name. A CEP that gives the holder's EU site ID links to that exact site ("· site"); CEPs held from outside India are not linked.</p>
          </>
        )}
    </div>
  );
}

export function MakersCard({ moleculeKey, bare, highlight }: { moleculeKey: string; bare?: boolean; highlight?: string | null }) {
  const { data: m, error, isLoading } = useQuery({ queryKey: ["makers", moleculeKey], queryFn: () => api<any>(`/api/plants/for-molecule/${moleculeKey}`), enabled: !!moleculeKey });
  if (error || (!isLoading && !m)) return null;
  const req = m?.molecule;
  return (
    <Frame bare={bare} title="Who can make it" subtitle={req ? `Plant registry (CDSCO + EU GMP + US FDA) · ${req.dosage_form || "dosage form unknown"}${req.segregated?.length ? ` · needs a separate ${req.segregated.map((x: string) => x.replace("_", "-")).join(" / ")} block` : ""}` : "Loading…"}>
      {!m ? <div className="p-5"><Skeleton className="h-32" /></div> : (<>
        <div className="grid gap-6 p-5 lg:grid-cols-3 lg:divide-x lg:divide-line [&>div]:min-w-0 lg:[&>div+div]:pl-6">
          <div>
            <div className="label mb-1.5">API makers <span className="font-normal normal-case text-ink-faint">· {m.api_makers_total} EU-inspected{m.listed_total ? ` · ${m.listed_total} named in CDSCO lists` : ""}</span></div>
            {m.api_makers.length + m.listed.length === 0 && <div className="text-xs text-ink-muted">No plant in the registry is inspected or listed for this API. (EU inspections name the substances; CDSCO lists name forms, rarely molecules.)</div>}
            {[...m.api_makers, ...m.listed].slice(0, 8).map((p: any) => <MakerRow key={p.id} p={p} highlight={highlight} sub={<span title={p.evidence}>{p.evidence.startsWith("EU") ? "EU-inspected API" : "CDSCO listing"}</span>} />)}
          </div>
          <div>
            <div className="label mb-1.5">Made it and failed (NSQ) <span className="font-normal normal-case text-ink-faint">· {m.made_total} registry plants{m.nsq_alerts_unlinked ? ` · ${m.nsq_alerts_unlinked} alerts from unlisted makers` : ""}</span></div>
            {m.made.length === 0 && <div className="text-xs text-ink-muted">No NSQ alert for this molecule traces to a registry plant.</div>}
            {m.made.slice(0, 8).map((p: any) => <MakerRow key={p.id} p={p} highlight={highlight} right={<Badge tone="rose">{p.alerts_for_molecule} NSQ</Badge>} />)}
          </div>
          <div>
            <div className="label mb-1.5">Permitted to make the form <span className="font-normal normal-case text-ink-faint">· {m.capable_total} plants</span></div>
            {!req?.forms?.length ? <div className="text-xs text-ink-muted">Dosage form not known for this molecule — add it in the molecule's Regulatory tab.</div> : (
              <>
                <div className="mb-2 flex flex-wrap gap-1 text-[11px]">
                  <Badge tone="sky">{m.capable_fda ?? 0} US FDA</Badge><Badge tone="indigo">{m.capable_eu} EU GMP</Badge><Badge tone="brand">{m.capable_who} WHO-GMP</Badge>{m.capable_ncr > 0 && <Badge tone="rose">{m.capable_ncr} EU non-compliant</Badge>}
                  {Object.entries(m.capable_by_state).slice(0, 4).map(([s, n]: any) => <Badge key={s}>{s} {n}</Badge>)}
                </div>
                {m.capable.slice(0, 8).map((p: any) => <MakerRow key={p.id} p={p} highlight={highlight} />)}
                <Link to={`/playground/plants?capability=${req.forms[0]}${req.segregated?.[0] ? `&segregated=${req.segregated[0]}` : ""}`} className="mt-1 block px-2 text-xs text-brand-700 hover:underline">All {m.capable_total} in the Plants tab →</Link>
              </>
            )}
            <p className="mt-2 px-2 text-[11px] text-ink-faint">{m.note}</p>
          </div>
        </div>
        <FilingsRow m={m} />
      </>)}
    </Frame>
  );
}
