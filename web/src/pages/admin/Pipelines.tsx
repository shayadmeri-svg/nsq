import { useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowRight, CalendarClock, CheckCircle2, Database, ExternalLink, Factory, FlaskConical, Layers, Play, Radio, RefreshCw, TerminalSquare, TriangleAlert, WifiOff } from "lucide-react";
import { motion } from "motion/react";
import { useState } from "react";
import { Link } from "react-router-dom";
import { LogViewer, RunModal, STATUS, UploadButton } from "../../components/jobs";
import { Badge, Button, Card, CardHeader, ErrorNote, PageHeader, PageSkeleton, Stat } from "../../components/ui";
import { useToast } from "../../components/ui/toast";
import { api, put } from "../../lib/api";
import { cn } from "../../lib/cn";
import { timeAgo } from "../../lib/format";

const SRC_STATUS: Record<string, { tone: any; label: string; icon: JSX.Element }> = {
  ok: { tone: "brand", label: "fresh", icon: <CheckCircle2 size={12} /> },
  unchanged: { tone: "brand", label: "unchanged", icon: <CheckCircle2 size={12} /> },
  unreachable: { tone: "amber", label: "unreachable", icon: <WifiOff size={12} /> },
  error: { tone: "rose", label: "error", icon: <TriangleAlert size={12} /> },
  never: { tone: "slate", label: "not fetched", icon: <Radio size={12} /> },
};
const DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];

export function timeUntil(iso?: string | null) {
  if (!iso) return "—";
  const s = (new Date(iso).getTime() - Date.now()) / 1000;
  if (s <= 60) return "due now";
  if (s < 3600) return `in ${Math.round(s / 60)} min`;
  if (s < 86400) return `in ${Math.round(s / 3600)} h`;
  return `in ${Math.round(s / 86400)} d`;
}

function Toggle({ on, onChange, disabled }: { on: boolean; onChange: (v: boolean) => void; disabled?: boolean }) {
  return (
    <button type="button" disabled={disabled} onClick={() => onChange(!on)} aria-pressed={on}
      className={cn("relative h-5 w-9 shrink-0 rounded-full transition-colors disabled:opacity-40", on ? "bg-brand-600" : "bg-slate-300")}>
      <motion.span layout transition={{ type: "spring", stiffness: 500, damping: 32 }} className={cn("absolute top-0.5 h-4 w-4 rounded-full bg-white shadow", on ? "right-0.5" : "left-0.5")} />
    </button>
  );
}

export function ScheduleEditor({ s, canEdit, compact }: { s: any; canEdit: boolean; compact?: boolean }) {
  const qc = useQueryClient();
  const toast = useToast();
  const [busy, setBusy] = useState(false);
  if (!s) return <span className="text-xs text-ink-faint">not schedulable</span>;
  const save = async (patch: any) => {
    setBusy(true);
    try {
      await put(`/api/pipelines/schedules/${s.job_key}`, { ...s, ...patch });
      qc.invalidateQueries({ queryKey: ["pipelines"] });
    } catch (e) {
      toast((e as Error).message, "error");
    } finally {
      setBusy(false);
    }
  };
  const time = `${String(s.hour).padStart(2, "0")}:${String(s.minute).padStart(2, "0")}`;
  return (
    <div className={cn("flex flex-wrap items-center gap-2 text-xs", busy && "opacity-60")}>
      <Toggle on={s.enabled} disabled={!canEdit || busy} onChange={(v) => save({ enabled: v })} />
      <select disabled={!canEdit} value={s.frequency} onChange={(e) => save({ frequency: e.target.value })} className="h-7 rounded-lg border border-line bg-white px-1.5 text-xs">
        <option value="daily">daily</option><option value="weekly">weekly</option><option value="monthly">monthly</option>
      </select>
      {s.frequency === "weekly" && (
        <select disabled={!canEdit} value={s.weekday} onChange={(e) => save({ weekday: Number(e.target.value) })} className="h-7 rounded-lg border border-line bg-white px-1.5 text-xs">
          {DAYS.map((d, i) => <option key={d} value={i}>{d}</option>)}
        </select>
      )}
      {s.frequency === "monthly" && (
        <select disabled={!canEdit} value={s.day} onChange={(e) => save({ day: Number(e.target.value) })} className="h-7 rounded-lg border border-line bg-white px-1.5 text-xs">
          {Array.from({ length: 28 }, (_, i) => <option key={i} value={i + 1}>day {i + 1}</option>)}
        </select>
      )}
      <input type="time" disabled={!canEdit} value={time} onChange={(e) => { const [h, m] = e.target.value.split(":").map(Number); if (!Number.isNaN(h)) save({ hour: h, minute: m }); }}
        className="h-7 rounded-lg border border-line bg-white px-1.5 text-xs" />
      {!compact && <span className="text-ink-muted">{s.enabled ? <>next {timeUntil(s.next_run_at)}</> : "paused"}</span>}
    </div>
  );
}

// Sources → normalise → build → Redis → dashboards, with packets flowing along the wires.
function Wire({ active, delay = 0 }: { active: boolean; delay?: number }) {
  return (
    <div className="relative hidden h-0.5 flex-1 self-center overflow-hidden rounded-full bg-slate-200 lg:block">
      {active && [0, 1, 2].map((i) => (
        <motion.span key={i} className="absolute top-1/2 h-1.5 w-6 -translate-y-1/2 rounded-full bg-gradient-to-r from-transparent via-brand-500 to-transparent"
          initial={{ left: "-15%" }} animate={{ left: "115%" }} transition={{ duration: 2.4, repeat: Infinity, delay: delay + i * 0.8, ease: "linear" }} />
      ))}
    </div>
  );
}

function Node({ icon, title, children, tone = "slate", delay = 0 }: { icon: JSX.Element; title: string; children: React.ReactNode; tone?: string; delay?: number }) {
  return (
    <motion.div initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} transition={{ delay, duration: 0.4 }}
      className="w-full rounded-2xl border border-line bg-white p-3.5 shadow-card lg:w-auto lg:min-w-[150px]">
      <div className="flex items-center gap-2 text-[13px] font-semibold"><span className={cn("grid h-7 w-7 place-items-center rounded-lg", tone)}>{icon}</span>{title}</div>
      <div className="mt-2 text-[11.5px] leading-relaxed text-ink-muted">{children}</div>
    </motion.div>
  );
}

function Flow({ data }: { data: any }) {
  const ok = data.sources.filter((s: any) => s.status === "ok" || s.status === "unchanged").length;
  const c = data.universe.counts ?? {};
  const anyRunning = data.sources.some((s: any) => s.running) || data.pipelines.some((p: any) => p.running);
  return (
    <Card delay={0.05} className="p-5">
      <div className="mb-4 flex items-center justify-between">
        <div className="font-display text-[15px] font-bold">How data reaches the dashboards</div>
        {anyRunning && <Badge tone="indigo"><span className="h-2 w-2 animate-pulse rounded-full bg-indigo-500" /> pipeline running</Badge>}
      </div>
      <div className="flex flex-col items-stretch gap-3 lg:flex-row lg:items-center">
        <Node icon={<Radio size={15} />} title="Public sources" tone="bg-sky-50 text-sky-600" delay={0}>
          {ok}/{data.sources.length} fetched · CDSCO, FDA, EMA, ClinicalTrials.gov
        </Node>
        <Wire active={anyRunning || ok > 0} />
        <Node icon={<Layers size={15} />} title="Normalised files" tone="bg-violet-50 text-violet-600" delay={0.08}>
          data/sources/*.json · raw downloads kept for audit
        </Node>
        <Wire active={anyRunning || ok > 0} delay={0.4} />
        <div className="flex flex-col gap-2">
          <Node icon={<FlaskConical size={15} />} title="Molecule universe" tone="bg-brand-50 text-brand-700" delay={0.16}>
            {c.molecules ?? 0} molecules · {c.curated ?? 0} curated · {c.auto ?? 0} auto · {c.manual ?? 0} watchlist
          </Node>
          <Node icon={<Factory size={15} />} title="Site directory" tone="bg-amber-50 text-amber-700" delay={0.2}>
            {(data.sites?.sites ?? 0).toLocaleString("en-IN")} sites · {data.sites?.fda_registered ?? 0} FDA-registered
          </Node>
        </div>
        <Wire active={true} delay={0.8} />
        <Node icon={<Database size={15} />} title="Redis → dashboards" tone="bg-slate-100 text-slate-700" delay={0.24}>
          Opportunities, EU route, infrastructure, explorer
        </Node>
      </div>
    </Card>
  );
}

export function Pipelines() {
  const { data, isLoading, error } = useQuery({ queryKey: ["pipelines"], queryFn: () => api<any>("/api/pipelines"), refetchInterval: 8_000 });
  const jobsQ = useQuery({ queryKey: ["jobs"], queryFn: () => api<any>("/api/jobs") });
  const [picked, setPicked] = useState<any | null>(null);
  const [viewing, setViewing] = useState<number | undefined>();
  const [openErr, setOpenErr] = useState<string | null>(null);
  const qc = useQueryClient();
  if (isLoading) return <PageSkeleton />;
  if (error) return <ErrorNote error={error} />;
  const jobByKey = Object.fromEntries((jobsQ.data?.jobs ?? []).map((j: any) => [j.key, j]));
  const canEdit = (job?: any) => !!job && (data.is_super || job.role === "admin");
  const ok = data.sources.filter((s: any) => s.status === "ok" || s.status === "unchanged").length;
  const nextRun = data.schedules.filter((s: any) => s.enabled && s.next_run_at).sort((a: any, b: any) => a.next_run_at.localeCompare(b.next_run_at))[0];
  const c = data.universe.counts ?? {};
  const open = (key: string) => jobByKey[key] && setPicked(jobByKey[key]);

  return (
    <>
      <PageHeader eyebrow="Platform" title="Data pipelines"
        subtitle={<>Public sources feed the molecule universe and the site directory. Schedules run inside the API ({data.scheduler.tz}); a source that is down is skipped and the rest still load.</>}
        actions={<>{data.is_super && <UploadButton label="Upload a source file" hint="pick it in the source's 'uploaded file' field" />}
          <Button disabled={!jobByKey["sync-sources"] || jobByKey["sync-sources"]?.running} onClick={() => open("sync-sources")}><RefreshCw size={15} /> Sync all sources</Button></>} />

      <div className="grid grid-cols-2 gap-4 xl:grid-cols-4">
        <Stat label="Molecules tracked" value={c.molecules ?? 0} icon={<FlaskConical size={18} />} hint={<Link to="/admin/molecules" className="hover:underline">{c.curated ?? 0} curated · {c.auto ?? 0} auto · {c.manual ?? 0} watchlist →</Link>} />
        <Stat label="Manufacturing sites" value={data.sites?.sites ?? 0} icon={<Factory size={18} />} tone="amber" delay={0.05} hint={<Link to="/admin/sites" className="hover:underline">{data.sites?.fda_registered ?? 0} FDA-registered · {data.sites?.import_alert ?? 0} on import alert →</Link>} />
        <Stat label="Sources healthy" value={ok} suffix={` / ${data.sources.length}`} icon={<Radio size={18} />} tone="indigo" delay={0.1} hint={`universe built ${timeAgo(data.universe.built_at)}`} />
        <Stat label="Scheduled jobs" value={data.schedules.filter((x: any) => x.enabled).length} icon={<CalendarClock size={18} />} tone="rose" delay={0.15}
          hint={nextRun ? `next: ${data.schedulable[nextRun.job_key] ?? nextRun.job_key} ${timeUntil(nextRun.next_run_at)}` : "nothing scheduled"} />
      </div>

      <div className="mt-5"><Flow data={data} /></div>

      <div className="mt-5 grid gap-4 lg:grid-cols-3">
        {data.pipelines.map((p: any, i: number) => {
          const job = jobByKey[p.key];
          const st = p.last_run?.status;
          return (
            <Card key={p.key} delay={0.1 + i * 0.05} className="flex flex-col p-5">
              <div className="flex items-start justify-between gap-2">
                <div className="font-display text-[15px] font-bold">{p.title}</div>
                {p.running ? <Badge tone="indigo"><span className="h-2 w-2 animate-pulse rounded-full bg-indigo-500" /> running</Badge> : st && <button onClick={() => setViewing(p.last_run.id)}><Badge tone={STATUS[st]?.tone ?? "slate"}>{STATUS[st]?.icon}{st}</Badge></button>}
              </div>
              <p className="mt-1.5 flex-1 text-[12.5px] leading-relaxed text-ink-muted">{p.description}</p>
              <div className="mt-3 rounded-xl bg-slate-50 p-2.5"><ScheduleEditor s={p.schedule} canEdit={canEdit(job)} /></div>
              <div className="mt-3 flex items-center justify-between text-xs text-ink-muted">
                <span>{p.last_run ? <>last run {timeAgo(p.last_run.created_at)} by {p.last_run.by}</> : "never run"}</span>
                <Button size="sm" className="shrink-0 whitespace-nowrap" disabled={!job || !job.allowed || p.running} onClick={() => open(p.key)}><Play size={13} /> Run now</Button>
              </div>
            </Card>
          );
        })}
      </div>

      <Card delay={0.2} className="mt-5">
        <CardHeader icon={<Radio size={16} />} title="Sources" subtitle="Each writes a normalised file; the molecule sources rebuild the universe after fetching. If the server cannot reach a source, upload its file and run the source with it." />
        <div className="mt-3 overflow-x-auto">
          <table className="w-full text-sm">
            <thead><tr className="border-y border-line bg-slate-50/70 text-left text-[11px] font-semibold uppercase tracking-wider text-ink-muted">
              <th className="px-5 py-2.5">Source</th><th className="px-3 py-2.5">Feeds</th><th className="px-3 py-2.5">Status</th><th className="px-3 py-2.5 text-right">Records</th><th className="px-3 py-2.5">Schedule</th><th className="px-5 py-2.5 text-right" />
            </tr></thead>
            <tbody>
              {data.sources.map((s: any) => {
                const st = SRC_STATUS[s.status] ?? SRC_STATUS.never;
                const job = jobByKey[s.job];
                const stale = s.age_days != null && s.age_days > 35;
                return (
                  <tr key={s.key} className="border-b border-line/70 align-top">
                    <td className="px-5 py-3">
                      <div className="flex items-center gap-1.5 font-semibold">{s.title}<a href={s.page} target="_blank" rel="noreferrer" className="text-ink-faint hover:text-brand-700"><ExternalLink size={12} /></a></div>
                      <div className="text-[11px] text-ink-muted">{s.publisher} · {s.cadence}</div>
                    </td>
                    <td className="px-3 py-3"><div className="flex max-w-[260px] flex-wrap gap-1">{(s.feeds ?? []).map((f: string) => <span key={f} className="rounded-md bg-slate-100 px-1.5 py-0.5 text-[10.5px] text-ink-soft">{f}</span>)}</div></td>
                    <td className="px-3 py-3">
                      <button onClick={() => s.error && setOpenErr(openErr === s.key ? null : s.key)} className="text-left">
                        <Badge tone={stale && st.tone === "brand" ? "amber" : st.tone}>{s.running ? <span className="h-2 w-2 animate-pulse rounded-full bg-indigo-500" /> : st.icon}{s.running ? "running" : stale ? "stale" : st.label}</Badge>
                        <div className="mt-1 text-[11px] text-ink-muted">{s.last_success ? `updated ${timeAgo(s.last_success)}` : s.last_attempt ? `tried ${timeAgo(s.last_attempt)}` : "—"}</div>
                      </button>
                      {openErr === s.key && <div className="mt-1.5 max-w-[280px] rounded-lg bg-rose-50 p-2 font-mono text-[10.5px] text-rose-800">{s.error}</div>}
                    </td>
                    <td className="px-3 py-3 text-right font-semibold tabular-nums">{s.records != null ? Number(s.records).toLocaleString("en-IN") : "—"}</td>
                    <td className="px-3 py-3"><ScheduleEditor s={s.schedule} canEdit={canEdit(job)} compact /></td>
                    <td className="px-5 py-3 text-right">
                      <div className="flex justify-end gap-1.5">
                        {s.last_run && <Button size="sm" variant="secondary" onClick={() => setViewing(s.last_run.id)} title="Last log"><TerminalSquare size={13} /></Button>}
                        <Button size="sm" disabled={!job || !job.allowed || s.running} onClick={() => open(s.job)}><Play size={13} /> Run</Button>
                      </div>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </Card>

      <div className="mt-5 grid gap-4 md:grid-cols-2">
        <Link to="/admin/molecules"><Card delay={0.25} className="group flex items-center justify-between p-5 transition hover:shadow-lift">
          <div><div className="font-display text-[15px] font-bold">Molecule universe</div><div className="text-xs text-ink-muted">Browse every tracked molecule, what each source says, and manage the watchlist.</div></div>
          <ArrowRight size={18} className="text-ink-faint transition group-hover:translate-x-1 group-hover:text-brand-700" />
        </Card></Link>
        <Link to="/admin/sites"><Card delay={0.3} className="group flex items-center justify-between p-5 transition hover:shadow-lift">
          <div><div className="font-display text-[15px] font-bold">Site directory</div><div className="text-xs text-ink-muted">Every Indian site named in NSQ alerts, joined with FDA records — add one to an organisation as a plant.</div></div>
          <ArrowRight size={18} className="text-ink-faint transition group-hover:translate-x-1 group-hover:text-brand-700" />
        </Card></Link>
      </div>

      <RunModal job={picked} onClose={() => setPicked(null)} onStarted={(id) => { setViewing(id); qc.invalidateQueries({ queryKey: ["pipelines"] }); qc.invalidateQueries({ queryKey: ["jobs"] }); }} />
      <LogViewer runId={viewing} onClose={() => setViewing(undefined)} />
    </>
  );
}
