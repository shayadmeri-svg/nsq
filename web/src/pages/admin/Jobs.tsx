import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Lock, Play, TerminalSquare } from "lucide-react";
import { useState } from "react";
import { LogViewer, RunModal, STATUS, UploadButton } from "../../components/jobs";
import { Badge, Button, Card, ErrorNote, PageHeader, PageSkeleton } from "../../components/ui";
import { api } from "../../lib/api";
import { fmtDateTime, timeAgo } from "../../lib/format";

export function Jobs() {
  const { data, isLoading, error } = useQuery({ queryKey: ["jobs"], queryFn: () => api<any>("/api/jobs"), refetchInterval: 10_000 });
  const runs = useQuery({ queryKey: ["runs"], queryFn: () => api<any>("/api/jobs/runs?size=20"), refetchInterval: 10_000 });
  const [picked, setPicked] = useState<any | null>(null);
  const [viewing, setViewing] = useState<number | undefined>();
  const qc = useQueryClient();
  if (isLoading) return <PageSkeleton />;
  if (error) return <ErrorNote error={error} />;
  const groups = [...new Set<string>(data.jobs.map((j: any) => j.group))];

  return (
    <>
      <PageHeader eyebrow="Platform" title="Data jobs" subtitle="The justfile's data recipes, run on the server with live logs. Destructive jobs need a super admin and a typed confirmation."
        actions={data.is_super && <UploadButton hint="pick it in the job's file field" />} />
      <div className="space-y-6">
        {groups.map((g) => (
          <div key={g}>
            <div className="label mb-2.5">{g}</div>
            <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
              {data.jobs.filter((j: any) => j.group === g).map((j: any, i: number) => {
                const st = j.last_run?.status;
                return (
                  <Card key={j.key} delay={i * 0.04} className="flex flex-col p-5">
                    <div className="flex items-start justify-between gap-3">
                      <div className="font-display text-[15px] font-bold">{j.title}</div>
                      {j.role === "super_admin" && <Badge tone="rose"><Lock size={10} /> super admin</Badge>}
                    </div>
                    <p className="mt-1.5 flex-1 text-[13px] leading-relaxed text-ink-muted">{j.description}</p>
                    <div className="mt-4 flex items-center justify-between">
                      <button disabled={!j.last_run} onClick={() => j.last_run && setViewing(j.last_run.id)} className="flex items-center gap-1.5 text-xs text-ink-muted hover:text-ink disabled:hover:text-ink-muted">
                        {st ? <><Badge tone={STATUS[st]?.tone ?? "slate"}>{STATUS[st]?.icon}{st}</Badge><span>{timeAgo(j.last_run.created_at)}</span></> : "never run"}
                      </button>
                      <Button size="sm" disabled={!j.allowed || !j.available || !!j.running} onClick={() => setPicked(j)} title={!j.available ? "UPSTASH_URL not configured" : undefined}>
                        {j.running ? <><span className="h-2 w-2 animate-pulse rounded-full bg-white" /> Running</> : <><Play size={13} /> Run</>}
                      </Button>
                    </div>
                  </Card>
                );
              })}
            </div>
          </div>
        ))}
      </div>

      <Card delay={0.2} className="mt-8">
        <div className="flex items-center gap-2 px-5 pt-5 font-display text-[15px] font-bold"><TerminalSquare size={16} /> Run history</div>
        <table className="mt-3 w-full text-sm">
          <thead><tr className="border-y border-line bg-slate-50/70 text-left text-[11px] font-semibold uppercase tracking-wider text-ink-muted"><th className="px-5 py-2.5">#</th><th className="px-3 py-2.5">Job</th><th className="px-3 py-2.5">Status</th><th className="px-3 py-2.5">By</th><th className="px-3 py-2.5">Started</th><th className="px-5 py-2.5">Duration</th></tr></thead>
          <tbody>
            {runs.data?.items.map((r: any) => (
              <tr key={r.id} onClick={() => setViewing(r.id)} className="cursor-pointer border-b border-line/70 hover:bg-slate-50">
                <td className="px-5 py-2.5 font-mono text-xs">{r.id}</td>
                <td className="px-3 py-2.5 font-mono text-xs">{r.job_key}</td>
                <td className="px-3 py-2.5"><Badge tone={STATUS[r.status]?.tone ?? "slate"}>{STATUS[r.status]?.icon}{r.status}</Badge></td>
                <td className="px-3 py-2.5 text-xs">{r.by}</td>
                <td className="px-3 py-2.5 text-xs text-ink-muted">{fmtDateTime(r.created_at)}</td>
                <td className="px-5 py-2.5 text-xs text-ink-muted">{r.finished_at && r.started_at ? `${((new Date(r.finished_at).getTime() - new Date(r.started_at).getTime()) / 1000).toFixed(1)} s` : "—"}</td>
              </tr>
            ))}
            {!runs.data?.items.length && <tr><td colSpan={6} className="px-5 py-6 text-center text-sm text-ink-muted">No runs yet.</td></tr>}
          </tbody>
        </table>
      </Card>
      <RunModal job={picked} onClose={() => setPicked(null)} onStarted={(id) => { setViewing(id); qc.invalidateQueries({ queryKey: ["jobs"] }); }} />
      <LogViewer runId={viewing} onClose={() => setViewing(undefined)} />
    </>
  );
}
