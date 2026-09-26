import { Activity, ArrowUpRight, Factory, Globe2, Sparkles, Trophy } from "lucide-react";
import { motion } from "motion/react";
import { Link } from "react-router-dom";
import { Legendary, RankBars, TrendBars } from "../../components/charts";
import { Badge, Card, CardHeader, Empty, ErrorNote, itemVariants, listVariants, PageHeader, PageSkeleton, Ring, Stat } from "../../components/ui";
import { Estimate } from "../../components/ui/Estimate";
import { fmtMonth, TIER_STYLE, titleCase } from "../../lib/format";
import { useOrg, useOrgData, VERDICT } from "./common";

export function OrgOverview() {
  const { org, slug } = useOrg();
  const { data, isLoading, error } = useOrgData<any>("overview");
  if (isLoading || !org) return <PageSkeleton />;
  if (error) return <ErrorNote error={error} />;
  const q = data.quality;
  const opp = data.opportunities;
  const eu = data.eu;
  const k = q.kpis ?? {};
  const good = (opp.tiers.strategic ?? 0) + (opp.tiers.core ?? 0);

  return (
    <>
      <PageHeader
        eyebrow="Organisation overview"
        title={org.name}
        subtitle={`${org.city ? org.city + " · " : ""}${org.country} — CDSCO quality record, manufacturing footprint, off-patent opportunities and EU export readiness.`}
      />

      <div className="grid grid-cols-2 gap-4 xl:grid-cols-4">
        <Stat label="NSQ alerts" value={k.alerts ?? 0} icon={<Activity size={18} />} tone="rose" hint={k.alerts ? `${k.last_12m} in the last 12 months · ${fmtMonth(q.period?.first)} – ${fmtMonth(q.period?.last)}` : "No alerts linked to this organisation"} />
        <Stat label="National rank" value={k.national_rank ? `#${k.national_rank}` : "—"} icon={<Trophy size={18} />} tone="amber" delay={0.05} hint={k.national_rank ? `by alert count among ${k.manufacturers_ranked?.toLocaleString("en-IN")} manufacturers` : "Not ranked"} />
        <Stat label="Molecules within reach" value={good} icon={<Sparkles size={18} />} tone="brand" delay={0.1} hint={`strategic or core fit · ${opp.ready_within_5y} available within 5 years`} />
        <Stat label="EU-ready or close" value={(eu.verdicts.ready ?? 0) + (eu.verdicts.close ?? 0)} icon={<Globe2 size={18} />} tone="indigo" delay={0.15} hint={eu.eu_gmp_sites.length ? `EU GMP site: ${eu.eu_gmp_sites.join(", ")}` : "No EU GMP certified site"} />
      </div>

      <div className="mt-5 grid gap-5 xl:grid-cols-[1.6fr_1fr]">
        <Card delay={0.1}>
          <CardHeader icon={<Activity size={16} />} title="Why batches get flagged" subtitle="Monthly CDSCO NSQ alerts by failure category" action={<Link to={`/o/${slug}/quality`} className="flex items-center gap-1 text-xs font-semibold text-brand-700 hover:underline">Quality signals <ArrowUpRight size={14} /></Link>} />
          <div className="px-3 pb-4 pt-3">
            {q.trend?.months?.length ? <><TrendBars data={q.trend} height={240} /><div className="px-3 pt-2"><Legendary items={q.trend.series} /></div></> : <Empty title="No NSQ alerts">This organisation has no linked manufacturer records.</Empty>}
          </div>
        </Card>
        <Card delay={0.15}>
          <CardHeader title="Top failure reasons" subtitle="Share of this organisation's alerts" />
          <div className="p-5">{q.categories?.length ? <RankBars rows={q.categories} color="#e11d48" /> : <div className="text-sm text-ink-muted">—</div>}</div>
        </Card>
      </div>

      <div className="mt-5 grid gap-5 xl:grid-cols-2">
        <Card delay={0.2}>
          <CardHeader icon={<Sparkles size={16} />} title={<span className="flex items-center gap-1.5">Best-fit off-patent molecules <Estimate field="loe" /></span>} subtitle="Tracked molecules: patent expiry × your plant capability" action={<Link to={`/o/${slug}/opportunities`} className="flex items-center gap-1 text-xs font-semibold text-brand-700 hover:underline">All opportunities <ArrowUpRight size={14} /></Link>} />
          <motion.ul variants={listVariants} initial="hidden" animate="show" className="divide-y divide-line px-5 py-2">
            {opp.top.map((m: any) => (
              <motion.li variants={itemVariants} key={m.molecule_key}>
                <Link to={`/o/${slug}/opportunities/${m.molecule_key}`} className="flex items-center justify-between gap-3 py-3 transition hover:translate-x-0.5">
                  <div className="min-w-0">
                    <div className="truncate text-sm font-semibold">{m.api_name}</div>
                    <div className="text-xs text-ink-muted">{m.therapeutic_area} · {m.available_now ? "off-patent now" : `LOE in ${m.years_to_loe} y`} · {m.best_plant?.name ?? "no plant"}</div>
                  </div>
                  <div className="flex items-center gap-3">
                    <span className={`rounded-full px-2 py-0.5 text-[11px] font-semibold ring-1 ring-inset ${TIER_STYLE[m.fit_tier]}`}>{titleCase(m.fit_tier)}</span>
                    <span className="w-10 text-right font-display text-sm font-bold tabular-nums">{Math.round(m.fit_score)}</span>
                  </div>
                </Link>
              </motion.li>
            ))}
          </motion.ul>
          {opp.unlocks?.length > 0 && (
            <div className="border-t border-line px-5 py-4">
              <div className="label mb-2">Biggest unlocks</div>
              <div className="flex flex-wrap gap-2">
                {opp.unlocks.map((u: any) => <Badge key={u.token} tone="indigo">+ {u.label} → {u.count} molecules</Badge>)}
              </div>
            </div>
          )}
        </Card>

        <Card delay={0.25}>
          <CardHeader icon={<Globe2 size={16} />} title="EU export readiness" subtitle="Generic route checklist per molecule" action={<Link to={`/o/${slug}/eu`} className="flex items-center gap-1 text-xs font-semibold text-brand-700 hover:underline">EU route <ArrowUpRight size={14} /></Link>} />
          <div className="grid grid-cols-5 gap-3 px-5 py-5">
            {eu.top.map((a: any, i: number) => (
              <motion.div key={a.molecule_key} initial={{ opacity: 0, scale: 0.9 }} animate={{ opacity: 1, scale: 1 }} transition={{ delay: 0.3 + i * 0.06 }}>
                <Link to={`/o/${slug}/eu/${a.molecule_key}`} className="flex flex-col items-center gap-2 text-center">
                  <Ring value={a.readiness_pct} size={68} color={VERDICT[a.verdict].color}><span className="font-display text-sm font-extrabold">{a.readiness_pct}%</span></Ring>
                  <span className="line-clamp-2 text-[11.5px] font-medium leading-tight">{a.api_name}</span>
                </Link>
              </motion.div>
            ))}
          </div>
          {eu.blockers?.length > 0 && (
            <div className="border-t border-line px-5 py-4">
              <div className="label mb-2">Blocking most molecules</div>
              <ul className="space-y-1.5 text-sm">
                {eu.blockers.map((b: any) => <li key={b.id} className="flex justify-between gap-3"><span className="text-ink-soft">{b.title}</span><span className="text-xs font-semibold text-rose-600">{b.molecules} molecules</span></li>)}
              </ul>
            </div>
          )}
        </Card>
      </div>

      <Card delay={0.3} className="mt-5">
        <CardHeader icon={<Factory size={16} />} title="Manufacturing footprint" subtitle={`${data.infrastructure.plants} plant(s) · ${data.infrastructure.capabilities} capabilities`} action={<Link to={`/o/${slug}/infrastructure`} className="flex items-center gap-1 text-xs font-semibold text-brand-700 hover:underline">Infrastructure <ArrowUpRight size={14} /></Link>} />
        <div className="flex flex-wrap gap-2 px-5 pb-5 pt-3">
          {data.infrastructure.certifications.length ? data.infrastructure.certifications.map((c: string) => <Badge key={c} tone="brand">{c.replace(/_/g, " ").toUpperCase()}</Badge>) : <span className="text-sm text-ink-muted">No plants linked yet.</span>}
        </div>
      </Card>
    </>
  );
}
