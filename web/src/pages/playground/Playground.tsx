import { Compass, Cpu, FlaskConical, Globe2, Lightbulb, Map, Table2 } from "lucide-react";
import { motion } from "motion/react";
import { useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { PageHeader } from "../../components/ui";
import { cn } from "../../lib/cn";
import { EMPTY, Explorer, FilterBar, Ledger, type Filters } from "./Explorer";
import { InsightsTab } from "./Insights";
import { ProcessLab } from "./ProcessLab";
import { RegulatoryMap } from "./RegulatoryMap";
import { Workbench } from "./Workbench";

const TABS = [
  { id: "explore", label: "NSQ explorer", icon: Map, hint: "All-India alerts: map, heatmaps, flows" },
  { id: "ledger", label: "Ledger", icon: Table2, hint: "Every alert — sort, pick columns, export" },
  { id: "insights", label: "Insights", icon: Lightbulb, hint: "Patterns the raw alerts don't show" },
  { id: "world", label: "Regulation map", icon: Globe2, hint: "India vs US vs EU vs Africa…" },
  { id: "molecule", label: "Molecule workbench", icon: FlaskConical, hint: "Passport, demand, scores, monographs" },
  { id: "process", label: "Process lab", icon: Cpu, hint: "Telmisartan CPP simulator" },
] as const;

export function Playground() {
  const { tab = "explore" } = useParams();
  const nav = useNavigate();
  const [f, setF] = useState<Filters>(EMPTY);
  return (
    <>
      <PageHeader eyebrow={<span className="flex items-center gap-1.5"><Compass size={13} /> Playground</span>} title="Explore everything"
        subtitle="The exploratory views from the original analytics and simulator apps, rebuilt on live platform data — plus new cross-cutting analytics. National CDSCO data and public sources; nothing here is organisation-private." />
      <div className="mb-5 flex gap-1 overflow-x-auto rounded-2xl bg-white p-1.5 ring-1 ring-inset ring-line scrollbar-thin">
        {TABS.map((t) => {
          const on = tab === t.id;
          return (
            <button key={t.id} onClick={() => nav(`/playground/${t.id}`)} title={t.hint}
              className={cn("relative flex shrink-0 items-center gap-2 rounded-xl px-3.5 py-2 text-[13px] font-medium transition", on ? "text-white" : "text-ink-soft hover:bg-slate-50")}>
              {on && <motion.span layoutId="pg-tab" className="absolute inset-0 rounded-xl bg-night-900" transition={{ type: "spring", stiffness: 500, damping: 38 }} />}
              <t.icon size={15} className="relative" /><span className="relative">{t.label}</span>
            </button>
          );
        })}
      </div>
      {(tab === "explore" || tab === "ledger") && <div className="mb-5"><FilterBar f={f} set={setF} /></div>}
      <motion.div key={tab} initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.25 }}>
        {tab === "explore" && <Explorer f={f} set={setF} />}
        {tab === "ledger" && <Ledger f={f} />}
        {tab === "insights" && <InsightsTab />}
        {tab === "world" && <RegulatoryMap />}
        {tab === "molecule" && <Workbench />}
        {tab === "process" && <ProcessLab />}
      </motion.div>
    </>
  );
}
