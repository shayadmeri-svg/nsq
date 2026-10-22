// Admin · Data operations · Coverage: for every official source, how many of its entries map to a tracked molecule
// (and how), the names it could not map, the molecules it misses — and, molecule by molecule, where the limits come from.
import { useQuery } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import { Badge, Card, CardHeader, ErrorNote, PageSkeleton, Segmented } from "../../components/ui";
import { api } from "../../lib/api";
import { cn } from "../../lib/cn";

const SRC_SHORT: Record<string, string> = { ip: "IP", ph_int: "WHO", jp: "JP", fda: "FDA", fda_dissolution: "FDA", edqm_kd: "Ph. Eur.", default: "default" };
const TONE: Record<string, string> = { ip: "bg-brand-600", ph_int: "bg-sky-500", jp: "bg-indigo-500", fda: "bg-amber-500", default: "bg-slate-200" };
const METHOD_LABEL: Record<string, string> = { exact: "exact name", salt: "salt / hydrate removed", inn_usan: "INN ↔ USAN", synonym: "synonym", pubchem: "same PubChem compound", fuzzy: "near spelling" };

function Share({ label, parts, total }: { label: string; parts: Record<string, number>; total: number }) {
  const order = ["ip", "ph_int", "jp", "fda", "default"].filter((k) => parts[k]);
  return (
    <div>
      <div className="mb-1 flex justify-between text-xs"><span className="font-medium text-ink-soft">{label}</span>
        <span className="tabular-nums text-ink-muted">{total - (parts.default ?? 0)} of {total} from a source</span></div>
      <div className="flex h-2.5 overflow-hidden rounded-full bg-slate-100">
        {order.map((k) => <div key={k} className={TONE[k]} style={{ width: `${(100 * parts[k]) / total}%` }} title={`${SRC_SHORT[k]}: ${parts[k]}`} />)}
      </div>
      <div className="mt-1 flex flex-wrap gap-x-3 text-[10.5px] text-ink-muted">
        {order.map((k) => <span key={k} className="flex items-center gap-1"><span className={cn("h-2 w-2 rounded-full", TONE[k])} />{SRC_SHORT[k]} {parts[k]}</span>)}
      </div>
    </div>
  );
}

export function Coverage() {
  const q = useQuery({ queryKey: ["coverage"], queryFn: () => api<any>("/api/admin/coverage"), staleTime: 60_000 });
  const [filter, setFilter] = useState<"all" | "none" | "default_q">("all");
  const d = q.data;
  const rows = useMemo(() => (d?.molecules ?? []).filter((m: any) =>
    filter === "none" ? m.sources.length === 0 : filter === "default_q" ? m.q === "default" : true), [d, filter]);
  if (q.isLoading) return <PageSkeleton />;
  if (q.error) return <ErrorNote error={q.error} />;

  return (
    <div className="space-y-5">
      <Card className="p-5">
        <div className="mb-4 text-[15px] font-semibold">Limits for the {d.tracked} tracked molecules: where each comes from</div>
        <div className="grid gap-5 md:grid-cols-3">
          <Share label="Assay limits" parts={d.limits.assay} total={d.tracked} />
          <Share label="Dissolution Q and time" parts={d.limits.q} total={d.tracked} />
          <Share label="Dissolution method" parts={d.limits.method} total={d.tracked} />
        </div>
        <p className="mt-3 text-[11px] text-ink-muted">"default" is the generic value the models fall back on. {d.no_official_source.length} molecules appear in no official source at all.</p>
      </Card>

      <Card className="overflow-hidden">
        <CardHeader title="Official sources" subtitle="Every name a source uses is resolved to a tracked molecule (core/identity.py); what it cannot map is listed, not dropped" />
        <div className="divide-y divide-line">
          {d.sources.map((s: any) => (
            <div key={s.id} className="px-5 py-3.5 text-xs">
              <div className="flex flex-wrap items-center gap-x-4 gap-y-1">
                <div className="min-w-[230px] text-[13px] font-semibold">{s.label}</div>
                {!s.loaded ? <Badge tone="slate">not imported</Badge> : <>
                  <span><b className="tabular-nums">{s.tracked_covered}</b><span className="text-ink-muted"> / {d.tracked} tracked molecules</span></span>
                  {s.entries != null && s.by_method && Object.keys(s.by_method).length > 0 &&
                    <span className="text-ink-muted"><b className="text-ink">{s.mapped}</b> of {s.entries} entries mapped</span>}
                  <span className="flex flex-wrap gap-1">{Object.entries(s.by_method).filter(([, n]) => (n as number) > 0).map(([m, n]) =>
                    <span key={m} className="rounded-md bg-slate-100 px-1.5 py-0.5 text-[10.5px] text-ink-soft">{METHOD_LABEL[m] ?? m} {n as number}</span>)}</span>
                </>}
              </div>
              {s.loaded && (
                <div className="mt-2 grid gap-2 md:grid-cols-2">
                  <details><summary className="cursor-pointer text-ink-muted hover:text-ink">Tracked molecules it does not cover ({s.tracked_missing.length})</summary>
                    <div className="mt-1 leading-relaxed text-ink-soft">{s.tracked_missing.join(", ") || "none"}</div></details>
                  {s.unmapped.length > 0 && <details><summary className="cursor-pointer text-ink-muted hover:text-ink">Its names that match no tracked molecule ({s.unmapped.length})</summary>
                    <div className="mt-1 leading-relaxed text-ink-soft">{s.unmapped.join(", ")}</div>
                    <div className="mt-1 text-[10.5px] text-ink-faint">Checked against PubChem's compound for each name too: these are other drugs, not tracked molecules under another name.</div></details>}
                </div>)}
              {s.note && <div className="mt-1 text-[10.5px] text-ink-faint">{s.note}</div>}
            </div>))}
        </div>
      </Card>

      <Card className="overflow-hidden">
        <CardHeader title="Molecule by molecule" subtitle="Which official sources hold it, and the source of each limit the models use" />
        <div className="px-5 pt-3"><Segmented value={filter} onChange={setFilter} options={[
          { value: "all", label: `All ${d.tracked}` }, { value: "default_q", label: "Q still generic" }, { value: "none", label: "In no source" }]} /></div>
        <div className="mt-3 max-h-[560px] overflow-auto">
          <table className="w-full text-xs">
            <thead className="sticky top-0 bg-slate-50 text-[10.5px] uppercase tracking-wide text-ink-muted"><tr>
              <th className="px-5 py-2 text-left">Molecule</th><th className="px-3 py-2 text-left">In sources</th>
              <th className="px-3 py-2 text-left">Assay</th><th className="px-3 py-2 text-left">Q</th><th className="px-3 py-2 text-left">Method</th></tr></thead>
            <tbody>{rows.map((m: any) => (
              <tr key={m.key} className="border-t border-line">
                <td className="px-5 py-1.5 font-medium">{m.key.replace(/_/g, " ")}</td>
                <td className="px-3 py-1.5"><span className="flex flex-wrap gap-1">{m.sources.map((s: string) => <span key={s} className="rounded bg-slate-100 px-1.5 text-[10.5px]">{SRC_SHORT[s] ?? s}</span>)}</span></td>
                {(["assay", "q", "method"] as const).map((f) => <td key={f} className="px-3 py-1.5">
                  <span className={cn("rounded px-1.5 py-0.5 text-[10.5px]", m[f] === "default" ? "text-ink-faint" : "bg-brand-50 font-semibold text-brand-800")}>{SRC_SHORT[m[f]] ?? m[f]}</span></td>)}
              </tr>))}</tbody>
          </table>
        </div>
      </Card>
    </div>
  );
}
