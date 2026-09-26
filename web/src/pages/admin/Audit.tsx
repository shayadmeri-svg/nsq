import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { ChevronLeft, ChevronRight } from "lucide-react";
import { useState } from "react";
import { Badge, Button, Card, PageHeader, Segmented } from "../../components/ui";
import { api } from "../../lib/api";
import { fmtDateTime } from "../../lib/format";

const TONE = (a: string) => (a.includes("failed") ? "rose" : a.startsWith("job") ? "indigo" : a.startsWith("auth") ? "sky" : a.startsWith("org") || a.startsWith("plant") ? "brand" : "slate") as any;

export function Audit() {
  const [page, setPage] = useState(1);
  const [action, setAction] = useState("");
  const { data, isFetching } = useQuery({ queryKey: ["audit", page, action], queryFn: () => api<any>(`/api/admin/audit?page=${page}&size=40&action=${action}`), placeholderData: keepPreviousData });
  const pages = data ? Math.max(1, Math.ceil(data.total / data.size)) : 1;
  return (
    <>
      <PageHeader eyebrow="Platform" title="Audit log" subtitle="Sign-ins, access changes, organisation edits, plant edits and data jobs — who did what, when, from where." actions={
        <Segmented value={action} onChange={(v) => { setAction(v); setPage(1); }} options={[{ value: "", label: "All" }, { value: "auth", label: "Sign-ins" }, { value: "user", label: "Users" }, { value: "org", label: "Orgs" }, { value: "job", label: "Jobs" }]} />
      } />
      <Card className={isFetching ? "opacity-70 transition" : "transition"}>
        <table className="w-full text-sm">
          <thead><tr className="border-b border-line bg-slate-50/70 text-left text-[11px] font-semibold uppercase tracking-wider text-ink-muted"><th className="px-5 py-2.5">When</th><th className="px-3 py-2.5">Who</th><th className="px-3 py-2.5">Action</th><th className="px-3 py-2.5">Target</th><th className="px-5 py-2.5">Detail</th></tr></thead>
          <tbody>
            {data?.items.map((a: any) => (
              <tr key={a.id} className="border-b border-line/70">
                <td className="whitespace-nowrap px-5 py-2.5 text-xs text-ink-muted">{fmtDateTime(a.at)}</td>
                <td className="px-3 py-2.5 text-xs">{a.actor || "—"}<div className="text-ink-faint">{a.ip}</div></td>
                <td className="px-3 py-2.5"><Badge tone={TONE(a.action)}>{a.action}</Badge></td>
                <td className="px-3 py-2.5 font-mono text-xs">{a.target}</td>
                <td className="max-w-[360px] truncate px-5 py-2.5 font-mono text-[11px] text-ink-muted" title={JSON.stringify(a.detail)}>{Object.keys(a.detail || {}).length ? JSON.stringify(a.detail) : ""}</td>
              </tr>
            ))}
          </tbody>
        </table>
        <div className="flex items-center justify-between px-5 py-3 text-xs text-ink-muted">
          <span>{data?.total ?? 0} events · page {page} of {pages}</span>
          <div className="flex gap-1.5"><Button size="sm" variant="secondary" disabled={page <= 1} onClick={() => setPage(page - 1)}><ChevronLeft size={14} /></Button><Button size="sm" variant="secondary" disabled={page >= pages} onClick={() => setPage(page + 1)}><ChevronRight size={14} /></Button></div>
        </div>
      </Card>
    </>
  );
}
