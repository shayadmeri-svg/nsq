// Plant setup wizard (Eurveda Connect): the plant, its machines (from a catalog of equipment types), how each machine is
// reached and which of its tags is which signal (browsed and test-read by the plant's agent), the products and their
// routes through the machines with ideal values and acceptable ranges, and the agents. Every step saves as you go.
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowDown, ArrowUp, Check, ClipboardCopy, Loader2, Plus, Search, Trash2, Wand2, X } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { Badge, Button, Modal, SearchSelect } from "../../components/ui";
import { useToast } from "../../components/ui/toast";
import { api, del, post, put } from "../../lib/api";
import { cn } from "../../lib/cn";
import { TYPE_ICON } from "./PlantMonitor";

const STEPS = [
  { id: "plant", label: "Plant", hint: "Name and place" },
  { id: "machines", label: "Machines", hint: "What is on the floor" },
  { id: "connect", label: "Connections", hint: "How each machine is read" },
  { id: "products", label: "Products & routes", hint: "What runs on which machines" },
  { id: "agents", label: "Agents", hint: "The plant-side reader" },
] as const;
type Step = (typeof STEPS)[number]["id"];
const STATUS_TONE: Record<string, any> = { available: "brand", beta: "amber", planned: "slate" };

function useWait() {
  /** Polls a job until the agent answers (or 60 s pass). */
  return async (id: number, onTick?: (s: string) => void): Promise<any> => {
    for (let i = 0; i < 40; i++) {
      const j = await api<any>(`/api/connect/jobs/${id}`);
      onTick?.(j.status);
      if (j.status === "done" || j.status === "failed") return j;
      await new Promise((r) => setTimeout(r, 1500));
    }
    return { status: "timeout", result: { error: "The plant agent did not answer within a minute: is it running and online?" } };
  };
}

function PlantStep({ d, plantId, refresh }: { d: any; plantId: number; refresh: () => void }) {
  const [f, setF] = useState({ name: d.plant.name, location: d.plant.location, timezone: d.plant.timezone });
  const toast = useToast();
  return (
    <div className="max-w-lg space-y-3">
      {(["name", "location", "timezone"] as const).map((k) => (
        <label key={k} className="block"><span className="label">{k === "timezone" ? "Time zone (the plant's records)" : k}</span>
          <input className="input mt-1" value={f[k]} onChange={(e) => setF({ ...f, [k]: e.target.value })} /></label>))}
      <Button onClick={async () => { await put(`/api/connect/plants/${plantId}`, f); toast("Saved"); refresh(); }}>Save</Button>
    </div>
  );
}

function MachinesStep({ d, cat, plantId, refresh }: { d: any; cat: any; plantId: number; refresh: () => void }) {
  const [type, setType] = useState<string | null>(null);
  const [f, setF] = useState({ name: "", make: "", model: "" });
  const [find, setFind] = useState("");
  const toast = useToast();
  const makers: string[] = cat.equipment_types.find((t: any) => t.id === type)?.makers ?? [];
  const add = async () => {
    try { await post(`/api/connect/plants/${plantId}/equipment`, { ...f, type, protocol: "opcua" }); setType(null); setF({ name: "", make: "", model: "" }); refresh(); }
    catch (e) { toast((e as Error).message, "error"); }
  };
  const move = async (e: any, dir: -1 | 1) => {
    const list = [...d.equipment]; const i = list.findIndex((x) => x.id === e.id); const j = i + dir;
    if (j < 0 || j >= list.length) return;
    [list[i], list[j]] = [list[j], list[i]];
    await Promise.all(list.map((x, k) => put(`/api/connect/equipment/${x.id}`, { position: k })));
    refresh();
  };
  return (
    <div className="space-y-4">
      <div className="space-y-1.5">
        {d.equipment.map((e: any, i: number) => {
          const I = TYPE_ICON[e.type] ?? Plus;
          return (
            <div key={e.id} className="flex items-center gap-3 rounded-xl px-3 py-2 ring-1 ring-inset ring-line">
              <span className="w-5 text-center text-xs text-ink-faint">{i + 1}</span>
              <span className="grid h-8 w-8 place-items-center rounded-lg bg-gold-50 text-gold-600"><I size={16} /></span>
              <div className="min-w-0 flex-1"><div className="text-[13px] font-semibold">{e.name}</div>
                <div className="text-[11px] text-ink-muted">{cat.equipment_types.find((t: any) => t.id === e.type)?.label} · {[e.make, e.model].filter(Boolean).join(" ") || "make/model not set"}</div></div>
              <button onClick={() => move(e, -1)} className="rounded p-1 text-ink-faint hover:bg-slate-100"><ArrowUp size={14} /></button>
              <button onClick={() => move(e, 1)} className="rounded p-1 text-ink-faint hover:bg-slate-100"><ArrowDown size={14} /></button>
              <button onClick={async () => { try { await del(`/api/connect/equipment/${e.id}`); refresh(); } catch (x) { toast((x as Error).message, "error"); } }} className="rounded p-1 text-ink-faint hover:bg-rose-50 hover:text-rose-600"><Trash2 size={14} /></button>
            </div>);
        })}
      </div>
      <div>
        <div className="mb-2 flex flex-wrap items-center justify-between gap-2"><span className="label">Add a machine · {cat.equipment_types.length} kinds</span>
          <input className="input h-8 w-60 text-xs" placeholder="Find a machine or a maker" value={find} onChange={(e) => setFind(e.target.value)} /></div>
        <div className="space-y-3">
          {(cat.areas ?? [{ id: undefined, label: "" }]).map((a: any) => {
            const list = cat.equipment_types.filter((t: any) => (a.id === undefined || t.area === a.id)
              && (!find || `${t.label} ${t.stage} ${(t.makers ?? []).join(" ")}`.toLowerCase().includes(find.toLowerCase())));
            if (!list.length) return null;
            return (
              <div key={a.id ?? "all"}>
                {a.label && <div className="mb-1 text-[10.5px] font-semibold uppercase tracking-wide text-ink-muted">{a.label}</div>}
                <div className="grid grid-cols-2 gap-2 md:grid-cols-5">
                  {list.map((t: any) => {
                    const I = TYPE_ICON[t.id] ?? Plus;
                    return (
                      <button key={t.id} onClick={() => { setType(t.id); setF({ ...f, name: f.name || `${t.id.toUpperCase().replace(/_/g, "-")}-${d.equipment.filter((e: any) => e.type === t.id).length + 1}` }); }}
                        className={cn("rounded-xl p-3 text-left ring-1 ring-inset transition hover:bg-gold-50", type === t.id ? "bg-gold-50 ring-2 ring-gold-400" : "ring-line")}>
                        <I size={16} className="text-gold-600" /><div className="mt-1 text-[12px] font-semibold leading-tight">{t.label}</div>
                        <div className="text-[10px] text-ink-faint">{t.stage} · {t.signals.length} signals{t.batch === false ? " · continuous" : ""}</div>
                      </button>);
                  })}
                </div>
              </div>);
          })}
        </div>
        {type && (
          <div className="mt-3 flex flex-wrap items-end gap-2 rounded-xl bg-slate-50 p-3">
            <label className="w-40"><span className="label">Name</span><input className="input mt-1 h-9" value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} /></label>
            <label className="w-48"><span className="label">Make</span><input className="input mt-1 h-9" list="cx-makers" placeholder={makers[0] ? `e.g. ${makers[0]}` : "manufacturer"} value={f.make} onChange={(e) => setF({ ...f, make: e.target.value })} />
              <datalist id="cx-makers">{makers.map((m) => <option key={m} value={m} />)}</datalist></label>
            <label className="w-40"><span className="label">Model</span><input className="input mt-1 h-9" placeholder="as on the nameplate" value={f.model} onChange={(e) => setF({ ...f, model: e.target.value })} /></label>
            <Button onClick={add}><Plus size={14} /> Add</Button><Button variant="ghost" onClick={() => setType(null)}>Cancel</Button>
          </div>)}
      </div>
    </div>
  );
}

function ConnectStep({ d, cat, refresh }: { d: any; cat: any; refresh: () => void }) {
  const [sel, setSel] = useState<number | null>(d.equipment[0]?.id ?? null);
  const e = d.equipment.find((x: any) => x.id === sel);
  const [f, setF] = useState<any>(null);
  const [tags, setTags] = useState<any[] | null>(null);
  const [busy, setBusy] = useState<string>("");
  const [test, setTest] = useState<any>(null);
  const [q, setQ] = useState("");
  const toast = useToast();
  const wait = useWait();
  useEffect(() => { if (e) { setF(structuredClone({ protocol: e.protocol, connection: e.connection ?? {}, tag_map: e.tag_map ?? {}, batch_tag: e.batch_tag, product_tag: e.product_tag, agent_id: e.agent_id, profile_id: e.profile_id })); setTags(null); setTest(null); } }, [sel]); // eslint-disable-line react-hooks/exhaustive-deps
  if (!e || !f) return <div className="text-sm text-ink-muted">Add a machine first.</div>;
  const type = cat.equipment_types.find((t: any) => t.id === e.type);
  const proto = cat.protocols.find((p: any) => p.id === f.protocol);
  const profiles = cat.profiles.filter((p: any) => p.type === e.type);
  const save = async (extra: any = {}) => { try { await put(`/api/connect/equipment/${e.id}`, { ...f, ...extra }); toast("Saved"); refresh(); } catch (x) { toast((x as Error).message, "error"); } };
  const run = async (kind: "browse" | "test") => {
    await save();
    setBusy(kind);
    try {
      const j = await post<any>(`/api/connect/equipment/${e.id}/${kind}`);
      const r = await wait(j.id, (s) => setBusy(`${kind}:${s}`));
      if (r.status !== "done") toast(r.result?.error ?? "The agent could not do it", "error");
      else if (kind === "browse") {
        setTags(r.result.tags);
        if (r.result.suggestion && Object.keys(r.result.suggestion).length) {
          setF((c: any) => ({ ...c, tag_map: { ...Object.fromEntries(Object.entries(r.result.suggestion).map(([k, v]: any) => [k, v.tag])), ...c.tag_map },
            batch_tag: c.batch_tag || r.result.batch_tag || "", product_tag: c.product_tag || r.result.product_tag || "" }));
          toast(`${r.result.tags.length} tags found · ${Object.keys(r.result.suggestion).length} matched to signals: check them and save`);
        }
      } else setTest(r.result);
    } catch (x) { toast((x as Error).message, "error"); } finally { setBusy(""); }
  };
  const mapped = (x: any) => Object.keys(x.tag_map ?? {}).length;
  const tagOpts = (tags ?? []).filter((t: any) => !q || `${t.name} ${t.node}`.toLowerCase().includes(q.toLowerCase())).map((t: any) => ({ value: t.node, label: t.name, sub: `${t.node} · ${String(t.value).slice(0, 18)}` }));
  return (
    <div className="grid gap-4 md:grid-cols-[220px_minmax(0,1fr)]">
      <div className="space-y-1">
        {d.equipment.map((x: any) => {
          const t = cat.equipment_types.find((y: any) => y.id === x.type);
          return (
            <button key={x.id} onClick={() => setSel(x.id)} className={cn("flex w-full items-center justify-between rounded-lg px-3 py-2 text-left text-[13px]", sel === x.id ? "bg-night-900 text-white" : "hover:bg-slate-50")}>
              <span className="font-semibold">{x.name}</span>
              <span className={cn("text-[10.5px]", sel === x.id ? "text-slate-300" : mapped(x) ? "text-emerald-600" : "text-amber-600")}>{mapped(x)}/{t?.signals.length} mapped</span>
            </button>);
        })}
      </div>
      <div className="min-w-0 space-y-4">
        <div>
          <div className="label mb-1.5">How is {e.name} reached?</div>
          <div className="grid grid-cols-2 gap-2 lg:grid-cols-3">
            {cat.protocols.map((p: any) => (
              <button key={p.id} disabled={p.status === "planned"} onClick={() => setF({ ...f, protocol: p.id })}
                className={cn("rounded-xl p-2.5 text-left ring-1 ring-inset transition", f.protocol === p.id ? "bg-gold-50 ring-2 ring-gold-400" : "ring-line hover:bg-slate-50", p.status === "planned" && "cursor-not-allowed opacity-50")}>
                <div className="flex items-center justify-between gap-1 text-[12.5px] font-semibold">{p.label}<Badge tone={STATUS_TONE[p.status]}>{p.status === "planned" ? "on request" : p.status}</Badge></div>
                <div className="mt-0.5 text-[10.5px] leading-snug text-ink-muted">{p.what}</div>
              </button>))}
          </div>
        </div>
        {proto?.fields?.length > 0 && (
          <div className="grid gap-2 sm:grid-cols-3">
            {proto.fields.map((fl: any) => (
              <label key={fl.id} className="block"><span className="label">{fl.label}{fl.required && " *"}</span>
                <input className="input mt-1 h-9 text-xs" placeholder={fl.placeholder} value={f.connection?.[fl.id] ?? ""} onChange={(ev) => setF({ ...f, connection: { ...f.connection, [fl.id]: ev.target.value } })} /></label>))}
          </div>)}
        <div className="grid gap-2 sm:grid-cols-2">
          <div><div className="label mb-1">Read by agent</div>
            <SearchSelect size="sm" value={String(f.agent_id ?? "")} onChange={(v) => setF({ ...f, agent_id: v ? Number(v) : null })} clearLabel="No agent yet" placeholder="No agent yet"
              options={d.agents.map((a: any) => ({ value: String(a.id), label: a.name, sub: a.last_seen_at ? "seen" : "never connected" }))} /></div>
          {profiles.length > 0 && <div><div className="label mb-1">Known machine model</div>
            <SearchSelect size="sm" value={f.profile_id ?? ""} onChange={(v) => { setF({ ...f, profile_id: v }); if (v) save({ profile_id: v }); }} clearLabel="None" placeholder="None"
              options={profiles.map((p: any) => ({ value: p.id, label: p.label, sub: `verified on: ${p.verified}` }))} /></div>}
        </div>
        {proto?.tag && <div className="text-[11px] text-ink-muted">Addresses for {proto.label}: <span className="font-mono text-ink-soft">{proto.tag}</span></div>}
        {proto?.agent && (
          <div className="flex flex-wrap items-center gap-2">
            {f.protocol === "opcua" && <Button variant="secondary" onClick={() => run("browse")} disabled={!!busy || !f.agent_id}>{busy.startsWith("browse") ? <Loader2 size={14} className="animate-spin" /> : <Search size={14} />} Browse tags</Button>}
            <Button variant="secondary" onClick={() => run("test")} disabled={!!busy || !f.agent_id || !mapped(f)}>{busy.startsWith("test") ? <Loader2 size={14} className="animate-spin" /> : <Wand2 size={14} />} Test read</Button>
            <span className="text-[11px] text-ink-muted">{busy ? `waiting for the plant agent… (${busy.split(":")[1] ?? "queued"})` : !f.agent_id ? "Choose the agent that reaches this machine" : "The agent at the plant does this; the cloud never connects in"}</span>
          </div>)}
        <div className="rounded-xl ring-1 ring-inset ring-line">
          <div className="flex items-center justify-between border-b border-line px-3 py-2"><span className="label">Signals → tags</span>
            {tags && <input className="input h-8 w-48 text-xs" placeholder={`Filter ${tags.length} tags`} value={q} onChange={(ev) => setQ(ev.target.value)} />}</div>
          <div className="divide-y divide-line">
            {[...type.signals.map((s: any) => ({ ...s, kind: "signal" })), { id: "__batch", label: "Batch number", unit: "", kind: "batch" }, { id: "__product", label: "Product", unit: "", kind: "product" }].map((s: any) => {
              const val = s.kind === "batch" ? f.batch_tag : s.kind === "product" ? f.product_tag : f.tag_map[s.id] ?? "";
              const set = (v: string) => s.kind === "batch" ? setF({ ...f, batch_tag: v }) : s.kind === "product" ? setF({ ...f, product_tag: v })
                : setF({ ...f, tag_map: Object.fromEntries(Object.entries({ ...f.tag_map, [s.id]: v }).filter(([, x]) => x)) });
              return (
                <div key={s.id} className="flex items-center gap-3 px-3 py-1.5">
                  <div className="w-48 shrink-0 text-xs">{val ? <Check size={11} className="mr-1 inline text-emerald-600" /> : null}<span className={cn(s.key && "font-semibold")}>{s.label}</span>{s.unit && <span className="text-ink-faint"> ({s.unit})</span>}</div>
                  <div className="min-w-0 flex-1">{tags
                    ? <SearchSelect size="sm" value={val} onChange={set} clearLabel="Not read" placeholder="Not read" options={tagOpts} />
                    : <input className="input h-8 font-mono text-[11px]" placeholder={(proto?.tag ?? "address").split("  ·  ")[0]} value={val} onChange={(ev) => set(ev.target.value)} />}</div>
                  {test && s.kind === "signal" && <span className="w-20 text-right text-[11px] font-semibold tabular-nums">{test.values?.[s.id] != null ? Number(test.values[s.id]).toPrecision(4) : "—"}</span>}
                  {test && s.kind !== "signal" && <span className="w-20 truncate text-right text-[11px] font-semibold">{s.kind === "batch" ? test.batch : test.product}</span>}
                </div>);
            })}
          </div>
        </div>
        <div className="flex gap-2"><Button onClick={() => save()}>Save {e.name}</Button>{test && <span className="self-center text-xs text-emerald-700"><Check size={13} className="mr-0.5 inline" />Test read: compare with the machine's screen</span>}</div>
      </div>
    </div>
  );
}

function ProductsStep({ d, cat, plantId, refresh }: { d: any; cat: any; plantId: number; refresh: () => void }) {
  const [sel, setSel] = useState<number | "new" | null>(d.products[0]?.id ?? null);
  const p0 = d.products.find((x: any) => x.id === sel);
  const [f, setF] = useState<any>(null);
  const toast = useToast();
  const mols = useQuery({ queryKey: ["cx-mols"], queryFn: () => api<any>("/api/lab/molecules").catch(() => ({ molecules: [] })), staleTime: 3600_000 });
  useEffect(() => { setF(sel === "new" ? { name: "", molecule_key: "", dosage_form: "tablet", codes: [], color: "#10b996", route: [] } : p0 ? structuredClone(p0) : null); }, [sel]); // eslint-disable-line react-hooks/exhaustive-deps
  const eq = useMemo(() => Object.fromEntries(d.equipment.map((e: any) => [e.id, e])), [d]);
  const save = async () => {
    try {
      if (sel === "new") { const r = await post<any>(`/api/connect/plants/${plantId}/products`, f); setSel(r.id); } else await put(`/api/connect/products/${f.id}`, f);
      toast("Saved"); refresh();
    } catch (x) { toast((x as Error).message, "error"); }
  };
  const setStep = (i: number, fn: (st: any) => void) => setF((c: any) => { const n = structuredClone(c); fn(n.route[i]); return n; });
  return (
    <div className="grid gap-4 md:grid-cols-[220px_minmax(0,1fr)]">
      <div className="space-y-1">
        {d.products.map((p: any) => (
          <button key={p.id} onClick={() => setSel(p.id)} className={cn("flex w-full items-center gap-2 rounded-lg px-3 py-2 text-left text-[13px]", sel === p.id ? "bg-night-900 text-white" : "hover:bg-slate-50")}>
            <span className="h-2.5 w-2.5 shrink-0 rounded-full" style={{ background: p.color }} /><span className="truncate font-semibold">{p.name}</span></button>))}
        <Button size="sm" variant="ghost" onClick={() => setSel("new")}><Plus size={13} /> Add a product</Button>
      </div>
      {f && (
        <div className="min-w-0 space-y-4">
          <div className="grid gap-2 sm:grid-cols-2">
            <label><span className="label">Product</span><input className="input mt-1 h-9" placeholder="e.g. Metformin Tablets IP 500 mg" value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} /></label>
            <div><span className="label">Molecule</span><div className="mt-1"><SearchSelect size="sm" value={f.molecule_key} onChange={(v) => setF({ ...f, molecule_key: v })} clearLabel="Not set" placeholder="Choose"
              options={(mols.data?.molecules ?? []).map((m: any) => ({ value: m.key, label: m.name }))} /></div></div>
            <div><span className="label">Dosage form</span><div className="mt-1"><SearchSelect size="sm" value={f.dosage_form} onChange={(v) => setF({ ...f, dosage_form: v })} options={cat.dosage_forms.map((x: string) => ({ value: x, label: x }))} /></div></div>
            <label><span className="label">What the machines report as this product</span><input className="input mt-1 h-9" placeholder="product codes, comma-separated" value={(f.codes ?? []).join(", ")}
              onChange={(e) => setF({ ...f, codes: e.target.value.split(",").map((s) => s.trim()).filter(Boolean) })} /></label>
          </div>
          <div>
            <div className="label mb-1.5">Route — click machines in the order the product goes through them</div>
            <div className="flex flex-wrap gap-1.5">
              {d.equipment.map((e: any) => {
                const on = f.route.some((st: any) => st.equipment_id === e.id);
                return <button key={e.id} onClick={() => setF({ ...f, route: on ? f.route.filter((st: any) => st.equipment_id !== e.id) : [...f.route, { equipment_id: e.id, params: {} }] })}
                  className={cn("rounded-lg px-2.5 py-1.5 text-[12px] font-semibold ring-1 ring-inset", on ? "bg-night-900 text-white ring-night-900" : "ring-line hover:bg-slate-50")}>{on ? "✓ " : "+ "}{e.name}</button>;
              })}
            </div>
          </div>
          <div className="space-y-3">
            {f.route.map((st: any, i: number) => {
              const e = eq[st.equipment_id];
              const type = cat.equipment_types.find((t: any) => t.id === e?.type);
              const unused = (type?.signals ?? []).filter((s: any) => !(s.id in st.params));
              return (
                <div key={st.equipment_id} className="rounded-xl ring-1 ring-inset ring-line">
                  <div className="flex items-center justify-between border-b border-line px-3 py-2 text-[13px] font-semibold"><span>{i + 1}. {e?.name} <span className="font-normal text-ink-muted">· {type?.stage}</span></span>
                    {unused.length > 0 && <select className="input h-8 w-56 text-xs" value="" onChange={(ev) => setStep(i, (s) => { s.params[ev.target.value] = { ideal: null, lo: null, hi: null, check: "continuous", source: "" }; })}>
                      <option value="">+ add a limit…</option>{unused.map((s: any) => <option key={s.id} value={s.id}>{s.label} ({s.unit})</option>)}</select>}</div>
                  <table className="w-full text-xs"><thead className="text-[10px] uppercase tracking-wide text-ink-muted"><tr><th className="px-3 py-1.5 text-left">Signal</th><th>Ideal</th><th>Low</th><th>High</th><th>Judged</th><th className="text-left">Source of the range</th><th /></tr></thead>
                    <tbody>{Object.entries(st.params).map(([sid, par]: any) => {
                      const s = type?.signals.find((x: any) => x.id === sid);
                      const num = (k: string) => <input type="number" step="any" className="input h-7 w-20 px-1.5 text-right text-xs" value={par[k] ?? ""} onChange={(ev) => setStep(i, (x) => { x.params[sid][k] = ev.target.value === "" ? null : Number(ev.target.value); })} />;
                      return (
                        <tr key={sid} className="border-t border-line">
                          <td className="px-3 py-1.5">{s?.label ?? sid} <span className="text-ink-faint">{s?.unit}</span></td>
                          <td className="px-1 text-center">{num("ideal")}</td><td className="px-1 text-center">{num("lo")}</td><td className="px-1 text-center">{num("hi")}</td>
                          <td className="px-1"><select className="input h-7 px-1 text-xs" value={par.check} onChange={(ev) => setStep(i, (x) => { x.params[sid].check = ev.target.value; })}><option value="continuous">every reading</option><option value="end">at end of step</option></select></td>
                          <td className="px-1"><input className="input h-7 text-xs" placeholder="validated range, monograph…" value={par.source ?? ""} onChange={(ev) => setStep(i, (x) => { x.params[sid].source = ev.target.value; })} /></td>
                          <td className="px-1"><button onClick={() => setStep(i, (x) => { delete x.params[sid]; })} className="rounded p-1 text-ink-faint hover:text-rose-600"><X size={13} /></button></td>
                        </tr>);
                    })}</tbody></table>
                </div>);
            })}
          </div>
          <div className="flex gap-2"><Button onClick={save}>Save product</Button>
            {sel !== "new" && <Button variant="ghost" onClick={async () => { if (confirm(`Delete ${f.name}?`)) { await del(`/api/connect/products/${f.id}`); setSel(null); refresh(); } }}><Trash2 size={14} /> Delete</Button>}</div>
        </div>)}
    </div>
  );
}

function AgentsStep({ d, plantId, refresh }: { d: any; plantId: number; refresh: () => void }) {
  const [name, setName] = useState("");
  const [made, setMade] = useState<any>(null);
  const toast = useToast();
  const origin = typeof window !== "undefined" ? window.location.origin : "";
  const yaml = made ? `eurveda:\n  url: ${origin}\n  remote: true            # machines come from this setup\n  token_env: EURVEDA_TOKEN\nmachines: []` : "";
  return (
    <div className="max-w-2xl space-y-4">
      <p className="text-sm text-ink-soft">An agent is a small program on a PC or gateway at the plant, on the same network as the machines. It reads them read-only and sends the readings out — nothing connects into the plant. With <b>remote mode</b> it takes its machine list from this setup, so you configure machines here, not on the PC.</p>
      {d.agents.map((a: any) => (
        <div key={a.id} className="flex items-center gap-3 rounded-xl px-3 py-2.5 ring-1 ring-inset ring-line">
          <span className={cn("h-2.5 w-2.5 rounded-full", a.last_seen_at && Date.now() - new Date(a.last_seen_at).getTime() < 90000 ? "bg-emerald-500" : "bg-slate-300")} />
          <div className="min-w-0 flex-1"><div className="text-[13px] font-semibold">{a.name} <span className="font-mono text-[11px] font-normal text-ink-faint">{a.token_hint}…</span></div>
            <div className="text-[11px] text-ink-muted">{a.last_seen_at ? `last seen ${new Date(a.last_seen_at).toLocaleString("en-IN")}` : "never connected"}{a.info?.machines?.length ? ` · ${a.info.machines.join(", ")}` : ""}</div></div>
          <button onClick={async () => { if (confirm(`Revoke ${a.name}?`)) { await del(`/api/connect/agents/${a.id}`); refresh(); } }} className="rounded p-1.5 text-ink-faint hover:bg-rose-50 hover:text-rose-600"><Trash2 size={14} /></button>
        </div>))}
      <div className="flex gap-2"><input className="input h-9 w-64" placeholder="e.g. Line 1 HMI PC" value={name} onChange={(e) => setName(e.target.value)} />
        <Button onClick={async () => { setMade(await post<any>(`/api/connect/plants/${plantId}/agents`, { name: name || "Plant agent" })); setName(""); refresh(); }}><Plus size={14} /> Add an agent</Button></div>
      {made && (
        <div className="rounded-xl bg-night-900 p-4 text-xs text-slate-300">
          <div className="mb-1 font-semibold text-white">Copy the token now: it is not shown again.</div>
          <div className="flex items-center gap-2"><code className="min-w-0 flex-1 truncate rounded bg-white/10 px-2 py-1.5 font-mono text-gold-200">{made.token}</code>
            <Button size="sm" variant="secondary" onClick={() => navigator.clipboard.writeText(made.token).then(() => toast("Copied"))}><ClipboardCopy size={13} /></Button></div>
          <div className="mt-3 text-slate-400">config.yaml on the plant PC:</div>
          <pre className="mt-1 overflow-x-auto rounded bg-white/5 p-2 font-mono text-[11px] text-slate-200">{yaml}</pre>
          <div className="mt-2 text-slate-400">Run: <code className="text-gold-200">EURVEDA_TOKEN=&lt;token&gt; python eurveda_agent.py --config config.yaml</code> (agent files: Plant data → Live → Connect a real plant).</div>
        </div>)}
    </div>
  );
}

export function PlantSetup({ open, onClose, plantId }: { open: boolean; onClose: () => void; plantId: number }) {
  const qc = useQueryClient();
  const [step, setStep] = useState<Step>("machines");
  const cat = useQuery({ queryKey: ["cx-catalog"], queryFn: () => api<any>("/api/connect/catalog"), enabled: open, staleTime: 3600_000 });
  const q = useQuery({ queryKey: ["cx-plant", plantId], queryFn: () => api<any>(`/api/connect/plants/${plantId}`), enabled: open });
  const refresh = () => qc.invalidateQueries({ queryKey: ["cx-plant", plantId] });
  const d = q.data;
  const counts: Record<Step, string> = d ? {
    plant: d.plant.name, machines: `${d.equipment.length}`, connect: `${d.equipment.filter((e: any) => Object.keys(e.tag_map ?? {}).length).length}/${d.equipment.length} mapped`,
    products: `${d.products.length}`, agents: `${d.agents.length}`,
  } : ({} as any);
  return (
    <Modal open={open} onClose={onClose} width={1120} title="Plant setup" footer={<Button onClick={onClose}>Done</Button>}>
      {!d || !cat.data ? <div className="grid h-64 place-items-center"><Loader2 className="animate-spin text-ink-faint" /></div> : (
        <div className="grid gap-5 md:grid-cols-[200px_minmax(0,1fr)]">
          <nav className="space-y-1">
            {STEPS.map((s, i) => (
              <button key={s.id} onClick={() => setStep(s.id)} className={cn("flex w-full items-start gap-2.5 rounded-xl px-3 py-2.5 text-left transition", step === s.id ? "bg-gold-50 ring-1 ring-inset ring-gold-200" : "hover:bg-slate-50")}>
                <span className={cn("grid h-6 w-6 shrink-0 place-items-center rounded-full text-[11px] font-bold", step === s.id ? "bg-gold-500 text-white" : "bg-slate-100 text-ink-muted")}>{i + 1}</span>
                <span className="min-w-0"><span className="block text-[13px] font-semibold">{s.label}</span><span className="block truncate text-[10.5px] text-ink-muted">{counts[s.id] ?? s.hint}</span></span>
              </button>))}
          </nav>
          <div className="min-w-0">
            {step === "plant" && <PlantStep d={d} plantId={plantId} refresh={refresh} />}
            {step === "machines" && <MachinesStep d={d} cat={cat.data} plantId={plantId} refresh={refresh} />}
            {step === "connect" && <ConnectStep d={d} cat={cat.data} refresh={refresh} />}
            {step === "products" && <ProductsStep d={d} cat={cat.data} plantId={plantId} refresh={refresh} />}
            {step === "agents" && <AgentsStep d={d} plantId={plantId} refresh={refresh} />}
          </div>
        </div>)}
    </Modal>
  );
}
