// Pharmacopoeia changes for this organisation's products: Ph. Eur. monographs of the molecules in its CDSCO alerts,
// what EDQM is changing, and from when (EDQM Knowledge Database + EDQM's publication schedule).
import { BookOpenCheck, CalendarClock, ExternalLink, FileWarning, Pencil } from "lucide-react";
import { useState } from "react";
import { Badge, Card, CardHeader, ErrorNote, PageHeader, PageSkeleton, Segmented, Stat } from "../../components/ui";
import { cn } from "../../lib/cn";
import { fmtDate, plural } from "../../lib/format";
import { useOrg, useOrgData } from "./common";

const STATE: Record<string, { label: string; tone: "rose" | "brand" | "slate" }> = {
  upcoming: { label: "upcoming", tone: "rose" }, in_force: { label: "in force", tone: "brand" }, earlier: { label: "earlier", tone: "slate" },
};

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

export function Pharmacopoeia() {
  const { org } = useOrg();
  const { data, isLoading, error } = useOrgData<any>("pharmacopoeia");
  const [view, setView] = useState<"action" | "all">("action");
  if (isLoading) return <PageSkeleton />;
  if (error) return <ErrorNote error={error} />;
  if (!data) return null;
  const c = data.counts;
  const rows = (data.molecules ?? []).filter((r: any) => view === "all" || r.monographs.some((m: any) => m.upcoming.length || m.under_revision || m.touches_your_failures));
  return (
    <>
      <PageHeader eyebrow="Organisation" title="Pharmacopoeia changes" subtitle={`Ph. Eur. revisions that touch ${org?.name ?? "your"} products: what changes and from when`} />
      <div className="mb-5 grid grid-cols-2 gap-4 xl:grid-cols-4">
        <Stat label="Your molecules with a Ph. Eur. monograph" value={c.with_monograph} hint={`of ${plural(c.molecules, "molecule")} in your CDSCO alerts`} icon={<BookOpenCheck size={18} />} />
        <Stat label="Upcoming changes" value={c.upcoming} hint="published, applying on a future date" icon={<CalendarClock size={18} />} tone="rose" delay={0.05} />
        <Stat label="Under revision" value={c.under_revision} hint="drafts in Pharmeuropa, not yet adopted" icon={<Pencil size={18} />} tone="amber" delay={0.1} />
        <Stat label="Relevant to your quality records" value={c.touching_failures} hint="the revised section is a test that appears in your CDSCO records" icon={<FileWarning size={18} />} tone="indigo" delay={0.15} />
      </div>

      {data.upcoming?.length > 0 && (
        <Card className="mb-5">
          <CardHeader icon={<CalendarClock size={16} />} title="Calendar" subtitle="Changes already published, in the order they apply" />
          <div className="divide-y divide-line">{data.upcoming.map((u: any, i: number) => (
            <div key={i} className="flex flex-wrap items-start gap-4 px-5 py-3 text-sm">
              <div className="w-32 shrink-0"><div className="font-display font-bold">{fmtDate(u.implementation)}</div><div className="text-[11px] text-ink-muted">Issue {u.issue}</div></div>
              <div className="min-w-0 flex-1"><div className="font-semibold">{u.molecule} <span className="font-normal text-ink-muted">— Ph. Eur. {u.monograph} {u.monograph_name}</span></div>
                <div className="mt-0.5 text-xs text-ink-soft">{(u.changes ?? []).map((ch: any) => ch.section || ch.text).filter(Boolean).join(" · ")}</div></div>
            </div>))}</div>
        </Card>
      )}

      <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
        <Segmented value={view} onChange={setView as any} options={[{ value: "action", label: "Needs attention" }, { value: "all", label: "All your molecules" }]} />
        <span className="text-[11px] text-ink-muted">Source: <a href={data.source.url} target="_blank" rel="noreferrer" className="text-brand-700 hover:underline">{data.source.label}</a>
          {data.schedule_source && <> · dates: <a href={data.schedule_source.url} target="_blank" rel="noreferrer" className="text-brand-700 hover:underline">{data.schedule_source.label}</a></>}</span>
      </div>

      <div className="space-y-4">
        {rows.length === 0 && <Card className="p-6 text-sm text-ink-muted">No upcoming or in-progress Ph. Eur. changes for your molecules. Switch to "All your molecules" to see their monographs.</Card>}
        {rows.map((r: any) => (
          <Card key={r.key}>
            <CardHeader title={r.name} subtitle={`${r.alerts} CDSCO notice${r.alerts === 1 ? "" : "s"}${r.your_failures.length ? ` · tests in your records: ${r.your_failures.map((f: any) => f.name).join(", ")}` : ""}`} />
            <div className="space-y-3 px-5 pb-5">
              {!r.has_monograph && <p className="text-xs text-ink-muted">No Ph. Eur. monograph for this active substance in the EDQM Knowledge Database.</p>}
              {r.monographs.map((m: any) => (
                <div key={m.number} className="rounded-xl ring-1 ring-inset ring-line p-3">
                  <div className="flex flex-wrap items-center gap-2 text-sm"><b>Ph. Eur. {m.number}</b> {m.name} <Badge tone={/use/i.test(m.status ?? "") ? "brand" : "slate"}>{m.status ?? "—"}</Badge>
                    <span className="text-xs text-ink-muted">last published in {m.last_published}{m.reference_standards ? ` · ${m.reference_standards} reference standards` : ""}</span>
                    <a href={m.url} target="_blank" rel="noreferrer" className="ml-auto inline-flex items-center gap-1 text-xs text-brand-700 hover:underline">EDQM page <ExternalLink size={11} /></a></div>
                  {m.under_revision && (
                    <div className="mt-2 rounded-lg bg-amber-50 p-2.5 text-xs"><b className="text-amber-800">Under revision{m.under_revision.pharmeuropa ? ` (Pharmeuropa ${m.under_revision.pharmeuropa})` : ""}: </b>{m.under_revision.text}
                      <div className="mt-0.5 text-[10px] text-ink-muted">A draft is published in Pharmeuropa for comment before it is adopted: check your method against it now.</div></div>)}
                  <div className="mt-2 space-y-2">{[...m.upcoming, ...m.recent].map((e: any, i: number) => <Change key={i} e={e} />)}</div>
                  <a href={m.history_url} target="_blank" rel="noreferrer" className="mt-1.5 inline-flex items-center gap-1 text-[11px] text-brand-700 hover:underline">Full history on EDQM <ExternalLink size={10} /></a>
                </div>
              ))}
            </div>
          </Card>
        ))}
      </div>
      <p className="mt-4 text-[11px] text-ink-muted">{data.scope}</p>
    </>
  );
}
