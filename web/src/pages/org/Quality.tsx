import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { Activity, ChevronLeft, ChevronRight, FileWarning, Layers, Search, Trophy } from "lucide-react";
import { motion } from "motion/react";
import { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { CompareBars, Donut, Legendary, RankBars, TrendBars } from "../../components/charts";
import { Badge, Button, Card, CardHeader, Empty, ErrorNote, PageHeader, PageSkeleton, Stat } from "../../components/ui";
import { api } from "../../lib/api";
import { fmtMonth } from "../../lib/format";
import { useOrg, useOrgData } from "./common";
import { IssueDrawer } from "./IssueDrawer";

function useDebounced<T>(v: T, ms = 300) {
  const [d, setD] = useState(v);
  useEffect(() => {
    const t = setTimeout(() => setD(v), ms);
    return () => clearTimeout(t);
  }, [v, ms]);
  return d;
}

export function Quality() {
  const { org, slug } = useOrg();
  const { issueId } = useParams();
  const nav = useNavigate();
  const { data, isLoading, error } = useOrgData<any>("quality");
  const [q, setQ] = useState("");
  const [category, setCategory] = useState("");
  const [page, setPage] = useState(1);
  const dq = useDebounced(q);
  useEffect(() => setPage(1), [dq, category]);
  const issues = useQuery({
    queryKey: ["org", slug, "issues", dq, category, page],
    queryFn: () => api<any>(`/api/orgs/${slug}/quality/issues?${new URLSearchParams({ q: dq, category, page: String(page), size: "15" })}`),
    placeholderData: keepPreviousData,
    enabled: !!slug,
  });

  if (isLoading || !org) return <PageSkeleton />;
  if (error) return <ErrorNote error={error} />;
  if (data.empty) {
    return (
      <>
        <PageHeader eyebrow="Quality signals" title="CDSCO NSQ alerts" />
        <Empty icon={<FileWarning />} title="No NSQ alerts linked">Ask a platform admin to link this organisation's manufacturer names to its profile.</Empty>
      </>
    );
  }
  const k = data.kpis;

  return (
    <>
      <PageHeader eyebrow="Quality signals" title="Where and why your batches fail" subtitle={`Every CDSCO Not-of-Standard-Quality alert against ${org.name}, ${fmtMonth(data.period.first)} – ${fmtMonth(data.period.last)}. Open any alert for the diagnosis and CAPA.`} />
      <div className="grid grid-cols-2 gap-4 xl:grid-cols-4">
        <Stat label="Alerts" value={k.alerts} icon={<Activity size={18} />} tone="rose" hint={`${k.last_12m} in the last 12 months`} />
        <Stat label="Products affected" value={k.products} icon={<Layers size={18} />} tone="amber" delay={0.05} hint={`${k.batches} distinct batches`} />
        <Stat label="Share of all-India alerts" value={k.national_share_pct} decimals={2} suffix="%" icon={<Trophy size={18} />} tone="indigo" delay={0.1} hint={`Rank #${k.national_rank} of ${k.manufacturers_ranked.toLocaleString("en-IN")}`} />
        <Stat label="Top failure" value={k.top_category} tone="brand" delay={0.15} hint="most common reason in your alerts" />
      </div>

      <div className="mt-5 grid gap-5 xl:grid-cols-[1.7fr_1fr]">
        <Card delay={0.1}>
          <CardHeader title="Alerts over time" subtitle="By failure category (top 5)" />
          <div className="px-3 pb-4 pt-3"><TrendBars data={data.trend} height={260} /><div className="px-3 pt-2"><Legendary items={data.trend.series} /></div></div>
        </Card>
        <Card delay={0.15}>
          <CardHeader title="You vs all of India" subtitle="Failure mix, % of alerts" />
          <div className="px-3 pb-3 pt-2"><CompareBars rows={data.compare} height={270} /></div>
        </Card>
      </div>

      <div className="mt-5 grid gap-5 lg:grid-cols-3">
        <Card delay={0.2}>
          <CardHeader title="Dosage forms" />
          <div className="p-4"><Donut rows={data.forms} height={200} center={<div><div className="font-display text-2xl font-extrabold">{k.alerts}</div><div className="text-[11px] text-ink-muted">alerts</div></div>} /></div>
          <div className="px-5 pb-5"><Legendary items={data.forms} /></div>
        </Card>
        <Card delay={0.25}>
          <CardHeader title="Most-flagged products" />
          <div className="p-5"><RankBars rows={data.products.slice(0, 7).map((p: any) => ({ name: p.name, count: p.alerts }))} color="#f59e0b" /></div>
        </Card>
        <Card delay={0.3}>
          <CardHeader title="Testing laboratories" subtitle="Who reported the failures" />
          <div className="p-5"><RankBars rows={data.labs.slice(0, 7)} color="#6366f1" /></div>
        </Card>
      </div>

      <Card delay={0.3} className="mt-5">
        <CardHeader title="All alerts" subtitle={`${issues.data?.total ?? "…"} matching`} action={
          <div className="flex flex-wrap items-center gap-2">
            <div className="relative"><Search size={15} className="absolute left-3 top-2.5 text-ink-faint" /><input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Product, batch, reason…" className="input h-9 w-64 pl-9" /></div>
            <select value={category} onChange={(e) => setCategory(e.target.value)} className="input h-9 w-48">
              <option value="">All categories</option>
              {data.categories.filter((c: any) => c.name !== "Other").map((c: any) => <option key={c.name}>{c.name}</option>)}
            </select>
          </div>
        } />
        <div className="mt-4 overflow-x-auto">
          <table className="w-full text-sm">
            <thead><tr className="border-y border-line bg-slate-50/70 text-left text-[11px] font-semibold uppercase tracking-wider text-ink-muted">
              <th className="px-5 py-2.5">Product</th><th className="px-3 py-2.5">Why flagged</th><th className="px-3 py-2.5">Category</th><th className="px-3 py-2.5">Batch</th><th className="px-5 py-2.5 text-right">Reported</th>
            </tr></thead>
            <tbody className={issues.isFetching ? "opacity-60 transition" : "transition"}>
              {issues.data?.items.map((it: any, i: number) => (
                <motion.tr key={it.id} initial={{ opacity: 0 }} animate={{ opacity: 1 }} transition={{ delay: i * 0.015 }} onClick={() => nav(`/o/${slug}/quality/${it.id}`)} className="cursor-pointer border-b border-line/70 transition hover:bg-brand-50/40">
                  <td className="max-w-[280px] px-5 py-3"><div className="truncate font-medium" title={it.product}>{it.product}</div><div className="text-xs text-ink-muted">{it.form}</div></td>
                  <td className="max-w-[340px] px-3 py-3 text-ink-soft"><div className="line-clamp-2 text-[13px]">{it.reason}</div></td>
                  <td className="px-3 py-3"><Badge tone="rose">{it.category}</Badge></td>
                  <td className="px-3 py-3 font-mono text-xs">{it.batch}</td>
                  <td className="whitespace-nowrap px-5 py-3 text-right text-xs text-ink-muted">{fmtMonth(it.month)}</td>
                </motion.tr>
              ))}
            </tbody>
          </table>
        </div>
        {issues.data && issues.data.pages > 1 && (
          <div className="flex items-center justify-between px-5 py-3 text-xs text-ink-muted">
            <span>Page {issues.data.page} of {issues.data.pages}</span>
            <div className="flex gap-1.5">
              <Button size="sm" variant="secondary" disabled={page <= 1} onClick={() => setPage((p) => p - 1)}><ChevronLeft size={14} /></Button>
              <Button size="sm" variant="secondary" disabled={page >= issues.data.pages} onClick={() => setPage((p) => p + 1)}><ChevronRight size={14} /></Button>
            </div>
          </div>
        )}
      </Card>
      <IssueDrawer slug={slug} issueId={issueId} onClose={() => nav(`/o/${slug}/quality`)} />
    </>
  );
}
