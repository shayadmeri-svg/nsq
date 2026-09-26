import { useQuery } from "@tanstack/react-query";
import { AlertTriangle, Beaker, BookOpenCheck, ClipboardCheck, History, Microscope, TrendingUp } from "lucide-react";
import { motion } from "motion/react";
import type { ReactNode } from "react";
import { Badge, Drawer, ErrorNote, Skeleton } from "../../components/ui";
import { RankBars } from "../../components/charts";
import { api } from "../../lib/api";
import { fmtMonth } from "../../lib/format";
import { useMe } from "../../lib/session";

const TIER: Record<string, { label: string; tone: "brand" | "indigo" | "amber" | "slate" | "sky" }> = {
  monograph: { label: "Monograph", tone: "brand" },
  ich_guideline: { label: "ICH", tone: "indigo" },
  regulatory_registry: { label: "Regulatory registry", tone: "sky" },
  patent: { label: "Patent", tone: "sky" },
  empirical_cohort: { label: "NSQ cohort", tone: "indigo" },
  expert_corridor: { label: "Expert corridor", tone: "amber" },
  uncited: { label: "Uncited", tone: "slate" },
};

function Prov({ p }: { p?: any }) {
  if (!p?.authority_tier) return null;
  const t = TIER[p.authority_tier] ?? { label: p.authority_tier, tone: "slate" as const };
  return <span title={[p.source_ref, p.notes].filter(Boolean).join(" — ")}><Badge tone={t.tone}>{t.label}{p.source_ref ? ` · ${p.source_ref}` : ""}</Badge></span>;
}

function Section({ icon, title, children, i }: { icon: ReactNode; title: string; children: ReactNode; i: number }) {
  return (
    <motion.section initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.05 * i, duration: 0.35 }} className="rounded-2xl border border-line p-5">
      <h4 className="mb-3 flex items-center gap-2 font-display text-sm font-bold"><span className="text-brand-700">{icon}</span>{title}</h4>
      {children}
    </motion.section>
  );
}

const ORDER: Record<string, string[]> = {
  QA: ["why", "pattern", "cause", "corridor", "methods", "capa", "history"],
  Regulatory: ["why", "methods", "capa", "cause", "pattern", "corridor", "history"],
  Executive: ["why", "pattern", "capa", "cause", "history", "methods", "corridor"],
};

export function IssueDrawer({ slug, issueId, onClose }: { slug: string; issueId?: string; onClose: () => void }) {
  const { data: me } = useMe();
  const { data, isLoading, error } = useQuery({
    queryKey: ["issue", slug, issueId],
    queryFn: () => api<any>(`/api/orgs/${slug}/quality/issues/${issueId}`),
    enabled: !!issueId,
  });
  const d = data?.diagnosis;
  const issue = data?.issue;
  const drug = d?.drug;

  const blocks: Record<string, ReactNode> = d ? {
    why: (
      <Section key="why" i={0} icon={<AlertTriangle size={15} />} title="Why it was flagged">
        <p className="text-[15px] font-medium leading-relaxed">{issue.reason}</p>
        <div className="mt-3 flex flex-wrap gap-2">
          <Badge tone="rose">{issue.category}</Badge>
          <Badge>{issue.form}</Badge>
          {d.is_dominant_failure && <Badge tone="amber">Your most frequent failure mode</Badge>}
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
      <Section key="pattern" i={1} icon={<TrendingUp size={15} />} title="Pattern across your alerts">
        <div className="mb-3 text-xs text-ink-muted">{d.tenant_alert_count} alerts across {d.form_span} dosage forms.</div>
        <RankBars rows={d.dominant_failures.map((f: any) => ({ name: f[0], count: f[1], sub: `${f[2]}%` }))} color="#6366f1" />
        {d.temporal_clusters?.length > 0 && (
          <div className="mt-5">
            <div className="label mb-2">Alerts per month (last 24)</div>
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
      <Section key="cause" i={2} icon={<Microscope size={15} />} title="Probable root causes">
        {drug ? (
          <>
            <div className="mb-2 text-xs text-ink-muted">Curated profile: <b>{drug.name}</b> · {drug.dosage_form} <Prov p={drug.common_alerts_prov} /></div>
            <ul className="space-y-2">
              {drug.common_alerts.map((a: string) => <li key={a} className="flex gap-2 text-sm"><span className="mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full bg-rose-500" />{a}</li>)}
            </ul>
            {drug.vigibase_risks?.length > 0 && (
              <div className="mt-4 rounded-xl bg-rose-50/60 p-3">
                <div className="label mb-1.5 text-rose-700">Patient-safety consequence</div>
                {drug.vigibase_risks.map((r: any) => <div key={r.hazard} className="text-sm"><b>{r.hazard}.</b> <span className="text-ink-soft">{r.desc}</span></div>)}
              </div>
            )}
          </>
        ) : (
          <div className="space-y-2 text-sm text-ink-soft">
            <p>No curated molecule profile for this product yet — showing the generic standards.</p>
            {d.generic_text && Object.values(d.generic_text).map((t: any, i) => <p key={i} className="rounded-xl bg-slate-50 p-3 text-xs leading-relaxed">{t}</p>)}
          </div>
        )}
        {d.synthesis_gap && <p className="mt-3 text-xs text-ink-muted">Synthesis-route data is not in the knowledge base yet, so route-related causes are not assessed.</p>}
      </Section>
    ),
    corridor: drug ? (
      <Section key="corridor" i={3} icon={<Beaker size={15} />} title="GMP process corridor">
        <div className="mb-3 text-sm">Optimal process: <b>{drug.optimal_process}</b> <Prov p={drug.optimal_process_prov} /></div>
        <div className="space-y-4">
          {Object.entries(drug.ideal_parameters ?? {}).map(([k, p]: [string, any]) => {
            const pos = ((p.ideal - p.min) / (p.max - p.min || 1)) * 100;
            return (
              <div key={k}>
                <div className="mb-1 flex justify-between text-xs"><span className="font-medium">{p.label}</span><span className="text-ink-muted">{p.min}–{p.max} {p.unit} · ideal {p.ideal}</span></div>
                <div className="relative h-2 rounded-full bg-gradient-to-r from-amber-200 via-brand-200 to-amber-200">
                  <motion.div className="absolute -top-1 h-4 w-1.5 rounded-full bg-brand-700" initial={{ left: "0%" }} animate={{ left: `calc(${pos}% - 3px)` }} transition={{ duration: 0.8 }} />
                </div>
              </div>
            );
          })}
        </div>
        {drug.ideal_excipients?.length > 0 && (
          <table className="mt-5 w-full text-xs">
            <thead><tr className="text-left text-ink-muted"><th className="pb-1.5 font-medium">Excipient</th><th className="pb-1.5 font-medium">Role</th><th className="pb-1.5 text-right font-medium">% w/w</th></tr></thead>
            <tbody>{drug.ideal_excipients.map((e: any) => <tr key={e.name} className="border-t border-line" title={e.description}><td className="py-1.5 font-medium">{e.name}</td><td>{e.role}</td><td className="text-right tabular-nums">{e.ratio}</td></tr>)}</tbody>
          </table>
        )}
      </Section>
    ) : null,
    methods: d.method_diffs?.length ? (
      <Section key="methods" i={4} icon={<BookOpenCheck size={15} />} title={`Pharmacopoeial differences (${d.nsq_relevant_method_diffs} relevant)`}>
        <div className="space-y-3">
          {d.method_diffs.filter((m: any) => m.significance === "NSQ_RELEVANT").map((m: any) => (
            <div key={m.section} className="rounded-xl bg-slate-50 p-3">
              <div className="flex items-center justify-between"><span className="text-sm font-semibold capitalize">{m.section.replace(/_/g, " ")}</span><Badge tone="amber">{m.rationale}</Badge></div>
              <div className="mt-2 grid gap-2 sm:grid-cols-3">
                {Object.entries(m.methods).map(([k, v]: [string, any]) => (
                  <div key={k} className="rounded-lg bg-white p-2.5 text-[11.5px] ring-1 ring-line">
                    <div className="mb-1 font-semibold">{v?.pharmacopeia ?? k.replace("Pharmacopeia.", "")}</div>
                    <div className="text-ink-soft">{v?.raw_text ?? <span className="text-ink-faint">No monograph</span>}</div>
                  </div>
                ))}
              </div>
            </div>
          ))}
        </div>
      </Section>
    ) : null,
    capa: (
      <Section key="capa" i={5} icon={<ClipboardCheck size={15} />} title="Corrective & preventive actions">
        <ol className="space-y-2.5">
          {d.mitigations.map((m: any, i: number) => (
            <li key={i} className="flex gap-3 text-sm">
              <span className="grid h-6 w-6 shrink-0 place-items-center rounded-full bg-brand-50 text-xs font-bold text-brand-700">{i + 1}</span>
              <div>{m.text} <div className="mt-1"><Prov p={m.provenance} /></div></div>
            </li>
          ))}
        </ol>
      </Section>
    ),
    history: data.history?.length > 1 ? (
      <Section key="history" i={6} icon={<History size={15} />} title="Same product — earlier alerts">
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
