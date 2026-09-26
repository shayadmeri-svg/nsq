import { keepPreviousData, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertOctagon, BadgeCheck, ChevronLeft, ChevronRight, Factory, MapPin, PackageX, Plus, Search } from "lucide-react";
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { RankBars } from "../../components/charts";
import { Badge, Button, Card, CardHeader, Drawer, ErrorNote, PageHeader, PageSkeleton, Segmented, Stat } from "../../components/ui";
import { Estimate } from "../../components/ui/Estimate";
import { useToast } from "../../components/ui/toast";
import { api, post } from "../../lib/api";
import { cn } from "../../lib/cn";
import { fmtMonth } from "../../lib/format";

export function FdaBadges({ fda }: { fda: any }) {
  return (
    <div className="flex flex-wrap gap-1">
      {fda.registered && <Badge tone={fda.match === "site" ? "brand" : "sky"}><BadgeCheck size={11} /> FDA reg.{fda.match === "company" ? " (co.)" : ""}</Badge>}
      {fda.import_alert?.length > 0 && <Badge tone="rose"><AlertOctagon size={11} /> Import alert</Badge>}
      {fda.recalls && <Badge tone="amber"><PackageX size={11} /> {fda.recalls.recalls} US recalls</Badge>}
    </div>
  );
}

export function SiteDetail({ site, actions }: { site: any; actions?: React.ReactNode }) {
  const fda = site.fda;
  return (
    <div className="space-y-5 text-sm">
      <div className="flex items-start gap-2 text-ink-soft"><MapPin size={15} className="mt-0.5 shrink-0" />{site.address}</div>
      <div className="grid grid-cols-3 gap-3">
        <div className="rounded-xl bg-slate-50 p-3"><div className="label">NSQ alerts</div><div className="mt-1 font-display text-xl font-bold">{site.alerts}</div><div className="text-[11px] text-ink-muted">{fmtMonth(site.first)} – {fmtMonth(site.last)}</div></div>
        <div className="rounded-xl bg-slate-50 p-3"><div className="label">Products</div><div className="mt-1 font-display text-xl font-bold">{site.products}</div></div>
        <div className="rounded-xl bg-slate-50 p-3"><div className="label">State</div><div className="mt-1 font-semibold">{site.state || "—"}</div><div className="text-[11px] text-ink-muted">{site.pincode || "no PIN"}</div></div>
      </div>
      <div>
        <div className="label mb-1.5 flex items-center gap-1.5">What it makes (from alerted products) <Estimate field="capability_inferred" /></div>
        <div className="flex flex-wrap gap-1.5">{Object.entries(site.forms).map(([f, n]: any) => <Badge key={f}>{f} · {n}</Badge>)}</div>
        <div className="mt-2 flex flex-wrap gap-1">{site.capabilities.map((c: string) => <span key={c} className="rounded-md border border-dashed border-sky-400 px-1.5 py-0.5 text-[11px] text-sky-800">{c.replace(/_/g, " ")}</span>)}</div>
        <div className="mt-2 text-xs text-ink-muted">Top ingredients: {site.top_ingredients.join(", ")}</div>
      </div>
      <div>
        <div className="label mb-1.5">FDA public records</div>
        {!fda.registered && !fda.import_alert?.length && !fda.recalls && <div className="text-xs text-ink-muted">No match in the fetched FDA files (establishment registrations, Import Alert 66-40, recalls). Fetch them under Pipelines if they have not run.</div>}
        {fda.establishments?.map((e: any) => (
          <div key={e.fei || e.name} className="mb-1.5 rounded-lg border border-line p-2.5 text-xs">
            <div className="font-semibold">{e.name} <span className="font-normal text-ink-muted">· FEI {e.fei || "—"} · DUNS {e.duns || "—"}</span></div>
            <div className="text-ink-muted">{e.address} {e.city} {e.postal}</div>
            {e.operations?.length > 0 && <div className="mt-1">Operations: {e.operations.join(", ")}</div>}
            <div className="mt-0.5 text-ink-faint">{fda.match === "site" ? "Matched on company + PIN code" : "Matched on company name only — may be a different site"}</div>
          </div>
        ))}
        {fda.import_alert?.map((a: any) => (
          <div key={a.name} className="mb-1.5 rounded-lg bg-rose-50 p-2.5 text-xs text-rose-900"><b>Import Alert 66-40:</b> {a.name}{a.fei ? ` (FEI ${a.fei})` : ""} · {a.address} · published {(a.dates ?? []).join(", ")}</div>
        ))}
        {fda.recalls && (
          <div className="rounded-lg bg-amber-50 p-2.5 text-xs text-amber-900">
            <b>{fda.recalls.recalls} US recalls</b> ({fda.recalls.class_i} Class I), latest {fda.recalls.last}
            <ul className="mt-1 list-disc pl-4">{fda.recalls.items.slice(0, 4).map((r: any) => <li key={r.recall_number || r.date}>{r.classification}: {r.reason}</li>)}</ul>
          </div>
        )}
      </div>
      {actions}
    </div>
  );
}

function SiteDrawer({ id, onClose }: { id?: string; onClose: () => void }) {
  const { data, error } = useQuery({ queryKey: ["site", id], queryFn: () => api<any>(`/api/pipelines/sites/${id}`), enabled: !!id });
  const toast = useToast();
  const qc = useQueryClient();
  const add = async (slug: string) => {
    try {
      await post(`/api/orgs/${slug}/plants/from-site`, { site_id: id });
      toast("Plant added — capabilities are marked inferred until the organisation confirms them.");
      qc.invalidateQueries({ queryKey: ["site", id] });
    } catch (e) {
      toast((e as Error).message, "error");
    }
  };
  return (
    <Drawer open={!!id} onClose={onClose} title={data?.company ?? "Site"} subtitle={data ? <FdaBadges fda={data.fda} /> : undefined} width={720}>
      {error ? <ErrorNote error={error} /> : !data ? <div className="text-sm text-ink-muted">Loading…</div> : (
        <SiteDetail site={data} actions={
          <div>
            <div className="label mb-1.5">Organisations for this manufacturer</div>
            {data.orgs.length === 0 && <div className="text-xs text-ink-muted">No organisation is linked to <span className="font-mono">{data.ontology_key}</span>. Link it in <Link to="/admin/orgs" className="text-brand-700 hover:underline">Organisations</Link> first.</div>}
            {data.orgs.map((o: any) => (
              <div key={o.slug} className="flex items-center justify-between rounded-lg border border-line px-3 py-2 text-sm">
                <span className="font-semibold">{o.name}</span>
                {o.linked ? <Badge tone="brand">already a plant</Badge> : <Button size="sm" onClick={() => add(o.slug)}><Plus size={13} /> Add as plant</Button>}
              </div>
            ))}
          </div>
        } />
      )}
    </Drawer>
  );
}

export function Sites() {
  const summary = useQuery({ queryKey: ["sites-summary"], queryFn: () => api<any>("/api/pipelines/sites/summary") });
  const [q, setQ] = useState("");
  const [dq, setDq] = useState("");
  const [state, setState] = useState("");
  const [form, setForm] = useState("");
  const [fda, setFda] = useState<"" | "registered" | "import_alert" | "recalls">("");
  const [page, setPage] = useState(1);
  const [open, setOpen] = useState<string | undefined>();
  useEffect(() => { const t = setTimeout(() => { setDq(q); setPage(1); }, 250); return () => clearTimeout(t); }, [q]);
  const list = useQuery({
    queryKey: ["sites", dq, state, form, fda, page],
    queryFn: () => api<any>(`/api/pipelines/sites?${new URLSearchParams({ q: dq, state, form, fda, page: String(page), size: "25" })}`),
    placeholderData: keepPreviousData,
  });
  if (summary.isLoading) return <PageSkeleton />;
  if (summary.error) return <ErrorNote error={summary.error} />;
  const s = summary.data;

  return (
    <>
      <PageHeader eyebrow="Platform · Pipelines" title="Site directory" subtitle="Every Indian manufacturing site named in CDSCO NSQ alerts (one manufacturer at one PIN code), joined with FDA establishment registrations, Import Alert 66-40 and US recalls." />
      <div className="grid grid-cols-2 gap-4 xl:grid-cols-4">
        <Stat label="Sites" value={s.sites} icon={<Factory size={18} />} hint={`${s.companies.toLocaleString("en-IN")} manufacturers · ${s.with_pincode.toLocaleString("en-IN")} with a PIN code`} />
        <Stat label="FDA-registered" value={s.fda_registered} tone="indigo" delay={0.05} hint={`${s.fda_site_match} matched to the exact site`} />
        <Stat label="On import alert" value={s.import_alert} tone="rose" delay={0.1} hint="FDA drug-GMP red list" />
        <Stat label="With US recalls" value={s.recalls} tone="amber" delay={0.15} hint="openFDA enforcement reports" />
      </div>
      <div className="mt-5 grid gap-5 lg:grid-cols-2">
        <Card delay={0.1}><CardHeader title="Sites by state" subtitle="Click to filter" /><div className="p-5"><RankBars rows={s.states.slice(0, 10).map((x: any) => ({ name: x.name, count: x.count }))} color="#6366f1" onClick={(n) => { setState(state === n ? "" : n); setPage(1); }} /></div></Card>
        <Card delay={0.15}><CardHeader title="Dosage forms made" subtitle="Sites with alerts in each form · click to filter" /><div className="p-5"><RankBars rows={s.forms.map((x: any) => ({ name: x.name, count: x.count }))} color="#f59e0b" onClick={(n) => { setForm(form === n ? "" : n); setPage(1); }} /></div></Card>
      </div>
      <Card delay={0.2} className="mt-5">
        <CardHeader title="Sites" subtitle={`${list.data?.total?.toLocaleString("en-IN") ?? "…"} sites`} action={
          <div className="flex flex-wrap items-center gap-2">
            {(state || form) && <button onClick={() => { setState(""); setForm(""); }}><Badge tone="indigo">{[state, form].filter(Boolean).join(" · ")} ✕</Badge></button>}
            <Segmented value={fda} onChange={(v) => { setFda(v); setPage(1); }} options={[{ value: "", label: "All" }, { value: "registered", label: "FDA reg." }, { value: "import_alert", label: "Import alert" }, { value: "recalls", label: "Recalls" }]} />
            <div className="relative"><Search size={15} className="absolute left-3 top-2.5 text-ink-faint" /><input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Company, address or PIN…" className="input h-9 w-60 pl-9" /></div>
          </div>
        } />
        <div className="mt-4 overflow-x-auto">
          <table className={cn("w-full text-sm", list.isFetching && "opacity-60")}>
            <thead><tr className="border-y border-line bg-slate-50/70 text-left text-[11px] font-semibold uppercase tracking-wider text-ink-muted">
              <th className="px-5 py-2.5">Site</th><th className="px-3 py-2.5">State</th><th className="px-3 py-2.5">Forms</th><th className="px-3 py-2.5 text-right">Alerts</th><th className="px-3 py-2.5">Last</th><th className="px-5 py-2.5">FDA</th>
            </tr></thead>
            <tbody>
              {list.data?.items.map((x: any) => (
                <tr key={x.id} onClick={() => setOpen(x.id)} className="cursor-pointer border-b border-line/70 hover:bg-slate-50">
                  <td className="max-w-[340px] px-5 py-2.5"><div className="truncate font-semibold">{x.company}</div><div className="truncate text-[11px] text-ink-muted" title={x.address}>{x.city || x.address}</div></td>
                  <td className="px-3 py-2.5 text-xs">{x.state || "—"}<div className="text-ink-faint">{x.pincode}</div></td>
                  <td className="px-3 py-2.5"><div className="flex max-w-[220px] flex-wrap gap-1">{Object.keys(x.forms).slice(0, 3).map((f) => <span key={f} className="rounded-md bg-slate-100 px-1.5 py-0.5 text-[10.5px]">{f}</span>)}</div></td>
                  <td className="px-3 py-2.5 text-right tabular-nums">{x.alerts}</td>
                  <td className="px-3 py-2.5 text-xs text-ink-muted">{fmtMonth(x.last)}</td>
                  <td className="px-5 py-2.5"><FdaBadges fda={x.fda} /></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {list.data && (
          <div className="flex items-center justify-between px-5 py-3 text-xs text-ink-muted">
            <span>Page {list.data.page} of {list.data.pages}</span>
            <div className="flex gap-1.5"><Button size="sm" variant="secondary" disabled={page <= 1} onClick={() => setPage(page - 1)}><ChevronLeft size={14} /></Button><Button size="sm" variant="secondary" disabled={page >= list.data.pages} onClick={() => setPage(page + 1)}><ChevronRight size={14} /></Button></div>
          </div>
        )}
      </Card>
      <SiteDrawer id={open} onClose={() => setOpen(undefined)} />
    </>
  );
}
