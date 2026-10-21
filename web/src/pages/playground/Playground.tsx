import { Compass, Cpu, Radio, Factory, FlaskRound, FileCheck2, Microscope, ScanSearch, FlaskConical, Globe2, HeartPulse, Lightbulb, Map, Pill, Table2 } from "lucide-react";
import { motion } from "motion/react";
import { useState } from "react";
import { Navigate, useLocation, useNavigate, useParams } from "react-router-dom";
import { useMe } from "../../lib/session";
import { Empty } from "../../components/ui";
import { cn } from "../../lib/cn";
import { EMPTY, Explorer, FilterBar, Ledger, type Filters } from "./Explorer";
import { Forensics } from "./Forensics";
import { InsightsTab } from "./Insights";
import { Investigate } from "./Investigate";
import { Lab } from "./Lab";
import { Medicines } from "./Medicines";
import { PlantData } from "./PlantData";
import { Plants } from "./Plants";
import { ReactionLab } from "./ReactionLab";
import { RegulatoryMap } from "./RegulatoryMap";
import { Signals } from "./Signals";
import { Workbench } from "./Workbench";
import { WrittenConfirmations } from "./WrittenConfirmations";

export const TABS = [
  { id: "explore", short: "Explorer", label: "NSQ explorer", icon: Map, hint: "All-India alerts: map, heatmaps, flows" },
  { id: "ledger", short: "Ledger", label: "Ledger", icon: Table2, hint: "Every alert — sort, pick columns, export" },
  { id: "insights", short: "Insights", label: "Insights", icon: Lightbulb, hint: "Patterns the raw alerts don't show" },
  { id: "forensics", short: "Forensics", label: "Failure forensics", icon: Microscope, hint: "Why products fail NSQ: which test, how early, formula or plant — and what to check before your first batch" },
  { id: "investigate", short: "Investigate", label: "Investigate", icon: ScanSearch, hint: "Any product or manufacturer: full NSQ history, and each alert's standards, causes and mitigation" },
  { id: "world", short: "Regulation", label: "Regulation map", icon: Globe2, hint: "India vs US vs EU vs Africa…" },
  { id: "molecule", short: "Workbench", label: "Molecule workbench", icon: FlaskConical, hint: "Passport, demand, scores, monographs" },
  { id: "plants", short: "Plants", label: "Plants", icon: Factory, hint: "CDSCO plant registry: what each plant may make, and its NSQ record" },
  { id: "wc", short: "WC letters", label: "Written confirmations", icon: FileCheck2, hint: "CDSCO International Cell: every Written Confirmation for API exports to the EU, with the letters" },
  { id: "health", short: "Health", label: "Health & trade", icon: HeartPulse, hint: "Disease burden by district (NFHS), outbreaks (IDSP), pharma trade (UN Comtrade)" },
  { id: "medicines", short: "Medicines", label: "Medicines", icon: Pill, hint: "Add a medicine: composition from open databases, gaps" },
  { id: "process", short: "Lab", label: "Lab", icon: Cpu, hint: "Structure-based molecule and process models" },
  { id: "plant-data", short: "Plant data", label: "Plant data", icon: Radio, hint: "Your batch records and machine streams (CSV, Excel, SCADA): control charts, batch diagnosis, live forecast and the failure tree on your data" },
  { id: "reactions", short: "Reactions", label: "Reaction lab", icon: FlaskRound, hint: "Run a synthesis step: kinetics, yield map, operating window and thermal safety — anchored to published routes" },
] as const;

// `base`: where the tabs live — /playground for platform staff, /o/<slug>/playground inside an organisation.
// Only the features the server says this user has are shown (the API enforces the same list).
export function Playground({ base }: { base?: string }) {
  const { tab: want, slug } = useParams();
  const nav = useNavigate();
  const loc = useLocation();
  const { data: me } = useMe();
  const [f, setF] = useState<Filters>(EMPTY);
  const root = base ?? (slug ? `/o/${slug}/playground` : "/playground");
  if (me && !me.is_platform && !slug) return <Navigate to={me.org ? `/o/${me.org.slug}/playground${want ? "/" + want : ""}${loc.search}` : "/account"} replace />;
  const tabs = TABS.filter((t) => me?.is_platform || me?.features?.includes(t.id));
  if (!tabs.length) return <Empty title="No Playground tools yet">Your organisation doesn't have any Playground features, or your admin hasn't shared them with your role. Ask your organisation admin.</Empty>;
  const cur = tabs.find((t) => t.id === want) ?? tabs[0];
  const tab = cur.id;
  return (
    <>
      <div className="mb-5 space-y-3">
        <div className="min-w-0">
          <div className="flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-[0.14em] text-gold-600"><Compass size={13} /> Playground</div>
          <h1 className="mt-0.5 font-display text-[30px] font-semibold leading-tight tracking-tight">{cur.label}</h1>
          <p className="truncate text-xs text-ink-muted">{cur.hint}</p>
        </div>
        {/* every tool the same size, so switching never moves the strip */}
        <div className="no-scrollbar flex w-fit max-w-full gap-1 overflow-x-auto rounded-2xl bg-white p-1.5 shadow-card ring-1 ring-inset ring-line">
          {tabs.map((t) => {
            const on = tab === t.id;
            return (
              <button key={t.id} onClick={() => nav(`${root}/${t.id}`)} title={`${t.label} — ${t.hint}`} aria-label={t.label} aria-current={on ? "page" : undefined}
                className={cn("relative flex h-[58px] w-[78px] shrink-0 flex-col items-center justify-center gap-1 rounded-xl transition",
                  on ? "text-white" : "text-ink-soft hover:bg-gold-50 hover:text-ink")}>
                {on && <motion.span layoutId="pg-tab" className="absolute inset-0 rounded-xl bg-night-900 shadow-lift" transition={{ type: "spring", stiffness: 500, damping: 38 }} />}
                <t.icon size={18} className={cn("relative", on && "text-gold-400")} />
                <span className="relative w-full truncate px-1 text-center text-[10.5px] font-semibold leading-none">{t.short}</span>
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
        {tab === "forensics" && <Forensics />}
        {tab === "investigate" && <Investigate />}
        {tab === "world" && <RegulatoryMap />}
        {tab === "molecule" && <Workbench initial={new URLSearchParams(window.location.search).get("m") ?? undefined} />}
        {tab === "plants" && <Plants />}
        {tab === "wc" && <WrittenConfirmations />}
        {tab === "health" && <Signals />}
        {tab === "medicines" && <Medicines />}
        {tab === "process" && <Lab />}
        {tab === "plant-data" && <PlantData />}
        {tab === "reactions" && <ReactionLab />}
      </motion.div>
    </>
  );
}
