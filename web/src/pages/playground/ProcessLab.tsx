import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { AnimatePresence, motion } from "motion/react";
import { useEffect, useState } from "react";
import { Badge, Card, CardHeader, ErrorNote, Segmented, Skeleton } from "../../components/ui";
import { api, post } from "../../lib/api";
import { cn } from "../../lib/cn";

const SEV: Record<string, { tone: any; ring: string }> = {
  optimal: { tone: "brand", ring: "ring-emerald-300 bg-emerald-50/50" },
  warning: { tone: "amber", ring: "ring-amber-300 bg-amber-50/50" },
  critical: { tone: "rose", ring: "ring-rose-300 bg-rose-50/50" },
};

export function ProcessLab() {
  const routes = useQuery({ queryKey: ["pg-routes"], queryFn: () => api<any[]>("/api/process/routes"), staleTime: Infinity });
  const [route, setRoute] = useState("");
  const [vals, setVals] = useState<Record<string, number>>({});
  const [dv, setDv] = useState(vals);
  const r = routes.data?.find((x) => x.id === route) ?? routes.data?.[0];
  useEffect(() => { if (r) { setRoute(r.id); setVals(Object.fromEntries(r.stages.flatMap((s: any) => s.cpps.map((c: any) => [c.name, c.default])))); } }, [r?.id]); // eslint-disable-line
  useEffect(() => { const t = setTimeout(() => setDv(vals), 200); return () => clearTimeout(t); }, [vals]);
  const sim = useQuery({ queryKey: ["pg-sim", route, dv], enabled: !!route && Object.keys(dv).length > 0, placeholderData: keepPreviousData,
    queryFn: () => post<any>(`/api/process/${route}`, dv) });
  if (routes.error) return <ErrorNote error={routes.error} />;
  if (!r) return <Skeleton className="h-96" />;
  const res = sim.data;
  const overall = res ? SEV[res.overall_severity] ?? SEV.warning : null;

  return (
    <div className="space-y-5">
      <Card className="flex flex-wrap items-center justify-between gap-3 p-4">
        <div><div className="font-display text-[15px] font-bold">Telmisartan process simulator</div><div className="text-xs text-ink-muted">{r.description}</div></div>
        <Segmented value={route} onChange={setRoute} options={(routes.data ?? []).map((x) => ({ value: x.id, label: x.label.split("+")[0].trim() }))} />
      </Card>
      {res && (
        <motion.div layout className={cn("rounded-2xl p-4 ring-1 ring-inset", overall?.ring)}>
          <div className="flex items-center gap-2 text-sm"><Badge tone={overall?.tone}>{res.overall_severity}</Badge><b>{res.route_label}</b>{res.overall_failure_mode !== "none" && <span className="text-ink-muted">· likely failure: {String(res.overall_failure_mode).replace(/_/g, " ")}</span>}</div>
        </motion.div>
      )}
      <div className="grid gap-5 xl:grid-cols-2">
        {r.stages.map((s: any) => {
          const out = res?.stages?.find((x: any) => x.stage_id === s.id);
          const sev = out ? SEV[out.severity] ?? SEV.warning : null;
          return (
            <Card key={s.id}>
              <CardHeader title={s.label} subtitle="Critical process parameters → critical quality attributes" />
              <div className="space-y-4 p-5">
                {s.cpps.map((c: any) => {
                  const v = vals[c.name] ?? c.default;
                  const inBand = (c.optimum_low == null || v >= c.optimum_low) && (c.optimum_high == null || v <= c.optimum_high) && (c.required_min == null || v >= c.required_min);
                  return (
                    <label key={c.name} className="block text-xs">
                      <div className="flex justify-between"><span className="font-medium">{c.label}</span><span className={cn("font-semibold tabular-nums", !inBand && "text-rose-600")}>{v} {c.unit}</span></div>
                      <input type="range" min={c.min} max={c.max} step={c.step} value={v} onChange={(e) => setVals({ ...vals, [c.name]: Number(e.target.value) })} className="w-full accent-brand-600" />
                      <div className="flex justify-between text-[10px] text-ink-faint"><span>{c.min}</span>{(c.optimum_low != null || c.target != null || c.required_min != null) && <span>{c.optimum_low != null ? `optimum ${c.optimum_low}–${c.optimum_high}` : c.target != null ? `target ${c.target}` : `≥ ${c.required_min}`}</span>}<span>{c.max}</span></div>
                    </label>
                  );
                })}
              </div>
              <AnimatePresence mode="wait">
                {out && (
                  <motion.div key={out.severity + out.failure_mode} initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0 }} className={cn("m-5 mt-0 rounded-xl p-3.5 ring-1 ring-inset", sev?.ring)}>
                    <div className="flex items-center gap-2 text-sm font-semibold"><Badge tone={sev?.tone}>{out.severity}</Badge>{out.title}</div>
                    <p className="mt-1 text-xs text-ink-soft">{out.description}</p>
                    <div className="mt-2 flex flex-wrap gap-2">{Object.entries(out.cqas).map(([k, v]: any) => <span key={k} className="rounded-lg bg-white px-2 py-1 text-[11px] ring-1 ring-line"><span className="text-ink-muted">{(s.cqas.find((q: any) => q.name === k)?.label) ?? k}:</span> <b>{v}</b> {s.cqas.find((q: any) => q.name === k)?.unit}</span>)}</div>
                  </motion.div>
                )}
              </AnimatePresence>
            </Card>
          );
        })}
      </div>
    </div>
  );
}
