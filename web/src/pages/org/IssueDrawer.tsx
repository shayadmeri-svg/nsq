import { useQuery } from "@tanstack/react-query";
import { Beaker, BookOpenCheck, ClipboardCheck, ExternalLink, FileText, History, Microscope, ShieldAlert, TrendingUp } from "lucide-react";
import { motion } from "motion/react";
import type { ReactNode } from "react";
import { Badge, Drawer, ErrorNote, Skeleton } from "../../components/ui";
import { RankBars } from "../../components/charts";
import { api } from "../../lib/api";
import { fmtMonth } from "../../lib/format";
import { useMe } from "../../lib/session";

function Section({ icon, title, children, i }: { icon: ReactNode; title: string; children: ReactNode; i: number }) {
  return (
    <motion.section initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.05 * i, duration: 0.35 }} className="rounded-2xl border border-line p-5">
      <h4 className="mb-3 flex items-center gap-2 font-display text-sm font-bold"><span className="text-brand-700">{icon}</span>{title}</h4>
      {children}
    </motion.section>
  );
}

const ORDER: Record<string, string[]> = {
  QA: ["why", "pattern", "cause", "corridor", "recalls", "methods", "capa", "history"],
  Regulatory: ["why", "methods", "capa", "cause", "recalls", "pattern", "corridor", "history"],
  Executive: ["why", "pattern", "capa", "cause", "recalls", "history", "methods", "corridor"],
};

function Src({ label, url }: { label: string; url?: string | null }) {
  return url
    ? <a href={url} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 text-[11px] text-brand-700 hover:underline">{label} <ExternalLink size={10} /></a>
    : <span className="text-[11px] text-ink-muted">{label}</span>;
}

const PK_LABEL: Record<string, string> = { half_life_h: "Half-life (h)", vd_l: "Volume of distribution (L)", vd_l_kg: "Volume of distribution (L/kg)",
  f_pct: "Bioavailability (%)", tmax_h: "Tmax (h)", cl: "Clearance" };

export function IssueDrawer({ slug, issueId, onClose, endpoint, who }: { slug?: string; issueId?: string; onClose: () => void;
  /** national use (Playground · Investigate): the alert URL, and whose alerts these are */ endpoint?: string; who?: string }) {
  const { data: me } = useMe();
  const { data, isLoading, error } = useQuery({
    queryKey: ["issue", endpoint ?? slug, issueId],
    queryFn: () => api<any>(endpoint ? `${endpoint}/${issueId}` : `/api/orgs/${slug}/quality/issues/${issueId}`),
    enabled: !!issueId,
  });
  const d = data?.diagnosis;
  const issue = data?.issue;
  const ev = data?.evidence;

  const blocks: Record<string, ReactNode> = d ? {
    why: (
      <Section key="why" i={0} icon={<FileText size={15} />} title="What the notice says">
        <p className="text-[15px] font-medium leading-relaxed">{issue.reason}</p>
        <div className="mt-3 flex flex-wrap gap-2">
          <Badge tone="slate">{issue.category}</Badge>
          <Badge>{issue.form}</Badge>
          {d.is_dominant_failure && <Badge tone="indigo">{who ? `the test most often involved for ${who}` : "the test most often involved in your records"}</Badge>}
        </div>
        <dl className="mt-4 grid grid-cols-2 gap-3 text-xs">
          <div><dt className="text-ink-muted">Tested by</dt><dd className="font-medium">{issue.lab} <span className="text-ink-faint">({issue.source})</span></dd></div>
          <div><dt className="text-ink-muted">Reported</dt><dd className="font-medium">{fmtMonth(issue.month)}</dd></div>
          <div><dt className="text-ink-muted">Batch</dt><dd className="font-medium">{issue.batch}</dd></div>
          <div><dt className="text-ink-muted">Mfg / Expiry</dt><dd className="font-medium">{issue.mfg_date} → {issue.expiry}</dd></div>
        </dl>
      </Section>
    ),
    pattern: (
      <Section key="pattern" i={1} icon={<TrendingUp size={15} />} title={who ? `Pattern across ${who}'s notices` : "Pattern across your notices"}>
        <div className="mb-3 text-xs text-ink-muted">{d.tenant_alert_count} notices across {d.form_span} dosage forms.</div>
        <RankBars rows={d.dominant_failures.map((f: any) => ({ name: f[0], count: f[1], sub: `${f[2]}%` }))} color="#6366f1" />
        {d.temporal_clusters?.length > 0 && (
          <div className="mt-5">
            <div className="label mb-2">Notices per month (last 24)</div>
            <div className="flex h-16 items-end gap-[3px]">
              {d.temporal_clusters.slice(-24).map(([m, n]: [string, number], i: number, arr: any[]) => {
                const max = Math.max(...arr.map((x: any) => x[1]));
                return <motion.div key={m} title={`${fmtMonth(m)}: ${n}`} className="flex-1 rounded-t bg-indigo-400/80" initial={{ height: 0 }} animate={{ height: `${(100 * n) / max}%` }} transition={{ delay: 0.2 + i * 0.015 }} />;
              })}
            </div>
          </div>
        )}
      </Section>
    ),
    cause: (
      <Section key="cause" i={2} icon={<Microscope size={15} />} title={ev?.molecule ? `What the national record shows for ${ev.molecule.name}` : "What the national record shows"}>
        {ev?.nsq?.alerts ? (
          <>
            <p className="text-sm">{ev.nsq.alerts} CDSCO notices name single-ingredient {ev.molecule.name} products{ev.nsq.manufacturers ? `, from ${ev.nsq.manufacturers} manufacturers` : ""}; <b>{ev.nsq.this_category_pct}%</b> of them involve {issue.category}.</p>
            <div className="mt-3"><RankBars rows={ev.nsq.categories.map((c: any) => ({ name: c.name, count: c.count, sub: `${c.pct}%` }))} color="#6366f1" /></div>
            {ev.nsq.similar?.length > 0 && (
              <div className="mt-4">
                <div className="label mb-1.5">Similar {issue.category} notices, as CDSCO published them</div>
                <ul className="space-y-1.5">{ev.nsq.similar.map((q: any, i: number) => <li key={i} className="rounded-lg bg-slate-50 px-3 py-2 text-xs"><span className="text-ink-soft">“{q.result}”</span> <span className="text-ink-faint">— {q.product} · {q.lab} · {fmtMonth(q.month)}</span></li>)}</ul>
              </div>
            )}
            <div className="mt-2"><Src label={ev.nsq.source.label} url={ev.nsq.source.url} /></div>
          </>
        ) : <p className="text-sm text-ink-soft">{ev?.note ?? "No other single-ingredient notices for this molecule."}</p>}
        <p className="mt-3 text-xs text-ink-muted">Public records show patterns, not the root cause of this batch: that needs the batch record, the method and the retained sample.</p>
      </Section>
    ),
    corridor: ev?.molecule && (ev.dissolution?.methods?.length || ev.label) ? (
      <Section key="corridor" i={3} icon={<Beaker size={15} />} title="Reference method and formulation">
        {ev.dissolution?.methods?.length > 0 && (
          <div className="mb-4">
            <div className="label mb-1.5">FDA-recommended dissolution method</div>
            <div className="overflow-x-auto"><table className="w-full text-xs"><thead><tr className="text-left text-ink-muted"><th className="pb-1.5 font-medium">Form</th><th className="pb-1.5 font-medium">Apparatus</th><th className="pb-1.5 font-medium">rpm</th><th className="pb-1.5 font-medium">Medium</th><th className="pb-1.5 font-medium">Volume</th><th className="pb-1.5 font-medium">Sampling (min)</th></tr></thead>
              <tbody>{ev.dissolution.methods.map((m: any, i: number) => <tr key={i} className="border-t border-line"><td className="py-1.5 font-medium">{m.dosage_form}</td><td>{m.apparatus || "—"}</td><td>{m.rpm ?? "—"}</td><td>{m.medium}</td><td>{m.volume_ml ? `${m.volume_ml} mL` : "—"}</td><td>{m.times_text || "—"}</td></tr>)}</tbody></table></div>
            <div className="mt-1.5"><Src label="FDA Dissolution Methods Database" url={ev.dissolution.source?.url} /></div>
          </div>
        )}
        {ev.label && (
          <div>
            <div className="label mb-1.5">US reference label{ev.label.brand ? `: ${ev.label.brand} (${ev.label.application})` : ""}</div>
            {ev.label.inactive_ingredients?.length > 0 && <p className="text-xs"><span className="text-ink-muted">Inactive ingredients: </span>{ev.label.inactive_ingredients.join(", ")}</p>}
            {Object.keys(ev.label.pk ?? {}).length > 0 && <ul className="mt-2 space-y-1">{Object.entries(ev.label.pk).map(([k, v]: [string, any]) => <li key={k} className="text-xs"><b>{PK_LABEL[k] ?? k}: {v.value}{v.unit ? ` ${v.unit}` : ""}</b> <span className="text-ink-faint">— “{String(v.text).slice(0, 160)}{String(v.text).length > 160 ? "…" : ""}”</span></li>)}</ul>}
            <div className="mt-1.5"><Src label="DailyMed label" url={ev.label.url} /></div>
          </div>
        )}
        <p className="mt-3 text-xs text-ink-muted">Excipient amounts and process parameters are not public; compare these against your own validated process.</p>
      </Section>
    ) : null,
    recalls: ev?.recalls?.items?.length ? (
      <Section key="recalls" i={4} icon={<ShieldAlert size={15} />} title={`FDA recalls naming ${ev.molecule.name}`}>
        <p className="mb-2 text-xs text-ink-muted">{ev.recalls.total} FDA enforcement reports; {ev.recalls.matching_category} for a reason like this notice's ({issue.category}).</p>
        <ul className="divide-y divide-line text-xs">{ev.recalls.items.map((r: any) => <li key={r.recall_number} className="py-2"><div className="flex justify-between gap-3"><b>{r.reason}</b><a href={r.url} target="_blank" rel="noreferrer" className="shrink-0 text-brand-700 hover:underline">{r.recall_number}</a></div><div className="text-ink-faint">{r.firm} · {r.class} · {r.date?.slice(0, 4)}-{r.date?.slice(4, 6)}</div></li>)}</ul>
        <div className="mt-1.5"><Src label={ev.recalls.source.label} url={ev.recalls.source.url} /></div>
      </Section>
    ) : null,
    methods: ev?.patents ? (
      <Section key="methods" i={5} icon={<BookOpenCheck size={15} />} title="Patent and pharmacopoeia status">
        <div className="grid gap-2 sm:grid-cols-3">{ev.patents.markets.map((g: any) => (
          <div key={g.code} className="rounded-xl bg-slate-50 p-3 text-xs">
            <div className="flex items-center justify-between"><b>{g.name}</b><Badge tone={g.status === "off_patent" ? "brand" : g.status === "unknown" ? "slate" : g.status === "loe_pending" ? "amber" : "rose"}>{String(g.status).replace("_", " ")}</Badge></div>
            <div className="mt-1 text-ink-muted">{g.basis}{g.date ? ` · ${g.date}` : ""}</div>
            <div className="mt-1 text-ink-soft">{g.note}</div>
            <div className="mt-1 flex flex-wrap gap-2">{(g.sources ?? []).map((x: any, i: number) => <Src key={i} label={x.label} url={x.url} />)}</div>
          </div>))}</div>
        {(ev.pheur ?? []).map((m: any) => (
          <div key={m.number} className="mt-3 rounded-xl bg-slate-50 p-3 text-xs">
            <div><b>Ph. Eur. {m.number} {m.name}</b> <span className="text-ink-muted">· last published {m.last_published}</span>
              <a href={m.url} target="_blank" rel="noreferrer" className="ml-2 text-brand-700 hover:underline">EDQM</a></div>
            {m.under_revision && <div className="mt-1"><b>Under revision:</b> {m.under_revision.text}</div>}
            {m.upcoming.map((e: any) => <div key={e.issue} className="mt-1 text-rose-700"><b>Issue {e.issue} applies {e.implementation}:</b> {(e.changes ?? []).map((c: any) => c.section || c.text).join(", ")}</div>)}
            {[...m.upcoming, ...m.recent].some((e: any) => (e.changes ?? []).some((c: any) => c.you_failed_it)) && <div className="mt-1 font-semibold text-indigo-700">A Ph. Eur. revision covers this test: worth checking your method against it.</div>}
          </div>))}
        {ev.patents.compound?.number && <p className="mt-3 text-xs">Compound patent: <a href={ev.patents.compound.url} target="_blank" rel="noreferrer" className="text-brand-700 hover:underline">{ev.patents.compound.number} — {ev.patents.compound.title}</a></p>}
      </Section>
    ) : null,
    capa: (
      <Section key="capa" i={5} icon={<ClipboardCheck size={15} />} title="What to check (general, not specific to this batch)">
        <ol className="space-y-2.5">
          {d.mitigations.map((m: any, i: number) => (
            <li key={i} className="flex gap-3 text-sm">
              <span className="grid h-6 w-6 shrink-0 place-items-center rounded-full bg-brand-50 text-xs font-bold text-brand-700">{i + 1}</span>
              <div>{m.text}</div>
            </li>
          ))}
        </ol>
        {ev?.guidance?.length > 0 && (
          <div className="mt-4">
            <div className="label mb-1.5">General practice — the documents these checks come from</div>
            <ul className="space-y-1">{ev.guidance.map((g: any) => <li key={g.url}><Src label={`${g.title} (${g.issuer})`} url={g.url} /></li>)}</ul>
          </div>
        )}
      </Section>
    ),
    history: data.history?.length > 1 ? (
      <Section key="history" i={6} icon={<History size={15} />} title="Same product — earlier notices">
        <ul className="divide-y divide-line text-sm">
          {data.history.map((h: any) => <li key={h.id} className="flex justify-between gap-3 py-2"><span className="truncate">{h.reason}</span><span className="shrink-0 text-xs text-ink-muted">{fmtMonth(h.month)} · {h.batch}</span></li>)}
        </ul>
      </Section>
    ) : null,
  } : {};

  const order = ORDER[me?.persona ?? "QA"] ?? ORDER.QA;
  return (
    <Drawer open={!!issueId} onClose={onClose} title={issue?.product ?? "Loading…"} subtitle={issue ? `Batch ${issue.batch} · ${issue.manufacturer}` : undefined} width={760}>
      {isLoading && <div className="space-y-4"><Skeleton className="h-32" /><Skeleton className="h-48" /><Skeleton className="h-40" /></div>}
      <ErrorNote error={error} />
      {d && <div className="space-y-4">{order.map((k) => blocks[k]).filter(Boolean)}</div>}
    </Drawer>
  );
}
