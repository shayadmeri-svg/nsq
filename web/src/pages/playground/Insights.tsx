import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { BadgeCheck, CalendarRange, CloudRain, FlaskConical, Globe2, Lightbulb, MapPin, ShieldAlert, Timer, Users } from "lucide-react";
import { Bar, BarChart, CartesianGrid, Legend, Line, LineChart, ResponsiveContainer, Scatter, ScatterChart, Tooltip, XAxis, YAxis, ZAxis } from "recharts";
import { RankBars } from "../../components/charts";
import { Badge, Card, CardHeader, ErrorNote, PageSkeleton, Segmented, Skeleton } from "../../components/ui";
import { api } from "../../lib/api";
import { ExpandedProvider, Frame, Tile, type Section } from "../../components/ui/Expanded";

const LIFE_COLORS = ["#10b996", "#6366f1", "#f59e0b", "#e11d48", "#0f172a"];
const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

function Takeaway({ children }: { children: React.ReactNode }) {
  return <div className="mx-5 mb-4 flex gap-2 rounded-xl bg-amber-50 p-3 text-[12.5px] leading-relaxed text-amber-900 ring-1 ring-inset ring-amber-200"><Lightbulb size={15} className="mt-0.5 shrink-0" /><div>{children}</div></div>;
}
const tip = { contentStyle: { borderRadius: 10, fontSize: 12 } };

const SURV_COLORS = ["#0a9a7d", "#6366f1", "#e11d48", "#f59e0b", "#0ea5e9", "#7c3aed"];

function Survival({ bare }: { bare?: boolean }) {
  const [group, setGroup] = useState("form");
  const [measure, setMeasure] = useState<"months" | "shelf">("months");
  const q = useQuery({ queryKey: ["pg-surv", group, measure], queryFn: () => api<any>(`/api/playground/survival?group=${group}&measure=${measure}`), placeholderData: keepPreviousData });
  const d = q.data;
  const rows = d ? d.grid.map((x: number, i: number) => Object.fromEntries([["x", x], ...d.curves.map((c: any) => [c.group, Math.round(c.sf[i] * 1000) / 10])])) : [];
  const fastest = d?.curves.filter((c: any) => c.median != null).sort((a: any, b: any) => a.median - b.median)[0];
  const slowest = d?.curves.filter((c: any) => c.median != null).sort((a: any, b: any) => b.median - a.median)[0];
  return (
    <Frame bare={bare} title="Shelf-life survival: how long until a failing batch is caught?" subtitle="Kaplan-Meier curves (lifelines) of time from manufacture to the NSQ report, with a log-rank test between groups">
      <div className="flex flex-wrap justify-end gap-2 px-5 pt-3">
          <select className="input h-9 w-44 text-xs" value={group} onChange={(e) => setGroup(e.target.value)}>{(d?.groups ?? [{ key: "form", label: "Dosage form" }]).map((g: any) => <option key={g.key} value={g.key}>{g.label}</option>)}</select>
          <Segmented value={measure} onChange={setMeasure} options={[{ value: "months", label: "Months" }, { value: "shelf", label: "% of shelf life" }]} />
      </div>
      {q.error ? <div className="p-5"><ErrorNote error={q.error} /></div> : !d ? <Skeleton className="m-5 h-64" /> : (
        <div className="grid gap-4 p-4 lg:grid-cols-[1.5fr_1fr]">
          <ResponsiveContainer width="100%" height={300}>
            <LineChart data={rows}><CartesianGrid stroke="#eef2f7" /><XAxis dataKey="x" type="number" fontSize={11} unit={measure === "months" ? " m" : "%"} /><YAxis fontSize={11} width={40} unit="%" domain={[0, 100]} />
              <Tooltip {...tip} formatter={(v: any) => `${v}% not yet detected`} labelFormatter={(l: any) => `${l} ${d.unit}`} />
              <Legend wrapperStyle={{ fontSize: 11 }} />
              {d.curves.map((c: any, i: number) => <Line key={c.group} type="stepAfter" dataKey={c.group} stroke={SURV_COLORS[i % SURV_COLORS.length]} dot={false} strokeWidth={2} />)}
            </LineChart>
          </ResponsiveContainer>
          <div className="text-xs">
            <table className="w-full"><thead><tr className="text-left text-[10.5px] uppercase tracking-wider text-ink-muted"><th className="py-1">{d.group_label}</th><th className="text-right">n</th><th className="text-right">Median (95% CI)</th><th className="text-right">25%</th></tr></thead>
              <tbody>{d.curves.map((c: any, i: number) => <tr key={c.group} className="border-t border-line/60"><td className="py-1.5"><span className="mr-1.5 inline-block h-2 w-2 rounded-full" style={{ background: SURV_COLORS[i % SURV_COLORS.length] }} />{c.group}</td>
                <td className="text-right tabular-nums">{c.n}</td><td className="text-right tabular-nums">{c.median ?? "—"} {c.median_low != null && <span className="text-ink-faint">({c.median_low}–{c.median_high})</span>}</td><td className="text-right tabular-nums">{c.p25}</td></tr>)}</tbody></table>
            {d.logrank && <p className="mt-3">Log-rank test across groups: χ² {d.logrank.statistic} on {d.logrank.df} df, <b>p = {d.logrank.p}</b> {d.logrank.p < 0.05 ? "(the groups differ)" : "(no clear difference)"}.</p>}
          </div>
        </div>
      )}
      {d && fastest && slowest && fastest.group !== slowest.group && <Takeaway>Half of <b>{fastest.group}</b> failures are caught by {fastest.median} {d.unit}, against {slowest.median} for <b>{slowest.group}</b>. {d.note}</Takeaway>}
    </Frame>
  );
}

export function InsightsTab() {
  const { data: d, isLoading, error } = useQuery({ queryKey: ["pg-insights"], queryFn: () => api<any>("/api/playground/insights"), staleTime: 300_000 });
  const survQ = useQuery({ queryKey: ["pg-surv", "form", "months"], queryFn: () => api<any>(`/api/playground/survival?group=form&measure=months`), placeholderData: keepPreviousData });
  const [active, setActive] = useState<string | null>(null);
  if (isLoading) return <PageSkeleton />;
  if (error) return <ErrorNote error={error} />;
  const sl = d.shelf_life;
  const lateShare = (r: any) => r["last quarter"] + r["after expiry"];
  const named = sl.rows.filter((r: any) => !/uncategori|other/i.test(r.category));
  const mostLate = [...named].sort((a: any, b: any) => lateShare(b) - lateShare(a))[0];
  const early = [...named].sort((a: any, b: any) => b["first quarter"] - a["first quarter"])[0];
  const conc = d.repeat.concentration;
  const top = conc.find((c: any) => c.tier === "10+");
  const reg = d.fda_overlap.registered, non = d.fda_overlap.not_registered;
  const hub = d.hubs[0];
  const ws = d.whitespace[0];
  const season = d.seasonality;
  const mon = season.rows.filter((r: any) => [6, 7, 8, 9].includes(r.month));
  const dry = season.rows.filter((r: any) => [11, 12, 1, 2].includes(r.month));
  const avg = (rows: any[], k: string) => rows.reduce((s, r) => s + (r[k] || 0), 0) / Math.max(rows.length, 1);
  const moist = season.categories.includes("Description / Appearance") ? "Description / Appearance" : season.categories[0];

  const surv = survQ.data;
  const survFast = surv?.curves.filter((c: any) => c.median != null).sort((a: any, b: any) => a.median - b.median)[0];
  const sections: Section[] = [
    { id: "survival", title: "How long until a failing batch is caught", icon: <Timer size={16} />, subtitle: "Kaplan-Meier survival from manufacture to NSQ report", render: () => <Survival bare /> },
    { id: "shelf", title: "When in its shelf life a batch fails", icon: <CalendarRange size={16} />, subtitle: `${sl.with_dates.toLocaleString("en-IN")} alerts with both dates`, render: () => (
<div className="-m-5 md:-m-6 bg-white pt-2">
        <div className="grid gap-4 p-4 lg:grid-cols-[1.4fr_1fr]">
          <ResponsiveContainer width="100%" height={300}>
            <BarChart data={sl.rows} layout="vertical" margin={{ left: 40, right: 10 }} stackOffset="expand">
              <CartesianGrid horizontal={false} stroke="#eef2f7" />
              <XAxis type="number" tickFormatter={(v) => `${Math.round(v * 100)}%`} fontSize={11} />
              <YAxis type="category" dataKey="category" width={150} fontSize={11} />
              <Tooltip {...tip} formatter={(v: any) => `${v}%`} />
              <Legend wrapperStyle={{ fontSize: 11 }} />
              {sl.buckets.map((b: string, i: number) => <Bar key={b} dataKey={b} stackId="a" fill={LIFE_COLORS[i]} />)}
            </BarChart>
          </ResponsiveContainer>
          <div>
            <div className="label mb-2">Months from manufacture to report</div>
            <ResponsiveContainer width="100%" height={170}>
              <BarChart data={sl.lag_hist}><XAxis dataKey="months" fontSize={10} /><YAxis fontSize={10} width={30} /><Tooltip {...tip} /><Bar dataKey="alerts" fill="#6366f1" radius={[3, 3, 0, 0]} /></BarChart>
            </ResponsiveContainer>
            <div className="label mb-1 mt-3">Median age at failure by form (months)</div>
            <div className="flex flex-wrap gap-1.5">{sl.median_age_by_form.map((r: any) => <Badge key={r.name}>{r.name} · {r.months}</Badge>)}</div>
          </div>
        </div>
        <Takeaway>
          Most failures surface in the <b>second quarter</b> of shelf life, roughly 10 months after manufacture: post-market surveillance catches batches mid-life, not at release.
          {early && <> <b>{early.category}</b> has the largest early share ({early["first quarter"]}% in the first quarter), which points to a release or manufacturing defect rather than stability.</>}
          {mostLate && <> <b>{mostLate.category}</b> skews latest ({Math.round(lateShare(mostLate))}% in the last quarter or expired), which is a stability or packaging signal.</>}
          {sl.after_expiry > 0 && <> {sl.after_expiry} alerts were on batches already past expiry when tested.</>}
        </Takeaway>
      </div>
    ) },
    { id: "concentration", title: "A few manufacturers carry most of the problem", icon: <Users size={16} />, subtitle: `${d.spurious.alerts} spurious batches excluded`, render: () => (
<div className="-m-5 md:-m-6 bg-white pt-2">
          <div className="p-4">
            <ResponsiveContainer width="100%" height={220}>
              <BarChart data={conc}><XAxis dataKey="tier" fontSize={11} /><YAxis yAxisId="l" fontSize={10} width={36} /><YAxis yAxisId="r" orientation="right" fontSize={10} width={36} tickFormatter={(v) => `${v}%`} /><Tooltip {...tip} />
                <Legend wrapperStyle={{ fontSize: 11 }} /><Bar yAxisId="l" dataKey="manufacturers" fill="#94a3b8" radius={[3, 3, 0, 0]} /><Bar yAxisId="r" dataKey="alert_share" name="share of all alerts %" fill="#e11d48" radius={[3, 3, 0, 0]} /></BarChart>
            </ResponsiveContainer>
          </div>
          <Takeaway>
            {top && <><b>{top.manufacturers}</b> manufacturers with 10 or more alerts account for <b>{top.alert_share}%</b> of alerts attributable to a maker. </>}
            {d.repeat.repeat_share}% of alerts repeat the same product with the same failure at the same maker, so the corrective action didn't hold.
          </Takeaway>
          <div className="border-t border-line">
            <table className="w-full text-xs"><thead><tr className="bg-slate-50/70 text-left text-[10.5px] uppercase tracking-wider text-ink-muted"><th className="px-4 py-2">Manufacturer</th><th className="px-2 py-2">State</th><th className="px-2 py-2 text-right">Alerts</th><th className="px-2 py-2 text-right">Months flagged</th><th className="px-4 py-2 text-right">Repeats</th></tr></thead>
              <tbody>{d.repeat.top.map((r: any) => <tr key={r.manufacturer} className="border-t border-line/60"><td className="max-w-[220px] truncate px-4 py-1.5 font-medium" title={r.manufacturer}>{r.manufacturer}</td><td className="whitespace-nowrap px-2">{r.state}</td><td className="px-2 text-right tabular-nums">{r.alerts}</td><td className="px-2 text-right tabular-nums" title={`${r.first} → ${r.last}`}>{r.months}</td><td className="px-4 text-right tabular-nums">{r.repeat_alerts}</td></tr>)}</tbody></table>
          </div>
        </div>
    ) },
    { id: "hubs", title: "Manufacturing hubs", icon: <MapPin size={16} />, subtitle: "Alerts per PIN code — industrial clusters", render: () => (
<div className="-m-5 md:-m-6 bg-white pt-2">
          <div className="p-5"><RankBars rows={d.hubs.map((h: any) => ({ name: `${h.pin} ${h.city || h.state}`, count: h.alerts, sub: `${h.sites} sites · ${h.fda} FDA-reg.` }))} color="#6366f1" /></div>
          {hub && <Takeaway>PIN <b>{hub.pin}</b> ({hub.city || hub.state}) alone has <b>{hub.sites}</b> sites with alerts and {hub.alerts} alerts. Cluster-level interventions such as shared testing labs or state-led GMP audits reach many makers at once.</Takeaway>}
        </div>
    ) },
    { id: "spurious", title: "Spurious batches", icon: <ShieldAlert size={16} />, subtitle: "Kept out of every company ranking", render: () => (
<div className="-m-5 md:-m-6 bg-white pt-2">
        <div className="grid gap-5 p-5 md:grid-cols-3">
          <div><div className="label mb-2">Products</div><RankBars rows={d.spurious.products} color="#7c3aed" /></div>
          <div><div className="label mb-2">Therapeutic class</div><RankBars rows={d.spurious.drug_types} color="#7c3aed" /></div>
          <div><div className="label mb-2">Found by</div><RankBars rows={d.spurious.labs} color="#0ea5e9" /></div>
        </div>
        <Takeaway><b>{d.spurious.alerts}</b> alerts ({d.spurious.share}%) are spurious. Some are counterfeits of real brands; others are the label maker's own product spiked with an undeclared drug. Either way the named company is not a confirmed source, so they appear here and in the Ledger (Authenticity column) but not in rankings.</Takeaway>
      </div>
    ) },
    { id: "labs", title: "Does the testing lab change what is found?", icon: <FlaskConical size={16} />, subtitle: "CDSCO labs vs state labs", render: () => (
<div className="-m-5 md:-m-6 bg-white pt-2">
          <div className="p-4">
            <ResponsiveContainer width="100%" height={260}>
              <BarChart data={d.labs.mix} layout="vertical" margin={{ left: 40 }}><CartesianGrid horizontal={false} stroke="#eef2f7" /><XAxis type="number" fontSize={10} tickFormatter={(v) => `${v}%`} /><YAxis type="category" dataKey="category" width={150} fontSize={11} interval={0} /><Tooltip {...tip} /><Legend wrapperStyle={{ fontSize: 11 }} />
                <Bar dataKey="cdsco" name="CDSCO labs" fill="#0ea5e9" radius={[0, 3, 3, 0]} /><Bar dataKey="state" name="State labs" fill="#f59e0b" radius={[0, 3, 3, 0]} /></BarChart>
            </ResponsiveContainer>
          </div>
          <div className="border-t border-line">
            <table className="w-full text-xs"><thead><tr className="bg-slate-50/70 text-left text-[10.5px] uppercase tracking-wider text-ink-muted"><th className="px-4 py-2">Lab (≥ 40 alerts)</th><th className="px-2 py-2 text-right">Alerts</th><th className="px-4 py-2 text-right">Dissolution share</th></tr></thead>
              <tbody>{d.labs.top.map((r: any) => <tr key={r.lab} className="border-t border-line/60"><td className="px-4 py-1.5">{r.lab}</td><td className="px-2 text-right tabular-nums">{r.alerts}</td><td className="px-4 text-right tabular-nums">{r.dissolution_pct}%</td></tr>)}</tbody></table>
          </div>
          <Takeaway>Dissolution share varies widely between labs testing similar products. A lab with a very low share may lack dissolution capacity rather than be receiving better batches, which is worth checking before treating a region as "clean".</Takeaway>
        </div>
    ) },
    { id: "season", title: "Month of manufacture vs failure type", icon: <CloudRain size={16} />, subtitle: "Is there a monsoon effect?", render: () => (
<div className="-m-5 md:-m-6 bg-white pt-2">
          <div className="p-4">
            <ResponsiveContainer width="100%" height={260}>
              <LineChart data={season.rows.map((r: any) => ({ ...r, m: MONTHS[r.month - 1] }))}><CartesianGrid stroke="#eef2f7" /><XAxis dataKey="m" fontSize={11} /><YAxis fontSize={10} width={34} tickFormatter={(v) => `${v}%`} /><Tooltip {...tip} /><Legend wrapperStyle={{ fontSize: 11 }} />
                {season.categories.map((c: string, i: number) => <Line key={c} dataKey={c} stroke={LIFE_COLORS[i]} strokeWidth={2} dot={false} />)}</LineChart>
            </ResponsiveContainer>
          </div>
          <Takeaway>{moist}: {avg(mon, moist).toFixed(1)}% of alerts on batches made in the monsoon months (Jun–Sep) vs {avg(dry, moist).toFixed(1)}% in the dry months (Nov–Feb). {Math.abs(avg(mon, moist) - avg(dry, moist)) < 1.5
            ? "So far there is no meaningful seasonal effect: humidity during manufacture doesn't show up as a driver at national level. Filter by a hub or maker in the explorer to check locally."
            : "A gap this size points to humidity control during granulation, drying and packing."}</Takeaway>
        </div>
    ) },
    { id: "fda", title: "FDA-registered vs other sites", icon: <BadgeCheck size={16} />, subtitle: "NSQ record of FDA-registered sites", render: () => (
<div className="-m-5 md:-m-6 bg-white pt-2">
          <div className="grid grid-cols-2 gap-3 p-5 text-sm">
            {[["FDA-registered", reg], ["Not registered", non]].map(([label, p]: any) => (
              <div key={label} className="rounded-xl bg-slate-50 p-4">
                <div className="label">{label}</div>
                <div className="mt-1 font-display text-2xl font-extrabold">{p.sites?.toLocaleString("en-IN") ?? 0}<span className="ml-1 text-sm font-medium text-ink-muted">sites</span></div>
                <div className="text-xs text-ink-muted">{p.alerts_per_site ?? "—"} alerts per site · {p.injection_share ?? "—"}% injectables</div>
                <div className="mt-2 flex flex-wrap gap-1">{(p.top_categories ?? []).map((c: any) => <Badge key={c.name}>{c.name} {c.count}</Badge>)}</div>
              </div>
            ))}
          </div>
          <Takeaway>{reg.sites ? <>FDA-registered sites average <b>{reg.alerts_per_site}</b> alerts each against <b>{non.alerts_per_site}</b> for the rest. {d.fda_overlap.import_alert_companies.length} companies with Indian NSQ alerts also appear on FDA's Import Alert 66-40 red list. That's a company-name match: the listed facility may be a different plant of the same company.</> : "Fetch the FDA establishment registrations and Import Alert sources (Admin → Data pipelines) to fill this in."}</Takeaway>
          {d.fda_overlap.import_alert_companies.length > 0 && <div className="flex flex-wrap gap-1.5 px-5 pb-5">{d.fda_overlap.import_alert_companies.map((s: any) => <Badge key={s.company} tone="rose">{s.company} · {s.alerts} NSQ alerts · {s.sites} site{s.sites > 1 ? "s" : ""}</Badge>)}</div>}
        </div>
    ) },
    { id: "whitespace", title: "Export whitespace", icon: <Globe2 size={16} />, subtitle: "Made by many Indian firms, few Indian US ANDAs", render: () => (
<div className="-m-5 md:-m-6 bg-white pt-2">
          <div className="p-4">
            <ResponsiveContainer width="100%" height={250}>
              <ScatterChart margin={{ left: 0, right: 10 }}><CartesianGrid stroke="#eef2f7" /><XAxis type="number" dataKey="indian_makers" name="Indian makers (NSQ)" fontSize={10} /><YAxis type="number" dataKey="indian_anda_holders" name="Indian US-ANDA holders" fontSize={10} width={30} /><ZAxis type="number" dataKey="anda_active" range={[40, 400]} name="Active ANDAs" />
                <Tooltip {...tip} cursor={{ strokeDasharray: "3 3" }} formatter={(v: any, n: any) => [v, n]} labelFormatter={() => ""} content={({ payload }: any) => payload?.[0] ? <div className="rounded-lg bg-night-900 px-2.5 py-1.5 text-[11px] text-white"><b>{payload[0].payload.name}</b><br />{payload[0].payload.indian_makers} Indian makers · {payload[0].payload.indian_anda_holders} Indian ANDA holders · {payload[0].payload.anda_active} active ANDAs</div> : null} />
                <Scatter data={d.whitespace} fill="#10b996" /></ScatterChart>
            </ResponsiveContainer>
          </div>
          {ws && <Takeaway><b>{ws.name}</b> is made by at least {ws.indian_makers} Indian manufacturers (counting only those with NSQ alerts), but only {ws.indian_anda_holders} Indian firm{ws.indian_anda_holders === 1 ? "" : "s"} hold{ws.indian_anda_holders === 1 ? "s" : ""} a US ANDA for it. That's a large domestic base with little US export presence; the constraint is quality (US-grade GMP), not know-how.</Takeaway>}
        </div>
    ) },
  ];
  const tiles: { id: string; accent: string; figure: React.ReactNode; label: React.ReactNode; text: React.ReactNode }[] = [
    { id: "survival", accent: "#10b996", figure: survFast ? `${survFast.median} m` : "…", label: survFast ? `half of ${survFast.group} failures caught` : "median time to detection", text: surv?.logrank ? `Log-rank p = ${surv.logrank.p} across dosage forms.` : "Kaplan-Meier curves by form, category, lab or state." },
    { id: "shelf", accent: "#6366f1", figure: "Q2", label: "of shelf life — when most failures surface", text: <>{early ? <><b>{early.category}</b> fails earliest; </> : null}{mostLate ? <><b>{mostLate.category}</b> skews latest.</> : null}</> },
    { id: "concentration", accent: "#e11d48", figure: top ? `${top.alert_share}%` : "—", label: top ? `of alerts from ${top.manufacturers} makers with 10+` : "alert concentration", text: `${d.repeat.repeat_share}% of alerts repeat the same product and failure at the same maker.` },
    { id: "hubs", accent: "#6366f1", figure: hub ? hub.pin : "—", label: hub ? `${hub.city || hub.state} · ${hub.sites} sites, ${hub.alerts} alerts` : "top hub", text: "Cluster-level fixes (shared labs, state GMP audits) reach many makers at once." },
    { id: "spurious", accent: "#7c3aed", figure: `${d.spurious.share}%`, label: `${d.spurious.alerts} spurious alerts`, text: "Counterfeits or spiked products — the named company is not a confirmed source." },
    { id: "labs", accent: "#0ea5e9", figure: `${d.labs.top.length}`, label: "labs with 40+ alerts compared", text: "Dissolution share varies widely between labs testing similar products." },
    { id: "season", accent: "#f59e0b", figure: `${Math.abs(avg(mon, moist) - avg(dry, moist)).toFixed(1)} pt`, label: `${moist}: monsoon vs dry-month gap`, text: Math.abs(avg(mon, moist) - avg(dry, moist)) < 1.5 ? "No meaningful seasonal effect at national level." : "A gap this size points to humidity control." },
    { id: "fda", accent: "#0ea5e9", figure: reg.sites ? `${reg.alerts_per_site} vs ${non.alerts_per_site}` : "—", label: "alerts per site: FDA-registered vs others", text: `${d.fda_overlap.import_alert_companies.length} companies also on FDA Import Alert 66-40.` },
    { id: "whitespace", accent: "#10b996", figure: ws ? ws.name : "—", label: ws ? `${ws.indian_makers} Indian makers · ${ws.indian_anda_holders} US ANDA holders` : "", text: "Large domestic base, little US export presence." },
  ];

  return (
    <ExpandedProvider sections={sections} active={active} onActive={setActive} title="Insights" subtitle="Patterns the raw alerts don't show">
      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
        {tiles.map((t) => {
          const sec = sections.find((x) => x.id === t.id)!;
          return (
            <Tile key={t.id} id={t.id} title={sec.title} icon={sec.icon} accent={t.accent}>
              <div className="font-display text-2xl font-extrabold tracking-tight" style={{ color: t.accent }}>{t.figure}</div>
              <div className="text-xs text-ink-muted">{t.label}</div>
              <p className="mt-2 line-clamp-3 text-[12.5px] leading-relaxed text-ink-soft">{t.text}</p>
            </Tile>
          );
        })}
      </div>
    </ExpandedProvider>
  );
}
