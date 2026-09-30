// Organisation · Feature access: the org admin decides which of the organisation's Playground features each
// member persona sees. Platform admins decide what the organisation has (Admin → Feature access).
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, Compass, Crown, Eye } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { Button, Card, Empty, ErrorNote, PageHeader, PageSkeleton } from "../../components/ui";
import { useToast } from "../../components/ui/toast";
import { api, put } from "../../lib/api";
import { cn } from "../../lib/cn";
import { groupFeatures, ScopeBadge } from "../admin/Features";
import { useOrg } from "./common";

type Payload = { registry: any[]; entitled: string[]; visibility: Record<string, string[] | null>; personas: string[]; configured: boolean; can_manage: boolean; mine: string[] };

export function FeatureAccess() {
  const { org, slug } = useOrg();
  const q = useQuery({ queryKey: ["org", slug, "features"], enabled: !!slug, queryFn: () => api<Payload>(`/api/orgs/${slug}/features`) });
  const [vis, setVis] = useState<Record<string, string[] | null>>({});
  const [busy, setBusy] = useState(false);
  const qc = useQueryClient();
  const toast = useToast();
  useEffect(() => { if (q.data) setVis(q.data.visibility); }, [q.data]);
  const groups = useMemo(() => groupFeatures(q.data?.registry ?? []), [q.data]);

  if (q.error) return <ErrorNote error={q.error} />;
  if (!q.data) return <PageSkeleton />;
  const d = q.data;
  const sees = (p: string, id: string) => (vis[p] == null ? true : vis[p]!.includes(id));
  const toggle = (p: string, id: string) => setVis((v) => {
    const cur = v[p] == null ? [...d.entitled] : [...v[p]!];
    const next = cur.includes(id) ? cur.filter((x) => x !== id) : [...cur, id];
    return { ...v, [p]: next.length === d.entitled.length ? null : next };  // everything = "follows the organisation"
  });
  const dirty = JSON.stringify(vis) !== JSON.stringify(d.visibility);
  const save = async () => {
    setBusy(true);
    try {
      await put(`/api/orgs/${slug}/features/visibility`, { visibility: vis });
      await qc.invalidateQueries({ queryKey: ["org", slug, "features"] });
      qc.invalidateQueries({ queryKey: ["me"] });
      toast("Access saved — members see the change on their next page load");
    } catch (e: any) {
      toast(e?.message ?? "Could not save", "error");
    } finally {
      setBusy(false);
    }
  };

  return (
    <>
      <PageHeader eyebrow="Feature access" title={`Who sees what at ${org?.name ?? "…"}`}
        subtitle="Your organisation's Playground tools, and which of them each persona sees. Org admins see every tool the organisation has. Everything is limited to your organisation's own records — other companies never appear by name."
        actions={d.can_manage ? <Button disabled={!dirty} loading={busy} onClick={save}>Save changes</Button> : undefined} />

      {!d.entitled.length ? (
        <Empty icon={<Compass />} title="No Playground tools for this organisation">A platform admin grants tools to organisations. Ask them to enable the ones you need.</Empty>
      ) : (
        <Card className="overflow-x-auto p-0">
          <table className="w-full min-w-[640px] border-separate border-spacing-0 text-sm">
            <thead>
              <tr className="text-left">
                <th className="px-4 pb-2 pt-4"><span className="label">Tool</span></th>
                <th className="w-28 px-2 pb-2 pt-4 text-center"><div className="flex flex-col items-center gap-0.5 text-[11px] font-semibold"><Crown size={14} className="text-amber-500" />Org admin</div></th>
                {d.personas.map((p) => (
                  <th key={p} className="w-28 px-2 pb-2 pt-4 text-center">
                    <div className="flex flex-col items-center gap-0.5 text-[11px] font-semibold"><Eye size={14} className="text-ink-muted" />{p}</div>
                    <div className="text-[10px] font-normal text-ink-faint">{vis[p] == null ? "all tools" : `${vis[p]!.length} of ${d.entitled.length}`}</div>
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {groups.map(([g, fs]) => [
                <tr key={g}><td colSpan={2 + d.personas.length} className="border-t border-line bg-slate-50/70 px-4 py-1.5 text-[10.5px] font-semibold uppercase tracking-wider text-ink-muted">{g}</td></tr>,
                ...fs.map((f: any) => (
                  <tr key={f.id} className="hover:bg-slate-50/60">
                    <td className="border-t border-line px-4 py-2.5">
                      <div className="flex items-center gap-2 font-medium">
                        {d.mine.includes(f.id) ? <Link to={`/o/${slug}/playground/${f.id}`} className="hover:text-brand-700 hover:underline">{f.label}</Link> : f.label}
                        <ScopeBadge f={f} />
                      </div>
                      <div className="text-[11.5px] text-ink-muted">{f.hint}{f.notes ? ` · ${f.notes}` : ""}</div>
                    </td>
                    <td className="border-t border-line text-center"><span className="mx-auto grid h-7 w-7 place-items-center rounded-lg bg-slate-100 text-ink-muted" title="Org admins see every tool the organisation has"><Check size={14} strokeWidth={3} /></span></td>
                    {d.personas.map((p) => {
                      const on = sees(p, f.id);
                      return (
                        <td key={p} className="border-t border-line text-center">
                          <button disabled={!d.can_manage} onClick={() => toggle(p, f.id)} aria-pressed={on} aria-label={`${f.label} for ${p}`}
                            className={cn("mx-auto grid h-7 w-7 place-items-center rounded-lg ring-1 ring-inset transition disabled:cursor-not-allowed",
                              on ? "bg-brand-600 text-white ring-brand-600 enabled:hover:bg-brand-700" : "bg-white text-transparent ring-line enabled:hover:ring-brand-300")}>
                            <Check size={15} strokeWidth={3} />
                          </button>
                        </td>
                      );
                    })}
                  </tr>
                )),
              ])}
            </tbody>
          </table>
        </Card>
      )}
      <p className="mt-3 text-xs text-ink-muted">A member's persona is set on the <Link to={`/o/${slug}/team`} className="text-brand-700 hover:underline">Team</Link> page. Tools a platform admin adds later are shown to a persona only if that persona sees all tools today.</p>
    </>
  );
}
