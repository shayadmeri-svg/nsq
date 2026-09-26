import { useQuery } from "@tanstack/react-query";
import { Activity, ArrowUpRight, Building2, Database, HardDrive, PlayCircle, Users } from "lucide-react";
import { motion } from "motion/react";
import { Link } from "react-router-dom";
import { Legendary, TrendArea } from "../../components/charts";
import { Badge, Bar, Card, CardHeader, ErrorNote, itemVariants, listVariants, PageHeader, PageSkeleton, Stat } from "../../components/ui";
import { api } from "../../lib/api";
import { fmtDateTime, fmtMonth, timeAgo } from "../../lib/format";

const JOB_TONE: Record<string, any> = { succeeded: "brand", failed: "rose", running: "indigo", queued: "slate" };

export function AdminOverview() {
  const { data, isLoading, error } = useQuery({ queryKey: ["admin-overview"], queryFn: () => api<any>("/api/admin/overview"), refetchInterval: 30_000 });
  if (isLoading) return <PageSkeleton />;
  if (error) return <ErrorNote error={error} />;
  const r = data.data.redis ?? {};
  const snap = data.data.snapshot;
  const k = data.nsq.kpis;
  const frameOk = r.frame?.record_count && String(r.frame.record_count) === String(r.records);

  return (
    <>
      <PageHeader eyebrow="Platform" title="Admin overview" subtitle="Latest CDSCO data, data-store health, organisations and usage at a glance." actions={<Link to="/admin/jobs" className="inline-flex h-10 items-center gap-2 rounded-xl bg-ink px-4 text-sm font-medium text-white"><PlayCircle size={16} /> Data jobs</Link>} />
      <div className="grid grid-cols-2 gap-4 xl:grid-cols-4">
        <Stat label="NSQ alerts" value={k.alerts} icon={<Activity size={18} />} hint={`${k.manufacturers.toLocaleString("en-IN")} manufacturers · latest ${fmtMonth(k.latest_month)}`} />
        <Stat label={`Alerts in ${fmtMonth(k.latest_month)}`} value={k.latest_month_alerts} tone="rose" delay={0.05} hint="most recent CDSCO notification month" />
        <Stat label="Organisations" value={data.orgs.length} icon={<Building2 size={18} />} tone="indigo" delay={0.1} hint={`${data.orgs.filter((o: any) => o.is_active).length} active`} />
        <Stat label="Users" value={data.users.total} icon={<Users size={18} />} tone="amber" delay={0.15} hint={`${data.users.active_7d} active this week · ${data.users.failed_logins_7d} failed sign-ins`} />
      </div>

      <div className="mt-5 grid gap-5 xl:grid-cols-[1.6fr_1fr]">
        <Card delay={0.1}>
          <CardHeader title="All-India NSQ alerts" subtitle="Monthly, by failure category" action={<Link to="/admin/explorer" className="flex items-center gap-1 text-xs font-semibold text-brand-700 hover:underline">Explore <ArrowUpRight size={14} /></Link>} />
          <div className="px-3 pb-4 pt-3"><TrendArea data={data.nsq.trend} height={250} /><div className="px-3 pt-2"><Legendary items={data.nsq.trend.series} /></div></div>
        </Card>
        <Card delay={0.15}>
          <CardHeader icon={<Database size={16} />} title="Data stores" subtitle="What the dashboards are reading" />
          <div className="space-y-4 p-5 text-sm">
            <div>
              <div className="flex items-center justify-between"><span className="font-medium">In-server Redis</span><Badge tone={r.ok ? "brand" : "rose"}>{r.ok ? "online" : "down"}</Badge></div>
              {r.ok && <>
                <div className="mt-1 text-xs text-ink-muted">{r.records?.toLocaleString("en-IN")} records · loaded {timeAgo(r.meta?.loaded_at)}</div>
                <div className="mt-2 flex justify-between text-xs"><span className="text-ink-muted">Memory</span><span>{r.used_memory_mb} / {r.maxmemory_mb || "∞"} MB</span></div>
                {r.maxmemory_mb > 0 && <Bar value={(100 * r.used_memory_mb) / r.maxmemory_mb} className="mt-1" />}
                <div className="mt-2 flex flex-wrap gap-1.5">{Object.entries(r.cdmo ?? {}).map(([k, v]: any) => <Badge key={k}>{k} {v}</Badge>)}</div>
              </>}
            </div>
            <div className="border-t border-line pt-4">
              <div className="flex items-center justify-between"><span className="font-medium">Precomputed frame</span><Badge tone={frameOk ? "brand" : "amber"}>{frameOk ? "in sync" : "stale"}</Badge></div>
              <div className="mt-1 text-xs text-ink-muted">built {timeAgo(r.frame?.built_at)} from {Number(r.frame?.record_count ?? 0).toLocaleString("en-IN")} records · served from {data.data.frame_source}</div>
            </div>
            <div className="border-t border-line pt-4">
              <div className="flex items-center justify-between"><span className="flex items-center gap-1.5 font-medium"><HardDrive size={14} /> Snapshot file</span><Badge tone={snap ? "slate" : "amber"}>{snap ? "present" : "missing"}</Badge></div>
              {snap && <div className="mt-1 text-xs text-ink-muted">{snap.records?.toLocaleString("en-IN")} records · generated {fmtDateTime(snap.generated_at)}</div>}
            </div>
            <div className="border-t border-line pt-4 text-xs text-ink-muted">Upstash backup: {data.data.upstash_configured ? <span className="font-semibold text-brand-700">configured</span> : <span className="font-semibold text-amber-700">not configured</span>}</div>
          </div>
        </Card>
      </div>

      <div className="mt-5 grid gap-5 xl:grid-cols-3">
        <Card delay={0.2} className="xl:col-span-2">
          <CardHeader title="Latest alerts" subtitle={`CDSCO notification ${fmtMonth(k.latest_month)}`} />
          <motion.ul variants={listVariants} initial="hidden" animate="show" className="divide-y divide-line px-5 py-2">
            {data.nsq.latest_alerts.map((a: any) => (
              <motion.li variants={itemVariants} key={a.id} className="flex items-center justify-between gap-4 py-2.5 text-sm">
                <div className="min-w-0"><div className="truncate font-medium">{a.product}</div><div className="truncate text-xs text-ink-muted">{a.manufacturer} · {a.reason}</div></div>
                <Badge tone="rose">{a.category}</Badge>
              </motion.li>
            ))}
          </motion.ul>
        </Card>
        <Card delay={0.25}>
          <CardHeader title="Recent jobs" action={<Link to="/admin/jobs" className="text-xs font-semibold text-brand-700 hover:underline">All</Link>} />
          <ul className="space-y-2 p-5 text-sm">
            {data.recent_jobs.length === 0 && <li className="text-ink-muted">No jobs run yet.</li>}
            {data.recent_jobs.map((j: any) => (
              <li key={j.id} className="flex items-center justify-between gap-2"><span className="font-mono text-xs">{j.job_key}</span><span className="flex items-center gap-2 text-xs text-ink-muted">{timeAgo(j.created_at)}<Badge tone={JOB_TONE[j.status]}>{j.status}</Badge></span></li>
            ))}
          </ul>
        </Card>
      </div>

      <Card delay={0.3} className="mt-5">
        <CardHeader title="Organisations" action={<Link to="/admin/orgs" className="text-xs font-semibold text-brand-700 hover:underline">Manage</Link>} />
        <div className="grid gap-3 p-5 sm:grid-cols-2 xl:grid-cols-4">
          {data.orgs.map((o: any) => (
            <Link key={o.slug} to={`/o/${o.slug}`} className="rounded-2xl border border-line p-4 transition hover:border-brand-300 hover:shadow-card">
              <div className="font-semibold">{o.name}</div>
              <div className="mt-2 flex gap-3 text-xs text-ink-muted"><span>{o.stats.alerts} alerts</span><span>{o.stats.plants} plants</span><span>{o.stats.users} users</span></div>
            </Link>
          ))}
          {data.orgs.length === 0 && <div className="text-sm text-ink-muted">No organisations yet — create the first one.</div>}
        </div>
      </Card>
    </>
  );
}
