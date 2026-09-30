// Admin · Data operations: everything that keeps the data current, in one place —
// update jobs and sources, their schedules, and the map of where each dataset flows.
import { useQuery } from "@tanstack/react-query";
import { CalendarClock, Network, RefreshCcw } from "lucide-react";
import { motion } from "motion/react";
import { Navigate, useLocation, useNavigate, useParams } from "react-router-dom";
import { api } from "../../lib/api";
import { cn } from "../../lib/cn";
import { DataMap } from "./DataMap";
import { Jobs } from "./Jobs";
import { Pipelines } from "./Pipelines";

const TABS = [
  { id: "update", label: "Update & sources", icon: RefreshCcw, hint: "Update everything, each source's data and its job, run history" },
  { id: "schedules", label: "Schedules", icon: CalendarClock, hint: "When each source and pipeline runs on its own" },
  { id: "map", label: "Data map", icon: Network, hint: "Where every dataset comes from, where it lives, what changes it and which screens read it" },
] as const;

// Old addresses keep working
export const LEGACY: Record<string, string> = { "/admin/jobs": "update", "/admin/pipelines": "schedules", "/admin/data-map": "map" };

export function LegacyDataRoute() {
  const loc = useLocation();
  return <Navigate to={`/admin/data/${LEGACY[loc.pathname] ?? "update"}${loc.search}`} replace />;
}

export function DataOps() {
  const { tab = "update" } = useParams();
  const nav = useNavigate();
  const loc = useLocation();
  // live status for the tab strip (same query key the jobs page uses, so no extra request)
  const jobs = useQuery({ queryKey: ["jobs"], queryFn: () => api<any>("/api/jobs"), refetchInterval: 10_000 });
  const running = (jobs.data?.jobs ?? []).filter((j: any) => j.running).length;
  const failing = (jobs.data?.jobs ?? []).filter((j: any) => j.source && j.last_run?.status === "failed").length;
  const cur = TABS.find((t) => t.id === tab);
  if (!cur) return <Navigate to={`/admin/data/update${loc.search}`} replace />;

  return (
    <>
      <div className="sticky top-16 z-10 -mx-4 mb-5 bg-canvas/85 px-4 pb-3 pt-1 backdrop-blur-md md:-mx-8 md:px-8">
        <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
          <div className="flex items-center gap-2">
            <span className="relative grid h-8 w-8 place-items-center rounded-xl bg-gradient-to-br from-brand-500 to-emerald-700 text-white shadow-sm">
              <RefreshCcw size={15} className={cn(running > 0 && "animate-spin [animation-duration:2.4s]")} />
            </span>
            <div className="leading-tight">
              <div className="text-[11px] font-semibold uppercase tracking-[0.14em] text-brand-700">Data operations</div>
              <div className="text-[11.5px] text-ink-muted">
                {running > 0 ? <span className="font-semibold text-brand-700">{running} job{running > 1 ? "s" : ""} running</span> : "Nothing running"}
                {failing > 0 && <> · <button onClick={() => nav("/admin/data/update")} className="font-semibold text-rose-600 hover:underline">{failing} source{failing > 1 ? "s" : ""} failed last run</button></>}
              </div>
            </div>
          </div>
          <div className="flex w-fit max-w-full items-center gap-1 overflow-x-auto rounded-2xl bg-white p-1.5 ring-1 ring-inset ring-line">
            {TABS.map((t) => {
              const on = t.id === tab;
              return (
                <button key={t.id} onClick={() => nav(`/admin/data/${t.id}`)} title={t.hint}
                  className={cn("relative flex h-9 items-center gap-2 whitespace-nowrap rounded-xl px-3.5 text-[13px] font-medium transition", on ? "text-white" : "text-ink-soft hover:bg-slate-50 hover:text-ink")}>
                  {on && <motion.span layoutId="dataops-tab" className="absolute inset-0 rounded-xl bg-night-900" transition={{ type: "spring", stiffness: 500, damping: 38 }} />}
                  <t.icon size={15} className="relative" />
                  <span className="relative">{t.label}</span>
                  {t.id === "update" && running > 0 && <span className="relative h-1.5 w-1.5 animate-pulse rounded-full bg-emerald-400" />}
                </button>
              );
            })}
          </div>
        </div>
      </div>
      <motion.div key={tab} initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.2 }}>
        {tab === "update" && <Jobs />}
        {tab === "schedules" && <Pipelines />}
        {tab === "map" && <DataMap />}
      </motion.div>
    </>
  );
}
