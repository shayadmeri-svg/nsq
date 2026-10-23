// Plant monitor: the live plant from Eurveda Connect (connect/) — every machine on the line with the batch and product
// on it now, each signal against that product's range for that step, batches moving machine to machine, and alarms.
// Plant setup (machines, connections, products and routes, agents) opens from here.
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  AlertTriangle, ArrowRight, BellRing, Boxes, CheckCircle2, Circle, Cog, Factory, Gauge, Layers, Pill, Radio, Settings2, Thermometer, Wind,
} from "lucide-react";
import { AnimatePresence, motion } from "motion/react";
import { useEffect, useMemo, useState } from "react";
import { Badge, Button, Card, CardHeader, Empty, ErrorNote, SearchSelect, Skeleton } from "../../components/ui";
import { useToast } from "../../components/ui/toast";
import { api, post } from "../../lib/api";
import { cn } from "../../lib/cn";
import { plural } from "../../lib/format";
import { PlantSetup } from "./PlantSetup";

export const TYPE_ICON: Record<string, any> = { rmg: Cog, fbd: Wind, blender: Layers, press: Gauge, coater: Pill, capsule_filler: Boxes, liquid_vessel: Thermometer, filling_line: Boxes, autoclave: Thermometer, hvac_room: Wind };
const ZONE: Record<string, string> = { ok: "bg-emerald-500", warn: "bg-amber-400", alarm: "bg-rose-500", end: "bg-indigo-400", none: "bg-slate-400" };
const fmt = (v: number | null | undefined) => (v == null ? "—" : Math.abs(v) >= 1000 ? Math.round(v).toLocaleString("en-IN") : String(Number(v.toPrecision(4))));
const ago = (iso?: string | null) => { if (!iso) return "never"; const s = Math.max(0, (Date.now() - new Date(iso).getTime()) / 1000); return s < 60 ? `${Math.round(s)} s ago` : s < 3600 ? `${Math.round(s / 60)} min ago` : `${Math.round(s / 3600)} h ago`; };

/** A tick from the stream onto the state: machines replace theirs, each signal's new readings extend its history,
 *  and any other section the tick carries replaces the old one. */
function merge(prev: any, tick: any) {
  if (!prev) return prev;
  const old = new Map<number, any>((prev.equipment ?? []).map((e: any) => [e.id, e]));
  const equipment = (tick.equipment ?? []).map((e: any) => {
    const was = new Map<string, any>((old.get(e.id)?.signals ?? []).map((s: any) => [s.id, s]));
    return { ...e, signals: e.signals.map(({ append, ...s }: any) => ({ ...s, history: [...(was.get(s.id)?.history ?? []), ...(append ?? [])].slice(-120) })) };
  });
  return { ...prev, ...tick, equipment };
}

/** The live state: one snapshot when the stream opens, then a tick whenever a machine reports (and every 15 s).
 *  The browser reconnects a dropped stream by itself (a deploy, a network blip); while it is down the page polls. */
function useLive(plantId: number | null) {
  const [data, setData] = useState<any>(null);
  const [err, setErr] = useState<unknown>(null);
  const [connected, setConnected] = useState(false);
  useEffect(() => {
    if (!plantId) return;
    setData(null);
    let timer: any = null;
    const poll = async () => { try { setData(await api<any>(`/api/connect/plants/${plantId}/live`)); setErr(null); } catch (e) { setErr(e); } };
    const startPolling = () => { if (!timer) timer = setInterval(poll, 4000); };
    const stopPolling = () => { if (timer) { clearInterval(timer); timer = null; } };
    const es = new EventSource(`/api/connect/plants/${plantId}/stream`, { withCredentials: true });
    es.onopen = () => { setConnected(true); stopPolling(); };
    es.addEventListener("snapshot", (m) => { try { setData(JSON.parse((m as MessageEvent).data)); setErr(null); } catch { /* partial frame */ } });
    es.addEventListener("tick", (m) => { try { const t = JSON.parse((m as MessageEvent).data); setData((d: any) => merge(d, t)); } catch { /* partial frame */ } });
    es.onerror = () => { setConnected(false); if (es.readyState === EventSource.CLOSED) { poll(); startPolling(); } else startPolling(); };
    return () => { es.close(); stopPolling(); };
  }, [plantId]);
  return { data, err, connected };
}

function Spark({ data, color }: { data: number[]; color: string }) {
  if (data.length < 2) return <div className="h-5" />;
  const lo = Math.min(...data), hi = Math.max(...data), w = 84, h = 20;
  const pts = data.map((y, i) => `${(i / (data.length - 1)) * w},${hi === lo ? h / 2 : h - ((y - lo) / (hi - lo)) * (h - 3) - 1.5}`).join(" ");
  return <svg width={w} height={h} className="shrink-0 overflow-visible"><polyline points={pts} fill="none" stroke={color} strokeWidth={1.4} strokeLinejoin="round" /></svg>;
}

/** Value against the product's range for this step: green band = acceptable range, tick = ideal, dot = now. */
function RangeBar({ s }: { s: any }) {
  if (s.lo == null || s.hi == null || s.value == null) return null;
  const span = s.hi - s.lo || 1;
  const a = Math.min(s.lo - span * 0.5, s.value), b = Math.max(s.hi + span * 0.5, s.value);
  const pct = (x: number) => `${((x - a) / (b - a || 1)) * 100}%`;
  return (
    <div className="relative mt-1 h-1.5 rounded-full bg-slate-100">
      <div className="absolute inset-y-0 rounded-full bg-emerald-200" style={{ left: pct(s.lo), width: `calc(${pct(s.hi)} - ${pct(s.lo)})` }} />
      {s.ideal != null && <div className="absolute -top-0.5 h-2.5 w-0.5 bg-emerald-700" style={{ left: pct(s.ideal) }} />}
      <motion.div className={cn("absolute -top-[3px] h-3 w-3 -translate-x-1/2 rounded-full ring-2 ring-white", ZONE[s.zone] ?? ZONE.none)} animate={{ left: pct(s.value) }} transition={{ type: "spring", stiffness: 120, damping: 18 }} />
    </div>
  );
}

function Machine({ e }: { e: any }) {
  const I = TYPE_ICON[e.type] ?? Factory;
  const running = e.status === "running";
  const sigs = [...e.signals].sort((x: any, y: any) => Number(y.key) - Number(x.key) || Number(y.lo != null) - Number(x.lo != null)).slice(0, 4);
  return (
    <motion.div layout className={cn("flex min-w-0 flex-col rounded-2xl bg-white p-4 shadow-card ring-1 ring-inset transition", e.alarms ? "ring-rose-300" : "ring-line")}>
      <div className="flex items-start gap-2.5">
        <span className={cn("grid h-10 w-10 shrink-0 place-items-center rounded-xl ring-1 ring-inset", running ? "bg-gold-50 text-gold-600 ring-gold-100" : "bg-slate-50 text-ink-faint ring-line")}><I size={19} /></span>
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-1.5 text-[14px] font-semibold">{e.name}
            {running && <span className="relative flex h-2 w-2"><span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-emerald-400 opacity-60" /><span className="relative inline-flex h-2 w-2 rounded-full bg-emerald-500" /></span>}
            {e.alarms > 0 && <Badge tone="rose">{e.alarms}</Badge>}</div>
          <div className="truncate text-[11px] text-ink-muted" title={[e.make, e.model].filter(Boolean).join(" ") || undefined}>{e.stage} · {[e.make, e.model].filter(Boolean).join(" ") || e.type_label}</div>
        </div>
      </div>
      <div className="mt-3 h-7">
        <AnimatePresence mode="popLayout" initial={false}>
          {running ? (
            <motion.span key={e.batch} initial={{ x: -30, opacity: 0 }} animate={{ x: 0, opacity: 1 }} exit={{ x: 30, opacity: 0 }}
              className="inline-flex max-w-full items-center gap-1.5 truncate rounded-lg px-2 py-1 font-mono text-[11.5px] font-semibold text-white" style={{ background: e.product?.color ?? "#334155" }}>
              {e.batch}{e.product && <span className="font-sans font-medium opacity-80">· {e.product.name.split(" ")[0]}</span>}
            </motion.span>
          ) : (
            <motion.span key="idle" initial={{ opacity: 0 }} animate={{ opacity: 1 }} className="text-[11.5px] text-ink-faint">
              {e.status === "not connected" ? "not connected yet" : e.status === "no data" ? "no data yet" : `idle · last reading ${ago(e.last_ts)}`}</motion.span>
          )}
        </AnimatePresence>
      </div>
      <div className="mt-2 space-y-2.5">
        {sigs.map((s: any) => (
          <div key={s.id}>
            <div className="flex items-end justify-between gap-2">
              <div className="min-w-0"><div className="truncate text-[10.5px] text-ink-muted">{s.label}{s.check === "end" && s.lo != null && <span className="text-indigo-600"> · judged at end</span>}</div>
                <div className={cn("text-[17px] font-semibold leading-tight tabular-nums", running && s.zone === "alarm" && "text-rose-600")}>{fmt(s.value)} <span className="text-[10px] font-normal text-ink-faint">{s.unit}</span></div></div>
              <Spark data={s.history} color={running ? e.product?.color ?? "#06a7c4" : "#cbd5e1"} />
            </div>
            {running && <RangeBar s={s} />}
          </div>))}
      </div>
    </motion.div>
  );
}

export function PlantMonitor() {
  const qc = useQueryClient();
  const toast = useToast();
  const plants = useQuery({ queryKey: ["cx-plants"], queryFn: () => api<any>("/api/connect/plants"), retry: 1 });
  const [pid, setPid] = useState<number | null>(null);
  const plantId = pid ?? plants.data?.plants?.[0]?.id ?? null;
  const { data: d, err, connected } = useLive(plantId);
  const [setup, setSetup] = useState(false);
  const eqName = useMemo(() => Object.fromEntries((d?.equipment ?? []).map((e: any) => [e.id, e.name])), [d]);
  const ack = async (id: number) => { try { await post(`/api/connect/alarms/${id}/ack`); toast("Acknowledged"); } catch (e) { toast((e as Error).message, "error"); } };

  if (plants.error) return <ErrorNote error={plants.error} />;
  if (plants.isLoading) return <Skeleton className="h-96" />;
  if (!plants.data?.plants?.length) return <Empty icon={<Factory size={20} />} title="No plant yet">Set up your first plant: its machines, how each is reached, and the products made on it.</Empty>;
  const plant = plants.data.plants.find((p: any) => p.id === plantId);
  const agentsOn = (d?.agents ?? []).filter((a: any) => a.online).length;

  return (
    <div className="space-y-5">
      <div className="relative overflow-hidden rounded-3xl bg-night-900 px-6 py-5 text-white shadow-lift">
        <div className="pointer-events-none absolute -right-20 -top-24 h-64 w-64 rounded-full bg-gold-400/15 blur-3xl" />
        <div className="relative flex flex-wrap items-center gap-x-8 gap-y-4">
          <div className="min-w-0">
            <div className="flex items-center gap-2 text-[11px] font-semibold uppercase tracking-[0.16em] text-gold-300">
              <span className="relative flex h-2 w-2">{agentsOn > 0 && <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-emerald-400 opacity-70" />}<span className={cn("relative inline-flex h-2 w-2 rounded-full", agentsOn ? "bg-emerald-400" : "bg-slate-500")} /></span>
              {agentsOn ? "Live" : "Waiting for the plant agent"}
              {!connected && <span className="font-normal normal-case tracking-normal text-slate-400">· reconnecting, updating every 4 s</span>}</div>
            {plants.data.plants.length > 1
              ? <div className="mt-1 w-72"><SearchSelect size="sm" value={String(plantId)} onChange={(v) => setPid(Number(v))} options={plants.data.plants.map((p: any) => ({ value: String(p.id), label: p.name }))} /></div>
              : <div className="mt-0.5 truncate text-[22px] font-semibold tracking-tight">{plant?.name}</div>}
            <div className="text-xs text-slate-400">{plant?.location}</div>
          </div>
          {d && [["Machines running", `${d.counts.running}/${d.counts.machines}`], ["Batches on the line", d.counts.batches_running], ["Active alarms", d.counts.active_alarms], ["Agents online", `${agentsOn}/${d.agents.length}`]].map(([k, v], i) => (
            <div key={k as string}><div className="text-[10px] font-semibold uppercase tracking-[0.12em] text-slate-400">{k}</div>
              <div className={cn("text-[26px] font-semibold leading-tight tabular-nums", i === 2 && Number(v) > 0 && "text-rose-300")}>{v}</div></div>))}
          <Button className="ml-auto bg-gold-400 text-night-900 hover:bg-gold-300" onClick={() => setSetup(true)}><Settings2 size={15} /> Plant setup</Button>
        </div>
      </div>

      {err != null && !d && <ErrorNote error={err} />}
      {!d ? <Skeleton className="h-72" /> : (
        <>
          <div>
            <div className="mb-2 flex items-baseline justify-between"><h2 className="text-[17px] font-semibold tracking-tight">The line</h2>
              <span className="text-[11px] text-ink-muted">green band: the acceptable range for the product on the machine · tick: ideal · dot: now</span></div>
            <div className="grid gap-3 md:grid-cols-3 xl:grid-cols-5">{d.equipment.map((e: any) => <Machine key={e.id} e={e} />)}</div>
          </div>

          <div className="grid gap-5 xl:grid-cols-[minmax(0,1.3fr)_minmax(0,1fr)]">
            <Card>
              <CardHeader icon={<Layers size={16} />} title="Batches" subtitle="Each batch's route through the line: done, running, still to come" />
              <div className="divide-y divide-line px-5 pb-3 pt-2">
                <AnimatePresence initial={false}>
                  {d.batches.map((b: any) => (
                    <motion.div key={b.batch_no} layout initial={{ opacity: 0, y: -8 }} animate={{ opacity: 1, y: 0 }} className="flex flex-wrap items-center gap-x-4 gap-y-2 py-2.5">
                      <div className="w-44 min-w-0"><div className="flex items-center gap-1.5 font-mono text-[12.5px] font-semibold"><span className="h-2.5 w-2.5 shrink-0 rounded-full" style={{ background: b.product.color }} />{b.batch_no}</div>
                        <div className="truncate text-[10.5px] text-ink-muted">{b.product.name}</div></div>
                      <div className="flex flex-1 flex-wrap items-center gap-1">
                        {b.steps.map((st: any, i: number) => (
                          <span key={st.equipment_id} className="flex items-center gap-1">
                            <span className={cn("rounded-md px-1.5 py-0.5 text-[10px] font-semibold", st.status === "done" ? "bg-emerald-50 text-emerald-700 ring-1 ring-inset ring-emerald-200" : st.status === "running" ? "animate-pulse text-white" : "bg-slate-100 text-ink-faint")}
                              style={st.status === "running" ? { background: b.product.color } : undefined}>{eqName[st.equipment_id] ?? "?"}</span>
                            {i < b.steps.length - 1 && <ArrowRight size={10} className="text-ink-faint" />}
                          </span>))}
                      </div>
                      <div className="w-24 text-right text-[11px]">{b.complete ? <span className="font-semibold text-emerald-600"><CheckCircle2 size={12} className="mr-0.5 inline" />complete</span> : <span className="text-ink-muted">in progress</span>}
                        {b.alarms > 0 && <div className="text-rose-600">{plural(b.alarms, "alarm")}</div>}</div>
                    </motion.div>))}
                </AnimatePresence>
                {!d.batches.length && <div className="py-6 text-center text-xs text-ink-muted">No batch seen yet.</div>}
              </div>
            </Card>
            <Card>
              <CardHeader icon={<BellRing size={16} />} title="Alarms" subtitle="Readings outside the product's acceptable range for that step" />
              <div className="max-h-[440px] space-y-2 overflow-auto px-5 pb-4 pt-2">
                <AnimatePresence initial={false}>
                  {d.alarms.map((a: any) => (
                    <motion.div key={a.id} layout initial={{ opacity: 0, x: 12 }} animate={{ opacity: 1, x: 0 }}
                      className={cn("rounded-xl px-3 py-2.5 text-xs ring-1 ring-inset", a.active ? "bg-rose-50 ring-rose-200" : "bg-slate-50 ring-line")}>
                      <div className="flex items-start gap-2">
                        {a.active ? <AlertTriangle size={14} className="mt-0.5 shrink-0 text-rose-500" /> : <Circle size={12} className="mt-0.5 shrink-0 text-ink-faint" />}
                        <div className="min-w-0 flex-1"><div className="font-semibold">{a.equipment} · <span className="font-mono">{a.batch}</span></div>
                          <div className="text-ink-soft">{a.message}</div>
                          <div className="text-[10px] text-ink-faint">{a.product} · {ago(a.started_at)}{a.acked_by ? ` · acknowledged by ${a.acked_by}` : a.active ? "" : " · back in range"}</div></div>
                        {a.active && <Button size="sm" variant="secondary" onClick={() => ack(a.id)}>Ack</Button>}
                      </div>
                    </motion.div>))}
                </AnimatePresence>
                {!d.alarms.length && <div className="py-6 text-center text-xs text-ink-muted"><CheckCircle2 size={16} className="mx-auto mb-1 text-emerald-500" />No alarms.</div>}
              </div>
            </Card>
          </div>

          <Card>
            <CardHeader icon={<Radio size={16} />} title="Products on this line" subtitle="Each product's route: shared machines are set up once; a product-specific step belongs to one product" />
            <div className="grid gap-3 p-5 md:grid-cols-2">
              {d.products.map((p: any) => (
                <div key={p.id} className="rounded-xl p-4 ring-1 ring-inset ring-line">
                  <div className="flex items-center gap-2"><span className="h-3 w-3 rounded-full" style={{ background: p.color }} /><span className="text-[14px] font-semibold">{p.name}</span><Badge>{p.dosage_form}</Badge></div>
                  <div className="mt-2 flex flex-wrap items-center gap-1">
                    {p.route.map((st: any, i: number) => (
                      <span key={st.equipment_id} className="flex items-center gap-1">
                        <span className={cn("rounded-md px-2 py-1 text-[11px] font-semibold ring-1 ring-inset", st.shared ? "bg-slate-50 text-ink-soft ring-line" : "text-white ring-transparent")}
                          style={st.shared ? undefined : { background: p.color }} title={st.shared ? "shared with another product" : "only this product"}>{st.name}</span>
                        {i < p.route.length - 1 && <ArrowRight size={11} className="text-ink-faint" />}
                      </span>))}
                  </div>
                  {p.route.some((st: any) => !st.shared) && <div className="mt-1.5 text-[10.5px] text-ink-muted">Coloured: only this product · grey: shared</div>}
                </div>))}
            </div>
          </Card>
        </>
      )}
      {plantId && <PlantSetup open={setup} onClose={() => { setSetup(false); qc.invalidateQueries({ queryKey: ["cx-plant", plantId] }); }} plantId={plantId} />}
    </div>
  );
}
