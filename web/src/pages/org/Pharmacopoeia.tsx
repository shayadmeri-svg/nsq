// Pharmacopoeias for this organisation's products: every connected one (IP, Ph. Eur., JP, Ph. Int., FDA), each shown on its
// own terms with the insights that matter for that country, and an overview of where they disagree with the IP.
import { BookOpenCheck, CalendarClock, ExternalLink, FileWarning, Globe2, Pencil } from "lucide-react";
import { useState } from "react";
import { Badge, Card, CardHeader, ErrorNote, PageHeader, PageSkeleton, Segmented, Stat } from "../../components/ui";
import { cn } from "../../lib/cn";
import { fmtDate, plural } from "../../lib/format";
import { useOrg, useOrgData } from "./common";

type Tone = "rose" | "brand" | "slate" | "amber" | "indigo" | "sky";
const STATE: Record<string, { label: string; tone: Tone }> = {
  upcoming: { label: "upcoming", tone: "rose" }, in_force: { label: "in force", tone: "brand" }, earlier: { label: "earlier", tone: "slate" },
};
const VS: Record<string, { label: string; cls: string }> = {
  stricter: { label: "stricter", cls: "text-rose-600" }, looser: { label: "looser", cls: "text-emerald-600" },
  same: { label: "same", cls: "text-ink-muted" }, different: { label: "not comparable", cls: "text-amber-600" },
};
const n = (v: any) => (v == null ? "—" : typeof v === "number" ? v.toLocaleString("en-IN", { maximumFractionDigits: 1 }) : v);
const range = (lo: any, hi: any) => (lo == null ? "—" : `${n(lo)}–${n(hi)}%`);
const qText = (q: any, t: any) => (q == null ? "—" : `Q ${n(q)}%${t != null ? ` at ${n(t)} min` : ""}`);

function Change({ e }: { e: any }) {
  const st = STATE[e.state] ?? STATE.earlier;
  return (
    <div className="rounded-lg bg-slate-50 p-2.5 text-xs">
      <div className="flex flex-wrap items-center gap-2"><b>{e.kind === "issue" ? "Issue" : e.kind === "edition" ? "Edition" : "Supplement"} {e.issue}</b>
        <Badge tone={st.tone}>{st.label}</Badge>
        {e.implementation && <span className="text-ink-muted">applies from <b className="text-ink">{fmtDate(e.implementation)}</b> · published {e.published}</span>}
        {!e.implementation && <span className="text-ink-faint">before the 13th-Edition schedule: date stated in that supplement</span>}</div>
      <ul className="mt-1.5 space-y-1">{(e.changes ?? []).map((c: any, i: number) => (
        <li key={i} className={cn("rounded px-1.5 py-0.5", c.you_failed_it && "bg-indigo-50 ring-1 ring-inset ring-indigo-200")}>
          {c.section && <b>{c.section}: </b>}<span className="text-ink-soft">{c.text}</span>
          {c.you_failed_it && <span className="ml-1 text-[10px] font-semibold text-indigo-700">· a test in your quality records</span>}</li>))}</ul>
    </div>
  );
}

function Insights({ items }: { items: any[] }) {
  if (!items?.length) return null;
  const dot: Record<string, string> = { rose: "bg-rose-500", amber: "bg-amber-500", indigo: "bg-indigo-500", brand: "bg-brand-500", slate: "bg-slate-300" };
  return (
    <Card className="mb-5">
      <CardHeader title="What this means for your products" />
      <ul className="divide-y divide-line">{items.map((i, k) => (
        <li key={k} className="flex gap-3 px-5 py-2.5 text-sm"><span className={cn("mt-1.5 h-2 w-2 shrink-0 rounded-full", dot[i.tone] ?? dot.slate)} />
          <div><div>{i.text}</div><div className="mt-0.5 text-xs text-ink-muted">{i.molecules.join(" · ")}</div></div></li>))}</ul>
    </Card>
  );
}

// one monograph as its pharmacopoeia states it (IP, JP, Ph. Int.)
function Monograph({ m, src }: { m: any; src: string }) {
  const d = m.dissolution, ref = m.reference;
  const where = src === "ip" && ref ? `${ref.edition ?? ""}${ref.volume ? `, vol. ${ref.volume}` : ""}${ref.page ? `, p. ${ref.page}` : ""}`
    : src === "jp" && ref?.page ? `p. ${ref.page}${ref.supplement ? ` · ${ref.supplement}` : ""}` : m.id ?? "";
  return (
    <div className="rounded-xl p-3 ring-1 ring-inset ring-line">
      <div className="flex flex-wrap items-center gap-2 text-sm"><b>{m.title}</b>{m.combination && <Badge>combination</Badge>}
        {src === "ip" && (m.verified?.by ? <Badge tone="brand">checked by {m.verified.by}</Badge> : <Badge tone="amber">not yet checked against the print</Badge>)}
        <span className="text-xs text-ink-muted">{where}</span>
        {m.url && <a href={m.url} target="_blank" rel="noreferrer" className="ml-auto inline-flex items-center gap-1 text-xs text-brand-700 hover:underline">source <ExternalLink size={11} /></a>}</div>
      <dl className="mt-2 grid gap-x-6 gap-y-1 text-xs sm:grid-cols-[110px_1fr]">
        {m.assay && <><dt className="text-ink-muted">Assay</dt><dd>{range(m.assay.lo, m.assay.hi)} <span className="text-ink-faint">of the stated amount</span></dd></>}
        {d && <><dt className="text-ink-muted">Dissolution</dt><dd>
          {d.q_pct != null ? <b>{qText(d.q_pct, d.time_min)}</b> : d.each_unit_min_pct != null ? <b>each unit ≥ {n(d.each_unit_min_pct)}% at {n(d.time_min)} min</b> : <span className="text-amber-700">no Q stated</span>}
          <span className="text-ink-muted"> · {[d.apparatus, d.rpm && `${n(d.rpm)} rpm`, d.volume_ml && `${n(d.volume_ml)} mL`, d.medium, d.ph != null && `pH ${n(d.ph)}`].filter(Boolean).join(", ")}</span>
          {src !== "ip" && d.text && <div className="mt-0.5 text-[11px] text-ink-faint">“{d.text}”</div>}</dd></>}
        {m.disintegration?.max_min != null && <><dt className="text-ink-muted">Disintegration</dt><dd>≤ {n(m.disintegration.max_min)} min</dd></>}
        {m.related_substances && <><dt className="text-ink-muted">Related substances</dt><dd>{m.related_substances}</dd></>}
        {m.strengths_mg?.length > 0 && <><dt className="text-ink-muted">Usual strengths</dt><dd>{m.strengths_mg.join(", ")} mg</dd></>}
      </dl>
      {m.issues?.length > 0 && <div className="mt-2 text-[11px] text-amber-700">To check: {m.issues.join("; ")}</div>}
    </div>
  );
}

function FdaMethods({ rows }: { rows: any[] }) {
  return (
    <div className="overflow-x-auto"><table className="w-full text-xs">
      <thead className="text-ink-muted"><tr><th className="py-1 text-left">Dosage form</th><th className="px-2 text-left">Apparatus</th><th className="px-2 text-right">rpm</th>
        <th className="px-2 text-left">Medium</th><th className="px-2 text-right">mL</th><th className="px-2 text-left">Sampling (min)</th><th className="px-2 text-left">Updated</th></tr></thead>
      <tbody>{rows.map((r, i) => (
        <tr key={i} className="border-t border-line"><td className="py-1">{r.dosage_form}{r.combination && <span className="text-ink-faint"> · {r.drug}</span>}</td>
          {r.refers_to ? <td colSpan={5} className="px-2 text-ink-muted">Refers to {r.refers_to}{r.refers_to === "USP" ? " (the USP monograph holds the method; not connected)" : ": Q 80% in 30 min, 500 mL 0.1 N HCl, paddle 50 rpm"}</td>
            : <><td className="px-2">{r.apparatus}</td><td className="px-2 text-right tabular-nums">{n(r.rpm)}</td><td className="px-2">{r.medium}</td>
              <td className="px-2 text-right tabular-nums">{n(r.volume_ml)}</td><td className="px-2">{r.times_text}</td></>}
          <td className="px-2 text-ink-muted">{r.updated}</td></tr>))}</tbody>
    </table></div>
  );
}

function PhEur({ mons }: { mons: any[] }) {
  return <>{mons.map((m: any) => (
    <div key={m.number} className="rounded-xl p-3 ring-1 ring-inset ring-line">
      <div className="flex flex-wrap items-center gap-2 text-sm"><b>Ph. Eur. {m.number}</b> {m.name} <Badge tone={/use/i.test(m.status ?? "") ? "brand" : "slate"}>{m.status ?? "—"}</Badge>
        <span className="text-xs text-ink-muted">last published in {m.last_published}{m.reference_standards ? ` · ${m.reference_standards} reference standards` : ""}</span>
        <a href={m.url} target="_blank" rel="noreferrer" className="ml-auto inline-flex items-center gap-1 text-xs text-brand-700 hover:underline">EDQM page <ExternalLink size={11} /></a></div>
      {m.under_revision && (
        <div className="mt-2 rounded-lg bg-amber-50 p-2.5 text-xs"><b className="text-amber-800">Under revision{m.under_revision.pharmeuropa ? ` (Pharmeuropa ${m.under_revision.pharmeuropa})` : ""}: </b>{m.under_revision.text}
          <div className="mt-0.5 text-[10px] text-ink-muted">A draft is published in Pharmeuropa for comment before it is adopted: check your method against it now.</div></div>)}
      <div className="mt-2 space-y-2">{[...m.upcoming, ...m.recent].map((e: any, i: number) => <Change key={i} e={e} />)}</div>
      <a href={m.history_url} target="_blank" rel="noreferrer" className="mt-1.5 inline-flex items-center gap-1 text-[11px] text-brand-700 hover:underline">Full history on EDQM <ExternalLink size={10} /></a>
    </div>))}</>;
}

function RegionStats({ r, eu }: { r: any; eu: any }) {
  const base = <Stat label={`Your molecules in the ${r.short}`} value={r.with} hint={`of ${plural(r.of, "molecule")} in your CDSCO alerts`} icon={<BookOpenCheck size={18} />} />;
  const stats: Record<string, JSX.Element[]> = {
    ip: [base, <Stat key="m" label="Monographs" value={r.monographs} hint="tablets, capsules and combinations" icon={<FileWarning size={18} />} tone="indigo" delay={0.05} />,
      <Stat key="q" label="With a dissolution Q" value={r.with_q} hint="the rest fall back to the next source" icon={<CalendarClock size={18} />} tone="gold" delay={0.1} />,
      <Stat key="u" label="Not yet checked" value={r.unverified} hint="against the printed IP 2022" icon={<Pencil size={18} />} tone="amber" delay={0.15} />],
    ph_eur: [base, <Stat key="u" label="Upcoming changes" value={r.upcoming} hint="published, applying on a future date" icon={<CalendarClock size={18} />} tone="rose" delay={0.05} />,
      <Stat key="r" label="Under revision" value={r.under_revision} hint="drafts in Pharmeuropa" icon={<Pencil size={18} />} tone="amber" delay={0.1} />,
      <Stat key="t" label="Relevant to your records" value={r.touching_failures} hint="the revised section is a test you have failed" icon={<FileWarning size={18} />} tone="indigo" delay={0.15} />],
    fda: [base, <Stat key="u" label="Method in the USP" value={r.refer_usp} hint="FDA's database refers to the USP monograph" icon={<FileWarning size={18} />} tone="amber" delay={0.05} />],
  };
  const list = stats[r.id] ?? [base];
  return (
    <>
      <div className={cn("mb-5 grid grid-cols-2 gap-4", list.length > 2 ? "xl:grid-cols-4" : "xl:grid-cols-2")}>{list}</div>
      {r.id === "ph_eur" && eu.upcoming?.length > 0 && (
        <Card className="mb-5">
          <CardHeader icon={<CalendarClock size={16} />} title="Calendar" subtitle="Changes already published, in the order they apply" />
          <div className="divide-y divide-line">{eu.upcoming.map((u: any, i: number) => (
            <div key={i} className="flex flex-wrap items-start gap-4 px-5 py-3 text-sm">
              <div className="w-32 shrink-0"><div className="font-display font-bold">{fmtDate(u.implementation)}</div><div className="text-[11px] text-ink-muted">Issue {u.issue}</div></div>
              <div className="min-w-0 flex-1"><div className="font-semibold">{u.molecule} <span className="font-normal text-ink-muted">— Ph. Eur. {u.monograph} {u.monograph_name}</span></div>
                <div className="mt-0.5 text-xs text-ink-soft">{(u.changes ?? []).map((ch: any) => ch.section || ch.text).filter(Boolean).join(" · ")}</div></div>
            </div>))}</div>
        </Card>)}
      {r.id === "ip" && r.failed_against?.length > 0 && (
        <Card className="mb-5">
          <CardHeader title="Your failed tests, against the IP limit" subtitle="CDSCO notices on your products, with the limit the IP monograph sets for that test" />
          <div className="divide-y divide-line">{r.failed_against.slice(0, 12).map((f: any, i: number) => (
            <div key={i} className="flex flex-wrap gap-3 px-5 py-2 text-sm"><div className="w-48 shrink-0"><b>{f.molecule}</b><div className="text-xs text-ink-muted">{f.test} · {plural(f.count, "notice")}</div></div>
              <div className="min-w-0 flex-1 text-xs text-ink-soft">{f.limit}</div></div>))}</div>
        </Card>)}
    </>
  );
}

function Overview({ d }: { d: any }) {
  const [only, setOnly] = useState<"disagree" | "all">(d.disagree.length ? "disagree" : "all");
  const rows = d.molecules.filter((m: any) => only === "all" || d.disagree.includes(m.key));
  const cell = (m: any, s: string) => {
    if (s === "ph_eur") return m.sources.ph_eur.present ? <span>{m.sources.ph_eur.monographs.map((x: any) => x.number).join(", ")}</span> : <span className="text-ink-faint">—</span>;
    const r = m.compare.rows.find((x: any) => x.source === s);
    if (!r) return m.sources[s].present ? <span className="text-ink-muted">monograph, no tablet limits</span> : <span className="text-ink-faint">—</span>;
    const dv = VS[r.dissolution_vs_ip], av = VS[r.assay_vs_ip];
    return (<div className="leading-tight">
      <div>{qText(r.q_pct, r.q_time_min)}{dv && <span className={cn("ml-1 text-[10px] font-semibold", dv.cls)}>{dv.label}</span>}</div>
      {r.assay_lo != null && <div className="text-ink-muted">{range(r.assay_lo, r.assay_hi)}{av && <span className={cn("ml-1 text-[10px] font-semibold", av.cls)}>{av.label}</span>}</div>}
      {r.method_vs_ip?.length > 0 && <div className="text-[10px] text-amber-700">{r.method_vs_ip.join(" · ")}</div>}
    </div>);
  };
  return (
    <>
      <div className="mb-5 grid gap-4 md:grid-cols-2 xl:grid-cols-5">{d.regions.map((r: any) => (
        <Card key={r.id} className="p-4"><div className="text-[11px] font-semibold uppercase tracking-wide text-ink-muted">{r.country}</div>
          <div className="font-semibold">{r.label}</div>
          <div className="mt-1 text-2xl font-bold tabular-nums">{r.with}<span className="text-sm font-normal text-ink-muted"> / {r.of}</span></div>
          <div className="text-[11px] text-ink-muted">of your molecules covered{r.insights.length ? ` · ${plural(r.insights.length, "finding")}` : ""}</div></Card>))}</div>
      <Card>
        <CardHeader icon={<Globe2 size={16} />} title="Your molecules, pharmacopoeia by pharmacopoeia"
          subtitle="Tablet limits as each states them, marked against the IP: stricter means a batch that passes in India can fail there"
          action={<Segmented value={only} onChange={setOnly as any} options={[{ value: "disagree", label: `Stricter than IP (${d.disagree.length})` }, { value: "all", label: `All ${d.molecules.length}` }]} />} />
        <div className="overflow-x-auto"><table className="w-full text-xs">
          <thead className="bg-slate-50 text-ink-muted"><tr><th className="px-5 py-2 text-left">Molecule</th><th className="px-3 text-left">India · IP</th><th className="px-3 text-left">Europe · Ph. Eur.</th>
            <th className="px-3 text-left">Japan · JP</th><th className="px-3 text-left">WHO · Ph. Int.</th><th className="px-3 text-left">US · FDA</th><th className="px-3 text-left">The models use</th></tr></thead>
          <tbody>{rows.map((m: any) => (
            <tr key={m.key} className="border-t border-line align-top"><td className="px-5 py-2"><b>{m.name}</b><div className="text-ink-muted">{plural(m.alerts, "notice")}</div></td>
              {["ip", "ph_eur", "jp", "ph_int", "fda"].map((s) => <td key={s} className="px-3 py-2">{cell(m, s)}</td>)}
              <td className="px-3 py-2 text-ink-muted">{m.applies.q_pct ? `${qText(m.applies.q_pct.value, m.applies.q_time_min?.value)} (${m.applies.q_pct.source})` : "—"}</td></tr>))}</tbody>
        </table></div>
      </Card>
    </>
  );
}

export function Pharmacopoeia() {
  const { org } = useOrg();
  const { data, isLoading, error } = useOrgData<any>("pharmacopoeia");
  const [tab, setTab] = useState("overview");
  const [view, setView] = useState<"action" | "all">("action");
  if (isLoading) return <PageSkeleton />;
  if (error) return <ErrorNote error={error} />;
  if (!data) return null;
  const region = data.regions.find((r: any) => r.id === tab);
  const flagged = new Set<string>((region?.insights ?? []).flatMap((i: any) => i.keys));
  const rows = region ? data.molecules.filter((m: any) => m.sources[tab].present || (tab === "ip")).filter((m: any) => view === "all" || flagged.has(m.key)) : [];
  return (
    <>
      <PageHeader eyebrow="Organisation" title="Pharmacopoeia" subtitle={`What each country's pharmacopoeia requires of ${org?.name ?? "your"} products, and where they differ`} />
      <div className="mb-5 overflow-x-auto"><Segmented value={tab} onChange={(v) => { setTab(v); setView("action"); }}
        options={[{ value: "overview", label: "All countries" }, ...data.regions.map((r: any) => ({ value: r.id, label: `${r.country} · ${r.short}` }))]} /></div>

      {!region && <Overview d={data} />}
      {region && (
        <>
          <Card className="mb-5 p-5"><div className="text-[11px] font-semibold uppercase tracking-wide text-ink-muted">{region.country}</div>
            <div className="font-display text-lg font-bold">{region.label}{region.source.edition && <span className="ml-2 text-sm font-normal text-ink-muted">{region.source.edition}</span>}</div>
            <p className="mt-1 text-sm text-ink-soft">{region.role}</p>
            <div className="mt-2 text-[11px] text-ink-muted">Source: {region.source.url ? <a href={region.source.url} target="_blank" rel="noreferrer" className="text-brand-700 hover:underline">{region.source.title}</a> : region.source.title}
              {region.source.retrieved_at && <> · retrieved {fmtDate(region.source.retrieved_at)}</>}{region.source.licence && <> · {region.source.licence}</>}</div></Card>
          <RegionStats r={region} eu={data.ph_eur} />
          <Insights items={region.insights} />
          <div className="mb-3"><Segmented value={view} onChange={setView as any} options={[{ value: "action", label: `In the findings (${flagged.size})` }, { value: "all", label: "All your molecules" }]} /></div>
          <div className="space-y-4">
            {rows.length === 0 && <Card className="p-6 text-sm text-ink-muted">Nothing to flag here. Switch to "All your molecules" to see every monograph.</Card>}
            {rows.map((m: any) => (
              <Card key={m.key}>
                <CardHeader title={m.name} subtitle={`${plural(m.alerts, "CDSCO notice")}${m.your_failures.length ? ` · tests in your records: ${m.your_failures.map((f: any) => f.name).join(", ")}` : ""}`} />
                <div className="space-y-3 px-5 pb-5">
                  {!m.sources[tab].present && <p className="text-xs text-ink-muted">No {region.short} monograph for this molecule.</p>}
                  {tab === "ph_eur" && <PhEur mons={m.sources.ph_eur.monographs} />}
                  {tab === "fda" && m.sources.fda.present && <FdaMethods rows={m.sources.fda.methods} />}
                  {["ip", "jp", "ph_int"].includes(tab) && m.sources[tab].monographs.map((mo: any, i: number) => <Monograph key={i} m={mo} src={tab} />)}
                </div>
              </Card>))}
          </div>
        </>
      )}
      <p className="mt-4 text-[11px] text-ink-muted">{data.scope}</p>
    </>
  );
}
