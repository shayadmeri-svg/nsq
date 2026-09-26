import { useQuery } from "@tanstack/react-query";
import { Lightbulb } from "lucide-react";
import { Bar, BarChart, CartesianGrid, Legend, Line, LineChart, ResponsiveContainer, Scatter, ScatterChart, Tooltip, XAxis, YAxis, ZAxis } from "recharts";
import { RankBars } from "../../components/charts";
import { Badge, Card, CardHeader, ErrorNote, PageSkeleton } from "../../components/ui";
import { api } from "../../lib/api";

const LIFE_COLORS = ["#10b996", "#6366f1", "#f59e0b", "#e11d48", "#0f172a"];
const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

function Takeaway({ children }: { children: React.ReactNode }) {
  return <div className="mx-5 mb-4 flex gap-2 rounded-xl bg-amber-50 p-3 text-[12.5px] leading-relaxed text-amber-900 ring-1 ring-inset ring-amber-200"><Lightbulb size={15} className="mt-0.5 shrink-0" /><div>{children}</div></div>;
}
const tip = { contentStyle: { borderRadius: 10, fontSize: 12 } };

export function InsightsTab() {
  const { data: d, isLoading, error } = useQuery({ queryKey: ["pg-insights"], queryFn: () => api<any>("/api/playground/insights"), staleTime: 300_000 });
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

  return (
    <div className="space-y-5">
      <Card>
        <CardHeader title="When in its shelf life does a batch fail?" subtitle={`Months from manufacture to the NSQ report, as a share of the labelled shelf life — ${sl.with_dates.toLocaleString("en-IN")} alerts with both dates`} />
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
      </Card>

      <div className="grid gap-5 xl:grid-cols-2">
        <Card>
          <CardHeader title="A few manufacturers carry most of the problem" subtitle="Manufacturers grouped by how many alerts they have" />
          <div className="p-4">
            <ResponsiveContainer width="100%" height={220}>
              <BarChart data={conc}><XAxis dataKey="tier" fontSize={11} /><YAxis yAxisId="l" fontSize={10} width={36} /><YAxis yAxisId="r" orientation="right" fontSize={10} width={36} tickFormatter={(v) => `${v}%`} /><Tooltip {...tip} />
                <Legend wrapperStyle={{ fontSize: 11 }} /><Bar yAxisId="l" dataKey="manufacturers" fill="#94a3b8" radius={[3, 3, 0, 0]} /><Bar yAxisId="r" dataKey="alert_share" name="share of all alerts %" fill="#e11d48" radius={[3, 3, 0, 0]} /></BarChart>
            </ResponsiveContainer>
          </div>
          <Takeaway>
            {top && <><b>{top.manufacturers}</b> manufacturers with 10 or more alerts account for <b>{top.alert_share}%</b> of all NSQ alerts. </>}
            {d.repeat.repeat_share}% of alerts repeat the same product with the same failure at the same maker, so the corrective action didn't hold.
          </Takeaway>
          <div className="max-h-72 overflow-auto border-t border-line scrollbar-thin">
            <table className="w-full text-xs"><thead><tr className="bg-slate-50/70 text-left text-[10.5px] uppercase tracking-wider text-ink-muted"><th className="px-4 py-2">Manufacturer</th><th className="px-2 py-2">State</th><th className="px-2 py-2 text-right">Alerts</th><th className="px-2 py-2 text-right">Months flagged</th><th className="px-4 py-2 text-right">Repeats</th></tr></thead>
              <tbody>{d.repeat.top.map((r: any) => <tr key={r.manufacturer} className="border-t border-line/60"><td className="max-w-[220px] truncate px-4 py-1.5 font-medium" title={r.manufacturer}>{r.manufacturer}</td><td className="whitespace-nowrap px-2">{r.state}</td><td className="px-2 text-right tabular-nums">{r.alerts}</td><td className="px-2 text-right tabular-nums" title={`${r.first} → ${r.last}`}>{r.months}</td><td className="px-4 text-right tabular-nums">{r.repeat_alerts}</td></tr>)}</tbody></table>
          </div>
        </Card>

        <Card>
          <CardHeader title="Manufacturing hubs" subtitle="Alerts per PIN code — industrial clusters" />
          <div className="p-5"><RankBars rows={d.hubs.map((h: any) => ({ name: `${h.pin} ${h.city || h.state}`, count: h.alerts, sub: `${h.sites} sites · ${h.fda} FDA-reg.` }))} color="#6366f1" /></div>
          {hub && <Takeaway>PIN <b>{hub.pin}</b> ({hub.city || hub.state}) alone has <b>{hub.sites}</b> sites with alerts and {hub.alerts} alerts. Cluster-level interventions such as shared testing labs or state-led GMP audits reach many makers at once.</Takeaway>}
        </Card>
      </div>

      <div className="grid gap-5 xl:grid-cols-2">
        <Card>
          <CardHeader title="Does the testing lab change what is found?" subtitle="Failure mix: CDSCO labs vs state labs (share of each lab type's alerts)" />
          <div className="p-4">
            <ResponsiveContainer width="100%" height={260}>
              <BarChart data={d.labs.mix} layout="vertical" margin={{ left: 40 }}><CartesianGrid horizontal={false} stroke="#eef2f7" /><XAxis type="number" fontSize={10} tickFormatter={(v) => `${v}%`} /><YAxis type="category" dataKey="category" width={150} fontSize={11} interval={0} /><Tooltip {...tip} /><Legend wrapperStyle={{ fontSize: 11 }} />
                <Bar dataKey="cdsco" name="CDSCO labs" fill="#0ea5e9" radius={[0, 3, 3, 0]} /><Bar dataKey="state" name="State labs" fill="#f59e0b" radius={[0, 3, 3, 0]} /></BarChart>
            </ResponsiveContainer>
          </div>
          <div className="max-h-56 overflow-auto border-t border-line scrollbar-thin">
            <table className="w-full text-xs"><thead><tr className="bg-slate-50/70 text-left text-[10.5px] uppercase tracking-wider text-ink-muted"><th className="px-4 py-2">Lab (≥ 40 alerts)</th><th className="px-2 py-2 text-right">Alerts</th><th className="px-4 py-2 text-right">Dissolution share</th></tr></thead>
              <tbody>{d.labs.top.map((r: any) => <tr key={r.lab} className="border-t border-line/60"><td className="px-4 py-1.5">{r.lab}</td><td className="px-2 text-right tabular-nums">{r.alerts}</td><td className="px-4 text-right tabular-nums">{r.dissolution_pct}%</td></tr>)}</tbody></table>
          </div>
          <Takeaway>Dissolution share varies widely between labs testing similar products. A lab with a very low share may lack dissolution capacity rather than be receiving better batches, which is worth checking before treating a region as "clean".</Takeaway>
        </Card>

        <Card>
          <CardHeader title="Month of manufacture vs failure type" subtitle="Share of alerts in each failure category, by the month the batch was made" />
          <div className="p-4">
            <ResponsiveContainer width="100%" height={260}>
              <LineChart data={season.rows.map((r: any) => ({ ...r, m: MONTHS[r.month - 1] }))}><CartesianGrid stroke="#eef2f7" /><XAxis dataKey="m" fontSize={11} /><YAxis fontSize={10} width={34} tickFormatter={(v) => `${v}%`} /><Tooltip {...tip} /><Legend wrapperStyle={{ fontSize: 11 }} />
                {season.categories.map((c: string, i: number) => <Line key={c} dataKey={c} stroke={LIFE_COLORS[i]} strokeWidth={2} dot={false} />)}</LineChart>
            </ResponsiveContainer>
          </div>
          <Takeaway>{moist}: {avg(mon, moist).toFixed(1)}% of alerts on batches made in the monsoon months (Jun–Sep) vs {avg(dry, moist).toFixed(1)}% in the dry months (Nov–Feb). {Math.abs(avg(mon, moist) - avg(dry, moist)) < 1.5
            ? "So far there is no meaningful seasonal effect: humidity during manufacture doesn't show up as a driver at national level. Filter by a hub or maker in the explorer to check locally."
            : "A gap this size points to humidity control during granulation, drying and packing."}</Takeaway>
        </Card>
      </div>

      <div className="grid gap-5 xl:grid-cols-2">
        <Card>
          <CardHeader title="FDA-registered vs other sites" subtitle="NSQ record of sites that also hold an FDA establishment registration" />
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
        </Card>

        <Card>
          <CardHeader title="Export whitespace" subtitle="Off-patent in the US, made by many Indian firms (lower bound: those with NSQ alerts), few Indian US-ANDA holders (Orange Book)" />
          <div className="p-4">
            <ResponsiveContainer width="100%" height={250}>
              <ScatterChart margin={{ left: 0, right: 10 }}><CartesianGrid stroke="#eef2f7" /><XAxis type="number" dataKey="indian_makers" name="Indian makers (NSQ)" fontSize={10} /><YAxis type="number" dataKey="indian_anda_holders" name="Indian US-ANDA holders" fontSize={10} width={30} /><ZAxis type="number" dataKey="anda_active" range={[40, 400]} name="Active ANDAs" />
                <Tooltip {...tip} cursor={{ strokeDasharray: "3 3" }} formatter={(v: any, n: any) => [v, n]} labelFormatter={() => ""} content={({ payload }: any) => payload?.[0] ? <div className="rounded-lg bg-night-900 px-2.5 py-1.5 text-[11px] text-white"><b>{payload[0].payload.name}</b><br />{payload[0].payload.indian_makers} Indian makers · {payload[0].payload.indian_anda_holders} Indian ANDA holders · {payload[0].payload.anda_active} active ANDAs</div> : null} />
                <Scatter data={d.whitespace} fill="#10b996" /></ScatterChart>
            </ResponsiveContainer>
          </div>
          {ws && <Takeaway><b>{ws.name}</b> is made by at least {ws.indian_makers} Indian manufacturers (counting only those with NSQ alerts), but only {ws.indian_anda_holders} Indian firm{ws.indian_anda_holders === 1 ? "" : "s"} hold{ws.indian_anda_holders === 1 ? "s" : ""} a US ANDA for it. That's a large domestic base with little US export presence; the constraint is quality (US-grade GMP), not know-how.</Takeaway>}
        </Card>
      </div>
    </div>
  );
}
