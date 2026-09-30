// CDSCO International Cell: every Written Confirmation for API exports to the EU, each letter viewable as a PDF.
import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { LoadingEdge } from "../../components/ui/Loading";
import { ChevronLeft, ChevronRight, Download, ExternalLink, FileCheck2, FileText, Info, Search } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { Badge, Button, Card, ErrorNote, Segmented, Skeleton } from "../../components/ui";
import { ExpandedProvider, Figure, Tile, useExpanded, type Section } from "../../components/ui/Expanded";
import { api } from "../../lib/api";
import { cn } from "../../lib/cn";

type Row = {
  id: string; kind: "wc" | "notice"; wc: string | null; wc_raw: string; company: string | null; products: string | null; items: number;
  date: string | null; size_kb: number | null; valid_until: string | null; latest?: boolean; has_pdf: boolean; source_url?: string; hit?: string;
};

const nf = (n: number | null | undefined) => (n == null ? "—" : n.toLocaleString("en-IN"));
const fmtDate = (d: string | null | undefined) => (d ? new Date(d + "T00:00:00").toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric" }) : "—");
const mb = (kb: number | null | undefined) => (kb == null ? "" : kb >= 1024 ? `${(kb / 1024).toFixed(1)} MB` : `${kb} KB`);
const pdfUrl = (id: string) => `/api/playground/wc/${encodeURIComponent(id)}.pdf`;
const titleOf = (r: Row) => (r.kind === "wc" ? `${r.wc_raw} · ${r.company ?? ""}` : r.wc_raw);

function useDebounced<T>(v: T, ms = 300) {
  const [d, setD] = useState(v);
  useEffect(() => { const t = setTimeout(() => setD(v), ms); return () => clearTimeout(t); }, [v, ms]);
  return d;
}

function PdfViewer({ r }: { r: Row }) {
  return (
    <div className="-m-5 flex h-[calc(100%+2.5rem)] flex-col md:-m-6 md:h-[calc(100%+3rem)]">
      <div className="flex flex-wrap items-center gap-2 border-b border-line bg-white px-5 py-2.5 text-xs">
        {r.kind === "wc" ? <Badge tone="indigo"><FileCheck2 size={11} /> Written confirmation</Badge> : <Badge>Notice</Badge>}
        <span className="text-ink-muted">Released {fmtDate(r.date)}</span>
        {r.valid_until && <span className="text-ink-muted">· valid until <b className="text-ink-soft">{fmtDate(r.valid_until)}</b></span>}
        {r.latest === false && <Badge tone="amber">superseded by a newer letter with this number</Badge>}
        {r.products && <span className="min-w-0 truncate text-ink-soft" title={r.products}>· {r.products}</span>}
        <span className="ml-auto flex items-center gap-1.5">
          {r.has_pdf && <a href={pdfUrl(r.id)} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 rounded-md px-2 py-1 hover:bg-slate-100"><ExternalLink size={13} /> New tab</a>}
          {r.has_pdf && <a href={pdfUrl(r.id)} download className="inline-flex items-center gap-1 rounded-md px-2 py-1 hover:bg-slate-100"><Download size={13} /> Download</a>}
          {r.source_url && <a href={r.source_url} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 rounded-md px-2 py-1 text-ink-muted hover:bg-slate-100" title="The same document on cdsco.gov.in">CDSCO ↗</a>}
        </span>
      </div>
      {r.has_pdf ? (
        <iframe key={r.id} src={`${pdfUrl(r.id)}#view=FitH`} title={titleOf(r)} className="min-h-0 w-full flex-1 bg-slate-100" />
      ) : (
        <div className="m-6 rounded-xl border border-dashed border-line p-6 text-sm text-ink-muted">
          <b className="text-ink-soft">This PDF is not on the server yet.</b> Run <code>just fetch-cdsco-wc</code> on your laptop, then <code>just push-wc HOST KEY</code>.
          {r.source_url && <> Meanwhile it opens on <a className="text-brand-700 hover:underline" href={r.source_url} target="_blank" rel="noreferrer">cdsco.gov.in ↗</a> (CDSCO does not allow its PDFs to be embedded).</>}
        </div>
      )}
    </div>
  );
}

function About({ about }: { about: any[] }) {
  if (!about?.length) return <div className="text-sm text-ink-muted">Not loaded yet.</div>;
  return (
    <div className="max-w-3xl space-y-6">
      <p className="text-sm text-ink-soft">
        The International Cell grants Written Confirmations under EU Directive 2011/62/EU (Article 46b): since July 2013 every active substance imported into the EU
        needs one from the exporting country, confirming the API site follows GMP equivalent to the EU's. A WC names the site and the APIs it covers; companies
        re-apply to add APIs or renew, so one WC number can carry several letters.
      </p>
      {about.map((a) => (
        <div key={a.title}>
          <div className="label mb-2">{a.title}</div>
          {a.paragraphs.length === 0 && a.links.length === 0 && <div className="text-xs text-ink-faint">CDSCO has published nothing under this tab.</div>}
          <ul className="space-y-1.5 text-sm text-ink-soft">{a.paragraphs.map((p: string, i: number) => <li key={i} className="leading-relaxed">{p}</li>)}</ul>
          {a.links.map((l: any) => (
            <div key={l.url} className="mt-2">
              {l.file ? (
                <div className="overflow-hidden rounded-xl ring-1 ring-line">
                  <div className="flex items-center justify-between border-b border-line bg-white px-3 py-2 text-xs"><span className="font-medium">{l.title}</span>
                    <a href={pdfUrl(l.file.replace(/\.pdf$/i, ""))} target="_blank" rel="noreferrer" className="text-brand-700 hover:underline">New tab ↗</a></div>
                  <iframe src={pdfUrl(l.file.replace(/\.pdf$/i, ""))} title={l.title} className="h-[70vh] w-full bg-slate-100" />
                </div>
              ) : <a href={l.url} target="_blank" rel="noreferrer" className="text-sm text-brand-700 hover:underline">{l.title} ↗</a>}
            </div>
          ))}
        </div>
      ))}
    </div>
  );
}

function YearBars({ years, year, onPick }: { years: Record<string, number>; year: string; onPick: (y: string) => void }) {
  const ys = Object.entries(years);
  const max = Math.max(1, ...ys.map(([, n]) => n));
  return (
    <div className="flex h-14 items-end gap-[3px]">
      {ys.map(([y, n]) => (
        <button key={y} onClick={(e) => { e.stopPropagation(); onPick(year === y ? "" : y); }} title={`${y}: ${n} letters`}
          className="group flex h-full min-w-0 flex-1 flex-col justify-end">
          <span className={cn("block w-full rounded-t-sm transition", year === y ? "bg-brand-600" : "bg-indigo-200 group-hover:bg-indigo-400")} style={{ height: `${Math.max(6, (100 * n) / max)}%` }} />
          <span className="mt-0.5 block text-center text-[8.5px] tabular-nums text-ink-faint">{y.slice(2)}</span>
        </button>
      ))}
    </div>
  );
}

function Rows({ items, q }: { items: Row[]; q: string }) {
  const { open } = useExpanded();
  return (
    <table className="w-full text-sm">
      <thead><tr className="border-y border-line bg-slate-50/70 text-left text-[11px] font-semibold uppercase tracking-wider text-ink-muted">
        <th className="px-5 py-2.5">WC</th><th className="px-3 py-2.5">Company</th><th className="px-3 py-2.5">Products</th><th className="px-3 py-2.5">Released</th><th className="px-5 py-2.5 text-right">PDF</th>
      </tr></thead>
      <tbody>
        {items.map((r) => (
          <tr key={r.id} onClick={() => open(`doc:${r.id}`)} className="cursor-pointer border-b border-line/70 align-top hover:bg-slate-50">
            <td className="whitespace-nowrap px-5 py-2.5 font-mono text-xs font-semibold">{r.kind === "wc" ? r.wc_raw : <Badge>Notice</Badge>}
              {r.latest === false && <div className="font-sans text-[10.5px] font-normal text-amber-700">older letter</div>}</td>
            <td className="max-w-[280px] px-3 py-2.5">{r.kind === "wc" ? <div className="line-clamp-2 font-medium">{r.company}</div> : <div className="line-clamp-2">{r.wc_raw}</div>}</td>
            <td className="max-w-[380px] px-3 py-2.5 text-xs text-ink-soft">
              <div className="line-clamp-2">{r.products || "—"}</div>
              {r.hit && q && <div className="mt-1 line-clamp-2 rounded bg-amber-50 px-1.5 py-0.5 text-[11px] text-amber-900" title="Found in the letter's text">…{r.hit.replace(/^…|…$/g, "")}…</div>}
            </td>
            <td className="whitespace-nowrap px-3 py-2.5 text-xs">{fmtDate(r.date)}{r.valid_until && <div className="text-ink-faint">valid to {r.valid_until.slice(0, 7)}</div>}</td>
            <td className="whitespace-nowrap px-5 py-2.5 text-right text-xs">
              <span className={cn("inline-flex items-center gap-1", r.has_pdf ? "text-rose-600" : "text-ink-faint")}><FileText size={14} />{mb(r.size_kb)}</span>
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

export function WrittenConfirmations() {
  const [qIn, setQ] = useState("");
  const q = useDebounced(qIn.trim());
  const [kind, setKind] = useState<"wc" | "notice" | "all">("wc");
  const [year, setYear] = useState("");
  const [latest, setLatest] = useState(false);
  const [page, setPage] = useState(1);
  const [active, setActive] = useState<string | null>(null);
  useEffect(() => setPage(1), [q, kind, year, latest]);
  const { data: d, error, isLoading, isFetching } = useQuery({
    queryKey: ["wc", q, kind, year, latest, page],
    queryFn: () => api<any>(`/api/playground/wc?${new URLSearchParams({ q, kind, year, latest: String(latest), page: String(page), size: "25" })}`),
    placeholderData: keepPreviousData,
  });

  const items: Row[] = d?.items ?? [];
  const sections: Section[] = useMemo(() => [
    ...items.map((r) => ({ id: `doc:${r.id}`, title: r.kind === "wc" ? `${r.wc_raw} · ${r.company}` : r.wc_raw, subtitle: r.kind === "wc" ? `${r.products ?? ""} · released ${fmtDate(r.date)}` : fmtDate(r.date),
      icon: <FileText size={15} />, render: () => <PdfViewer r={r} /> })),
    { id: "about", title: "About the International Cell", icon: <Info size={15} />, subtitle: "Functions, foreign delegations, SOP, organogram", render: () => <About about={d?.about ?? []} /> },
  ], [items, d?.about]);

  if (error) return <ErrorNote error={error} />;
  if (isLoading) return <div className="grid gap-4 md:grid-cols-4">{[0, 1, 2, 3].map((i) => <Skeleton key={i} className="h-36" />)}</div>;
  if (!d?.available) return (
    <Card className="p-6 text-sm text-ink-muted">
      <b className="text-ink-soft">Written Confirmations are not loaded yet.</b> CDSCO refuses cloud servers, so this runs on your laptop:
      <pre className="mt-3 rounded-lg bg-slate-50 p-3 text-xs text-ink-soft">just fetch-cdsco-wc          # the list + every PDF (~1.5 GB the first time)\njust push-wc HOST KEY          # copies the list and the new PDFs to the server</pre>
    </Card>
  );
  const s = d.stats;
  return (
    <ExpandedProvider sections={sections} active={active} onActive={setActive} title="Written confirmations" subtitle={`${nf(d.total)} documents match`}>
      <div className="mb-4 grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <Tile title="Written confirmations" subtitle="CDSCO · API exports to the EU" icon={<FileCheck2 size={14} />} accent="#6366f1" clickable={false}>
          <div className="grid grid-cols-3 gap-2"><Figure value={nf(s.letters)} label="letters" /><Figure value={nf(s.numbers)} label="WC numbers" /><Figure value={nf(s.companies)} label="companies" /></div>
        </Tile>
        <Tile title="Issued per year" subtitle={`${nf(s.last_12m)} in the last 12 months · latest ${fmtDate(s.latest_date)}`} clickable={false}
          action={year ? <button className="text-[11px] text-brand-700 hover:underline" onClick={() => setYear("")}>{year} ✕</button> : undefined}>
          <YearBars years={d.years} year={year} onPick={setYear} />
        </Tile>
        <Tile title="Letters on the server" subtitle={`retrieved ${d.meta?.retrieved_at?.slice(0, 10) ?? "—"}`} icon={<FileText size={14} />} clickable={false}>
          <div className="grid grid-cols-2 gap-2"><Figure value={`${nf(s.pdfs)}`} label={`of ${nf(s.letters + s.notices)} PDFs`} tone={s.pdfs < s.letters ? "#b45309" : undefined} /><Figure value={nf(s.with_text)} label="searchable text" /></div>
        </Tile>
        <Tile id="about" title="About the International Cell" subtitle="Functions · delegations · organogram" icon={<Info size={14} />}>
          <p className="line-clamp-3 text-xs text-ink-muted">Why a WC exists (EU Directive 2011/62/EU), what the cell does, and its organogram.</p>
        </Tile>
      </div>

      <Card>
        <div className="flex flex-wrap items-center gap-2 px-5 py-4">
          <div className="relative min-w-[240px] flex-[1_1_320px]">
            <Search size={15} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-ink-faint" />
            <input className="input h-9 w-full pl-9" placeholder="Company, WC number, API — searches the letters' text too" value={qIn} onChange={(e) => setQ(e.target.value)} />
          </div>
          <Segmented value={kind} onChange={setKind} options={[{ value: "wc", label: "Confirmations" }, { value: "notice", label: "Notices" }, { value: "all", label: "All" }]} />
          <select className="input h-9 w-auto" value={year} onChange={(e) => setYear(e.target.value)}>
            <option value="">All years</option>{Object.keys(d.years).reverse().map((y) => <option key={y} value={y}>{y}</option>)}
          </select>
          <label className="flex items-center gap-1.5 text-xs text-ink-soft" title="Hide letters superseded by a newer one with the same WC number">
            <input type="checkbox" checked={latest} onChange={(e) => setLatest(e.target.checked)} /> Latest per WC
          </label>
        </div>
        <div className={cn("relative overflow-x-auto", isFetching && "opacity-60")}><LoadingEdge active={isFetching} />
          <Rows items={items} q={q} />
          {items.length === 0 && <div className="p-8 text-center text-sm text-ink-muted">Nothing matches.</div>}
        </div>
        <div className="flex items-center justify-between px-5 py-3 text-xs text-ink-muted">
          <span>{nf(d.total)} documents · page {d.page} of {d.pages} · click a row to read the letter (Alt + ↑/↓ flips through this page)</span>
          <div className="flex gap-1.5">
            <Button size="sm" variant="secondary" disabled={page <= 1} onClick={() => setPage(page - 1)}><ChevronLeft size={14} /></Button>
            <Button size="sm" variant="secondary" disabled={page >= d.pages} onClick={() => setPage(page + 1)}><ChevronRight size={14} /></Button>
          </div>
        </div>
      </Card>
      <p className="mt-3 text-[11px] text-ink-faint">Source: <a className="hover:underline" href={d.meta?.url} target="_blank" rel="noreferrer">CDSCO International Cell</a>. Letters are copies of CDSCO's PDFs; "valid until" is read from the letter's text where it has one.</p>
    </ExpandedProvider>
  );
}
