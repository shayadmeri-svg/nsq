import { useQuery, useQueryClient } from "@tanstack/react-query";
import { CheckCircle2, Clock, Lock, Play, TerminalSquare, TriangleAlert, Upload, XCircle } from "lucide-react";
import { AnimatePresence, motion } from "motion/react";
import { useEffect, useRef, useState } from "react";
import { Badge, Button, Card, Drawer, ErrorNote, Field, Modal, PageHeader, PageSkeleton } from "../../components/ui";
import { useToast } from "../../components/ui/toast";
import { api, post } from "../../lib/api";
import { fmtDateTime, timeAgo } from "../../lib/format";

const STATUS: Record<string, { tone: any; icon: JSX.Element }> = {
  succeeded: { tone: "brand", icon: <CheckCircle2 size={14} /> },
  failed: { tone: "rose", icon: <XCircle size={14} /> },
  running: { tone: "indigo", icon: <span className="h-2 w-2 animate-pulse rounded-full bg-indigo-500" /> },
  queued: { tone: "slate", icon: <Clock size={14} /> },
};

function LogViewer({ runId, onClose }: { runId?: number; onClose: () => void }) {
  const [log, setLog] = useState("");
  const [status, setStatus] = useState<string>("running");
  const ref = useRef<HTMLPreElement>(null);
  const qc = useQueryClient();
  useEffect(() => {
    if (!runId) return;
    setLog("");
    setStatus("running");
    const es = new EventSource(`/api/jobs/runs/${runId}/stream`, { withCredentials: true });
    es.addEventListener("log", (e) => setLog((l) => l + JSON.parse((e as MessageEvent).data)));
    es.addEventListener("done", (e) => {
      setStatus(JSON.parse((e as MessageEvent).data).status);
      es.close();
      qc.invalidateQueries({ queryKey: ["jobs"] });
      qc.invalidateQueries({ queryKey: ["runs"] });
      qc.invalidateQueries({ queryKey: ["admin-overview"] });
      qc.invalidateQueries({ queryKey: ["data-status"] });
    });
    es.onerror = () => es.close();
    return () => es.close();
  }, [runId, qc]);
  useEffect(() => { ref.current?.scrollTo({ top: ref.current.scrollHeight }); }, [log]);
  return (
    <Drawer open={!!runId} onClose={onClose} title={`Run #${runId ?? ""}`} subtitle={<span className="flex items-center gap-1.5">{STATUS[status]?.icon} {status}</span>} width={860}>
      <pre ref={ref} className="scrollbar-thin h-[calc(100vh-160px)] overflow-auto rounded-2xl bg-night-900 p-5 font-mono text-[12px] leading-relaxed text-slate-200">{log || "Waiting for output…"}</pre>
    </Drawer>
  );
}

function RunModal({ job, onClose, onStarted }: { job: any | null; onClose: () => void; onStarted: (id: number) => void }) {
  const [params, setParams] = useState<Record<string, any>>({});
  const [confirm, setConfirm] = useState("");
  const [err, setErr] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);
  const uploads = useQuery({ queryKey: ["uploads"], queryFn: () => api<any>("/api/jobs/uploads"), enabled: !!job?.params.some((p: any) => p.kind === "csv") });
  useEffect(() => { if (job) { setParams(Object.fromEntries(job.params.map((p: any) => [p.name, p.default]))); setConfirm(""); setErr(null); } }, [job]);
  if (!job) return <Modal open={false} onClose={onClose} title="">{null}</Modal>;
  const destructive = job.key === "refresh-nsq" || job.key === "load-seeds" || ((job.key === "pull-upstash" || job.key === "backup-to-upstash") && !params.dry_run) || (job.key === "restore-snapshot" && params.flush);

  const run = async () => {
    setBusy(true);
    setErr(null);
    try {
      const r = await post<any>(`/api/jobs/${job.key}/run`, { params, confirm });
      onStarted(r.run.id);
      onClose();
    } catch (e) {
      setErr(e);
    } finally {
      setBusy(false);
    }
  };

  return (
    <Modal open onClose={onClose} title={job.title} footer={<><Button variant="secondary" onClick={onClose}>Cancel</Button><Button variant={destructive ? "danger" : "primary"} loading={busy} disabled={destructive && confirm !== job.key} onClick={run}><Play size={15} /> Run</Button></>}>
      <p className="text-sm text-ink-soft">{job.description}</p>
      <div className="mt-4 space-y-3">
        {job.params.map((p: any) => p.kind === "bool" ? (
          <label key={p.name} className="flex items-center gap-2.5 text-sm"><input type="checkbox" checked={!!params[p.name]} onChange={(e) => setParams({ ...params, [p.name]: e.target.checked })} className="h-4 w-4 accent-brand-600" />{p.label}</label>
        ) : (
          <Field key={p.name} label={p.label}>
            <select className="input" value={params[p.name] ?? ""} onChange={(e) => setParams({ ...params, [p.name]: e.target.value })}>
              <option value="">{uploads.data?.default_csv ? `Bundled: ${uploads.data.default_csv}` : "Bundled CSV"}</option>
              {uploads.data?.uploads.map((u: any) => <option key={u.name} value={u.name}>{u.name} · {(u.bytes / 1e6).toFixed(1)} MB · {timeAgo(u.modified_at)}</option>)}
            </select>
          </Field>
        ))}
      </div>
      <AnimatePresence>
        {destructive && (
          <motion.div initial={{ opacity: 0, height: 0 }} animate={{ opacity: 1, height: "auto" }} exit={{ opacity: 0, height: 0 }} className="mt-4 overflow-hidden">
            <div className="rounded-xl bg-rose-50 p-3.5 text-sm text-rose-800 ring-1 ring-inset ring-rose-200">
              <div className="flex items-center gap-2 font-semibold"><TriangleAlert size={16} /> This overwrites live data</div>
              <p className="mt-1 text-xs">Dashboards will show the new data as soon as it finishes. Type <b className="font-mono">{job.key}</b> to confirm.</p>
              <input className="input mt-2 bg-white font-mono" value={confirm} onChange={(e) => setConfirm(e.target.value)} placeholder={job.key} />
            </div>
          </motion.div>
        )}
      </AnimatePresence>
      <div className="mt-3"><ErrorNote error={err} /></div>
    </Modal>
  );
}

export function Jobs() {
  const { data, isLoading, error } = useQuery({ queryKey: ["jobs"], queryFn: () => api<any>("/api/jobs"), refetchInterval: 10_000 });
  const runs = useQuery({ queryKey: ["runs"], queryFn: () => api<any>("/api/jobs/runs?size=20"), refetchInterval: 10_000 });
  const [picked, setPicked] = useState<any | null>(null);
  const [viewing, setViewing] = useState<number | undefined>();
  const [uploading, setUploading] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);
  const toast = useToast();
  const qc = useQueryClient();
  if (isLoading) return <PageSkeleton />;
  if (error) return <ErrorNote error={error} />;
  const groups = [...new Set<string>(data.jobs.map((j: any) => j.group))];

  const upload = async (file: File) => {
    setUploading(true);
    const fd = new FormData();
    fd.append("file", file);
    try {
      const res = await fetch("/api/jobs/uploads", { method: "POST", body: fd, credentials: "include", headers: { "x-nsq-client": "web" } });
      if (!res.ok) throw new Error((await res.json()).detail);
      toast(`${file.name} uploaded — pick it in “Monthly NSQ refresh”.`);
      qc.invalidateQueries({ queryKey: ["uploads"] });
    } catch (e) {
      toast((e as Error).message, "error");
    } finally {
      setUploading(false);
    }
  };

  return (
    <>
      <PageHeader eyebrow="Platform" title="Data jobs" subtitle="The justfile's data recipes, run on the server with live logs. Destructive jobs need a super admin and a typed confirmation."
        actions={data.is_super && <><input ref={fileRef} type="file" accept=".csv" hidden onChange={(e) => e.target.files?.[0] && upload(e.target.files[0])} /><Button variant="secondary" loading={uploading} onClick={() => fileRef.current?.click()}><Upload size={15} /> Upload CDSCO CSV</Button></>} />
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
                        {st ? <><Badge tone={STATUS[st].tone}>{STATUS[st].icon}{st}</Badge><span>{timeAgo(j.last_run.created_at)}</span></> : "never run"}
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
                <td className="px-3 py-2.5"><Badge tone={STATUS[r.status].tone}>{STATUS[r.status].icon}{r.status}</Badge></td>
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
