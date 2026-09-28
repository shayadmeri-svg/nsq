import { useQuery, useQueryClient } from "@tanstack/react-query";
import { CheckCircle2, Clock, ExternalLink, Info, Play, TriangleAlert, Upload, XCircle } from "lucide-react";
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
    // If the stream drops (proxy timeout, network blip), fall back to polling the run until it finishes.
    let poll: ReturnType<typeof setInterval> | undefined;
    es.onerror = () => {
      es.close();
      if (poll) return;
      poll = setInterval(async () => {
        try {
          const r = await api<any>(`/api/jobs/runs/${runId}`);
          setLog(r.run.log || "");
          if (!["queued", "running"].includes(r.run.status)) {
            setStatus(r.run.status);
            clearInterval(poll);
          }
        } catch { /* keep trying */ }
      }, 2000);
    };
    return () => { es.close(); if (poll) clearInterval(poll); };
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
  const destructive = !!job.destructive_by_default || job.key === "refresh-nsq" || job.key === "fetch-nsq" || job.key === "load-seeds" || ((job.key === "pull-upstash" || job.key === "backup-to-upstash") && !params.dry_run) || (job.key === "restore-snapshot" && params.flush);

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



export function UploadButton({ label = "Upload data file", accept = ".csv,.zip,.json,.txt,.html,.htm,.xlsx,.xls,.pdf", hint }: { label?: string; accept?: string; hint?: string }) {
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

// "Where do I get this file?": for sources the server often cannot download, what to fetch in a browser, where, and how
// to hand it to the job (upload here, then run the source with it).
export type Manual = { file: string; accepts: string; links: { label: string; url: string }[]; steps: string[] };

export function ManualFileButton({ manual, title, onRunWithFile, compact }: { manual: Manual; title: string; onRunWithFile?: () => void; compact?: boolean }) {
  const [open, setOpen] = useState(false);
  const uploadable = /\.\w+/.test(manual.accepts);
  return (
    <>
      <button onClick={(e) => { e.stopPropagation(); setOpen(true); }}
        className={compact ? "inline-flex items-center gap-1 text-[11px] font-semibold text-brand-700 hover:underline"
          : "inline-flex items-center gap-1.5 rounded-lg bg-brand-50 px-2.5 py-1.5 text-xs font-semibold text-brand-800 ring-1 ring-inset ring-brand-200 hover:bg-brand-100"}>
        <Info size={13} /> {uploadable ? "Where do I get this file?" : "How to provide this data"}
      </button>
      <Modal open={open} onClose={() => setOpen(false)} title={title}
        footer={<>
          <Button variant="secondary" onClick={() => setOpen(false)}>Close</Button>
          {uploadable && onRunWithFile && <Button onClick={() => { setOpen(false); onRunWithFile(); }}><Play size={14} /> Run with an uploaded file</Button>}
        </>}>
        <div className="space-y-4 text-sm">
          <div>
            <div className="label mb-1">The file</div>
            <p className="text-ink-soft">{manual.file}</p>
            <p className="mt-1 text-xs text-ink-muted">Accepted: <b>{manual.accepts}</b></p>
          </div>
          <div>
            <div className="label mb-1.5">Where to find it</div>
            <ul className="space-y-1.5">{manual.links.map((l) => (
              <li key={l.url}><a href={l.url} target="_blank" rel="noreferrer noopener" className="group flex items-start gap-2 rounded-lg p-2 ring-1 ring-inset ring-line hover:bg-slate-50">
                <ExternalLink size={14} className="mt-0.5 shrink-0 text-brand-600" />
                <span className="min-w-0"><span className="font-medium text-ink group-hover:text-brand-700">{l.label}</span><span className="block truncate text-[11px] text-ink-faint">{l.url}</span></span>
              </a></li>))}</ul>
            <p className="mt-1.5 text-[11px] text-ink-faint">Publishers move files; if a link is dead, search the publisher's site for the file named above.</p>
          </div>
          <div>
            <div className="label mb-1">Steps</div>
            <ol className="list-decimal space-y-0.5 pl-5 text-ink-soft">{manual.steps.map((s, i) => <li key={i}>{s}</li>)}
              {uploadable && <li>Then pick the upload in this source's file field and run it — Update everything uses the new file next time.</li>}</ol>
          </div>
          {uploadable && <div className="flex items-center gap-2 border-t border-line pt-3"><UploadButton hint="then run this source with it" /></div>}
        </div>
      </Modal>
    </>
  );
}
