import { useQuery, useQueryClient } from "@tanstack/react-query";
import { CheckCircle2, Clock, Play, TriangleAlert, Upload, XCircle } from "lucide-react";
import { AnimatePresence, motion } from "motion/react";
import { useEffect, useRef, useState } from "react";
import { Button, Drawer, ErrorNote, Field, Modal } from "../ui";
import { useToast } from "../ui/toast";
import { api, post } from "../../lib/api";
import { timeAgo } from "../../lib/format";

export const STATUS: Record<string, { tone: any; icon: JSX.Element }> = {
  succeeded: { tone: "brand", icon: <CheckCircle2 size={14} /> },
  partial: { tone: "amber", icon: <TriangleAlert size={14} /> },
  failed: { tone: "rose", icon: <XCircle size={14} /> },
  running: { tone: "indigo", icon: <span className="h-2 w-2 animate-pulse rounded-full bg-indigo-500" /> },
  queued: { tone: "slate", icon: <Clock size={14} /> },
};

export function LogViewer({ runId, onClose }: { runId?: number; onClose: () => void }) {
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
      qc.invalidateQueries({ queryKey: ["pipelines"] });
      qc.invalidateQueries({ queryKey: ["universe"] });
    });
    es.onerror = () => es.close();
    return () => es.close();
  }, [runId, qc]);
  useEffect(() => { const el = ref.current; if (el) el.scrollTop = el.scrollHeight; }, [log]);
  return (
    <Drawer open={!!runId} onClose={onClose} title={`Run #${runId ?? ""}`} subtitle={<span className="flex items-center gap-1.5">{STATUS[status]?.icon} {status}</span>} width={860}>
      <pre ref={ref} className="scrollbar-thin h-[calc(100vh-160px)] overflow-auto rounded-2xl bg-night-900 p-5 font-mono text-[12px] leading-relaxed text-slate-200">{log || "Waiting for output…"}</pre>
    </Drawer>
  );
}

export function RunModal({ job, onClose, onStarted }: { job: any | null; onClose: () => void; onStarted: (id: number) => void }) {
  const [params, setParams] = useState<Record<string, any>>({});
  const [confirm, setConfirm] = useState("");
  const [err, setErr] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);
  const uploads = useQuery({ queryKey: ["uploads"], queryFn: () => api<any>("/api/jobs/uploads"), enabled: !!job?.params.some((p: any) => p.kind === "csv" || p.kind === "file") });
  useEffect(() => { if (job) { setParams(Object.fromEntries(job.params.map((p: any) => [p.name, p.default]))); setConfirm(""); setErr(null); } }, [job]);
  if (!job) return <Modal open={false} onClose={onClose} title="">{null}</Modal>;
  const destructive = job.key === "refresh-nsq" || job.key === "fetch-nsq" || job.key === "load-seeds" || ((job.key === "pull-upstash" || job.key === "backup-to-upstash") && !params.dry_run) || (job.key === "restore-snapshot" && params.flush);

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
        ) : p.kind === "text" ? (
          <Field key={p.name} label={p.label}>
            <input className="input" value={params[p.name] ?? ""} onChange={(e) => setParams({ ...params, [p.name]: e.target.value })} placeholder={p.name.includes("month") || p.name.includes("from") ? "YYYY-MM" : ""} />
          </Field>
        ) : (
          <Field key={p.name} label={p.label}>
            <select className="input" value={params[p.name] ?? ""} onChange={(e) => setParams({ ...params, [p.name]: e.target.value })}>
              <option value="">{p.kind === "csv" ? (uploads.data?.default_csv ? `Bundled: ${uploads.data.default_csv}` : "Bundled CSV") : "Download from the source"}</option>
              {uploads.data?.uploads.filter((u: any) => p.kind !== "csv" || u.name.toLowerCase().endsWith(".csv")).map((u: any) => <option key={u.name} value={u.name}>{u.name} · {(u.bytes / 1e6).toFixed(1)} MB · {timeAgo(u.modified_at)}</option>)}
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



export function UploadButton({ label = "Upload data file", accept = ".csv,.zip,.json,.txt,.html,.xlsx", hint }: { label?: string; accept?: string; hint?: string }) {
  const [uploading, setUploading] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);
  const toast = useToast();
  const qc = useQueryClient();
  const upload = async (file: File) => {
    setUploading(true);
    const fd = new FormData();
    fd.append("file", file);
    try {
      const res = await fetch("/api/jobs/uploads", { method: "POST", body: fd, credentials: "include", headers: { "x-nsq-client": "web" } });
      if (!res.ok) throw new Error((await res.json()).detail);
      toast(`${file.name} uploaded${hint ? ` — ${hint}` : ""}.`);
      qc.invalidateQueries({ queryKey: ["uploads"] });
    } catch (e) {
      toast((e as Error).message, "error");
    } finally {
      setUploading(false);
      if (fileRef.current) fileRef.current.value = "";
    }
  };
  return <><input ref={fileRef} type="file" accept={accept} hidden onChange={(e) => e.target.files?.[0] && upload(e.target.files[0])} /><Button variant="secondary" loading={uploading} onClick={() => fileRef.current?.click()}><Upload size={15} /> {label}</Button></>;
}
