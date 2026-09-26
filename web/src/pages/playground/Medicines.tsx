import { useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, CheckCircle2, ExternalLink, FlaskConical, Info, Pill, Plus, RefreshCw, Save, Search, Trash2 } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { Badge, Button, Card, CardHeader, ErrorNote, Skeleton } from "../../components/ui";
import { api, del, post, put } from "../../lib/api";
import { cn } from "../../lib/cn";
import { useMe } from "../../lib/session";
import { useToast } from "../../components/ui/toast";

type Ing = Record<string, any>;
type Med = { id?: number; name: string; brand: string; dosage_form: string; route: string; ingredients: Ing[]; excipients: string[]; identifiers: any; sources: any; notes?: string;
  gaps?: any[]; gap_score?: any; us_market?: any; rxnorm?: any; label?: any; nsq?: any; offline?: string[] };

const FORMS = ["Tablet", "Capsule", "Syrup", "Suspension", "Injection", "Cream", "Ointment", "Gel", "Drops", "Powder", "Granules", "Inhaler", "Solution", "Lotion", "Spray", "Suppository"];
const STATUS: Record<string, { icon: any; cls: string; label: string }> = {
  ok: { icon: CheckCircle2, cls: "text-emerald-600", label: "have it" },
  missing: { icon: AlertTriangle, cls: "text-rose-600", label: "missing" },
  estimate: { icon: FlaskConical, cls: "text-amber-600", label: "estimated / defaulted" },
  info: { icon: Info, cls: "text-sky-600", label: "not available openly" },
};

function Structure({ smiles }: { smiles?: string }) {
  const q = useQuery({ queryKey: ["struct", smiles], queryFn: () => post<any>("/api/lab/structure", { smiles, width: 150, height: 100 }), enabled: !!smiles, staleTime: Infinity, retry: false });
  if (!smiles) return <div className="flex h-[100px] w-[150px] items-center justify-center rounded-lg bg-slate-50 text-[10px] text-ink-faint">no structure</div>;
  if (q.error) return <div className="flex h-[100px] w-[150px] items-center justify-center rounded-lg bg-rose-50 text-[10px] text-rose-600">invalid SMILES</div>;
  return <div className="h-[100px] w-[150px] rounded-lg bg-white ring-1 ring-line" dangerouslySetInnerHTML={{ __html: q.data?.svg ?? "" }} />;
}

function Gaps({ gaps }: { gaps: any[] }) {
  const areas = useMemo(() => [...new Set(gaps.map((g) => g.area))], [gaps]);
  const c = (s: string) => gaps.filter((g) => g.status === s).length;
  return (
    <Card>
      <CardHeader title="What's known and what's missing" subtitle={`${c("ok")} known · ${c("missing")} missing · ${c("estimate")} estimated or defaulted · ${c("info")} not available from open sources`} />
      <div className="grid gap-4 p-5 lg:grid-cols-2">
        {areas.map((a) => (
          <div key={a}>
            <div className="label mb-1.5">{a}</div>
            <div className="space-y-1">
              {gaps.filter((g) => g.area === a).map((g, i) => {
                const S = STATUS[g.status] ?? STATUS.info;
                return (
                  <div key={i} className="flex gap-2 rounded-lg px-2 py-1.5 text-xs hover:bg-slate-50" title={g.fix}>
                    <S.icon size={14} className={cn("mt-0.5 shrink-0", S.cls)} />
                    <div className="min-w-0"><b className="font-semibold">{g.item}</b> <span className="text-ink-muted">· {g.detail}</span>{g.fix && <div className="text-[11px] text-ink-faint">{g.fix}</div>}</div>
                  </div>
                );
              })}
            </div>
          </div>
        ))}
      </div>
    </Card>
  );
}

function IngredientRow({ a, onChange, onRemove }: { a: Ing; onChange: (a: Ing) => void; onRemove: () => void }) {
  const [busy, setBusy] = useState(false);
  const toast = useToast();
  const refetch = async () => {
    setBusy(true);
    try { onChange({ ...(await post<any>("/api/medicines/ingredient", { name: a.name, strength: a.strength, role: a.role })), strength: a.strength, role: a.role }); }
    catch (e) { toast((e as Error).message, "error"); }
    finally { setBusy(false); }
  };
  const s = a.strength ?? {};
  return (
    <div className="flex flex-wrap items-start gap-4 border-b border-line/70 py-3 last:border-0">
      <Structure smiles={a.smiles} />
      <div className="min-w-[280px] flex-1 space-y-2 text-xs">
        <div className="flex flex-wrap items-center gap-2">
          <input className="input h-8 w-56 text-sm font-semibold" value={a.name} onChange={(e) => onChange({ ...a, name: e.target.value })} />
          <input className="input h-8 w-20 text-xs" type="number" placeholder="amount" value={s.value ?? ""} onChange={(e) => onChange({ ...a, strength: e.target.value ? { ...s, value: Number(e.target.value), unit: s.unit || "mg" } : null })} />
          <select className="input h-8 w-20 text-xs" value={s.unit ?? "mg"} onChange={(e) => onChange({ ...a, strength: { ...s, unit: e.target.value } })}>{["mg", "mcg", "g", "iu", "%", "ml"].map((u) => <option key={u}>{u}</option>)}</select>
          <input className="input h-8 w-20 text-xs" placeholder="per" value={s.per ?? ""} onChange={(e) => onChange({ ...a, strength: { ...s, per: e.target.value || null } })} />
          <select className="input h-8 w-24 text-xs" value={a.role ?? "active"} onChange={(e) => onChange({ ...a, role: e.target.value })}><option value="active">active</option><option value="inactive">inactive</option></select>
          <Button size="sm" variant="secondary" onClick={refetch} loading={busy}><RefreshCw size={12} /> Chemistry</Button>
          <button onClick={onRemove} className="text-ink-faint hover:text-rose-600"><Trash2 size={14} /></button>
        </div>
        <input className="input h-7 w-full font-mono text-[10.5px]" placeholder="SMILES (fetched from PubChem / ChEMBL, or paste one)" value={a.smiles ?? ""} onChange={(e) => onChange({ ...a, smiles: e.target.value, structure_source: e.target.value ? "typed" : null })} />
        <div className="flex flex-wrap gap-1.5">
          {a.structure_source && <Badge tone="sky">structure: {a.structure_source}</Badge>}
          {a.mp_c != null && <Badge>mp {a.mp_c} °C</Badge>}
          {a.xlogp != null ? <Badge>XLogP3 {a.xlogp}</Badge> : a.logp_predicted != null && <Badge>logP {a.logp_predicted} (pred.)</Badge>}
          {a.pka_acid != null && <Badge tone="indigo">pKa acid {a.pka_acid}</Badge>}
          {a.pka_base != null && <Badge tone="indigo">pKa base {a.pka_base}</Badge>}
          {a.max_phase != null && <Badge tone="brand">phase {a.max_phase}{a.first_approval ? ` · approved ${a.first_approval}` : ""}</Badge>}
          {(a.atc ?? []).slice(0, 3).map((x: string) => <Badge key={x}>ATC {x}</Badge>)}
          {a.us_strengths?.length > 0 && !a.strength && <Badge tone="amber">US: {a.us_strengths.slice(0, 3).join(", ")}</Badge>}
          {Object.entries(a.links ?? {}).map(([k, v]: any) => <a key={k} href={v} target="_blank" rel="noreferrer" className="inline-flex items-center gap-0.5 text-[10.5px] text-brand-700 hover:underline">{k}<ExternalLink size={10} /></a>)}
          {a.molecule_key && a.smiles && <Link to={`/playground/process?m=${a.molecule_key}`} className="text-[10.5px] font-semibold text-brand-700 hover:underline">Open in Lab →</Link>}
        </div>
        {a.mechanisms?.length > 0 && <div className="text-[11px] text-ink-muted">{a.mechanisms.join("; ")}</div>}
      </div>
    </div>
  );
}

function Editor({ m, setM, canEdit, onSaved }: { m: Med; setM: (m: Med) => void; canEdit: boolean; onSaved: () => void }) {
  const toast = useToast();
  const [busy, setBusy] = useState(false);
  const [exText, setExText] = useState(m.excipients.join(", "));
  useEffect(() => setExText(m.excipients.join(", ")), [m.id, m.name]); // eslint-disable-line
  const setIng = (i: number, a: Ing) => setM({ ...m, ingredients: m.ingredients.map((x, j) => (j === i ? a : x)) });
  const save = async () => {
    setBusy(true);
    try {
      const body = { ...m, excipients: exText.split(",").map((s) => s.trim()).filter(Boolean) };
      const r = m.id ? await put<any>(`/api/medicines/${m.id}`, body) : await post<any>("/api/medicines", body);
      setM({ ...m, ...r });
      toast(r.tracked?.length ? `${r.name} saved. Added ${r.tracked.join(", ")} to the molecule universe; rebuilding (job #${r.run_id ?? "queued"}).` : `${r.name} saved. Its ingredients are in the Lab.`);
      onSaved();
    } catch (e) { toast((e as Error).message, "error"); } finally { setBusy(false); }
  };
  const nsq = m.nsq;
  return (
    <div className="space-y-5">
      <Card>
        <CardHeader title={m.id ? "Edit medicine" : "New medicine"} subtitle="Pre-filled from open databases where they know this product; every field can be corrected"
          action={canEdit ? <Button onClick={save} loading={busy}><Save size={14} /> {m.id ? "Save changes" : "Add medicine"}</Button> : <Badge>view only · super admin adds medicines</Badge>} />
        <div className="grid gap-3 p-5 md:grid-cols-4">
          <label className="text-xs md:col-span-2"><div className="mb-1 font-medium text-ink-soft">Product name</div><input className="input h-9 w-full" value={m.name} onChange={(e) => setM({ ...m, name: e.target.value })} /></label>
          <label className="text-xs"><div className="mb-1 font-medium text-ink-soft">Brand</div><input className="input h-9 w-full" value={m.brand} onChange={(e) => setM({ ...m, brand: e.target.value })} /></label>
          <div className="grid grid-cols-2 gap-2">
            <label className="text-xs"><div className="mb-1 font-medium text-ink-soft">Form</div><select className="input h-9 w-full" value={m.dosage_form} onChange={(e) => setM({ ...m, dosage_form: e.target.value })}><option value="">—</option>{FORMS.map((f) => <option key={f}>{f}</option>)}</select></label>
            <label className="text-xs"><div className="mb-1 font-medium text-ink-soft">Route</div><input className="input h-9 w-full" value={m.route} onChange={(e) => setM({ ...m, route: e.target.value })} /></label>
          </div>
        </div>
        <div className="px-5">
          <div className="label mb-1">Ingredients</div>
          {m.ingredients.map((a, i) => <IngredientRow key={i} a={a} onChange={(x) => setIng(i, x)} onRemove={() => setM({ ...m, ingredients: m.ingredients.filter((_, j) => j !== i) })} />)}
          <button onClick={() => setM({ ...m, ingredients: [...m.ingredients, { name: "", role: "active", strength: null }] })} className="my-3 inline-flex items-center gap-1 text-xs font-semibold text-brand-700 hover:underline"><Plus size={13} /> Add ingredient</button>
        </div>
        <div className="border-t border-line px-5 py-4 text-xs">
          <div className="mb-1 font-medium text-ink-soft">Excipients (inactive ingredients, comma-separated){m.label?.url && <a href={m.label.url} target="_blank" rel="noreferrer" className="ml-2 text-brand-700 hover:underline">US label ↗</a>}</div>
          <textarea className="input min-h-[60px] w-full text-xs" value={exText} onChange={(e) => setExText(e.target.value)} placeholder="e.g. microcrystalline cellulose, magnesium stearate, povidone" />
        </div>
      </Card>
      <div className="grid gap-5 xl:grid-cols-3">
        <Card className="p-4 text-xs">
          <div className="label mb-2">NSQ record for this exact composition</div>
          {nsq?.alerts ? <><div><b className="text-lg">{nsq.alerts}</b> alerts · {nsq.dissolution_pct}% dissolution · {nsq.manufacturers} makers · last {nsq.last}</div>
            <div className="mt-2 flex flex-wrap gap-1">{nsq.categories.map((c: any) => <Badge key={c.name}>{c.name} · {c.count}</Badge>)}</div></> : <div className="text-ink-muted">No NSQ alerts for products with exactly these actives.</div>}
        </Card>
        <Card className="p-4 text-xs">
          <div className="label mb-2">US market (openFDA NDC)</div>
          {m.us_market ? <><div><b>{m.us_market.products}</b> US products · {m.us_market.dosage_forms.join(", ")}</div>
            {Object.entries(m.us_market.strengths).map(([k, v]: any) => <div key={k} className="mt-1 text-ink-muted"><b className="text-ink-soft">{k}:</b> {v.join(", ")}</div>)}
            {m.us_market.brands.length > 0 && <div className="mt-1 text-ink-muted">Brands: {m.us_market.brands.slice(0, 6).join(", ")}</div>}</> : <div className="text-ink-muted">{m.offline?.includes("openfda_ndc") ? "Couldn't reach openFDA from the server; try again later." : m.id ? "Look it up again to refresh." : "Not in US product data (normal for India-only products)."}</div>}
        </Card>
        <Card className="p-4 text-xs">
          <div className="label mb-2">RxNorm</div>
          {m.rxnorm ? <><div>RxCUI {m.rxnorm.rxcui ?? "—"} · {m.rxnorm.count} clinical products</div><ul className="mt-1 max-h-32 list-disc overflow-auto pl-4 text-ink-muted scrollbar-thin">{m.rxnorm.clinical_drugs.map((x: string) => <li key={x}>{x}</li>)}</ul></> : <div className="text-ink-muted">{m.offline?.includes("rxnav") ? "Couldn't reach RxNav from the server." : "No RxNorm match."}</div>}
        </Card>
      </div>
      {m.gaps && <Gaps gaps={m.gaps} />}
    </div>
  );
}

export function Medicines() {
  const { data: me } = useMe();
  const canEdit = !!me?.permissions.edit_molecules;
  const qc = useQueryClient();
  const list = useQuery({ queryKey: ["medicines"], queryFn: () => api<any>("/api/medicines") });
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<unknown>(null);
  const [m, setM] = useState<Med | null>(null);
  const toast = useToast();
  const search = async () => {
    setBusy(true); setErr(null);
    try { setM(await api<Med>(`/api/medicines/lookup?text=${encodeURIComponent(text)}`)); } catch (e) { setErr(e); } finally { setBusy(false); }
  };
  const remove = async (id: number) => { await del(`/api/medicines/${id}`); qc.invalidateQueries({ queryKey: ["medicines"] }); toast("Removed"); if (m?.id === id) setM(null); };
  return (
    <div className="space-y-5">
      <Card className="p-4">
        <form className="flex flex-wrap items-center gap-2" onSubmit={(e) => { e.preventDefault(); if (text.trim().length > 2) search(); }}>
          <Pill size={18} className="text-brand-600" />
          <div className="relative min-w-[320px] flex-1"><Search size={15} className="absolute left-3 top-2.5 text-ink-faint" />
            <input className="input h-9 w-full pl-9" value={text} onChange={(e) => setText(e.target.value)} placeholder="Medicine as on the label, e.g. Telmisartan 40 mg + Hydrochlorothiazide 12.5 mg Tablets" /></div>
          <Button type="submit" loading={busy}>Look up</Button>
          <Button type="button" variant="secondary" onClick={() => setM({ name: text || "New medicine", brand: "", dosage_form: "", route: "", ingredients: [{ name: "", role: "active", strength: null }], excipients: [], identifiers: {}, sources: {} })}>Blank form</Button>
        </form>
        <p className="mt-2 text-[11px] text-ink-muted">Searches openFDA (US products and labels), RxNorm, ChEMBL and PubChem. Structures are drawn with RDKit. Indian-only combinations are usually not in these databases, so the composition is parsed from the name and the gaps are listed.</p>
      </Card>
      {err ? <ErrorNote error={err} /> : null}
      {busy && <Skeleton className="h-64" />}
      {m && !busy && <Editor m={m} setM={setM} canEdit={canEdit} onSaved={() => qc.invalidateQueries({ queryKey: ["medicines"] })} />}
      <Card>
        <CardHeader title="Medicines added" subtitle="Their active ingredients appear in the Lab with the structures and properties fetched here" />
        {list.error ? <ErrorNote error={list.error} /> : !list.data ? <Skeleton className="m-5 h-20" /> : list.data.items.length === 0 ? <div className="p-5 text-xs text-ink-muted">None yet.</div> : (
          <table className="w-full text-xs">
            <thead><tr className="border-y border-line bg-slate-50/70 text-left text-[10.5px] uppercase tracking-wider text-ink-muted"><th className="px-5 py-2">Medicine</th><th className="px-3 py-2">Actives</th><th className="px-3 py-2">Form</th><th className="px-3 py-2">Known / gaps</th><th className="px-5 py-2" /></tr></thead>
            <tbody>{list.data.items.map((x: any) => (
              <tr key={x.id} className="cursor-pointer border-b border-line/60 hover:bg-slate-50" onClick={() => setM(x)}>
                <td className="px-5 py-2 font-medium">{x.name}{x.brand && <span className="text-ink-muted"> · {x.brand}</span>}</td>
                <td className="px-3 py-2">{x.ingredients.filter((a: any) => a.role === "active").map((a: any) => `${a.name}${a.strength ? ` ${a.strength.value} ${a.strength.unit}` : ""}`).join(" + ")}</td>
                <td className="px-3 py-2">{x.dosage_form}</td>
                <td className="px-3 py-2"><span className="text-emerald-700">{x.gap_score.ok}</span> / <span className="text-rose-700">{x.gap_score.missing}</span> missing · <span className="text-amber-700">{x.gap_score.estimate}</span> estimated</td>
                <td className="px-5 py-2 text-right">{canEdit && <button onClick={(e) => { e.stopPropagation(); remove(x.id); }} className="text-ink-faint hover:text-rose-600"><Trash2 size={13} /></button>}</td>
              </tr>
            ))}</tbody>
          </table>
        )}
      </Card>
    </div>
  );
}
