import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { ChevronLeft, ChevronRight, Search } from "lucide-react";
import { useEffect, useState } from "react";
import { Legendary, RankBars, TrendArea } from "../../components/charts";
import { Badge, Button, Card, CardHeader, ErrorNote, PageHeader, PageSkeleton, Stat } from "../../components/ui";
import { api } from "../../lib/api";
import { fmtMonth } from "../../lib/format";

function TrackedCoverage({ cov }: { cov: any }) {
  if (!cov) return null;
  const pct = cov.alerts ? Math.round((100 * cov.alerts_tracked) / cov.alerts) : 0;
  const tracked = Object.entries(cov.tracked_counts as Record<string, number>).sort((a, b) => b[1] - a[1]);
  return (
    <Card delay={0.08} className="mt-5 p-5">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h3 className="font-display text-[15px] font-bold">Tracked vs untracked molecules</h3>
          <p className="mt-0.5 text-xs text-ink-muted">{cov.alerts_tracked.toLocaleString("en-IN")} of {cov.alerts.toLocaleString("en-IN")} alerts ({pct}%) involve one of the tracked molecules with a patent/regulatory profile. {cov.untracked_total.toLocaleString("en-IN")} other ingredients appear untracked.</p>
        </div>
      </div>
      <div className="mt-3 flex h-3 overflow-hidden rounded-full bg-slate-100">
        <div className="bg-brand-500 transition-all duration-700" style={{ width: `${pct}%` }} />
        <div className="flex-1 bg-[repeating-linear-gradient(45deg,#e2e8f0_0,#e2e8f0_4px,#f8fafc_4px,#f8fafc_8px)]" />
      </div>
      <div className="mt-4 grid gap-5 md:grid-cols-2">
        <div>
          <div className="label mb-2 text-brand-700">Tracked · alerts</div>
          <div className="flex flex-wrap gap-1.5">{tracked.map(([k, n]) => <Badge key={k} tone="brand">{k.split("_")[0]} · {n}</Badge>)}</div>
        </div>
        <div>
          <div className="label mb-2">Top untracked ingredients · alerts</div>
          <div className="flex flex-wrap gap-1.5">{cov.untracked.slice(0, 16).map((u: any) => <span key={u.ingredient} className="rounded-full border border-dashed border-slate-300 px-2 py-0.5 text-[11px] capitalize text-ink-soft">{u.ingredient} · {u.alerts}</span>)}</div>
        </div>
      </div>
    </Card>
  );
}

export function Explorer() {
  const { data, isLoading, error } = useQuery({ queryKey: ["nsq-summary"], queryFn: () => api<any>("/api/nsq/summary") });
  const [q, setQ] = useState("");
  const [dq, setDq] = useState("");
  const [category, setCategory] = useState("");
  const [manufacturer, setManufacturer] = useState("");
  const [page, setPage] = useState(1);
  useEffect(() => { const t = setTimeout(() => { setDq(q); setPage(1); }, 300); return () => clearTimeout(t); }, [q]);
  const ledger = useQuery({
    queryKey: ["nsq-alerts", dq, category, manufacturer, page],
    queryFn: () => api<any>(`/api/nsq/alerts?${new URLSearchParams({ q: dq, category, manufacturer, page: String(page), size: "20" })}`),
    placeholderData: keepPreviousData,
  });
  if (isLoading) return <PageSkeleton />;
  if (error) return <ErrorNote error={error} />;
  const k = data.kpis;

  return (
    <>
      <PageHeader eyebrow="All-India" title="CDSCO NSQ alert explorer" subtitle={`Every Not-of-Standard-Quality alert, ${fmtMonth(data.period.first)} – ${fmtMonth(data.period.last)}. Use it to find a manufacturer before creating its organisation.`} />
      <div className="grid grid-cols-2 gap-4 xl:grid-cols-4">
        <Stat label="Alerts" value={k.alerts} />
        <Stat label="Manufacturers" value={k.manufacturers} tone="indigo" delay={0.05} />
        <Stat label="Products" value={k.products} tone="amber" delay={0.1} />
        <Stat label="Dissolution share" value={k.dissolution_share} decimals={1} suffix="%" tone="rose" delay={0.15} />
      </div>
      <TrackedCoverage cov={data.coverage} />
      <Card delay={0.1} className="mt-5">
        <CardHeader title="Alerts per month" subtitle="By failure category" />
        <div className="px-3 pb-4 pt-3"><TrendArea data={data.trend} height={280} /><div className="px-3 pt-2"><Legendary items={data.trend.series} /></div></div>
      </Card>
      <div className="mt-5 grid gap-5 lg:grid-cols-3">
        <Card delay={0.15}><CardHeader title="Manufacturer states" /><div className="p-5"><RankBars rows={data.mfg_states.slice(0, 10)} color="#6366f1" /></div></Card>
        <Card delay={0.2}><CardHeader title="Failure categories" /><div className="p-5"><RankBars rows={data.categories.slice(0, 10)} color="#e11d48" onClick={(n) => { setCategory(n); setPage(1); }} /></div></Card>
        <Card delay={0.25}><CardHeader title="Most-flagged manufacturers" subtitle="Click to filter the ledger" /><div className="p-5"><RankBars rows={data.top_manufacturers.slice(0, 10).map((m: any) => ({ name: m.name, count: m.alerts, sub: m.state }))} color="#f59e0b" onClick={(n) => { const m = data.top_manufacturers.find((x: any) => x.name === n); setManufacturer(m?.key ?? ""); setPage(1); }} /></div></Card>
      </div>
      <Card delay={0.3} className="mt-5">
        <CardHeader title="Alert ledger" subtitle={`${ledger.data?.total?.toLocaleString("en-IN") ?? "…"} alerts`} action={
          <div className="flex flex-wrap items-center gap-2">
            {(category || manufacturer) && <button onClick={() => { setCategory(""); setManufacturer(""); }}><Badge tone="indigo">{[category, manufacturer].filter(Boolean).join(" · ")} ✕</Badge></button>}
            <div className="relative"><Search size={15} className="absolute left-3 top-2.5 text-ink-faint" /><input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Product, manufacturer, batch…" className="input h-9 w-72 pl-9" /></div>
          </div>
        } />
        <div className="mt-4 overflow-x-auto">
          <table className={`w-full text-sm ${ledger.isFetching ? "opacity-60" : ""}`}>
            <thead><tr className="border-y border-line bg-slate-50/70 text-left text-[11px] font-semibold uppercase tracking-wider text-ink-muted"><th className="px-5 py-2.5">Product</th><th className="px-3 py-2.5">Manufacturer</th><th className="px-3 py-2.5">Why flagged</th><th className="px-3 py-2.5">Category</th><th className="px-5 py-2.5 text-right">Month</th></tr></thead>
            <tbody>
              {ledger.data?.items.map((a: any) => (
                <tr key={a.id} className="border-b border-line/70">
                  <td className="max-w-[240px] truncate px-5 py-2.5 font-medium" title={a.product}>{a.product}</td>
                  <td className="max-w-[200px] truncate px-3 py-2.5 text-xs" title={a.manufacturer}>{a.manufacturer}<div className="text-ink-faint">{a.mfg_state}</div></td>
                  <td className="max-w-[320px] px-3 py-2.5 text-xs text-ink-soft"><div className="line-clamp-2">{a.reason}</div></td>
                  <td className="px-3 py-2.5"><Badge tone="rose">{a.category}</Badge></td>
                  <td className="whitespace-nowrap px-5 py-2.5 text-right text-xs text-ink-muted">{fmtMonth(a.month)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {ledger.data && (
          <div className="flex items-center justify-between px-5 py-3 text-xs text-ink-muted">
            <span>Page {ledger.data.page} of {ledger.data.pages}</span>
            <div className="flex gap-1.5"><Button size="sm" variant="secondary" disabled={page <= 1} onClick={() => setPage(page - 1)}><ChevronLeft size={14} /></Button><Button size="sm" variant="secondary" disabled={page >= ledger.data.pages} onClick={() => setPage(page + 1)}><ChevronRight size={14} /></Button></div>
          </div>
        )}
      </Card>
    </>
  );
}
