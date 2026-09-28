// "Update everything": the one refresh button. Draws the DAG the server derives from the data map (who reads what the
// others write), colours each task from the latest run's log, and highlights a task's upstream and downstream on click.
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowRight, CheckCircle2, Info, CircleDashed, Database, Loader2, Lock, Map as MapIcon, Play, RotateCw, Square, TerminalSquare, TriangleAlert, XCircle } from "lucide-react";
import { useMemo, useState, type ReactNode } from "react";
import { Link } from "react-router-dom";
import { Badge, Button, Card } from "../../components/ui";
import { ManualFileButton, STATUS, type Manual } from "../../components/jobs";
import { api, post } from "../../lib/api";
import { cn } from "../../lib/cn";
import { fmtDateTime, timeAgo } from "../../lib/format";

type Task = { id: string; title: string; stage: string; reads: string[]; writes: string[]; needs: { task: string; via: string[] }[];
  layer: number; soft: boolean; skip: string | null; note: string; source: string | null; node: string | null; steps: string[]; manual: Manual | null };
type Plan = { tasks: Task[]; order: string[]; layers: string[][]; stages: { id: string; title: string; hint: string }[];
  artifacts: Record<string, { node: string; label: string }>; run: any; running: number | null; others_running: string[]; job: any; allowed: boolean };

const STAGE: Record<string, string> = {
  prepare: "#64748b", nsq: "#e11d48", sources: "#0284c7", molecules: "#7c3aed", plants: "#d97706", persist: "#0a9a7d", serve: "#0f172a",
};
const ST: Record<string, { cls: string; icon: ReactNode; label: string }> = {
  pending: { cls: "bg-white ring-line text-ink", icon: <CircleDashed size={12} className="text-ink-faint" />, label: "waiting" },
  running: { cls: "bg-indigo-50 ring-indigo-300 text-indigo-900", icon: <Loader2 size={12} className="animate-spin text-indigo-600" />, label: "running" },
  ok: { cls: "bg-emerald-50 ring-emerald-200 text-emerald-900", icon: <CheckCircle2 size={12} className="text-emerald-600" />, label: "done" },
  warn: { cls: "bg-amber-50 ring-amber-200 text-amber-900", icon: <TriangleAlert size={12} className="text-amber-600" />, label: "kept last data" },
  failed: { cls: "bg-rose-50 ring-rose-300 text-rose-900", icon: <XCircle size={12} className="text-rose-600" />, label: "failed" },
  skipped: { cls: "bg-slate-50 ring-slate-200 text-ink-muted border-dashed", icon: <CircleDashed size={12} className="text-slate-400" />, label: "skipped" },
};

const COL_W = 196, NODE_W = 168, NODE_H = 34, GAP = 6, PAD = 8;

function closure(start: string, next: Record<string, string[]>) {
  const out = new Set<string>();
  const stack = [start];
  while (stack.length) for (const c of next[stack.pop()!] ?? []) if (!out.has(c)) { out.add(c); stack.push(c); }
  return out;
}

export function FullRefresh({ onRun, onLog, onRunSource }: { onRun: (job: any) => void; onLog: (id: number) => void; onRunSource: (source: string) => void }) {
  const { data: p } = useQuery({ queryKey: ["full-refresh-plan"], queryFn: () => api<Plan>("/api/jobs/full-refresh/plan"),
    refetchInterval: (q) => ((q.state.data as Plan | undefined)?.running ? 2500 : 15000) });
  const [sel, setSel] = useState<string | null>(null);

  const g = useMemo(() => {
    if (!p) return null;
    const by = Object.fromEntries(p.tasks.map((t) => [t.id, t]));
    const up: Record<string, string[]> = {}, down: Record<string, string[]> = {};
    for (const t of p.tasks) for (const n of t.needs) { (up[t.id] ??= []).push(n.task); (down[n.task] ??= []).push(t.id); }
    const pos: Record<string, { x: number; y: number }> = {};
    p.layers.forEach((layer, li) => layer.forEach((id, ri) => { pos[id] = { x: PAD + li * COL_W, y: PAD + 22 + ri * (NODE_H + GAP) }; }));
    const rows = Math.max(...p.layers.map((l) => l.length));
    return { by, up, down, pos, w: PAD * 2 + p.layers.length * COL_W - (COL_W - NODE_W), h: PAD * 2 + 22 + rows * (NODE_H + GAP) };
  }, [p]);

  if (!p || !g) return <Card className="mb-5 h-64 animate-pulse">{null}</Card>;
  const states: Record<string, { state: string; note: string }> = p.run?.states ?? {};
  const live = !!p.running;
  const stateOf = (t: Task) => states[t.id]?.state ?? (t.skip ? "skipped" : "pending");
  const runnable = p.tasks.filter((t) => !t.skip);
  const doneN = runnable.filter((t) => ["ok", "warn", "failed", "skipped"].includes(states[t.id]?.state)).length;
  const counts = p.tasks.reduce<Record<string, number>>((a, t) => { const s = stateOf(t); a[s] = (a[s] ?? 0) + 1; return a; }, {});
  const upSet = sel ? closure(sel, g.up) : new Set<string>();
  const downSet = sel ? closure(sel, g.down) : new Set<string>();
  const t = sel ? g.by[sel] : null;
  const edgeOn = (a: string, b: string) => !!sel && ((a === sel || upSet.has(a)) && (b === sel || upSet.has(b)) || (a === sel || downSet.has(a)) && (b === sel || downSet.has(b)));
  const run = p.run;
  const dur = run?.started_at ? ((new Date(run.finished_at ?? Date.now()).getTime() - new Date(run.started_at).getTime()) / 60000) : null;

  return (
    <Card className="mb-5 overflow-hidden">
      <div className="bg-gradient-to-br from-night-900 to-slate-800 p-5 text-white">
        <div className="flex flex-wrap items-start gap-4">
          <div className="min-w-0 flex-1">
            <div className="flex items-center gap-2 text-[11px] font-semibold uppercase tracking-wider text-brand-400"><RotateCw size={13} /> Update everything</div>
            <div className="mt-1 max-w-3xl font-display text-xl font-bold leading-snug">Every dataset on the platform, refreshed in dependency order and persisted — {p.tasks.length} tasks, {p.layers.length} steps deep.</div>
            <p className="mt-1.5 max-w-3xl text-[12.5px] leading-relaxed text-slate-300">
              New CDSCO months and the NSQ reload, every public source, the molecule universe (trials, structures, patents, regulatory, demand), plants and the India map;
              then portable copies of every store — the NSQ snapshot, every molecule and plant (<code className="text-slate-200">cdmo_snapshot.json.gz</code>), the app's own edits (<code className="text-slate-200">app_state.json</code>) — Redis flushed to disk, and the caches warmed.
              The order comes from the data map: a task waits for every task that writes something it reads.
            </p>
          </div>
          <div className="flex shrink-0 flex-col items-end gap-2">
            <Button onClick={() => onRun({ ...p.job, allowed: p.allowed })} disabled={!p.allowed || live || p.others_running.length > 0}
              className="!h-11 !px-5 !text-[14px]">
              {live ? <><Loader2 size={15} className="animate-spin" /> Updating… {doneN}/{runnable.length}</> : <><Play size={15} /> Update everything</>}
            </Button>
            {!p.allowed && <span className="flex items-center gap-1 text-[11px] text-rose-300"><Lock size={11} /> super admin</span>}
            {p.others_running.length > 0 && !live && <span className="text-[11px] text-amber-300">waiting for {p.others_running.join(", ")} to finish</span>}
            {run && <button onClick={() => onLog(run.id)} className="flex items-center gap-1 text-[11.5px] text-slate-300 hover:text-white"><TerminalSquare size={12} /> log of run #{run.id}</button>}
            {live && p.allowed && <StopButton runId={run?.id} />}
          </div>
        </div>
        {run && (
          <div className="mt-4">
            <div className="flex flex-wrap items-center gap-2 text-[11.5px] text-slate-300">
              <Badge tone={STATUS[run.status]?.tone ?? "slate"}>{STATUS[run.status]?.icon}{run.status}</Badge>
              <span>{live ? "started" : "last run"} {timeAgo(run.started_at ?? run.created_at)} · {fmtDateTime(run.started_at ?? run.created_at)} · by {run.by}{dur != null && ` · ${dur.toFixed(dur < 10 ? 1 : 0)} min`}</span>
              <span className="ml-auto flex flex-wrap gap-2">{Object.entries(counts).map(([k, n]) => <span key={k} className="flex items-center gap-1">{ST[k]?.icon}{n} {ST[k]?.label}</span>)}</span>
            </div>
            <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-white/10"><div className="h-full rounded-full bg-brand-500 transition-all" style={{ width: `${(100 * doneN) / Math.max(1, runnable.length)}%` }} /></div>
            {live && run.tail?.length > 0 && (
              <div className="mt-2 rounded-lg bg-black/30 px-3 py-1.5 font-mono text-[11px] leading-relaxed text-slate-300" title="Latest log lines — refreshes every few seconds">
                {run.tail.map((l: string, i: number) => <div key={i} className="truncate">{l}</div>)}
              </div>
            )}
          </div>
        )}
      </div>

      <div className="flex flex-wrap items-center gap-3 border-b border-line px-4 py-2 text-[11px] text-ink-muted">
        {p.stages.map((s) => <span key={s.id} title={s.hint} className="flex items-center gap-1"><span className="h-2.5 w-2.5 rounded-sm" style={{ background: STAGE[s.id] }} />{s.title}</span>)}
        <span className="ml-auto">Click a task: its upstream and downstream light up</span>
      </div>

      <div className="grid xl:grid-cols-[minmax(0,1fr)_22rem]">
        <div className="max-h-[34rem] overflow-auto bg-slate-50/60">
          <div className="relative" style={{ width: g.w, height: g.h }} onClick={() => setSel(null)}>
            {p.layers.map((_, li) => <div key={li} className="absolute text-[10px] font-semibold uppercase tracking-wider text-ink-faint" style={{ left: PAD + li * COL_W, top: PAD }}>step {li + 1}</div>)}
            <svg className="pointer-events-none absolute inset-0" width={g.w} height={g.h}>
              {p.tasks.flatMap((b) => b.needs.map((n) => {
                const a = g.pos[n.task], c = g.pos[b.id];
                if (!a || !c) return null;
                const x1 = a.x + NODE_W, y1 = a.y + NODE_H / 2, x2 = c.x, y2 = c.y + NODE_H / 2, mx = (x1 + x2) / 2;
                const on = edgeOn(n.task, b.id);
                return <path key={`${n.task}>${b.id}`} d={`M${x1},${y1} C${mx},${y1} ${mx},${y2} ${x2},${y2}`} fill="none"
                  stroke={on ? "#0a9a7d" : "#cbd5e1"} strokeWidth={on ? 1.8 : 0.8} opacity={sel && !on ? 0.25 : on ? 1 : 0.7} />;
              }))}
            </svg>
            {p.tasks.map((tk) => {
              const s = stateOf(tk), x = g.pos[tk.id];
              const dim = sel && tk.id !== sel && !upSet.has(tk.id) && !downSet.has(tk.id);
              return (
                <button key={tk.id} onClick={(e) => { e.stopPropagation(); setSel(tk.id === sel ? null : tk.id); }} title={states[tk.id]?.note || tk.skip || tk.note || tk.title}
                  className={cn("absolute flex items-center gap-1.5 overflow-hidden rounded-lg border-l-[3px] pl-1.5 pr-2 text-left text-[11.5px] font-medium ring-1 ring-inset transition",
                    ST[s].cls, tk.id === sel && "ring-2 ring-brand-500", dim && "opacity-30", s === "running" && "shadow-md")}
                  style={{ left: x.x, top: x.y, width: NODE_W, height: NODE_H, borderLeftColor: STAGE[tk.stage] }}>
                  {ST[s].icon}<span className="min-w-0 flex-1 truncate">{tk.title}</span>
                  {tk.manual && (s === "warn" || s === "failed" || tk.skip) && <Info size={11} className="shrink-0 text-brand-600" aria-label="needs a file — click for where to get it" />}
                </button>
              );
            })}
          </div>
        </div>

        <div className="border-t border-line p-4 text-xs xl:border-l xl:border-t-0">
          {!t ? (
            <div className="space-y-3 text-ink-muted">
              <div className="font-display text-[14px] font-bold text-ink">How the order is worked out</div>
              <p>Each task declares what it <b>reads</b> and <b>writes</b> — stores and files on the <Link to="/admin/data-map" className="text-brand-700 hover:underline">data map</Link>.
                A task runs after every task that writes something it reads; a few "runs after" links keep a write from landing before a flush.</p>
              <ul className="space-y-1">
                <li>● A source that is down <b className="text-amber-700">keeps its last file</b>; everything downstream still runs.</li>
                <li>● A hard failure (reload, build, load) <b className="text-rose-700">skips only its downstream</b>.</li>
                <li>● Nothing else can run while it runs; it waits for running jobs.</li>
                <li>● Laptop-only sources are shown, not run — push them from a laptop.</li>
                <li>● <Info size={11} className="inline text-brand-600" /> marks a source the server couldn't download — click it for where to get the file and how to upload it.</li>
              </ul>
              <p>Weekly schedule available on Data pipelines (off by default).</p>
            </div>
          ) : (
            <div className="space-y-3">
              <div>
                <div className="flex items-center gap-2"><span className="h-2.5 w-2.5 rounded-sm" style={{ background: STAGE[t.stage] }} />
                  <span className="text-[10.5px] font-semibold uppercase tracking-wider text-ink-muted">{p.stages.find((s) => s.id === t.stage)?.title} · step {t.layer + 1}</span></div>
                <div className="mt-1 font-display text-[15px] font-bold">{t.title}</div>
                <div className="mt-1 flex items-center gap-1.5">{ST[stateOf(t)].icon}<span>{ST[stateOf(t)].label}</span>{t.soft && <Badge tone="slate">keeps last data on failure</Badge>}</div>
                {(states[t.id]?.note || t.skip) && <div className="mt-1.5 rounded-md bg-slate-50 px-2 py-1 text-ink-muted">{states[t.id]?.note || t.skip}</div>}
                {t.note && <div className="mt-1.5 text-ink-muted">{t.note}</div>}
                {t.manual && t.source && <div className="mt-2"><ManualFileButton manual={t.manual} title={`${t.title} — providing the file`} onRunWithFile={() => onRunSource(t.source!)} /></div>}
              </div>
              <Io title="Reads" items={t.reads} p={p} />
              <Io title="Writes" items={t.writes} p={p} />
              <div>
                <div className="label mb-1">Upstream ({upSet.size})</div>
                {t.needs.length === 0 ? <div className="text-ink-muted">Nothing — starts first.</div> : t.needs.map((n) => (
                  <button key={n.task} onClick={() => setSel(n.task)} className="flex w-full items-start gap-1.5 py-0.5 text-left hover:text-brand-700">
                    <ArrowRight size={11} className="mt-0.5 shrink-0 rotate-180 text-ink-faint" /><span><b>{g.by[n.task]?.title}</b> <span className="text-ink-muted">via {n.via.map((v) => p.artifacts[v]?.label ?? v).join(", ")}</span></span>
                  </button>))}
              </div>
              <div>
                <div className="label mb-1">Downstream ({downSet.size})</div>
                {(g.down[t.id] ?? []).length === 0 ? <div className="text-ink-muted">Nothing waits on it.</div> : (g.down[t.id] ?? []).map((d) => (
                  <button key={d} onClick={() => setSel(d)} className="flex w-full items-center gap-1.5 py-0.5 text-left hover:text-brand-700"><ArrowRight size={11} className="text-ink-faint" />{g.by[d]?.title}</button>))}
              </div>
              {t.steps.length > 0 && <div><div className="label mb-1">Steps</div><ol className="list-decimal space-y-0.5 pl-4 text-ink-soft">{t.steps.map((s, i) => <li key={i}>{s}</li>)}</ol></div>}
            </div>
          )}
        </div>
      </div>
    </Card>
  );
}

function StopButton({ runId }: { runId?: number }) {
  const [busy, setBusy] = useState(false);
  const [asked, setAsked] = useState(false);
  const qc = useQueryClient();
  if (!runId) return null;
  const stop = async () => {
    setBusy(true);
    try { await post(`/api/jobs/runs/${runId}/cancel`); } finally { setBusy(false); setAsked(false); qc.invalidateQueries({ queryKey: ["full-refresh-plan"] }); }
  };
  return asked ? (
    <span className="flex items-center gap-2 text-[11.5px] text-slate-200">Stop now? Finished tasks keep their results.
      <button onClick={stop} disabled={busy} className="rounded-md bg-rose-600 px-2 py-0.5 font-semibold text-white hover:bg-rose-500">{busy ? "Stopping…" : "Stop"}</button>
      <button onClick={() => setAsked(false)} className="text-slate-400 hover:text-white">cancel</button></span>
  ) : (
    <button onClick={() => setAsked(true)} className="flex items-center gap-1 text-[11.5px] text-rose-300 hover:text-rose-200"><Square size={11} /> Stop</button>
  );
}

function Io({ title, items, p }: { title: string; items: string[]; p: Plan }) {
  if (!items.length) return null;
  return (
    <div>
      <div className="label mb-1">{title}</div>
      <div className="flex flex-wrap gap-1">{items.map((a) => {
        const art = p.artifacts[a];
        return <Link key={a} to={`/admin/data-map?node=${art?.node ?? ""}`} title="Open on the data map"
          className="inline-flex items-center gap-1 rounded-md bg-slate-100 px-1.5 py-0.5 text-[11px] text-ink-soft hover:bg-brand-50 hover:text-brand-700">
          {a.startsWith("src:") || a.startsWith("file:") || a.startsWith("gen:") ? <Database size={10} /> : <MapIcon size={10} />}{art?.label ?? a}</Link>;
      })}</div>
    </div>
  );
}
