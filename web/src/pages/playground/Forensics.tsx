// Failure forensics: why products fail NSQ, reverse-engineered from the pattern of their alerts —
// which test, when in the shelf life, how many independent makers, which laboratory, and the molecule's chemistry.
import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { LoadingEdge } from "../../components/ui/Loading";
import { Beaker, Building2, ChevronLeft, ChevronRight, Clock, Factory, FlaskConical, Gem, Microscope, Search, ShieldAlert, Sparkles, TestTube } from "lucide-react";
import { useEffect, useMemo, useState, type ReactNode } from "react";
import { Link } from "react-router-dom";
import { Legendary, TrendBars } from "../../components/charts";
import { Badge, Button, Card, CardHeader, ErrorNote, Segmented, Skeleton } from "../../components/ui";
import { ExpandedProvider, Figure, Tile, useExpanded, type Section } from "../../components/ui/Expanded";
import { api } from "../../lib/api";
import { cn } from "../../lib/cn";
import { fmtMonth } from "../../lib/format";
import { HowItWorks, Needed, PatternsSource, Portfolio } from "./ForensicsTools";

const ARCH: Record<string, { label: string; tone: any; icon: ReactNode; color: string }> = {
  born: { label: "Released that way", tone: "rose", icon: <Beaker size={12} />, color: "#e11d48" },
  ages: { label: "Fails with age", tone: "amber", icon: <Clock size={12} />, color: "#d97706" },
  marginal: { label: "Marginal formula", tone: "slate", icon: <TestTube size={12} />, color: "#64748b" },
  plant: { label: "Plant problem", tone: "indigo", icon: <Factory size={12} />, color: "#6366f1" },
  aseptic: { label: "Sterile process", tone: "sky", icon: <ShieldAlert size={12} />, color: "#0284c7" },
  labelling: { label: "Labelling", tone: "slate", icon: <ShieldAlert size={12} />, color: "#94a3b8" },
};
const pct = (x?: number | null) => (x == null ? "—" : `${Math.round(100 * x)}%`);

function useDebounced<T>(v: T, ms = 300) {
  const [d, setD] = useState(v);
  useEffect(() => { const t = setTimeout(() => setD(v), ms); return () => clearTimeout(t); }, [v, ms]);
  return d;
}

function ArchBadge({ a }: { a: string }) {
  const x = ARCH[a] ?? ARCH.marginal;
  return <Badge tone={x.tone}>{x.icon}{x.label}</Badge>;
}

// "When in the shelf life does it fail" — this product against every product failing the same test
function Timing({ t }: { t: any }) {
  const max = Math.max(1, ...t.product, ...t.all_products);
  return (
    <div>
      <div className="flex h-40 items-end gap-3">
        {t.bins.map((b: string, i: number) => (
          <div key={b} className="flex h-full min-w-0 flex-1 flex-col justify-end">
            <div className="flex h-full items-end justify-center gap-1">
              <div className="w-1/2 rounded-t bg-rose-500" style={{ height: `${(100 * t.product[i]) / max}%` }} title={`This product: ${t.product[i]}%`} />
              <div className="w-1/2 rounded-t bg-slate-300" style={{ height: `${(100 * t.all_products[i]) / max}%` }} title={`All products: ${t.all_products[i]}%`} />
            </div>
            <div className="mt-1 text-center text-[10.5px] text-ink-muted">{b}</div>
          </div>
        ))}
      </div>
      <div className="mt-2 flex gap-4 text-[11px] text-ink-muted">
        <span className="flex items-center gap-1"><span className="h-2 w-2 rounded-sm bg-rose-500" /> this product ({t.n} {t.test.toLowerCase()} failures)</span>
        <span className="flex items-center gap-1"><span className="h-2 w-2 rounded-sm bg-slate-300" /> every product failing {t.test.toLowerCase()}</span>
      </div>
      <p className="mt-1 text-[11px] text-ink-faint">Share of failures by how much of the shelf life had passed (manufacture → report month). Early = released that way; late = degraded.</p>
    </div>
  );
}

function Detail({ k }: { k: string }) {
  const { data: d, error } = useQuery({ queryKey: ["forensics", k], queryFn: () => api<any>(`/api/playground/forensics/product?key=${encodeURIComponent(k)}`) });
  if (error) return <ErrorNote error={error} />;
  if (!d) return <Skeleton className="h-96" />;
  const s = d.signals;
  return (
    <div className="max-w-6xl space-y-5">
      <div className="rounded-2xl bg-night-900 p-5 text-white">
        <div className="flex flex-wrap items-center gap-2"><ArchBadge a={d.archetype} />{s.class_wide && <Badge tone="rose">class-wide</Badge>}{s.maker_specific && <Badge tone="indigo">maker-specific</Badge>}</div>
        <div className="mt-2 font-display text-2xl font-bold leading-snug">{d.headline}</div>
        <div className="mt-1 text-sm text-slate-300">{s.n} NSQ alerts · {s.makers} makers · {Math.round(100 * s.dominant_share)}% fail <b className="text-white">{s.dominant.toLowerCase()}</b>
          {s.age_median_m != null && <> · typically reported {s.age_median_m} months after manufacture</>} · last {fmtMonth(s.last)}</div>
        <div className="mt-3 flex flex-wrap gap-1.5">{d.products.map((p: any) => (
          <Link key={p.name} to={`/playground/investigate?product=${encodeURIComponent(p.name)}`} className="rounded-md bg-white/10 px-2 py-0.5 text-[11px] text-slate-200 hover:bg-white/20">{p.name} · {p.alerts}</Link>
        ))}</div>
      </div>

      <div className="grid gap-4 lg:grid-cols-[1.1fr_1fr]">
        <Card><CardHeader title="When in the shelf life it fails" subtitle={`${s.dominant} failures, against every product`} /><div className="p-5"><Timing t={d.timing} /></div></Card>
        <Card><CardHeader title="Which tests fail" subtitle="One alert can name several" />
          <div className="space-y-2 p-5">{s.tests.map((t: any) => (
            <div key={t.test} className="grid grid-cols-[8.5rem_minmax(0,1fr)_3rem] items-center gap-2 text-xs">
              <span className="truncate text-ink-soft">{t.test}</span>
              <div className="h-2 rounded-full bg-slate-100"><div className="h-2 rounded-full bg-rose-500" style={{ width: `${t.share_pct}%` }} /></div>
              <span className="text-right tabular-nums text-ink-muted">{t.share_pct}%</span>
            </div>
          ))}</div></Card>
      </div>

      <div>
        <div className="label mb-2 flex items-center gap-1.5"><Microscope size={12} /> Reverse-engineered root causes</div>
        <div className="grid gap-3 md:grid-cols-2">{d.hypotheses.map((h: any, i: number) => (
          <div key={i} className={cn("rounded-2xl bg-white p-4 ring-1 ring-inset", h.confidence === "strong" ? "ring-rose-200" : "ring-line")}>
            <div className="flex items-start justify-between gap-2"><div className="font-display text-[15px] font-bold leading-snug">{h.title}</div>
              <Badge tone={h.confidence === "strong" ? "rose" : "slate"}>{h.confidence}</Badge></div>
            <ul className="mt-2 space-y-1 text-xs text-ink-soft">{h.evidence.map((e: string, j: number) => <li key={j} className="flex gap-1.5"><span className="text-rose-500">●</span>{e}</li>)}</ul>
            <div className="mt-3 rounded-lg bg-emerald-50 p-2.5">
              <div className="mb-1 text-[10.5px] font-semibold uppercase tracking-wider text-emerald-800">What to check before your first batch</div>
              <ul className="space-y-0.5 text-xs text-emerald-900">{h.checks.map((c: string, j: number) => <li key={j}>✓ {c}</li>)}</ul>
            </div>
          </div>
        ))}</div>
      </div>

      <div className="grid gap-4 lg:grid-cols-3">
        <Card className="lg:col-span-2"><CardHeader title="Alerts over time" subtitle="By first failed test" />
          <div className="px-3 pb-4 pt-2"><TrendBars data={d.trend} height={200} /><div className="px-3 pt-2"><Legendary items={d.trend.series} /></div></div></Card>
        <Card><CardHeader title="Chemistry" subtitle="PubChem / structure seed" />
          <div className="space-y-2 p-5 text-xs">{d.chemistry.length === 0 ? <div className="text-ink-muted">No structure on record for these ingredients yet.</div> : d.chemistry.map((c: any) => (
            <div key={c.ingredient} className="rounded-lg border border-line p-2.5">
              <div className="font-semibold">{c.ingredient}</div>
              <div className="mt-0.5 text-ink-muted">XLogP3 {c.xlogp ?? "—"}{c.xlogp != null && c.xlogp >= 3 ? " · lipophilic, poorly water-soluble" : ""}{c.mp_c ? ` · m.p. ${c.mp_c} °C` : ""}{c.amine ? " · free amine (Maillard risk with lactose)" : ""}</div>
            </div>
          ))}
            {d.tracked.map((m: string) => <Link key={m} to={`/playground/molecule?m=${m}`} className="block text-brand-700 hover:underline">Molecule workbench: {m.replace(/_/g, " ")} →</Link>)}
          </div></Card>
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <Card className="overflow-hidden"><CardHeader title="Makers" subtitle={`${s.makers} makers · top 3 = ${Math.round(100 * s.top3_share)}% of alerts · ${s.repeat_makers} failed more than once`} />
          <div className="mt-2 max-h-80 overflow-y-auto">{d.makers.map((m: any) => (
            <Link key={m.key} to={`/playground/investigate?mfr=${encodeURIComponent(m.key)}`} className="flex items-center gap-3 border-t border-line/70 px-5 py-2 text-xs hover:bg-slate-50">
              <div className="min-w-0 flex-1"><div className="truncate font-medium">{m.name}</div><div className="text-ink-muted">{m.state || "—"} · mostly {m.tests.toLowerCase()} · last {fmtMonth(m.last)}</div></div>
              <span className="tabular-nums font-semibold">{m.alerts}</span>
            </Link>
          ))}</div></Card>
        <Card><CardHeader title="Where it is made and where it is caught" />
          <div className="space-y-3 p-5 text-xs">
            <div><div className="label mb-1.5">Manufacturing states (vs all alerts)</div>{d.states.map((x: any) => (
              <div key={x.state} className="flex justify-between border-b border-line/60 py-1"><span>{x.state}</span><span className="tabular-nums text-ink-muted">{x.share_pct}% <span className="text-ink-faint">(all: {x.national_pct}%)</span></span></div>))}</div>
            <div><div className="label mb-1.5">Laboratories that find it unusually often</div>{s.labs.length === 0 ? <div className="text-ink-muted">No laboratory stands out.</div> : s.labs.map((l: any) => (
              <div key={l.lab} className="flex justify-between border-b border-line/60 py-1"><span className="min-w-0 truncate">{l.lab}</span><span className="shrink-0 tabular-nums text-ink-muted">{l.share_pct}% vs {l.national_pct}% · <b className="text-rose-700">{l.lift}×</b></span></div>))}</div>
          </div></Card>
      </div>

      <Card className="overflow-hidden"><CardHeader title="Latest alerts" subtitle="Open one for its full diagnosis" />
        <div className="mt-2">{d.examples.map((e: any) => (
          <Link key={e.id} to={`/playground/investigate?${new URLSearchParams({ mfr: e.mfr_key ?? "", alert: e.id })}`} className="flex items-start gap-3 border-t border-line/70 px-5 py-2 text-xs hover:bg-slate-50">
            <div className="min-w-0 flex-1"><div className="truncate font-medium">{e.product}</div><div className="line-clamp-1 text-ink-muted">{e.reason}</div></div>
            <div className="shrink-0 text-right text-ink-muted">{fmtMonth(e.month)}{e.age_m != null && <div>{e.age_m} mo after mfg</div>}</div>
          </Link>
        ))}</div></Card>
      <p className="text-[11px] text-ink-faint">{d.caveat}</p>
    </div>
  );
}

function GroupRow({ g, onOpen }: { g: any; onOpen: (k: string) => void }) {
  return (
    <button onClick={() => onOpen(g.key)} className="flex w-full items-center gap-3 border-t border-line/70 px-4 py-2.5 text-left hover:bg-slate-50">
      <span className="h-8 w-1 shrink-0 rounded-full" style={{ background: (ARCH[g.archetype] ?? ARCH.marginal).color }} />
      <div className="min-w-0 flex-1">
        <div className="truncate text-[13px] font-semibold">{g.label}</div>
        <div className="truncate text-[11.5px] text-ink-muted">{Math.round(100 * g.dominant_share)}% {g.dominant.toLowerCase()} · early {pct(g.early)} · late {pct(g.late)} · {g.makers} makers</div>
      </div>
      <span className="hidden shrink-0 sm:inline"><ArchBadge a={g.archetype} /></span>
      <span className="w-10 shrink-0 text-right text-sm font-semibold tabular-nums">{g.n}</span>
    </button>
  );
}

function List({ title, subtitle, icon, items, onOpen, empty }: { title: string; subtitle: string; icon: ReactNode; items: any[]; onOpen: (k: string) => void; empty?: string }) {
  return (
    <Card className="overflow-hidden">
      <CardHeader title={<span className="flex items-center gap-2">{icon}{title}</span>} subtitle={subtitle} />
      <div className="mt-2">{items.length ? items.map((g) => <GroupRow key={g.key} g={g} onOpen={onOpen} />) : <div className="p-5 text-sm text-ink-muted">{empty ?? "None."}</div>}</div>
    </Card>
  );
}

function Tiles({ o, onFilter }: { o: any; onFilter: (id: string) => void }) {
  const { open } = useExpanded();
  const gap = o.quality_gaps[0];
  return (
    <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
      <Tile title="Products read" icon={<Microscope size={14} />} clickable={false}>
        <Figure value={o.groups} label={`${o.alerts.toLocaleString("en-IN")} alerts · ≥ 8 alerts each`} />
      </Tile>
      <Tile title="Class-wide failures" icon={<Building2 size={14} />} clickable={false}>
        <Figure value={o.class_wide} label="products that dozens of independent makers fail the same way" tone="#e11d48" />
      </Tile>
      <Tile title="Released that way" icon={<Beaker size={14} />} clickable={false} action={<button className="text-[11px] text-brand-700 hover:underline" onClick={() => onFilter("born")}>list</button>}>
        <Figure value={o.archetypes.find((a: any) => a.id === "born")?.products ?? 0} label="fail from the first months — a formulation or process flaw" />
      </Tile>
      {gap && <Tile title="Biggest quality gap" icon={<Gem size={14} />} accent="#0a9a7d" clickable={false}
        action={<button className="text-[11px] text-brand-700 hover:underline" onClick={() => open(`g:${gap.key}`)}>why</button>}>
        <Figure value={gap.label.split(" · ")[0]} label={`${gap.recent_24m} alerts in 24 months across ${gap.makers} makers`} tone="#0a9a7d" />
      </Tile>}
    </div>
  );
}

type View = "patterns" | "portfolio" | "needed";

export function Forensics() {
  const { data: o, error, isLoading } = useQuery({ queryKey: ["forensics-overview"], queryFn: () => api<any>("/api/playground/forensics") });
  const [active, setActive] = useState<string | null>(null);
  const [filter, setFilter] = useState("");
  const keys = useMemo(() => {
    if (!o?.available) return [] as any[];
    const seen = new Map<string, any>();
    for (const g of [...o.quality_gaps, ...o.born, ...o.ages, ...o.plant, ...o.lab_hotspots]) seen.set(g.key, g);
    return [...seen.values()];
  }, [o]);
  const [extra, setExtra] = useState<any | null>(null);
  const sections: Section[] = useMemo(() => {
    const list = extra && !keys.some((g) => g.key === extra.key) ? [extra, ...keys] : keys;
    return list.map((g: any) => ({ id: `g:${g.key}`, title: g.label, subtitle: g.headline, icon: <span className="block h-2.5 w-2.5 rounded-full" style={{ background: (ARCH[g.archetype] ?? ARCH.marginal).color }} />,
      render: () => <Detail k={g.key} /> }));
  }, [keys, extra]);
  const openKey = (k: string, g?: any) => { setExtra(g ?? { key: k, label: k.split("|")[0].split("+").join(" + ") + " · " + k.split("|")[1], headline: "", archetype: "marginal" }); setActive(`g:${k}`); };
  const [view, setViewState] = useState<View>(() => {
    const v = new URLSearchParams(window.location.search).get("view");
    return v === "portfolio" || v === "needed" ? v : "patterns";
  });
  const setView = (v: View) => {
    setViewState(v);
    const u = new URL(window.location.href);
    if (v === "patterns") u.searchParams.delete("view"); else u.searchParams.set("view", v);
    window.history.replaceState(null, "", u);
  };

  if (error) return <ErrorNote error={error} />;
  if (isLoading) return <Skeleton className="h-96" />;
  if (!o?.available) return <Card className="p-6 text-sm text-ink-muted">No NSQ data loaded yet.</Card>;
  return (
    <ExpandedProvider sections={sections} active={active} onActive={setActive} title="Failure forensics" subtitle="Why products fail NSQ">
      <div className="space-y-4">
        <div className="rounded-2xl bg-gradient-to-br from-night-900 to-slate-800 p-5 text-white">
          <div className="flex items-center gap-2 text-[11px] font-semibold uppercase tracking-wider text-brand-400"><Sparkles size={13} /> Reverse-engineering NSQ failures</div>
          <div className="mt-1 max-w-3xl font-display text-xl font-bold leading-snug">Before you make a product, see how everyone else failed it — which test, how early in its shelf life, whether it's the formula or a few plants — and what to check so your batches don't.</div>
        </div>
        <Segmented value={view} onChange={setView} options={[{ value: "patterns", label: "Failure patterns" }, { value: "portfolio", label: "Check my portfolio" }, { value: "needed", label: "Needed & badly made" }]} />
        {view === "portfolio" && <div className="space-y-4"><HowItWorks /><Portfolio onOpen={openKey} /></div>}
        {view === "needed" && <Needed onOpen={openKey} />}
        {view === "patterns" && <>
        {o.source && <PatternsSource src={o.source} />}
        <Tiles o={o} onFilter={setFilter} />
        <div className="grid gap-4 xl:grid-cols-2">
          <List title="Quality gaps" icon={<Gem size={15} className="text-brand-600" />} onOpen={(k) => openKey(k)}
            subtitle="Many makers keep failing it — buyers want one who doesn't, and the fix is known" items={o.quality_gaps.slice(0, 6)} />
          <List title="Released that way" icon={<Beaker size={15} className="text-rose-600" />} onOpen={(k) => openKey(k)}
            subtitle="Fail in the first quarter of shelf life far more than usual — formulation / process" items={o.born.slice(0, 6)} />
          <List title="Fail with age" icon={<Clock size={15} className="text-amber-600" />} onOpen={(k) => openKey(k)}
            subtitle="Pass at release, fail late — stability, packaging, enteric coats" items={o.ages.slice(0, 6)} />
          <List title="Plant problems" icon={<Factory size={15} className="text-indigo-600" />} onOpen={(k) => openKey(k)}
            subtitle="A few makers cause most failures — the formula itself is workable" items={o.plant.slice(0, 6)} />
        </div>
        <div>
          <div className="label mb-2 flex items-center gap-1.5"><FlaskConical size={12} /> Every product with at least 8 alerts{filter && <button className="ml-2 normal-case text-brand-700 hover:underline" onClick={() => setFilter("")}>clear filter</button>}</div>
          <AllProductsWithFilter key={filter} initial={filter} onOpen={(k, g) => openKey(k, g)} />
        </div>
        </>}
      </div>
    </ExpandedProvider>
  );
}

function AllProductsWithFilter({ initial, onOpen }: { initial: string; onOpen: (k: string, g?: any) => void }) {
  const [q, setQ] = useState("");
  const dq = useDebounced(q.trim());
  const [arch, setArch] = useState(initial);
  const [sort, setSort] = useState<"alerts" | "recent" | "makers">("alerts");
  const [page, setPage] = useState(1);
  useEffect(() => setPage(1), [dq, arch, sort]);
  const r = useQuery({ queryKey: ["forensics-list", dq, arch, sort, page], placeholderData: keepPreviousData,
    queryFn: () => api<any>(`/api/playground/forensics/products?${new URLSearchParams({ q: dq, archetype: arch, sort, page: String(page), size: "15" })}`) });
  return (
    <Card className="overflow-hidden">
      <div className="flex flex-wrap items-center gap-2 px-4 py-3">
        <div className="relative min-w-[220px] flex-1"><Search size={14} className="absolute left-3 top-2.5 text-ink-faint" />
          <input className="input h-9 w-full pl-8" placeholder="Molecule or product" value={q} onChange={(e) => setQ(e.target.value)} /></div>
        <select className="input h-9 w-auto" value={arch} onChange={(e) => setArch(e.target.value)}>
          <option value="">Every pattern</option>{Object.entries(ARCH).map(([k, v]) => <option key={k} value={k}>{v.label}</option>)}</select>
        <Segmented value={sort} onChange={setSort} options={[{ value: "alerts", label: "Most alerts" }, { value: "recent", label: "Recent" }, { value: "makers", label: "Most makers" }]} />
      </div>
      <div className={cn("relative", r.isFetching && "opacity-70")}><LoadingEdge active={r.isFetching} />{r.data?.items.map((g: any) => <GroupRow key={g.key} g={g} onOpen={(k) => onOpen(k, g)} />)}</div>
      {r.data && <div className="flex items-center justify-between border-t border-line px-4 py-2.5 text-xs text-ink-muted"><span>{r.data.total} products · page {r.data.page} of {r.data.pages}</span>
        <div className="flex gap-1.5"><Button size="sm" variant="secondary" disabled={page <= 1} onClick={() => setPage(page - 1)}><ChevronLeft size={14} /></Button>
          <Button size="sm" variant="secondary" disabled={page >= r.data.pages} onClick={() => setPage(page + 1)}><ChevronRight size={14} /></Button></div></div>}
    </Card>
  );
}

