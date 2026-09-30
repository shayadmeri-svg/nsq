// Data jobs: every data recipe the server can run, and every public source with the data we hold from it.
// Compact rows grouped by what they feed; the detail (data held, how to refresh, laptop commands, recent runs) opens in
// the expanded view.
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Beaker, ChevronDown, Copy, Database, Factory, FlaskConical, HeartPulse, Laptop, Lock, Pill, Play, Server, TerminalSquare, Workflow, Wrench } from "lucide-react";
import { useMemo, useState, type ReactNode } from "react";
import { LogViewer, ManualFileButton, RunModal, STATUS, UploadButton } from "../../components/jobs";
import { FullRefresh } from "./FullRefresh";
import { Badge, Button, Card, ErrorNote, PageHeader, PageSkeleton, Segmented } from "../../components/ui";
import { ExpandedProvider, Figure, Tile, useExpanded, type Section } from "../../components/ui/Expanded";
import { api } from "../../lib/api";
import { cn } from "../../lib/cn";
import { fmtDateTime, timeAgo } from "../../lib/format";

type Job = any;

// What each source feeds, so the list reads by purpose rather than by publisher.
const THEMES: { id: string; title: string; icon: ReactNode; keys: string[] }[] = [
  { id: "molecules", title: "Molecules, patents & filings", icon: <Pill size={15} />,
    keys: ["src-orange-book", "src-purple-book", "src-ema", "src-clinical-trials", "src-fda-dmf", "src-edqm-cep"] },
  { id: "plants", title: "Plants & inspections", icon: <Factory size={15} />,
    keys: ["plant-registry", "src-cdsco-plants", "src-eudragmdp", "src-fda-inspections", "src-fda-establishments", "src-fda-import-alerts", "src-fda-recalls", "src-cdsco-wc"] },
  { id: "chemistry", title: "Chemistry", icon: <FlaskConical size={15} />, keys: ["src-pubchem", "src-ord"] },
  { id: "health", title: "Health & trade", icon: <HeartPulse size={15} />, keys: ["src-nfhs", "src-idsp", "src-comtrade"] },
];
const PIPELINES = ["fetch-nsq", "sync-sources", "build-universe", "load-seeds", "refresh-nsq"];

const STATE: Record<string, { dot: string; label: string; tone: any }> = {
  ok: { dot: "bg-emerald-500", label: "up to date", tone: "brand" },
  stale: { dot: "bg-amber-500", label: "last refresh failed — older data in use", tone: "amber" },
  failing: { dot: "bg-rose-500", label: "failing, no data", tone: "rose" },
  missing: { dot: "bg-rose-300", label: "no data yet", tone: "slate" },
  idle: { dot: "bg-slate-300", label: "not run yet", tone: "slate" },
};

const mb = (b?: number) => (b == null ? "" : b >= 1e9 ? `${(b / 1e9).toFixed(1)} GB` : b >= 1e6 ? `${(b / 1e6).toFixed(1)} MB` : `${Math.max(1, Math.round(b / 1e3))} KB`);
const jobState = (j: Job) => (j.data ? j.data.state : j.last_run?.status === "failed" ? "failing" : j.last_run ? "ok" : "idle");
const attention = (j: Job) => ["stale", "failing", "missing"].includes(jobState(j)) || j.last_run?.status === "failed";

function dataLine(j: Job) {
  const d = j.data;
  if (!d) return j.last_run ? `last run ${timeAgo(j.last_run.created_at)}` : "never run";
  if (!d.file) return d.error ? `no data · ${d.error}` : "no data yet";
  return [d.records != null && `${Number(d.records).toLocaleString()} records`, d.pdfs != null && `${d.pdfs.toLocaleString()} PDFs`,
    d.last_success && `retrieved ${timeAgo(d.last_success)}`].filter(Boolean).join(" · ");
}

function Row({ j, onRun }: { j: Job; onRun: (j: Job) => void }) {
  const { open } = useExpanded();
  const st = STATE[jobState(j)];
  const run = j.last_run?.status;
  return (
    <div onClick={() => open(j.key)} className="group flex cursor-pointer items-center gap-3 border-b border-line/70 px-4 py-2.5 last:border-0 hover:bg-slate-50">
      <span className={cn("h-2 w-2 shrink-0 rounded-full", st.dot)} title={st.label} />
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-1.5 text-[13px] font-semibold text-ink">
          <span className="truncate">{j.title}</span>
          {j.role === "super_admin" && <Lock size={11} className="shrink-0 text-rose-500" />}
        </div>
        <div className={cn("truncate text-[11.5px]", j.data?.state === "stale" || j.data?.state === "failing" ? "text-amber-700" : "text-ink-muted")}>{dataLine(j)}</div>
      </div>
      {j.laptop ? <span title={`Laptop job: ${j.laptop.why}`} className="hidden shrink-0 items-center gap-1 rounded-md bg-violet-50 px-1.5 py-0.5 text-[10.5px] font-medium text-violet-700 sm:inline-flex"><Laptop size={11} /> laptop</span>
        : j.source ? <span className="hidden shrink-0 items-center gap-1 rounded-md bg-slate-100 px-1.5 py-0.5 text-[10.5px] font-medium text-ink-muted sm:inline-flex"><Server size={11} /> server</span> : null}
      {run && <span className="hidden shrink-0 md:inline"><Badge tone={STATUS[run]?.tone ?? "slate"}>{STATUS[run]?.icon}{run}</Badge></span>}
      <button onClick={(e) => { e.stopPropagation(); onRun(j); }} disabled={!j.allowed || !j.available || !!j.running}
        title={j.running ? "Running" : !j.allowed ? "Super admin only" : "Run on the server"}
        className="shrink-0 rounded-lg p-2 text-ink-muted transition hover:bg-brand-50 hover:text-brand-700 disabled:opacity-40">
        {j.running ? <span className="block h-2.5 w-2.5 animate-pulse rounded-full bg-indigo-500" /> : <Play size={14} />}
      </button>
    </div>
  );
}

function Group({ title, icon, jobs, onRun, note, collapsed }: { title: string; icon: ReactNode; jobs: Job[]; onRun: (j: Job) => void; note?: string; collapsed?: boolean }) {
  const [shut, setShut] = useState(!!collapsed);
  if (!jobs.length) return null;
  const bad = jobs.filter(attention).length;
  return (
    <Card className={cn("overflow-hidden", shut && "self-start")}>
      <button onClick={() => setShut(!shut)} className={cn("flex w-full items-center justify-between gap-2 px-4 py-3 text-left", !shut && "border-b border-line")}>
        <div className="flex items-center gap-2 font-display text-[14px] font-bold"><span className="text-ink-muted">{icon}</span>{title}</div>
        <span className="flex items-center gap-2 text-[11px] text-ink-muted">{bad ? <span className="text-amber-700">{bad} need attention</span> : "all good"} · {jobs.length}
          <ChevronDown size={14} className={cn("transition", shut && "-rotate-90")} /></span>
      </button>
      {!shut && note && <div className="border-b border-line bg-slate-50/60 px-4 py-2 text-[11px] text-ink-muted">{note}</div>}
      {!shut && jobs.map((j) => <Row key={j.key} j={j} onRun={onRun} />)}
    </Card>
  );
}

function Cmd({ children }: { children: string }) {
  return (
    <div className="group relative">
      <pre className="overflow-x-auto rounded-lg bg-night-900 px-3 py-2 text-[12px] text-slate-100">{children}</pre>
      <button onClick={() => navigator.clipboard?.writeText(children)} title="Copy" className="absolute right-2 top-1.5 rounded p-1 text-slate-400 opacity-0 transition hover:text-white group-hover:opacity-100"><Copy size={13} /></button>
    </div>
  );
}

function JobDetail({ j, onRun, onLog }: { j: Job; onRun: (j: Job) => void; onLog: (id: number) => void }) {
  const d = j.data;
  const st = STATE[jobState(j)];
  return (
    <div className="max-w-4xl space-y-5">
      <p className="text-sm leading-relaxed text-ink-soft">{j.description}</p>
      {d && (
        <div className="grid gap-3 sm:grid-cols-4">
          <div className="rounded-xl bg-white p-3 ring-1 ring-inset ring-line"><Figure value={d.records != null ? Number(d.records).toLocaleString() : "—"} label="records held" /></div>
          <div className="rounded-xl bg-white p-3 ring-1 ring-inset ring-line"><Figure value={d.last_success ? timeAgo(d.last_success) : "—"} label={d.last_success ? `retrieved ${fmtDateTime(d.last_success)}` : "never retrieved"} /></div>
          <div className="rounded-xl bg-white p-3 ring-1 ring-inset ring-line"><Figure value={d.file ? mb(d.file.bytes) : "—"} label={`sources/${j.source}.json`} /></div>
          <div className="rounded-xl bg-white p-3 ring-1 ring-inset ring-line">{d.pdfs != null ? <Figure value={d.pdfs.toLocaleString()} label="letters (PDF) on the server" /> : <Figure value={<Badge tone={st.tone}>{st.label}</Badge>} label="status" />}</div>
        </div>
      )}
      {d?.error && <div className="rounded-lg bg-amber-50 px-3 py-2 text-xs text-amber-900 ring-1 ring-inset ring-amber-200"><b>Last attempt {d.last_attempt ? fmtDateTime(d.last_attempt) : ""}:</b> {d.error}</div>}
      {j.manual && <ManualFileButton manual={j.manual} title={`${j.title} — providing the file`} onRunWithFile={() => onRun(j)} />}
      <div className="grid gap-4 md:grid-cols-2">
        <div className="rounded-xl bg-white p-4 ring-1 ring-inset ring-line">
          <div className="label mb-2 flex items-center gap-1.5"><Server size={12} /> Run on the server</div>
          <p className="text-xs text-ink-muted">{j.laptop ? "Usually refused or too heavy here — use the laptop route. You can still upload the file this job parses." : "Runs here with live logs."}
            {j.schedule ? ` Schedule: ${j.schedule.enabled ? "" : "off by default · "}${j.schedule.frequency} ${String(j.schedule.hour).padStart(2, "0")}:${String(j.schedule.minute).padStart(2, "0")} IST.` : ""}</p>
          {j.params?.length > 0 && <ul className="mt-2 space-y-0.5 text-[11.5px] text-ink-muted">{j.params.map((p: any) => <li key={p.name}>· {p.label}</li>)}</ul>}
          <Button className="mt-3" size="sm" disabled={!j.allowed || !j.available || !!j.running} onClick={() => onRun(j)}>
            {j.running ? "Running…" : <><Play size={13} /> Run</>}</Button>
          {j.role === "super_admin" && <div className="mt-2 flex items-center gap-1 text-[11px] text-rose-600"><Lock size={11} /> super admin, typed confirmation</div>}
        </div>
        {j.laptop ? (
          <div className="rounded-xl bg-white p-4 ring-1 ring-inset ring-line">
            <div className="label mb-2 flex items-center gap-1.5"><Laptop size={12} /> On your laptop (from the repo folder)</div>
            <p className="mb-2 text-xs text-ink-muted">{j.laptop.why}.</p>
            <div className="space-y-1.5"><Cmd>{j.laptop.fetch}</Cmd><Cmd>{j.laptop.push.replace("HOST KEY", "ec2-user@<server> ~/.ssh/<key>.pem")}</Cmd></div>
          </div>
        ) : (
          <div className="rounded-xl bg-white p-4 ring-1 ring-inset ring-line">
            <div className="label mb-2 flex items-center gap-1.5"><TerminalSquare size={12} /> Same thing from a terminal</div>
            <Cmd>{j.source ? `just fetch-source ${j.source}` : `just ${j.key}`}</Cmd>
          </div>
        )}
      </div>
      <div>
        <div className="label mb-2">Recent runs</div>
        {!j.recent_runs?.length ? <div className="text-xs text-ink-muted">Never run on the server{j.laptop ? " — laptop jobs don't show here; the data above is what the server holds." : "."}</div> : (
          <div className="overflow-hidden rounded-xl ring-1 ring-inset ring-line">{j.recent_runs.map((r: any) => (
            <button key={r.id} onClick={() => onLog(r.id)} className="flex w-full items-center gap-3 border-b border-line/70 bg-white px-3 py-2 text-left text-xs last:border-0 hover:bg-slate-50">
              <span className="font-mono text-ink-faint">#{r.id}</span><Badge tone={STATUS[r.status]?.tone ?? "slate"}>{STATUS[r.status]?.icon}{r.status}</Badge>
              <span className="text-ink-muted">{fmtDateTime(r.created_at)} · {r.by}</span>
              <span className="ml-auto text-ink-faint">{r.finished_at && r.started_at ? `${((new Date(r.finished_at).getTime() - new Date(r.started_at).getTime()) / 1000).toFixed(0)} s` : ""} · log →</span>
            </button>
          ))}</div>
        )}
      </div>
    </div>
  );
}

function History({ onLog }: { onLog: (id: number) => void }) {
  const runs = useQuery({ queryKey: ["runs"], queryFn: () => api<any>("/api/jobs/runs?size=50"), refetchInterval: 10_000 });
  return (
    <div className="-m-5 md:-m-6">
      <table className="w-full text-sm">
        <thead><tr className="border-b border-line bg-slate-50/70 text-left text-[11px] font-semibold uppercase tracking-wider text-ink-muted"><th className="px-5 py-2.5">#</th><th className="px-3 py-2.5">Job</th><th className="px-3 py-2.5">Status</th><th className="px-3 py-2.5">By</th><th className="px-3 py-2.5">Started</th><th className="px-5 py-2.5">Duration</th></tr></thead>
        <tbody>
          {runs.data?.items.map((r: any) => (
            <tr key={r.id} onClick={() => onLog(r.id)} className="cursor-pointer border-b border-line/70 bg-white hover:bg-slate-50">
              <td className="px-5 py-2 font-mono text-xs">{r.id}</td>
              <td className="px-3 py-2 font-mono text-xs">{r.job_key}</td>
              <td className="px-3 py-2"><Badge tone={STATUS[r.status]?.tone ?? "slate"}>{STATUS[r.status]?.icon}{r.status}</Badge></td>
              <td className="px-3 py-2 text-xs">{r.by}</td>
              <td className="px-3 py-2 text-xs text-ink-muted">{fmtDateTime(r.created_at)}</td>
              <td className="px-5 py-2 text-xs text-ink-muted">{r.finished_at && r.started_at ? `${((new Date(r.finished_at).getTime() - new Date(r.started_at).getTime()) / 1000).toFixed(1)} s` : "—"}</td>
            </tr>
          ))}
          {!runs.data?.items.length && <tr><td colSpan={6} className="px-5 py-6 text-center text-sm text-ink-muted">No runs yet.</td></tr>}
        </tbody>
      </table>
    </div>
  );
}

export function Jobs() {
  const { data, isLoading, error } = useQuery({ queryKey: ["jobs"], queryFn: () => api<any>("/api/jobs"), refetchInterval: 10_000 });
  const [picked, setPicked] = useState<Job | null>(null);
  const [viewing, setViewing] = useState<number | undefined>();
  const [active, setActive] = useState<string | null>(null);
  const [filter, setFilter] = useState<"all" | "attention" | "laptop">("all");
  const qc = useQueryClient();
  const jobs: Job[] = data?.jobs ?? [];
  const byKey = useMemo(() => Object.fromEntries(jobs.map((j) => [j.key, j])), [jobs]);
  const onLog = (id: number) => { setActive(null); setViewing(id); };
  const onRun = (j: Job) => { setActive(null); setPicked(j); };
  const ordered = useMemo(() => {
    const order = [...THEMES.flatMap((t) => t.keys), ...PIPELINES];
    return [...jobs].sort((a, b) => (order.indexOf(a.key) + 1 || 999) - (order.indexOf(b.key) + 1 || 999));
  }, [jobs]);
  const sections: Section[] = useMemo(() => [
    ...ordered.map((j) => ({ id: j.key, title: j.title, subtitle: dataLine(j), icon: <span className={cn("block h-2 w-2 rounded-full", STATE[jobState(j)].dot)} />,
      render: () => <JobDetail j={j} onRun={onRun} onLog={onLog} /> })),
    { id: "history", title: "Run history", subtitle: "Every run on the server, newest first — click one for its log", icon: <TerminalSquare size={15} />, render: () => <History onLog={onLog} /> },
  ], [ordered]);  // eslint-disable-line react-hooks/exhaustive-deps

  if (isLoading) return <PageSkeleton />;
  if (error) return <ErrorNote error={error} />;

  const sources = jobs.filter((j) => j.source);
  const held = sources.filter((j) => j.data?.file).length;
  const need = jobs.filter((j) => (j.source || PIPELINES.includes(j.key)) && attention(j));
  const laptop = sources.filter((j) => j.laptop);
  const running = jobs.filter((j) => j.running);
  const show = (keys: string[]) => keys.map((k) => byKey[k]).filter(Boolean)
    .filter((j) => filter === "all" || (filter === "attention" ? attention(j) : !!j.laptop));
  const placed = new Set([...THEMES.flatMap((t) => t.keys), ...PIPELINES, "full-refresh"]);
  const maintenance = jobs.filter((j) => !placed.has(j.key) && !j.source);
  const lastRun = jobs.map((j) => j.last_run).filter(Boolean).sort((a: any, b: any) => (b.created_at > a.created_at ? 1 : -1))[0];

  return (
    <ExpandedProvider sections={sections} active={active} onActive={setActive} title="Update & sources" subtitle={`${jobs.length} jobs · ${sources.length} sources`}>
      <PageHeader title="Update & sources" subtitle="Every public source with the data the server holds from it, and the recipes that refresh it. Click a row for details, laptop commands and logs."
        actions={data.is_super && <UploadButton hint="pick it in the job's file field" />} />

      <FullRefresh onRun={onRun} onLog={onLog} onRunSource={(src) => { const j = byKey[`src-${src.replace(/_/g, "-")}`]; if (j) onRun(j); }} />

      <div className="mb-5 grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <Tile title="Sources holding data" icon={<Database size={14} />} clickable={false}>
          <Figure value={`${held} / ${sources.length}`} label="with a file on the server" tone={held < sources.length ? "#b45309" : undefined} />
        </Tile>
        <Tile title="Need attention" icon={<Wrench size={14} />} clickable={false}
          action={need.length ? <button className="text-[11px] text-brand-700 hover:underline" onClick={() => setFilter("attention")}>show</button> : undefined}>
          <Figure value={need.length} label={need.length ? need.slice(0, 3).map((j) => j.title).join(", ") + (need.length > 3 ? "…" : "") : "everything has data"} tone={need.length ? "#e11d48" : "#0a9a7d"} />
        </Tile>
        <Tile title="Laptop jobs" icon={<Laptop size={14} />} clickable={false}
          action={<button className="text-[11px] text-brand-700 hover:underline" onClick={() => setFilter("laptop")}>show</button>}>
          <Figure value={laptop.length} label="sources the server can't fetch — run with just, then push" />
        </Tile>
        <Tile id="history" title="Runs" icon={<TerminalSquare size={14} />}>
          <Figure value={running.length ? `${running.length} running` : lastRun ? timeAgo(lastRun.created_at) : "—"}
            label={running.length ? running.map((j) => j.title).join(", ") : lastRun ? `last: ${lastRun.job_key} · ${lastRun.status}` : "no runs yet"} />
        </Tile>
      </div>

      <div className="mb-4 flex flex-wrap items-center gap-2">
        <Segmented value={filter} onChange={setFilter} options={[{ value: "all", label: "All" }, { value: "attention", label: `Needs attention (${need.length})` }, { value: "laptop", label: "Laptop jobs" }]} />
        <span className="ml-auto flex items-center gap-3 text-[11px] text-ink-muted">
          {Object.entries(STATE).map(([k, v]) => <span key={k} className="flex items-center gap-1"><span className={cn("h-2 w-2 rounded-full", v.dot)} />{v.label}</span>)}
        </span>
      </div>

      <div className="grid gap-4 xl:grid-cols-2">
        {THEMES.map((t) => <Group key={t.id} title={t.title} icon={t.icon} jobs={show(t.keys)} onRun={onRun} />)}
        {filter !== "laptop" && <Group title="Pipelines" icon={<Workflow size={15} />} jobs={show(PIPELINES)} onRun={onRun}
          note="Scheduled end-to-end runs: new CDSCO months (daily 06:30 IST) and every server-reachable source (daily 02:30 IST)." />}
        {filter === "all" && <Group title="Maintenance" icon={<Beaker size={15} />} jobs={maintenance} onRun={onRun} collapsed
          note="Redis health, Upstash sync, snapshots and reloads — run when something is off." />}
      </div>

      <RunModal job={picked} onClose={() => setPicked(null)} onStarted={(id) => { setViewing(id); qc.invalidateQueries({ queryKey: ["jobs"] }); qc.invalidateQueries({ queryKey: ["full-refresh-plan"] }); }} />
      <LogViewer runId={viewing} onClose={() => setViewing(undefined)} />
    </ExpandedProvider>
  );
}
