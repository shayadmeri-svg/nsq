// Admin · Feature access: which Playground features each organisation has. The server enforces it on every API call;
// org admins then choose which of these each persona in their organisation sees (Organisation → Feature access).
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, KeyRound, Lock, RotateCcw, ShieldCheck } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { Badge, Button, Card, Empty, ErrorNote, PageHeader, PageSkeleton } from "../../components/ui";
import { LoadingEdge } from "../../components/ui/Loading";
import { useToast } from "../../components/ui/toast";
import { api, put } from "../../lib/api";
import { cn } from "../../lib/cn";

type Feat = { id: string; label: string; group: string; hint: string; scope: string; base: boolean; notes: string };
type Row = { slug: string; name: string; is_active: boolean; entitled: string[]; configured: boolean; restricted_personas: string[] };

export function groupFeatures(reg: Feat[]) {
  const g: Record<string, Feat[]> = {};
  reg.forEach((f) => (g[f.group] ??= []).push(f));
  return Object.entries(g);
}

export function ScopeBadge({ f }: { f: Feat }) {
  return f.scope === "own"
    ? <span title="Org users only get their own organisation's records" className="inline-flex items-center gap-0.5 rounded bg-indigo-50 px-1 text-[9.5px] font-semibold uppercase tracking-wide text-indigo-700"><Lock size={9} />own data</span>
    : <span title="National aggregates of public records; other manufacturers are pseudonymised" className="rounded bg-slate-100 px-1 text-[9.5px] font-semibold uppercase tracking-wide text-ink-muted">national</span>;
}

export function Features() {
  const q = useQuery({ queryKey: ["admin-features"], queryFn: () => api<{ registry: Feat[]; base: string[]; orgs: Row[] }>("/api/admin/features") });
  const [draft, setDraft] = useState<Record<string, string[]>>({});
  const [saving, setSaving] = useState<string | null>(null);
  const qc = useQueryClient();
  const toast = useToast();
  useEffect(() => { if (q.data) setDraft(Object.fromEntries(q.data.orgs.map((o) => [o.slug, o.entitled]))); }, [q.data]);
  const groups = useMemo(() => groupFeatures(q.data?.registry ?? []), [q.data]);

  if (q.error) return <ErrorNote error={q.error} />;
  if (!q.data) return <PageSkeleton />;
  const { registry, orgs, base } = q.data;
  const dirty = (o: Row) => [...(draft[o.slug] ?? [])].sort().join() !== [...o.entitled].sort().join();
  const toggle = (slug: string, id: string) => setDraft((d) => ({ ...d, [slug]: d[slug]?.includes(id) ? d[slug].filter((x) => x !== id) : [...(d[slug] ?? []), id] }));
  const save = async (o: Row) => {
    setSaving(o.slug);
    try {
      await put(`/api/admin/orgs/${o.slug}/features`, { features: draft[o.slug] ?? [] });
      await qc.invalidateQueries({ queryKey: ["admin-features"] });
      qc.invalidateQueries({ queryKey: ["me"] });
      toast(`${o.name}: ${draft[o.slug]?.length ?? 0} features`);
    } catch (e: any) {
      toast(e?.message ?? "Could not save", "error");
    } finally {
      setSaving(null);
    }
  };

  return (
    <>
      <PageHeader eyebrow="Access control" title="Feature access by organisation"
        subtitle="Tick what each organisation has. Its users can only call these tools — the API checks it on every request — and the organisation admin decides which of them each persona sees. No organisation ever receives another organisation's records." />

      <div className="mb-4 grid gap-3 md:grid-cols-3">
        <Card className="p-4 text-xs text-ink-soft"><div className="mb-1 flex items-center gap-1.5 font-semibold text-ink"><KeyRound size={14} /> 1 · You grant</div>Features per organisation, below. An organisation you haven't set up gets the base package ({base.map((b) => registry.find((f) => f.id === b)?.label).join(", ")}).</Card>
        <Card className="p-4 text-xs text-ink-soft"><div className="mb-1 flex items-center gap-1.5 font-semibold text-ink"><ShieldCheck size={14} /> 2 · Org admin shares</div>Which granted features the QA, Regulatory and Executive members see. Org admins always see everything granted.</Card>
        <Card className="p-4 text-xs text-ink-soft"><div className="mb-1 flex items-center gap-1.5 font-semibold text-ink"><Lock size={14} /> 3 · Isolation</div><b>Own data</b> tools return only the organisation's records; <b>national</b> tools show public aggregates with every other manufacturer pseudonymised.</Card>
      </div>

      {!orgs.length ? <Empty title="No organisations yet"><Link to="/admin/orgs" className="text-brand-700 hover:underline">Create one</Link> first.</Empty> : (
        <Card className="relative overflow-x-auto p-0"><LoadingEdge active={q.isFetching} />
          <table className="w-full min-w-[900px] border-separate border-spacing-0 text-sm">
            <thead>
              <tr>
                <th className="sticky left-0 z-10 bg-white px-4 pb-1 pt-3 text-left align-bottom" rowSpan={2}><span className="label">Organisation</span></th>
                {groups.map(([g, fs]) => <th key={g} colSpan={fs.length} className="border-l border-line px-2 pt-3 text-center text-[10.5px] font-semibold uppercase tracking-wider text-ink-muted">{g}</th>)}
                <th rowSpan={2} className="px-3" />
              </tr>
              <tr>
                {groups.flatMap(([, fs]) => fs).map((f, i) => (
                  <th key={f.id} title={`${f.hint}${f.notes ? " — " + f.notes : ""}`} className={cn("px-1.5 pb-2 pt-1 text-center align-bottom", i === 0 && "border-l border-line")}>
                    <div className="mx-auto w-[74px] text-[11px] font-semibold leading-tight text-ink">{f.label}</div>
                    <div className="mt-1"><ScopeBadge f={f} /></div>
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {orgs.map((o) => {
                const set = new Set(draft[o.slug] ?? []);
                return (
                  <tr key={o.slug} className="group">
                    <td className="sticky left-0 z-10 border-t border-line bg-white px-4 py-2.5 group-hover:bg-slate-50">
                      <div className="font-medium">{o.name}</div>
                      <div className="flex flex-wrap items-center gap-1 text-[11px] text-ink-muted">
                        {!o.is_active && <Badge tone="rose">disabled</Badge>}
                        {!o.configured && <Badge tone="slate">base package</Badge>}
                        {o.restricted_personas.length > 0 && <span title="The org admin narrowed what these personas see">narrowed for {o.restricted_personas.join(", ")}</span>}
                        <span className="text-ink-faint">{set.size}/{registry.length}</span>
                      </div>
                    </td>
                    {groups.flatMap(([, fs]) => fs).map((f, i) => {
                      const on = set.has(f.id);
                      return (
                        <td key={f.id} className={cn("border-t border-line px-1.5 text-center group-hover:bg-slate-50", i === 0 && "border-l")}>
                          <button onClick={() => toggle(o.slug, f.id)} aria-pressed={on} aria-label={`${f.label} for ${o.name}`}
                            className={cn("grid h-7 w-7 place-items-center rounded-lg ring-1 ring-inset transition mx-auto",
                              on ? "bg-brand-600 text-white ring-brand-600 hover:bg-brand-700" : "bg-white text-transparent ring-line hover:ring-brand-300")}>
                            <Check size={15} strokeWidth={3} />
                          </button>
                        </td>
                      );
                    })}
                    <td className="whitespace-nowrap border-t border-line px-3 text-right group-hover:bg-slate-50">
                      {dirty(o) ? (
                        <div className="flex items-center justify-end gap-1.5">
                          <Button size="sm" variant="ghost" onClick={() => setDraft((d) => ({ ...d, [o.slug]: o.entitled }))} title="Undo"><RotateCcw size={13} /></Button>
                          <Button size="sm" loading={saving === o.slug} onClick={() => save(o)}>Save</Button>
                        </div>
                      ) : <span className="text-[11px] text-ink-faint">saved</span>}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </Card>
      )}
    </>
  );
}
