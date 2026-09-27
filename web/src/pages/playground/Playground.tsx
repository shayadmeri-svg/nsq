import { Compass, Cpu, Factory, FlaskConical, Globe2, HeartPulse, Lightbulb, Map, Pill, Table2 } from "lucide-react";
import { motion } from "motion/react";
import { useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { cn } from "../../lib/cn";
import { EMPTY, Explorer, FilterBar, Ledger, type Filters } from "./Explorer";
import { InsightsTab } from "./Insights";
import { Lab } from "./Lab";
import { Medicines } from "./Medicines";
import { Plants } from "./Plants";
import { RegulatoryMap } from "./RegulatoryMap";
import { Signals } from "./Signals";
import { Workbench } from "./Workbench";

const TABS = [
  { id: "explore", label: "NSQ explorer", icon: Map, hint: "All-India alerts: map, heatmaps, flows" },
  { id: "ledger", label: "Ledger", icon: Table2, hint: "Every alert — sort, pick columns, export" },
  { id: "insights", label: "Insights", icon: Lightbulb, hint: "Patterns the raw alerts don't show" },
  { id: "world", label: "Regulation map", icon: Globe2, hint: "India vs US vs EU vs Africa…" },
  { id: "molecule", label: "Molecule workbench", icon: FlaskConical, hint: "Passport, demand, scores, monographs" },
  { id: "plants", label: "Plants", icon: Factory, hint: "CDSCO plant registry: what each plant may make, and its NSQ record" },
  { id: "health", label: "Health & trade", icon: HeartPulse, hint: "Disease burden by district (NFHS), outbreaks (IDSP), pharma trade (UN Comtrade)" },
  { id: "medicines", label: "Medicines", icon: Pill, hint: "Add a medicine: composition from open databases, gaps" },
  { id: "process", label: "Lab", icon: Cpu, hint: "Structure-based molecule and process models" },
] as const;

export function Playground() {
  const { tab = "explore" } = useParams();
  const nav = useNavigate();
  const [f, setF] = useState<Filters>(EMPTY);
  const cur = TABS.find((t) => t.id === tab) ?? TABS[0];
  return (
    <>
      <div className="mb-5 flex flex-wrap items-center justify-between gap-3">
        <div className="min-w-0">
          <div className="flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-[0.14em] text-brand-700"><Compass size={13} /> Playground</div>
          <h1 className="mt-0.5 font-display text-2xl font-extrabold tracking-tight">{cur.label}</h1>
          <p className="text-xs text-ink-muted">{cur.hint}</p>
        </div>
        <div className="flex items-center gap-1 rounded-2xl bg-white p-1.5 ring-1 ring-inset ring-line">
          {TABS.map((t) => {
            const on = tab === t.id;
            return (
              <button key={t.id} onClick={() => nav(`/playground/${t.id}`)} title={`${t.label} — ${t.hint}`} aria-label={t.label}
                className={cn("group relative flex h-10 items-center justify-center gap-2 rounded-xl text-[13px] font-medium transition", on ? "px-3.5 text-white" : "w-10 text-ink-soft hover:bg-slate-50 hover:text-ink")}>
                {on && <motion.span layoutId="pg-tab" className="absolute inset-0 rounded-xl bg-night-900" transition={{ type: "spring", stiffness: 500, damping: 38 }} />}
                <t.icon size={17} className="relative" />
                {on && <span className="relative whitespace-nowrap">{t.label}</span>}
                {!on && <span className="pointer-events-none absolute top-full z-30 mt-2 hidden whitespace-nowrap rounded-lg bg-night-900 px-2.5 py-1.5 text-xs text-white shadow-lift group-hover:block">{t.label}</span>}
              </button>
            );
          })}
        </div>
      </div>
      {(tab === "explore" || tab === "ledger") && <div className="mb-5"><FilterBar f={f} set={setF} /></div>}
      <motion.div key={tab} initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.25 }}>
        {tab === "explore" && <Explorer f={f} set={setF} />}
        {tab === "ledger" && <Ledger f={f} />}
        {tab === "insights" && <InsightsTab />}
        {tab === "world" && <RegulatoryMap />}
        {tab === "molecule" && <Workbench />}
        {tab === "plants" && <Plants />}
        {tab === "health" && <Signals />}
        {tab === "medicines" && <Medicines />}
        {tab === "process" && <Lab />}
      </motion.div>
    </>
  );
}
