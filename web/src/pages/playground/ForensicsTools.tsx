// Two answers built on Failure forensics:
//  * Portfolio check — paste your product list, see how the market fails each one and what to check first.
//  * Needed & badly made — products many makers keep failing, crossed with NFHS disease burden and IDSP outbreaks.
import { keepPreviousData, useMutation, useQuery } from "@tanstack/react-query";
import { Activity, ClipboardCheck, Download, Factory, HeartPulse, MapPin, Search, Sparkles, TrendingUp } from "lucide-react";
import { useEffect, useState } from "react";
import { Badge, Button, Card, CardHeader, ErrorNote, Skeleton } from "../../components/ui";
import { api, post } from "../../lib/api";
import { cn } from "../../lib/cn";
import { fmtMonth } from "../../lib/format";

type Open = (key: string, g?: any) => void;

const RISK: Record<string, { label: string; bar: string; chip: string }> = {
  high: { label: "High risk", bar: "bg-rose-500", chip: "bg-rose-50 text-rose-700 ring-rose-200" },
  watch: { label: "Watch", bar: "bg-amber-500", chip: "bg-amber-50 text-amber-700 ring-amber-200" },
  low: { label: "Low", bar: "bg-sky-400", chip: "bg-sky-50 text-sky-700 ring-sky-200" },
  clear: { label: "No NSQ history", bar: "bg-emerald-500", chip: "bg-emerald-50 text-emerald-700 ring-emerald-200" },
  unknown: { label: "Not recognised", bar: "bg-slate-300", chip: "bg-slate-100 text-slate-600 ring-slate-200" },
};

const EXAMPLE = ["Telmisartan 40 mg tablets", "Albendazole 400 mg tablets", "Metformin 500 SR", "Pantoprazole 40 mg tablets",
  "Amoxycillin + Clavulanate 625", "Omeprazole capsules", "Vitamin D3 60000 IU", "Cefixime 200 mg tablets", "Rosuvastatin 10 mg"].join("\n");
const STORE = "nsq.portfolio.v1";

function load(): string {
  try { return localStorage.getItem(STORE) ?? ""; } catch { return ""; }
}
function save(v: string) {
  try { localStorage.setItem(STORE, v); } catch { /* storage may be blocked */ }
}

function csv(rows: any[]) {
  const head = ["Your product", "Read as", "Risk", "Why", "NSQ alerts", "Last 24 months", "Makers failing", "Main test", "Likely cause", "Checks"];
  const esc = (v: any) => `"${String(v ?? "").replace(/"/g, '""')}"`;
  const body = rows.map((r) => [r.input, r.label, RISK[r.risk]?.label, r.why, r.alerts, r.recent_24m, r.makers, r.tests?.[0],
    r.diagnosis?.cause, (r.diagnosis?.checks ?? []).join(" | ")].map(esc).join(","));
  const blob = new Blob([[head.map(esc).join(","), ...body].join("\n")], { type: "text/csv" });
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = "nsq-portfolio-risk.csv";
  a.click();
  setTimeout(() => URL.revokeObjectURL(a.href), 1000);
}

function MakerLoader({ onLoad }: { onLoad: (lines: string[]) => void }) {
  const [q, setQ] = useState("");
  const [dq, setDq] = useState("");
  useEffect(() => { const t = setTimeout(() => setDq(q.trim()), 300); return () => clearTimeout(t); }, [q]);
  const r = useQuery({ queryKey: ["inv-search", dq], enabled: dq.length >= 2, placeholderData: keepPreviousData,
    queryFn: () => api<any>(`/api/playground/investigate/search?q=${encodeURIComponent(dq)}`) });
  const pick = async (key: string) => {
    const out = await api<any>(`/api/playground/forensics/portfolio/maker?key=${encodeURIComponent(key)}`);
    onLoad(out.products);
    setQ("");
  };
  return (
    <div className="relative">
      <Search size={13} className="absolute left-2.5 top-2.5 text-ink-faint" />
      <input className="input h-8 w-full pl-7 text-xs" placeholder="…or load a maker's products from NSQ" value={q} onChange={(e) => setQ(e.target.value)} />
      {dq.length >= 2 && q && (r.data?.manufacturers?.length ?? 0) > 0 && (
        <div className="absolute z-20 mt-1 max-h-64 w-full overflow-y-auto rounded-xl bg-white shadow-lg ring-1 ring-line">
          {r.data.manufacturers.map((m: any) => (
            <button key={m.key} onClick={() => pick(m.key)} className="block w-full px-3 py-2 text-left text-xs hover:bg-slate-50">
              <div className="font-medium">{m.name}</div><div className="text-ink-muted">{[m.city, m.state].filter(Boolean).join(", ")} · {m.alerts} alerts</div>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

export function Portfolio({ onOpen }: { onOpen: Open }) {
  const [text, setText] = useState(() => load() || EXAMPLE);
  useEffect(() => save(text), [text]);
  const m = useMutation({ mutationFn: (lines: string[]) => post<any>("/api/playground/forensics/portfolio", { lines }) });
  const run = (t = text) => m.mutate(t.split(/\n|;/).map((x) => x.trim()).filter(Boolean));
  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => { run(); }, []);
  const d = m.data;
  return (
    <div className="grid gap-4 xl:grid-cols-[20rem_minmax(0,1fr)]">
      <Card className="h-fit p-4">
        <div className="label mb-2 flex items-center gap-1.5"><ClipboardCheck size={12} /> Your products, one per line</div>
        <textarea className="input min-h-[16rem] w-full py-2 font-mono text-[12px] leading-relaxed" value={text} onChange={(e) => setText(e.target.value)}
          placeholder={"Generic name, strength, form\ne.g. Telmisartan 40 mg tablets"} />
        <div className="mt-2 flex gap-2">
          <Button className="flex-1" onClick={() => run()} loading={m.isPending}>Check my portfolio</Button>
          <Button variant="secondary" onClick={() => { setText(EXAMPLE); run(EXAMPLE); }}>Example</Button>
        </div>
        <div className="mt-3"><MakerLoader onLoad={(ls) => { const t = ls.join("\n"); setText(t); run(t); }} /></div>
        <p className="mt-3 text-[11px] leading-relaxed text-ink-faint">Stays in this browser. Generic names work best; brand names are matched through the NSQ product names that carry them. No form means the form the market fails most.</p>
      </Card>

      <div className="min-w-0 space-y-4">
        {m.error && <ErrorNote error={m.error} />}
        {!d && m.isPending && <Skeleton className="h-96" />}
        {d?.available && (
          <>
            <div className="rounded-2xl bg-night-900 p-5 text-white">
              <div className="text-[11px] font-semibold uppercase tracking-wider text-brand-400">Portfolio risk · NSQ {fmtMonth(d.period.first)} – {fmtMonth(d.period.last)}</div>
              <div className="mt-1 font-display text-xl font-bold leading-snug">
                {d.summary.high > 0
                  ? <>{d.summary.high} of your {d.rows.length} products fail NSQ across the market in a known way — the fix is usually a specification line or a pack change, not a new formula.</>
                  : <>None of your {d.rows.length} products has a strong market-wide failure pattern.</>}
              </div>
              <div className="mt-3 flex flex-wrap gap-2">{Object.entries(RISK).map(([k, v]) => d.summary[k] ? (
                <span key={k} className={cn("rounded-full px-2.5 py-0.5 text-[11px] font-semibold ring-1 ring-inset", v.chip)}>{d.summary[k]} {v.label.toLowerCase()}</span>) : null)}
                <button onClick={() => csv(d.rows)} className="ml-auto flex items-center gap-1 rounded-full bg-white/10 px-2.5 py-0.5 text-[11px] text-slate-200 hover:bg-white/20"><Download size={11} /> CSV</button>
              </div>
            </div>

            {d.common_checks.length > 0 && (
              <Card className="p-4">
                <div className="label mb-2 text-emerald-800">Checks that cover several of your high-risk products</div>
                <ul className="grid gap-1.5 text-xs text-emerald-900 md:grid-cols-2">{d.common_checks.map((c: any) => (
                  <li key={c.check} className="flex gap-2 rounded-lg bg-emerald-50 p-2"><span className="shrink-0 font-semibold tabular-nums">{c.products}×</span>{c.check}</li>))}</ul>
              </Card>
            )}

            <Card className="overflow-hidden">
              {d.rows.map((r: any) => {
                const x = RISK[r.risk];
                const dg = r.diagnosis;
                return (
                  <div key={r.input} className="flex gap-3 border-t border-line/70 px-4 py-3 first:border-t-0">
                    <span className={cn("w-1 shrink-0 rounded-full", x.bar)} />
                    <div className="min-w-0 flex-1">
                      <div className="flex flex-wrap items-center gap-2">
                        <span className="text-[13px] font-semibold">{r.input}</span>
                        {r.label && r.label.toLowerCase() !== r.input.toLowerCase() && <span className="text-[11.5px] text-ink-muted">→ {r.label}{r.via === "brand" && " (via brand)"}</span>}
                        <span className={cn("rounded-full px-2 py-0.5 text-[10.5px] font-semibold ring-1 ring-inset", x.chip)}>{x.label}</span>
                      </div>
                      <div className="mt-0.5 text-[11.5px] text-ink-muted">
                        {r.why}{r.alerts > 0 && <> · {r.alerts} alerts ({r.recent_24m} in 24 mo) · {r.makers} makers{r.tests?.length ? <> · mostly {r.tests[0].toLowerCase()}</> : null} · last {fmtMonth(r.last)}</>}
                      </div>
                      {dg && (
                        <div className="mt-2 grid gap-2 md:grid-cols-[minmax(0,1fr)_minmax(0,1.2fr)]">
                          <div className="text-xs"><div className="font-semibold text-ink">{dg.cause}</div>
                            {dg.evidence.map((e: string, i: number) => <div key={i} className="text-ink-muted">● {e}</div>)}</div>
                          <ul className="rounded-lg bg-emerald-50 p-2 text-[11.5px] text-emerald-900">{dg.checks.map((c: string, i: number) => <li key={i}>✓ {c}</li>)}</ul>
                        </div>
                      )}
                      {(r.other_forms?.length > 0 || r.in_combinations > 0) && (
                        <div className="mt-1.5 flex flex-wrap gap-1.5 text-[11px] text-ink-muted">
                          {r.other_forms.map((f: any) => f.key
                            ? <button key={f.form} onClick={() => onOpen(f.key)} className="rounded-md bg-slate-100 px-1.5 py-0.5 hover:bg-slate-200">{f.form}: {f.alerts} →</button>
                            : <span key={f.form} className="rounded-md bg-slate-50 px-1.5 py-0.5">{f.form}: {f.alerts}</span>)}
                          {r.in_combinations > 0 && <span className="rounded-md bg-slate-50 px-1.5 py-0.5">in combinations: {r.in_combinations}</span>}
                        </div>
                      )}
                    </div>
                    {r.key && <button onClick={() => onOpen(r.key)} className="shrink-0 self-start text-[11px] font-semibold text-brand-700 hover:underline">full diagnosis →</button>}
                  </div>
                );
              })}
            </Card>
            <p className="text-[11px] text-ink-faint">{d.note}</p>
          </>
        )}
      </div>
    </div>
  );
}

// ------------------------------------------------------------------------------------------ needed & badly made

function Burden({ b }: { b: any }) {
  return (
    <div className="flex items-baseline justify-between gap-2 text-[11.5px]">
      <span className="min-w-0 truncate text-ink-soft">{b.label}</span>
      <span className="shrink-0 tabular-nums"><b className="text-ink">{b.india ?? "—"}%</b>
        {b.change != null && <span className={cn("ml-1", b.change > 0 ? "text-rose-600" : "text-emerald-600")}>{b.change > 0 ? "▲" : "▼"}{Math.abs(b.change)}</span>}</span>
    </div>
  );
}

function Condition({ c, onOpen }: { c: any; onOpen: Open }) {
  const [more, setMore] = useState(false);
  const top = c.burden[0];
  return (
    <Card className="flex flex-col p-4">
      <div className="flex items-center justify-between gap-2">
        <div className="font-display text-[15px] font-bold">{c.label}</div>
        {c.class_wide > 0 && <Badge tone="rose">{c.class_wide} class-wide</Badge>}
      </div>
      <div className="mt-2 space-y-1">
        {c.burden.map((b: any) => <Burden key={b.indicator} b={b} />)}
        {top?.previous_round && top.change != null && <div className="text-[11px] text-ink-muted">{top.rising_states} of {top.states_total} states rising since {top.previous_round}</div>}
        {c.outbreaks?.outbreaks > 0 && <div className="flex items-baseline justify-between text-[11.5px]"><span className="text-ink-soft">Outbreaks, last {c.outbreaks.weeks} weeks (IDSP)</span>
          <span className="tabular-nums"><b>{c.outbreaks.outbreaks}</b> <span className="text-ink-muted">· {c.outbreaks.cases.toLocaleString("en-IN")} cases</span></span></div>}
      </div>
      <div className="mt-3 rounded-lg bg-rose-50 px-2.5 py-1.5 text-[11.5px] text-rose-900">
        <b>{c.products.length}</b> of its medicines keep failing · <b>{c.recent_alerts}</b> NSQ alerts in 24 months
      </div>
      <div className="mt-2 flex-1 space-y-0.5">{c.products.slice(0, more ? 12 : 4).map((p: any) => (
        <button key={p.key} onClick={() => onOpen(p.key, p)} className="flex w-full items-center justify-between gap-2 rounded-md px-1.5 py-1 text-left text-xs hover:bg-slate-50">
          <span className="min-w-0 truncate">{p.label}</span><span className="shrink-0 tabular-nums text-ink-muted">{p.recent_24m} · {p.makers} makers</span>
        </button>
      ))}</div>
      {more && (top?.top_states?.length || c.outbreaks?.top_states?.length) ? ( (
        <div className="mt-2 grid grid-cols-2 gap-3 border-t border-line pt-2 text-[11px]">
          {top && <div><div className="label mb-1 flex items-center gap-1"><MapPin size={10} /> Highest burden</div>
            {top.top_states.slice(0, 5).map((s: any) => <div key={s.state} className="flex justify-between"><span className="truncate">{s.state}</span><span className="tabular-nums text-ink-muted">{s.value}%</span></div>)}</div>}
          {c.outbreaks?.top_states?.length > 0 && <div><div className="label mb-1 flex items-center gap-1"><Activity size={10} /> Most outbreaks</div>
            {c.outbreaks.top_states.slice(0, 5).map((s: any) => <div key={s.state} className="flex justify-between"><span className="truncate">{s.state}</span><span className="tabular-nums text-ink-muted">{s.outbreaks}</span></div>)}</div>}
        </div>
      )) : null}
      <button onClick={() => setMore(!more)} className="mt-2 self-start text-[11px] font-semibold text-brand-700 hover:underline">{more ? "less" : "more · where it's needed"}</button>
    </Card>
  );
}

export function Needed({ onOpen }: { onOpen: Open }) {
  const { data: d, error } = useQuery({ queryKey: ["forensics-needed"], queryFn: () => api<any>("/api/playground/forensics/needed") });
  if (error) return <ErrorNote error={error} />;
  if (!d) return <Skeleton className="h-96" />;
  if (!d.available) return <Card className="p-6 text-sm text-ink-muted">No NSQ data loaded yet.</Card>;
  const lead = d.ranked[0];
  return (
    <div className="space-y-4">
      <div className="rounded-2xl bg-gradient-to-br from-emerald-900 to-night-900 p-5 text-white">
        <div className="flex items-center gap-2 text-[11px] font-semibold uppercase tracking-wider text-emerald-300"><Sparkles size={13} /> Needed and badly made</div>
        <div className="mt-1 max-w-4xl font-display text-xl font-bold leading-snug">
          India needs these medicines — and the market keeps shipping batches that fail. A maker who gets them right has something to sell to every state tender and hospital chain.
        </div>
        {lead && <div className="mt-2 text-sm text-emerald-100">Top of the list: <button className="font-semibold text-white underline decoration-emerald-400 underline-offset-2" onClick={() => onOpen(lead.key, lead)}>{lead.label}</button> — {lead.recent_24m} NSQ alerts in 24 months from {lead.makers} makers, serving {lead.conditions.join(", ").toLowerCase()}.</div>}
      </div>

      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">{d.conditions.map((c: any) => <Condition key={c.key} c={c} onOpen={onOpen} />)}</div>

      <Card className="overflow-hidden">
        <CardHeader title={<span className="flex items-center gap-2"><TrendingUp size={15} className="text-emerald-600" /> Ranked: quality gap × need</span>}
          subtitle={`Recent failures (${fmtMonth(d.window.from)} – ${fmtMonth(d.window.to)}) and how many makers fail it, weighted by the burden and outbreaks of the conditions it treats`} />
        <div className="mt-2">{d.ranked.map((r: any, i: number) => (
          <button key={r.key} onClick={() => onOpen(r.key, r)} className="flex w-full items-center gap-3 border-t border-line/70 px-4 py-2.5 text-left hover:bg-slate-50">
            <span className="w-5 shrink-0 text-right text-xs font-semibold tabular-nums text-ink-faint">{i + 1}</span>
            <div className="min-w-0 flex-1">
              <div className="flex flex-wrap items-center gap-1.5"><span className="truncate text-[13px] font-semibold">{r.label}</span>
                {r.conditions.map((c: string) => <span key={c} className="flex items-center gap-1 rounded-md bg-emerald-50 px-1.5 py-0.5 text-[10.5px] text-emerald-800"><HeartPulse size={10} />{c}</span>)}</div>
              <div className="truncate text-[11.5px] text-ink-muted">{r.headline} · mostly {r.dominant.toLowerCase()}
                {r.made_in.length > 0 && <> · <Factory size={10} className="inline" /> failing batches made in {r.made_in.map((m: any) => m.state).join(", ")}</>}</div>
            </div>
            <div className="shrink-0 text-right"><div className="text-sm font-semibold tabular-nums">{r.recent_24m}</div><div className="text-[10.5px] text-ink-muted">{r.makers} makers</div></div>
          </button>
        ))}</div>
      </Card>
      <p className="text-[11px] text-ink-faint">{d.note} Sources: {d.sources.nfhs?.title ?? "NFHS"}{d.sources.idsp ? ` · ${d.sources.idsp.title}` : ""}.</p>
    </div>
  );
}
