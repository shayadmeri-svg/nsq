import { CheckCircle2, CircleDashed, CircleSlash, Globe2, ShieldCheck, TriangleAlert, XCircle } from "lucide-react";
import { motion } from "motion/react";
import { useMemo, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { Badge, Card, CardHeader, Drawer, ErrorNote, itemVariants, listVariants, PageHeader, PageSkeleton, Ring, Segmented, Stat } from "../../components/ui";
import { cn } from "../../lib/cn";
import { fmtDate } from "../../lib/format";
import { STATUS_STYLE, useOrg, useOrgData, VERDICT } from "./common";

const STAGES = [
  { id: "access", title: "Market access", items: ["eu_market_open"] },
  { id: "dossier", title: "Dossier", items: ["ph_eur", "similarity", "stability"] },
  { id: "site", title: "Manufacturing site", items: ["eu_gmp_site", "annex_1", "fmd", "nsq_signal"] },
  { id: "import", title: "Import & release", items: ["qp_release", "written_confirmation"] },
];

const ICON: Record<string, JSX.Element> = {
  met: <CheckCircle2 size={18} className="text-emerald-600" />,
  attention: <CircleDashed size={18} className="text-amber-600" />,
  gap: <XCircle size={18} className="text-rose-600" />,
  na: <CircleSlash size={18} className="text-slate-400" />,
};

function RouteMap({ assessments }: { assessments: any[] }) {
  const stats = STAGES.map((s) => {
    const c = { met: 0, attention: 0, gap: 0 };
    assessments.forEach((a) => a.items.forEach((it: any) => { if (s.items.includes(it.id) && it.status in c) (c as any)[it.status]++; }));
    const tot = c.met + c.attention + c.gap || 1;
    return { ...s, c, tot };
  });
  return (
    <div className="grid gap-3 md:grid-cols-4">
      {stats.map((s, i) => (
        <motion.div key={s.id} initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.1 + i * 0.08 }} className="relative rounded-2xl border border-line bg-white p-4">
          {i < stats.length - 1 && <div className="absolute -right-3 top-1/2 z-10 hidden h-0.5 w-3 bg-line md:block" />}
          <div className="flex items-center gap-2"><span className="grid h-6 w-6 place-items-center rounded-full bg-ink text-[11px] font-bold text-white">{i + 1}</span><span className="text-sm font-semibold">{s.title}</span></div>
          <div className="mt-3 flex h-2 overflow-hidden rounded-full bg-slate-100">
            <motion.div className="bg-emerald-500" initial={{ width: 0 }} animate={{ width: `${(100 * s.c.met) / s.tot}%` }} transition={{ duration: 0.8, delay: 0.2 + i * 0.08 }} />
            <motion.div className="bg-amber-400" initial={{ width: 0 }} animate={{ width: `${(100 * s.c.attention) / s.tot}%` }} transition={{ duration: 0.8, delay: 0.3 + i * 0.08 }} />
            <motion.div className="bg-rose-500" initial={{ width: 0 }} animate={{ width: `${(100 * s.c.gap) / s.tot}%` }} transition={{ duration: 0.8, delay: 0.4 + i * 0.08 }} />
          </div>
          <div className="mt-2 flex gap-3 text-[11px] text-ink-muted"><span>{s.c.met} met</span><span>{s.c.attention} check</span><span className={s.c.gap ? "font-semibold text-rose-600" : ""}>{s.c.gap} gaps</span></div>
        </motion.div>
      ))}
    </div>
  );
}

function Checklist({ a }: { a: any }) {
  return (
    <div className="space-y-5">
      <div className="flex items-center gap-5 rounded-2xl border border-line p-4">
        <Ring value={a.readiness_pct} size={84} stroke={8} color={VERDICT[a.verdict].color}><div><div className="font-display text-lg font-extrabold">{a.readiness_pct}%</div></div></Ring>
        <div className="space-y-1 text-sm">
          <div className="font-semibold">{VERDICT[a.verdict].label}</div>
          <div className="text-xs text-ink-muted">Assessed on {a.plant_name ?? "no plant"} · EU LOE {a.eu_loe ? fmtDate(a.eu_loe) : "passed / none"} · barrier: {a.eu_patent_barrier}</div>
          <div className="flex gap-1.5 pt-1">{(["met", "attention", "gap"] as const).map((s) => <span key={s} className={cn("rounded-full px-2 py-0.5 text-[11px] font-semibold ring-1 ring-inset", STATUS_STYLE[s].cls)}>{a.counts[s]} {STATUS_STYLE[s].label.toLowerCase()}</span>)}</div>
        </div>
      </div>
      {STAGES.map((st) => (
        <div key={st.id}>
          <div className="label mb-2">{st.title}</div>
          <motion.ul variants={listVariants} initial="hidden" animate="show" className="space-y-2">
            {a.items.filter((it: any) => st.items.includes(it.id)).map((it: any) => (
              <motion.li variants={itemVariants} key={it.id} className={cn("rounded-xl border p-3.5", it.status === "gap" ? "border-rose-200 bg-rose-50/40" : "border-line")}>
                <div className="flex items-start gap-3">
                  <span className="mt-0.5">{ICON[it.status]}</span>
                  <div className="min-w-0 flex-1">
                    <div className="flex flex-wrap items-center justify-between gap-2"><span className="text-sm font-semibold">{it.title}</span>{it.reference && <span className="text-[11px] text-ink-faint">{it.reference}</span>}</div>
                    <div className="mt-0.5 text-[13px] text-ink-soft">{it.detail}</div>
                    {it.how_to_close && it.status !== "met" && <div className="mt-2 rounded-lg bg-white px-3 py-2 text-xs text-ink-soft ring-1 ring-inset ring-line"><b className="text-ink">How to close: </b>{it.how_to_close}</div>}
                  </div>
                </div>
              </motion.li>
            ))}
          </motion.ul>
        </div>
      ))}
    </div>
  );
}

export function EuExport() {
  const { org, slug } = useOrg();
  const { molecule } = useParams();
  const nav = useNavigate();
  const { data, isLoading, error } = useOrgData<any>("eu-export");
  const [filter, setFilter] = useState("all");
  const list = useMemo(() => (data?.assessments ?? []).filter((a: any) => filter === "all" || a.verdict === filter), [data, filter]);
  if (isLoading || !org) return <PageSkeleton />;
  if (error) return <ErrorNote error={error} />;
  const current = data.assessments.find((a: any) => a.molecule_key === molecule);
  const v = data.verdicts;

  return (
    <>
      <PageHeader eyebrow="EU export route" title="What stands between you and the EU market" subtitle="The EU generic route, checked per molecule on your best plant: patents & SPC, dossier, site GMP, falsified-medicines rules, importer release and the API written confirmation." />
      <div className="grid grid-cols-2 gap-4 xl:grid-cols-4">
        <Stat label="Within reach" value={(v.ready ?? 0) + (v.close ?? 0)} icon={<Globe2 size={18} />} hint={`${v.ready ?? 0} ready · ${v.close ?? 0} with ≤ 2 gaps`} />
        <Stat label="Far from ready" value={v.far ?? 0} icon={<TriangleAlert size={18} />} tone="rose" delay={0.05} hint="3 or more open gaps" />
        <Stat label="EU GMP sites" value={data.eu_gmp_sites.length} icon={<ShieldCheck size={18} />} tone="indigo" delay={0.1} hint={data.eu_gmp_sites.join(", ") || `of ${data.plants} plant(s)`} />
        <Stat label="NSQ alerts on record" value={data.org_nsq_alerts} tone="amber" delay={0.15} hint="EU inspectors review market quality history" />
      </div>

      <Card delay={0.15} className="mt-5 p-5">
        <div className="mb-4 flex items-center justify-between"><h3 className="font-display text-[15px] font-bold">Route map</h3><span className="text-xs text-ink-muted">status across all molecules</span></div>
        <RouteMap assessments={data.assessments} />
      </Card>

      <div className="mt-5 grid gap-5 xl:grid-cols-[1fr_1.7fr]">
        <Card delay={0.2}>
          <CardHeader title="Close these first" subtitle="Gaps that block the most molecules" />
          <motion.ul variants={listVariants} initial="hidden" animate="show" className="space-y-3 p-5">
            {data.blockers.length === 0 && <li className="text-sm text-ink-muted">No blocking gaps.</li>}
            {data.blockers.map((b: any) => (
              <motion.li variants={itemVariants} key={b.id} className="rounded-xl border border-rose-100 bg-rose-50/40 p-3.5">
                <div className="flex items-start justify-between gap-3"><span className="text-sm font-semibold">{b.title}</span><Badge tone="rose">{b.molecules} molecules</Badge></div>
                <p className="mt-1.5 text-xs leading-relaxed text-ink-soft">{b.how_to_close}</p>
                <p className="mt-1 text-[11px] text-ink-faint">{b.reference}</p>
              </motion.li>
            ))}
          </motion.ul>
        </Card>
        <Card delay={0.25}>
          <CardHeader title="Molecules" subtitle="Click one for its full checklist" action={<Segmented value={filter} onChange={setFilter} options={[{ value: "all", label: "All" }, { value: "ready", label: "Ready" }, { value: "close", label: "Within reach" }, { value: "far", label: "Far" }]} />} />
          <motion.div variants={listVariants} initial="hidden" animate="show" className="grid gap-3 p-5 sm:grid-cols-2">
            {list.map((a: any) => (
              <motion.button variants={itemVariants} whileHover={{ y: -2 }} key={a.molecule_key} onClick={() => nav(`/o/${slug}/eu/${a.molecule_key}`)} className="flex items-center gap-4 rounded-2xl border border-line p-3.5 text-left transition hover:border-brand-300 hover:shadow-card">
                <Ring value={a.readiness_pct} size={52} stroke={6} color={VERDICT[a.verdict].color}><span className="text-[11px] font-bold">{a.readiness_pct}</span></Ring>
                <div className="min-w-0">
                  <div className="truncate text-sm font-semibold">{a.api_name}</div>
                  <div className="mt-1 flex gap-1.5">
                    {a.counts.gap > 0 && <span className="rounded-full bg-rose-50 px-1.5 text-[10.5px] font-semibold text-rose-700">{a.counts.gap} gap</span>}
                    <span className="rounded-full bg-amber-50 px-1.5 text-[10.5px] font-semibold text-amber-700">{a.counts.attention} check</span>
                    <span className="rounded-full bg-emerald-50 px-1.5 text-[10.5px] font-semibold text-emerald-700">{a.counts.met} met</span>
                  </div>
                </div>
              </motion.button>
            ))}
          </motion.div>
        </Card>
      </div>
      <p className="mt-4 text-xs text-ink-muted">Checks use the curated patent, regulatory and plant data held on the platform. "Check" means the data cannot confirm the item — a regulatory specialist should verify it.</p>
      <Drawer open={!!molecule} onClose={() => nav(`/o/${slug}/eu`)} title={current?.api_name ?? ""} subtitle="EU generic-route checklist" width={760}>
        {current && <Checklist a={current} />}
      </Drawer>
    </>
  );
}
