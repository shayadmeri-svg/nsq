import { useQuery } from "@tanstack/react-query";
import { ArrowRight, CalendarClock, CircleDashed, Crosshair, Lightbulb, Rocket, Sparkles } from "lucide-react";
import { motion } from "motion/react";
import { useMemo, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { CartesianGrid, ResponsiveContainer, Scatter, ScatterChart, Tooltip, XAxis, YAxis, ZAxis, Cell, ReferenceLine } from "recharts";
import { PillarRadar } from "../../components/charts";
import { Badge, Button, Card, CardHeader, Drawer, Empty, ErrorNote, itemVariants, listVariants, PageHeader, PageSkeleton, Ring, Segmented, Skeleton, Stat } from "../../components/ui";
import { Estimate } from "../../components/ui/Estimate";
import { api } from "../../lib/api";
import { fmtDate, TIER_STYLE, titleCase } from "../../lib/format";
import { useOrg, useOrgData, VERDICT } from "./common";
import { useMe } from "../../lib/session";

const TIER_COLOR: Record<string, string> = { strategic: "#0a9a7d", core: "#6366f1", adjacent: "#f59e0b", stretch: "#94a3b8" };

function Loe({ loe, prov }: { loe: Record<string, string | null>; prov?: Record<string, any> }) {
  if (!loe.in && !loe.eu && !loe.us && !prov) return <span className="inline-flex rounded-full bg-emerald-50 px-2 py-0.5 text-[11px] font-semibold text-emerald-700 ring-1 ring-inset ring-emerald-200">Off-patent everywhere</span>;
  const past = (d: string | null) => !!d && new Date(d) < new Date();
  return (
    <div className="flex gap-3 text-xs">
      {(["in", "eu", "us"] as const).map((k) => {
        const p = prov?.[`loe_${k}`];
        const unknown = !loe[k] && p?.status === "unknown";
        return (
          <div key={k} className="flex items-center gap-0.5"><span className="text-ink-faint">{k.toUpperCase()}&nbsp;</span>
            <span className={`whitespace-nowrap font-medium ${past(loe[k]) || (!loe[k] && !unknown) ? "text-emerald-700" : ""} ${unknown ? "text-ink-faint" : ""}`}>{loe[k] ? fmtDate(loe[k]).replace(/^\d+ /, "") : unknown ? "?" : "open"}</span>
            {p && <Estimate field="loe" prov={p} />}
          </div>
        );
      })}
    </div>
  );
}

const ORIGIN_BADGE: Record<string, JSX.Element> = {
  curated: <Badge tone="brand">Tracked</Badge>,
  auto: <Badge tone="sky">Tracked · sourced</Badge>,
  manual: <Badge tone="amber">Watchlist</Badge>,
};

function CliffChart({ rows, onPick }: { rows: any[]; onPick: (k: string) => void }) {
  // Off-patent molecules all sit at x = 0; spread them deterministically so each bubble stays clickable.
  let n = 0;
  const pts = rows.map((r) => ({ ...r, x: r.available_now ? -0.6 + ((n++ * 0.37) % 1.2) : r.years_to_loe, y: r.fit_score + (r.available_now ? ((n % 5) - 2) * 1.2 : 0), z: r.market_size_usd_bn || 0.5 }));
  return (
    <ResponsiveContainer width="100%" height={300}>
      <ScatterChart margin={{ top: 16, right: 24, bottom: 8, left: -10 }}>
        <CartesianGrid stroke="#eef1f6" />
        <XAxis type="number" dataKey="x" name="Years to LOE" domain={[-1, "dataMax + 1"]} tickFormatter={(v) => (v < 0 ? "now" : String(v))} tickLine={false} axisLine={false} label={{ value: "Years until first loss of exclusivity →", position: "insideBottom", offset: -4, fontSize: 11, fill: "#94a3b8" }} height={40} />
        <YAxis type="number" dataKey="y" name="Plant fit" domain={[0, 100]} tickLine={false} axisLine={false} width={44} />
        <ZAxis type="number" dataKey="z" range={[60, 900]} />
        <ReferenceLine y={60} stroke="#cbd5e1" strokeDasharray="4 4" />
        <Tooltip cursor={{ strokeDasharray: "3 3" }} content={({ active, payload }: any) => active && payload?.[0] ? (
          <div className="rounded-xl bg-night-900/95 px-3 py-2 text-xs text-white shadow-lift">
            <div className="font-semibold">{payload[0].payload.api_name}</div>
            <div className="text-slate-300">Fit {Math.round(payload[0].payload.fit_score)} · {payload[0].payload.available_now ? "off-patent now" : `${payload[0].payload.years_to_loe} y to LOE`}</div>
            {payload[0].payload.market_size_usd_bn && <div className="text-slate-300">${payload[0].payload.market_size_usd_bn} bn market</div>}
          </div>
        ) : null} />
        <Scatter data={pts} onClick={(p: any) => onPick(p.molecule_key)} animationDuration={900} className="cursor-pointer">
          {pts.map((p) => <Cell key={p.molecule_key} fill={TIER_COLOR[p.fit_tier]} fillOpacity={0.65} stroke={TIER_COLOR[p.fit_tier]} />)}
        </Scatter>
      </ScatterChart>
    </ResponsiveContainer>
  );
}

function Detail({ slug, molecule, onClose }: { slug: string; molecule?: string; onClose: () => void }) {
  const { data, isLoading, error } = useQuery({ queryKey: ["opp", slug, molecule], queryFn: () => api<any>(`/api/orgs/${slug}/opportunities/${molecule}`), enabled: !!molecule });
  const r = data?.readiness;
  const fit = r?.customer_profile_fit;
  return (
    <Drawer open={!!molecule} onClose={onClose} title={data ? `${data.patent.api_name}` : "Loading…"} subtitle={data ? `${data.patent.brand_name} · ${data.patent.originator} · ${data.patent.therapeutic_area}` : undefined} width={780}>
      {isLoading && <div className="space-y-4"><Skeleton className="h-40" /><Skeleton className="h-60" /></div>}
      <ErrorNote error={error} />
      {data && (
        <div className="space-y-5">
          <div className="grid gap-4 sm:grid-cols-2">
            <div className="rounded-2xl border border-line p-4">
              <div className="label mb-2 flex items-center gap-1.5">Loss of exclusivity <Estimate field="loe" /></div>
              <Loe loe={{ in: data.patent.estimated_loe_in, eu: data.patent.estimated_loe_eu, us: data.patent.estimated_loe_us }} prov={data.patent.provenance && Object.keys(data.patent.provenance).length ? data.patent.provenance : undefined} />
              <div className="mt-3 flex flex-wrap items-center gap-1.5"><Badge tone={data.patent.fto_risk === "high" ? "rose" : data.patent.fto_risk === "medium" ? "amber" : "brand"}>FTO risk: {data.patent.fto_risk}</Badge><Estimate field="fto_risk" prov={data.patent.provenance?.fto_risk} />{data.patent.market_size_usd_bn && <><Badge tone="indigo">${data.patent.market_size_usd_bn} bn market</Badge><Estimate field="market_size_usd_bn" /></>}</div>
              <p className="mt-3 line-clamp-4 text-xs leading-relaxed text-ink-muted">{data.patent.notes}</p>
            </div>
            {fit ? (
              <div className="rounded-2xl border border-line p-4">
                <div className="flex items-center justify-between"><div className="label flex items-center gap-1.5">Fit with {data.plant.name} <Estimate field="talent_depth" /></div><span className={`rounded-full px-2 py-0.5 text-[11px] font-semibold ring-1 ring-inset ${TIER_STYLE[fit.commercial_fit_tier]}`}>{titleCase(fit.commercial_fit_tier)}</span></div>
                <PillarRadar height={190} scores={{ infrastructure: fit.infrastructure_fit_score, talent: fit.talent_fit_score, certification: fit.certification_fit_score, gmp: fit.gmp_readiness_score }} />
              </div>
            ) : <Empty title="No plant linked">Add a plant to score the fit.</Empty>}
          </div>
          {fit?.gaps?.length > 0 && (
            <div className="rounded-2xl bg-amber-50/70 p-4 ring-1 ring-inset ring-amber-200">
              <div className="mb-2 flex items-center gap-2 text-sm font-semibold text-amber-800"><Lightbulb size={15} /> What it takes</div>
              <ul className="space-y-1 text-sm text-amber-900">{fit.gaps.map((g: string) => <li key={g}>• {g.replace(/_/g, " ")}</li>)}</ul>
            </div>
          )}
          {r?.roadmap?.length > 0 && (
            <div>
              <div className="label mb-3">Roadmap to launch</div>
              <ol className="relative space-y-4 border-l-2 border-brand-100 pl-6">
                {r.roadmap.map((ph: any, i: number) => (
                  <motion.li key={ph.phase_id} initial={{ opacity: 0, x: -8 }} animate={{ opacity: 1, x: 0 }} transition={{ delay: i * 0.07 }} className="relative">
                    <span className="absolute -left-[33px] top-0.5 grid h-5 w-5 place-items-center rounded-full bg-brand-600 text-[10px] font-bold text-white">{i + 1}</span>
                    <div className="flex items-baseline justify-between gap-3"><span className="text-sm font-semibold">{ph.title}</span><span className="text-xs text-ink-muted">{ph.estimated_duration_months} mo</span></div>
                    <div className="mt-1 text-xs text-ink-soft">{ph.activities.slice(0, 3).join(" · ")}</div>
                    {ph.readiness_gates?.length > 0 && <div className="mt-1.5 flex flex-wrap gap-1">{ph.readiness_gates.slice(0, 3).map((g: string) => <Badge key={g} tone="slate">{g}</Badge>)}</div>}
                  </motion.li>
                ))}
              </ol>
            </div>
          )}
          {data.eu && (
            <Link to={`/o/${slug}/eu/${molecule}`} className="flex items-center justify-between rounded-2xl border border-line p-4 transition hover:border-brand-300 hover:bg-brand-50/30">
              <div className="flex items-center gap-4">
                <Ring value={data.eu.readiness_pct} size={56} color={VERDICT[data.eu.verdict].color}><span className="text-xs font-bold">{data.eu.readiness_pct}%</span></Ring>
                <div><div className="text-sm font-semibold">EU export readiness</div><div className="text-xs text-ink-muted">{data.eu.counts.gap} gaps · {data.eu.counts.attention} to check</div></div>
              </div>
              <ArrowRight size={16} className="text-ink-muted" />
            </Link>
          )}
        </div>
      )}
    </Drawer>
  );
}

export function Opportunities() {
  const { org, slug } = useOrg();
  const { data: me } = useMe();
  const { molecule } = useParams();
  const nav = useNavigate();
  const { data, isLoading, error } = useOrgData<any>("opportunities");
  const [tier, setTier] = useState<string>("all");
  const [shown, setShown] = useState(40);
  // Molecules that appear in the organisation's own alerts come first.
  const rows = useMemo(() => (data?.molecules ?? [])
    .filter((m: any) => tier === "all" || m.fit_tier === tier)
    .slice().sort((a: any, b: any) => (b.alerts_in_org > 0 ? 1 : 0) - (a.alerts_in_org > 0 ? 1 : 0) || b.alerts_in_org - a.alerts_in_org || b.fit_score - a.fit_score), [data, tier]);
  if (isLoading || !org) return <PageSkeleton />;
  if (error) return <ErrorNote error={error} />;
  const t = data.tiers;
  const total = data.molecules.length;

  return (
    <>
      <PageHeader eyebrow="Patent opportunities" title="Which off-patent medicines your plants can make" subtitle="Each molecule's patent expiry, market and FTO risk scored against your best plant — and the additions that would unlock the rest." />
      {!data.has_plants && <div className="mb-5"><Empty title="No plants linked">Scores below assume no plant. Add one under Infrastructure.</Empty></div>}
      <div className="mb-4 flex flex-wrap items-center gap-x-5 gap-y-2 rounded-2xl bg-white px-4 py-3 text-xs text-ink-soft ring-1 ring-inset ring-line">
        <span className="flex items-center gap-2"><span className="h-3 w-1 rounded-full bg-brand-500" /><b className="text-ink">Tracked</b> — one of {total} molecules with patent, regulatory and demand profiles; scored below.</span>
        <span className="flex items-center gap-2"><span className="h-3 w-3 rounded border border-dashed border-slate-400" /><b className="text-ink">Untracked</b> — appears in your CDSCO alerts but has no profile yet, so it cannot be scored.</span>
        <span className="flex items-center gap-1.5"><Estimate field="loe" /> marks estimated values — hover for what is present and what is missing.</span>
      </div>
      <div className="grid gap-4 md:grid-cols-4">
        <Stat label="Your alerts on tracked molecules" value={data.coverage.alerts_tracked} icon={<Crosshair size={18} />} tone="rose" hint={`of ${data.coverage.alerts} NSQ alerts · ${data.coverage.untracked_total} untracked ingredients`} />
        <Stat label="Strategic + core fit" value={(t.strategic ?? 0) + (t.core ?? 0)} icon={<Sparkles size={18} />} hint={`of ${total} molecules tracked`} />
        <Stat label="Available within 5 years" value={data.ready_within_5y} icon={<CalendarClock size={18} />} tone="indigo" delay={0.05} hint={<span className="inline-flex items-center gap-1">good fit and off-patent or LOE ≤ 5 y <Estimate field="loe" /></span>} />
        <Card delay={0.1} className="p-5">
          <div className="label">Fit distribution</div>
          <div className="mt-4 flex h-3 overflow-hidden rounded-full bg-slate-100">
            {["strategic", "core", "adjacent", "stretch"].map((k, i) => (
              <motion.div key={k} title={`${titleCase(k)}: ${t[k] ?? 0}`} style={{ background: TIER_COLOR[k] }} initial={{ width: 0 }} animate={{ width: `${(100 * (t[k] ?? 0)) / total}%` }} transition={{ delay: 0.2 + i * 0.1, duration: 0.7 }} />
            ))}
          </div>
          <div className="mt-3 flex flex-wrap gap-3 text-xs">{["strategic", "core", "adjacent", "stretch"].map((k) => <span key={k} className="flex items-center gap-1.5"><span className="h-2 w-2 rounded-full" style={{ background: TIER_COLOR[k] }} />{titleCase(k)} <b>{t[k] ?? 0}</b></span>)}</div>
        </Card>
      </div>

      <div className="mt-5 grid gap-5 xl:grid-cols-[1.5fr_1fr]">
        <Card delay={0.1}>
          <CardHeader title={<span className="flex items-center gap-1.5">Patent cliff × plant fit <Estimate field="loe" /><Estimate field="market_size_usd_bn" /></span>} subtitle="Bubble size = market size (estimate). Click a molecule for its roadmap." />
          <div className="px-2 pb-3"><CliffChart rows={data.molecules} onPick={(k) => nav(`/o/${slug}/opportunities/${k}`)} /></div>
        </Card>
        <Card delay={0.15}>
          <CardHeader icon={<Rocket size={16} />} title="What to add next" subtitle="Additions that unlock the most molecules" />
          <motion.ul variants={listVariants} initial="hidden" animate="show" className="space-y-3 p-5">
            {data.unlocks.length === 0 && <li className="text-sm text-ink-muted">Your plants already cover every tracked molecule's core requirements.</li>}
            {data.unlocks.slice(0, 6).map((u: any) => (
              <motion.li variants={itemVariants} key={u.kind + u.token} className="rounded-xl border border-line p-3.5">
                <div className="flex items-start justify-between gap-3">
                  <div>
                    <div className="text-sm font-semibold">{u.label}</div>
                    <div className="text-[11px] uppercase tracking-wider text-ink-faint">{u.kind}</div>
                  </div>
                  <div className="text-right"><div className="font-display text-lg font-extrabold text-brand-700">+{u.count}</div><div className="flex items-center justify-end gap-1 text-[11px] text-ink-muted">{u.market_usd_bn ? <>${u.market_usd_bn} bn <Estimate field="market_size_usd_bn" align="right" /></> : "molecules"}</div></div>
                </div>
                <div className="mt-2 truncate text-xs text-ink-muted">{u.molecules.join(", ")}</div>
              </motion.li>
            ))}
          </motion.ul>
        </Card>
      </div>

      <Card delay={0.2} className="mt-5">
        <CardHeader title="Tracked molecules" subtitle={`${rows.length} shown · highlighted rows appear in your own CDSCO alerts`} action={
          <Segmented value={tier} onChange={setTier} options={[{ value: "all", label: "All" }, { value: "strategic", label: "Strategic" }, { value: "core", label: "Core" }, { value: "adjacent", label: "Adjacent" }, { value: "stretch", label: "Stretch" }]} />
        } />
        <div className="mt-4 overflow-x-auto">
          <table className="w-full text-sm">
            <thead><tr className="border-y border-line bg-slate-50/70 text-left text-[11px] font-semibold uppercase tracking-wider text-ink-muted">
              <th className="px-5 py-2.5">Molecule</th><th className="px-3 py-2.5">Your alerts</th><th className="px-3 py-2.5"><span className="inline-flex items-center gap-1">Loss of exclusivity <Estimate field="loe" /></span></th><th className="px-3 py-2.5">Best plant</th><th className="px-3 py-2.5">Fit</th><th className="px-3 py-2.5">Missing</th><th className="px-5 py-2.5 text-right">Score</th>
            </tr></thead>
            <tbody>
              {rows.slice(0, shown).map((m: any) => (
                <tr key={m.molecule_key} onClick={() => nav(`/o/${slug}/opportunities/${m.molecule_key}`)} className={`cursor-pointer border-b border-line/70 transition hover:bg-brand-50/40 ${m.alerts_in_org ? "bg-rose-50/30" : ""}`}>
                  <td className={`border-l-[3px] px-5 py-3 ${m.alerts_in_org ? "border-rose-400" : "border-brand-500"}`}><div className="flex items-center gap-2 font-semibold">{m.api_name}{ORIGIN_BADGE[m.origin] ?? ORIGIN_BADGE.curated}</div><div className="text-xs text-ink-muted">{m.therapeutic_area} · {titleCase(m.modality)}{m.market_size_usd_bn ? ` · $${m.market_size_usd_bn} bn` : ""}</div></td>
                  <td className="px-3 py-3">{m.alerts_in_org ? <Badge tone="rose">{m.alerts_in_org} NSQ</Badge> : <span className="text-xs text-ink-faint">—</span>}</td>
                  <td className="px-3 py-3"><Loe loe={m.loe} prov={Object.keys(m.prov ?? {}).length ? m.prov : undefined} /></td>
                  <td className="px-3 py-3 text-xs">{m.best_plant?.name ?? "—"}</td>
                  <td className="px-3 py-3"><span className={`rounded-full px-2 py-0.5 text-[11px] font-semibold ring-1 ring-inset ${TIER_STYLE[m.fit_tier]}`}>{titleCase(m.fit_tier)}</span></td>
                  <td className="max-w-[260px] px-3 py-3 text-xs text-ink-muted"><div className="truncate">{[...m.missing_capabilities.map((c: any) => c.label), ...m.missing_certifications.map((c: string) => c.toUpperCase())].join(", ") || <span className="text-emerald-600">Nothing core</span>}</div></td>
                  <td className="px-5 py-3 text-right font-display font-bold tabular-nums">{Math.round(m.fit_score)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {rows.length > shown && <div className="flex justify-center p-4"><Button variant="secondary" size="sm" onClick={() => setShown(shown + 60)}>Show {Math.min(60, rows.length - shown)} more of {rows.length - shown}</Button></div>}
      </Card>
      <Card delay={0.25} className="mt-5 border-dashed bg-white/60">
        <CardHeader icon={<CircleDashed size={16} />} title="Also in your CDSCO alerts — untracked" subtitle={`${data.coverage.untracked_total} ingredients with no patent, regulatory or demand profile yet. They cannot be scored until they are added to the tracked set.`} />
        {data.untracked.length === 0 ? <div className="px-5 pb-5 pt-3 text-sm text-ink-muted">Every ingredient in your alerts is tracked.</div> : (
          <motion.div variants={listVariants} initial="hidden" animate="show" className="grid gap-3 p-5 sm:grid-cols-2 xl:grid-cols-3">
            {data.untracked.map((u: any) => (
              <motion.div variants={itemVariants} key={u.ingredient} className="rounded-xl border border-dashed border-slate-300 bg-slate-50/50 p-3.5">
                <div className="flex items-start justify-between gap-2">
                  <div className="min-w-0"><div className="truncate font-semibold capitalize text-ink-soft">{u.ingredient}</div><div className="mt-0.5 text-[11px] uppercase tracking-wider text-ink-faint">Untracked</div></div>
                  <Badge tone="rose">{u.alerts} NSQ</Badge>
                </div>
                <div className="mt-2 text-xs text-ink-muted">{u.categories.join(" · ")}{u.last ? ` · last ${u.last}` : ""}</div>
                <div className="mt-1 truncate text-[11px] text-ink-faint" title={u.products.join(" | ")}>{u.products[0]}</div>
                {u.variants?.length > 0 && <div className="mt-1 truncate text-[11px] text-amber-700" title={u.variants.join(", ")}>also spelt: {u.variants.join(", ")}</div>}
                {me?.permissions.edit_molecules && <Link to={`/admin/molecules?add=${encodeURIComponent(u.ingredient)}`} className="mt-2 inline-flex items-center gap-1 text-[11px] font-semibold text-brand-700 hover:underline">Start tracking <ArrowRight size={11} /></Link>}
              </motion.div>
            ))}
          </motion.div>
        )}
      </Card>
      <Detail slug={slug} molecule={molecule} onClose={() => nav(`/o/${slug}/opportunities`)} />
    </>
  );
}
