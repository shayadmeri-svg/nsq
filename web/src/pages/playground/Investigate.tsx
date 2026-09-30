// Investigate: start from any product or any manufacturer nationally, drill into a manufacturer's full NSQ history,
// and open any alert for its diagnosis — GMP & testing standards, probable causes, mitigation plan.
// (Replaces the legacy Streamlit dashboard's "Product → Manufacturer investigation" tab.)
import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { LoadingEdge } from "../../components/ui/Loading";
import { ArrowLeft, Building2, ChevronLeft, ChevronRight, Package, Search, ShieldAlert } from "lucide-react";
import { useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { CompareBars, Legendary, RankBars, TrendBars } from "../../components/charts";
import { Badge, Button, Card, CardHeader, ErrorNote, Skeleton } from "../../components/ui";
import { Figure, Tile } from "../../components/ui/Expanded";
import { api } from "../../lib/api";
import { cn } from "../../lib/cn";
import { fmtMonth } from "../../lib/format";
import { IssueDrawer } from "../org/IssueDrawer";

const clean = (s?: string) => (s ?? "").replace(/^M\/s\.?\s*/i, "").trim();

function useDebounced<T>(v: T, ms = 300) {
  const [d, setD] = useState(v);
  useEffect(() => { const t = setTimeout(() => setD(v), ms); return () => clearTimeout(t); }, [v, ms]);
  return d;
}

function Finder({ onProduct, onMfr }: { onProduct: (p: string) => void; onMfr: (k: string) => void }) {
  const [q, setQ] = useState("");
  const dq = useDebounced(q.trim());
  const r = useQuery({ queryKey: ["inv-search", dq], queryFn: () => api<any>(`/api/playground/investigate/search?q=${encodeURIComponent(dq)}`), placeholderData: keepPreviousData });
  return (
    <div className="space-y-4">
      <Card className="p-4">
        <div className="relative">
          <Search size={17} className="pointer-events-none absolute left-3.5 top-1/2 -translate-y-1/2 text-ink-faint" />
          <input autoFocus className="input h-12 w-full pl-11 text-[15px]" placeholder="Search a product (e.g. paracetamol 650) or a manufacturer (e.g. healer, karnataka antibiotics)"
            value={q} onChange={(e) => setQ(e.target.value)} />
        </div>
        <p className="mt-2 text-[11.5px] text-ink-muted">Every CDSCO NSQ alert since 2021, all of India. {dq ? "" : "Showing the most-flagged products and manufacturers."}</p>
      </Card>
      {r.error && <ErrorNote error={r.error} />}
      <div className={cn("relative grid gap-4 lg:grid-cols-2", r.isFetching && "opacity-70")}><LoadingEdge active={r.isFetching} />
        <Card className="overflow-hidden">
          <CardHeader title={<span className="flex items-center gap-2"><Package size={15} /> Products</span>} subtitle="Alerts · manufacturers that had them" />
          <div className="mt-2">{!r.data ? <div className="p-4"><Skeleton className="h-40" /></div> : r.data.products.length === 0 ? <div className="p-5 text-sm text-ink-muted">No product matches.</div> :
            r.data.products.map((p: any) => (
              <button key={p.name} onClick={() => onProduct(p.name)} className="flex w-full items-center gap-3 border-t border-line/70 px-5 py-2.5 text-left hover:bg-slate-50">
                <div className="min-w-0 flex-1"><div className="truncate text-[13px] font-medium">{p.name}</div><div className="text-[11px] text-ink-muted">{p.manufacturers} manufacturers · last {fmtMonth(p.last)}</div></div>
                <Badge tone="rose">{p.alerts} alerts</Badge>
              </button>
            ))}</div>
        </Card>
        <Card className="overflow-hidden">
          <CardHeader title={<span className="flex items-center gap-2"><Building2 size={15} /> Manufacturers</span>} subtitle="Alerts attributed to the maker (spurious labels excluded)" />
          <div className="mt-2">{!r.data ? <div className="p-4"><Skeleton className="h-40" /></div> : r.data.manufacturers.length === 0 ? <div className="p-5 text-sm text-ink-muted">No manufacturer matches.</div> :
            r.data.manufacturers.map((m: any) => (
              <button key={m.key} onClick={() => onMfr(m.key)} className="flex w-full items-center gap-3 border-t border-line/70 px-5 py-2.5 text-left hover:bg-slate-50">
                <div className="min-w-0 flex-1"><div className="truncate text-[13px] font-medium">{clean(m.name)}</div><div className="text-[11px] text-ink-muted">{[m.city, m.state].filter(Boolean).join(", ") || "—"}</div></div>
                <Badge tone="rose">{m.alerts} alerts</Badge>
              </button>
            ))}</div>
        </Card>
      </div>
    </div>
  );
}

function ProductView({ name, onMfr }: { name: string; onMfr: (k: string, product?: string) => void }) {
  const { data: d, error, isLoading } = useQuery({ queryKey: ["inv-product", name], queryFn: () => api<any>(`/api/playground/investigate/product?name=${encodeURIComponent(name)}`) });
  const [all, setAll] = useState(false);
  if (error) return <ErrorNote error={error} />;
  if (isLoading || !d) return <Skeleton className="h-96" />;
  const top = d.categories[0];
  return (
    <div className="space-y-4">
      <div>
        <div className="label flex items-center gap-1.5"><Package size={12} /> Product</div>
        <h2 className="font-display text-2xl font-bold leading-tight">{d.product}</h2>
        {d.ingredients?.length > 0 && <div className="mt-1 flex flex-wrap gap-1">{d.ingredients.map((i: string) => <Badge key={i}>{i}</Badge>)}</div>}
      </div>
      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <Tile title="NSQ alerts" clickable={false}><Figure value={d.alerts} label={`${fmtMonth(d.period.first)} – ${fmtMonth(d.period.last)}`} tone="#e11d48" /></Tile>
        <Tile title="Manufacturers" clickable={false}><Figure value={d.manufacturers.length} label="that had this product fail" /></Tile>
        <Tile title="Main failure" clickable={false}><Figure value={top?.name ?? "—"} label={top ? `${top.count} of ${d.alerts} alerts` : ""} /></Tile>
        <Tile title="Dosage form" clickable={false}><Figure value={d.forms[0]?.name ?? "—"} label={d.labs[0] ? `most reports: ${d.labs[0].name}` : ""} /></Tile>
      </div>
      <div className="grid gap-4 xl:grid-cols-[1.4fr_1fr]">
        <Card><CardHeader title="Alerts over time" subtitle="By failure category" /><div className="px-3 pb-4 pt-3"><TrendBars data={d.trend} height={220} /><div className="px-3 pt-2"><Legendary items={d.trend.series} /></div></div></Card>
        <Card><CardHeader title="Why it fails" /><div className="p-5"><RankBars rows={d.categories} color="#e11d48" /></div></Card>
      </div>
      <Card className="overflow-hidden">
        <CardHeader title="Who made the failing batches" subtitle="Click a manufacturer for its full history and the diagnosis of each alert" />
        <table className="mt-3 w-full text-sm">
          <thead><tr className="border-y border-line bg-slate-50/70 text-left text-[11px] font-semibold uppercase tracking-wider text-ink-muted"><th className="px-5 py-2.5">Manufacturer</th><th className="px-3 py-2.5">Why</th><th className="px-3 py-2.5">Last</th><th className="px-5 py-2.5 text-right">Alerts</th></tr></thead>
          <tbody>{(all ? d.manufacturers : d.manufacturers.slice(0, 12)).map((m: any) => (
            <tr key={(m.key ?? "") + m.name} onClick={() => m.key && onMfr(m.key, d.product)} className={cn("border-b border-line/70", m.key && "cursor-pointer hover:bg-slate-50")}>
              <td className="px-5 py-2.5"><div className="font-medium">{m.name}</div><div className="text-[11px] text-ink-muted">{m.state || "—"}{m.spurious ? ` · ${m.spurious} declared spurious` : ""}</div></td>
              <td className="px-3 py-2.5"><div className="flex flex-wrap gap-1">{m.categories.map((c: any) => <Badge key={c.name} tone="rose">{c.name} · {c.count}</Badge>)}</div></td>
              <td className="px-3 py-2.5 text-xs text-ink-muted">{fmtMonth(m.last)}</td>
              <td className="px-5 py-2.5 text-right font-semibold tabular-nums">{m.alerts}</td>
            </tr>
          ))}</tbody>
        </table>
        {d.manufacturers.length > 12 && <button className="w-full py-2.5 text-xs text-brand-700 hover:bg-slate-50" onClick={() => setAll(!all)}>{all ? "fewer" : `all ${d.manufacturers.length} manufacturers`}</button>}
      </Card>
    </div>
  );
}

function MfrView({ mkey, product, onProduct, setProduct, onAlert }: { mkey: string; product: string; onProduct: (p: string) => void; setProduct: (p: string) => void; onAlert: (id: string) => void }) {
  const { data: d, error, isLoading } = useQuery({ queryKey: ["inv-mfr", mkey], queryFn: () => api<any>(`/api/playground/investigate/manufacturer/${encodeURIComponent(mkey)}`) });
  const [q, setQ] = useState("");
  const [category, setCategory] = useState("");
  const [page, setPage] = useState(1);
  const dq = useDebounced(q);
  useEffect(() => setPage(1), [dq, category, product]);
  const issues = useQuery({
    queryKey: ["inv-mfr-alerts", mkey, dq, category, product, page], placeholderData: keepPreviousData,
    queryFn: () => api<any>(`/api/playground/investigate/manufacturer/${encodeURIComponent(mkey)}/alerts?${new URLSearchParams({ q: dq, category, product, page: String(page), size: "15" })}`),
  });
  if (error) return <ErrorNote error={error} />;
  if (isLoading || !d) return <Skeleton className="h-96" />;
  const k = d.kpis, m = d.manufacturer;
  return (
    <div className="space-y-4">
      <div>
        <div className="label flex items-center gap-1.5"><Building2 size={12} /> Manufacturer</div>
        <h2 className="font-display text-2xl font-bold leading-tight">{clean(m.name)}</h2>
        <div className="text-xs text-ink-muted">{[m.city, m.state].filter(Boolean).join(", ")}{m.raw_names?.length > 1 ? ` · also written as ${m.raw_names.slice(0, 3).map(clean).join("; ")}` : ""}</div>
      </div>
      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <Tile title="NSQ alerts" clickable={false}><Figure value={k.alerts} label={`${k.last_12m} in the last 12 months`} tone="#e11d48" /></Tile>
        <Tile title="Products affected" clickable={false}><Figure value={k.products} label={`${k.batches} distinct batches`} /></Tile>
        <Tile title="Alert rank (1 = most alerts)" clickable={false}><Figure value={k.national_rank ? `#${k.national_rank}` : "—"} label={`of ${k.manufacturers_ranked.toLocaleString("en-IN")} manufacturers · more alerts than ${k.more_alerts_than_pct ?? 0}% · ${k.national_share_pct}% of all alerts`} /></Tile>
        <Tile title="Top failure" clickable={false}><Figure value={k.top_category} label={k.spurious ? `${k.spurious} spurious (not ranked)` : "most common reason"} /></Tile>
      </div>
      <div className="grid gap-4 xl:grid-cols-[1.4fr_1fr]">
        <Card><CardHeader title="Alerts over time" subtitle="By failure category" /><div className="px-3 pb-4 pt-3"><TrendBars data={d.trend} height={220} /><div className="px-3 pt-2"><Legendary items={d.trend.series} /></div></div></Card>
        <Card><CardHeader title="Against all of India" subtitle="Failure mix, % of alerts" /><div className="px-3 pb-3 pt-2"><CompareBars rows={d.compare} height={230} /></div></Card>
      </div>
      <div className="grid gap-4 lg:grid-cols-2">
        <Card><CardHeader title="Products that failed" subtitle="Click one to filter the alerts below" />
          <div className="p-5"><RankBars rows={d.products.slice(0, 8).map((p: any) => ({ name: p.name, count: p.alerts }))} color="#f59e0b" onClick={(n) => setProduct(product === n ? "" : n)} /></div></Card>
        <Card><CardHeader title="Testing laboratories" subtitle="Who reported the failures" /><div className="p-5"><RankBars rows={d.labs.slice(0, 8)} color="#6366f1" /></div></Card>
      </div>
      <Card className="overflow-hidden">
        <CardHeader title="Alert history" subtitle={`${issues.data?.total ?? "…"} alerts${product ? ` for ${product}` : ""} · open one for GMP & testing standards, probable causes and a mitigation plan`}
          action={<div className="flex flex-wrap items-center gap-2">
            {product && <button onClick={() => setProduct("")} className="rounded-full bg-amber-50 px-2 py-1 text-[11px] text-amber-800 ring-1 ring-inset ring-amber-200">{product} ✕</button>}
            {product && <button onClick={() => onProduct(product)} className="text-[11px] text-brand-700 hover:underline">all makers of this product →</button>}
            <div className="relative"><Search size={14} className="absolute left-3 top-2.5 text-ink-faint" /><input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Product, batch, reason…" className="input h-9 w-56 pl-8" /></div>
            <select value={category} onChange={(e) => setCategory(e.target.value)} className="input h-9 w-44"><option value="">All categories</option>{d.categories.map((c: any) => <option key={c.name}>{c.name}</option>)}</select>
          </div>} />
        <div className="mt-3 overflow-x-auto">
          <table className="w-full text-sm">
            <thead><tr className="border-y border-line bg-slate-50/70 text-left text-[11px] font-semibold uppercase tracking-wider text-ink-muted"><th className="px-5 py-2.5">Product</th><th className="px-3 py-2.5">Why flagged</th><th className="px-3 py-2.5">Category</th><th className="px-3 py-2.5">Batch</th><th className="px-5 py-2.5 text-right">Reported</th></tr></thead>
            <tbody className={issues.isFetching ? "opacity-60" : ""}>{issues.data?.items.map((it: any) => (
              <tr key={it.id} onClick={() => onAlert(it.id)} className="cursor-pointer border-b border-line/70 hover:bg-brand-50/40">
                <td className="max-w-[280px] px-5 py-2.5"><div className="truncate font-medium" title={it.product}>{it.product}</div><div className="text-[11px] text-ink-muted">{it.form}</div></td>
                <td className="max-w-[340px] px-3 py-2.5 text-ink-soft"><div className="line-clamp-2 text-[13px]">{it.reason}</div></td>
                <td className="px-3 py-2.5"><Badge tone="rose">{it.category}</Badge>{it.spurious && <div className="mt-1"><Badge tone="indigo">Spurious</Badge></div>}</td>
                <td className="px-3 py-2.5 font-mono text-xs">{it.batch}</td>
                <td className="whitespace-nowrap px-5 py-2.5 text-right text-xs text-ink-muted">{fmtMonth(it.month)}</td>
              </tr>
            ))}</tbody>
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
    </div>
  );
}

export function Investigate() {
  const [sp, setSp] = useSearchParams();
  const product = sp.get("product") ?? "";
  const mfr = sp.get("mfr") ?? "";
  const alert = sp.get("alert") ?? undefined;
  const go = (p: Record<string, string>) => setSp(Object.fromEntries(Object.entries(p).filter(([, v]) => v)));
  const mfrName = useQuery({ queryKey: ["inv-mfr", mfr], enabled: !!mfr, queryFn: () => api<any>(`/api/playground/investigate/manufacturer/${encodeURIComponent(mfr)}`) }).data?.manufacturer?.name;
  return (
    <div className="space-y-4">
      {(product || mfr) && (
        <div className="flex flex-wrap items-center gap-2 text-xs">
          <button onClick={() => go({})} className="inline-flex items-center gap-1 rounded-lg px-2 py-1 text-ink-muted hover:bg-slate-100"><ArrowLeft size={13} /> Search</button>
          {mfr && product && <button onClick={() => go({ product })} className="rounded-lg px-2 py-1 text-ink-muted hover:bg-slate-100">{product}</button>}
          <span className="text-ink-faint">/</span><span className="font-medium text-ink-soft">{mfr ? clean(mfrName) || mfr : product}</span>
        </div>
      )}
      {mfr ? <MfrView mkey={mfr} product={product} onProduct={(p) => go({ product: p })} setProduct={(p) => go({ mfr, product: p })} onAlert={(id) => go({ mfr, product, alert: id })} />
        : product ? <ProductView name={product} onMfr={(k, p) => go({ mfr: k, product: p ?? "" })} />
          : <Finder onProduct={(p) => go({ product: p })} onMfr={(k) => go({ mfr: k })} />}
      {mfr && <IssueDrawer issueId={alert} endpoint={`/api/playground/investigate/manufacturer/${encodeURIComponent(mfr)}/alerts`} who={clean(mfrName) || "this manufacturer"}
        onClose={() => go({ mfr, product })} />}
      {!mfr && !product && <p className="flex items-center gap-1.5 text-[11px] text-ink-faint"><ShieldAlert size={12} /> Diagnoses come from the curated GMP knowledge (monographs, ICH guidelines) where the product is covered, and generic standards otherwise — never invented.</p>}
    </div>
  );
}
