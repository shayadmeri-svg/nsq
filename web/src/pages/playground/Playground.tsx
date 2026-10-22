import { Activity, BookOpenCheck, Compass, Cpu, Factory, FlaskConical, FlaskRound, FileCheck2, Globe2, HeartPulse, Layers, Lightbulb, Map, Microscope, Pill, Radio, ScanSearch, ShieldAlert, Table2 } from "lucide-react";
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
import { PlantMonitor } from "./PlantMonitor";
import { Plants } from "./Plants";
import { ReactionLab } from "./ReactionLab";
import { RegulatoryMap } from "./RegulatoryMap";
import { Signals } from "./Signals";
import { Workbench } from "./Workbench";
import { WrittenConfirmations } from "./WrittenConfirmations";

// Every tool keeps its id: it is the URL (/playground/<id>) and the feature the server grants (`feature` when two tools share one).
export const TABS = [
  // your plant
  { id: "monitor", group: "plant", short: "Live", label: "Plant monitor", icon: Activity, hint: "The live plant: every machine, the batch and product on it, each reading against that product's range, and alarms" },
  { id: "plant-data", group: "plant", short: "Batches", label: "Batch records", icon: Layers, hint: "Your batch records and machine exports (CSV, Excel, SCADA): control charts, batch diagnosis and the failure tree on your data" },
  { id: "line", feature: "plant-data", group: "plant", short: "Simulated line", label: "Simulated line", icon: Radio, hint: "The demo line streaming batches: tune each machine, and see each batch's forecast test results" },
  // CDSCO NSQ alerts
  { id: "explore", group: "nsq", short: "Map", label: "NSQ explorer", icon: Map, hint: "All-India alerts: map, heatmaps, flows" },
  { id: "ledger", group: "nsq", short: "Table", label: "NSQ ledger", icon: Table2, hint: "Every alert — sort, pick columns, export" },
  { id: "investigate", group: "nsq", short: "Investigate", label: "Investigate", icon: ScanSearch, hint: "Any product or manufacturer: full NSQ history, and each alert's standards, causes and mitigation" },
  { id: "forensics", group: "nsq", short: "Forensics", label: "Failure forensics", icon: Microscope, hint: "Why products fail NSQ: which test, how early, formula or plant — and what to check before your first batch" },
  { id: "insights", group: "nsq", short: "Insights", label: "Insights", icon: Lightbulb, hint: "Patterns the raw alerts don't show" },
  // market, registry and regulation
  { id: "plants", group: "market", short: "Plant registry", label: "Plant registry", icon: Factory, hint: "CDSCO plant registry: what each plant may make, and its NSQ record" },
  { id: "wc", group: "market", short: "WC letters", label: "Written confirmations", icon: FileCheck2, hint: "CDSCO International Cell: every Written Confirmation for API exports to the EU, with the letters" },
  { id: "world", group: "market", short: "Regulation", label: "Regulation map", icon: Globe2, hint: "India vs US vs EU vs Africa…" },
  { id: "health", group: "market", short: "Health & trade", label: "Health & trade", icon: HeartPulse, hint: "Disease burden by district (NFHS), outbreaks (IDSP), pharma trade (UN Comtrade)" },
  // product and process science
  { id: "molecule", group: "science", short: "Molecules", label: "Molecule workbench", icon: FlaskConical, hint: "Passport, demand, scores, monographs" },
  { id: "medicines", group: "science", short: "Medicines", label: "Medicines", icon: Pill, hint: "Add a medicine: composition from open databases, gaps" },
  { id: "process", group: "science", short: "Process lab", label: "Process lab", icon: Cpu, hint: "Structure-based molecule and process models" },
  { id: "reactions", group: "science", short: "Reactions", label: "Reaction lab", icon: FlaskRound, hint: "Run a synthesis step: kinetics, yield map, operating window and thermal safety — anchored to published routes" },
] as const;

type Tab = (typeof TABS)[number];

const GROUPS = [
  { id: "plant", label: "Your plant", icon: Factory, hint: "Live machines, batch records, the simulated line" },
  { id: "nsq", label: "NSQ alerts", icon: ShieldAlert, hint: "CDSCO not-of-standard-quality alerts: map, table, causes" },
  { id: "market", label: "Market & regulation", icon: Globe2, hint: "Plant registry, WC letters, regulators, demand" },
  { id: "science", label: "Science", icon: BookOpenCheck, hint: "Molecules, medicines, process and reaction models" },
] as const;

const LAST = "pg-last-tab:";
const remember = (group: string, id: string) => { try { localStorage.setItem(LAST + group, id); } catch { /* storage unavailable */ } };
const recall = (group: string) => { try { return localStorage.getItem(LAST + group); } catch { return null; } };

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
  const tabs: Tab[] = TABS.filter((t) => me?.is_platform || me?.features?.includes("feature" in t ? t.feature : t.id));
  if (!tabs.length) return <Empty title="No Playground tools yet">Your organisation doesn't have any Playground features, or your admin hasn't shared them with your role. Ask your organisation admin.</Empty>;
  const cur = tabs.find((t) => t.id === want) ?? tabs[0];
  const tab = cur.id;
  const groups = GROUPS.filter((g) => tabs.some((t) => t.group === g.id));
  const inGroup = tabs.filter((t) => t.group === cur.group);
  // within the plant section the org and molecule (?org=, ?m=) carry over; elsewhere a tool starts clean
  const go = (id: string, keep = false) => {
    const t = tabs.find((x) => x.id === id);
    if (t) remember(t.group, id);
    const q = new URLSearchParams(keep ? loc.search : "");
    ["view", "src", "tab"].forEach((k) => q.delete(k));
    const qs = q.toString();
    nav(`${root}/${id}${qs ? `?${qs}` : ""}`);
  };
  const openGroup = (g: string) => {
    const last = recall(g);
    go(tabs.find((t) => t.group === g && t.id === last)?.id ?? tabs.find((t) => t.group === g)!.id);
  };
  const plant = tab === "plant-data" || tab === "line";
  return (
    <>
      <div className="mb-5 space-y-3">
        {/* the four sections */}
        <div className="no-scrollbar flex w-fit max-w-full gap-1 overflow-x-auto rounded-2xl bg-white p-1.5 shadow-card ring-1 ring-inset ring-line">
          {groups.map((g) => {
            const on = cur.group === g.id;
            return (
              <button key={g.id} onClick={() => !on && openGroup(g.id)} title={g.hint} aria-current={on ? "page" : undefined}
                className={cn("relative flex h-10 shrink-0 items-center gap-2 rounded-xl px-4 text-[13px] font-semibold transition",
                  on ? "text-white" : "text-ink-soft hover:bg-gold-50 hover:text-ink")}>
                {on && <motion.span layoutId="pg-group" className="absolute inset-0 rounded-xl bg-night-900 shadow-lift" transition={{ type: "spring", stiffness: 500, damping: 38 }} />}
                <g.icon size={16} className={cn("relative", on && "text-gold-400")} />
                <span className="relative whitespace-nowrap">{g.label}</span>
              </button>
            );
          })}
        </div>
        <div className="min-w-0">
          <div className="flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-[0.14em] text-gold-600"><Compass size={13} /> Playground · {groups.find((g) => g.id === cur.group)?.label}</div>
          <h1 className="mt-0.5 font-display text-[30px] font-semibold leading-tight tracking-tight">{cur.label}</h1>
          <p className="truncate text-xs text-ink-muted">{cur.hint}</p>
        </div>
        {/* the tools in this section */}
        {inGroup.length > 1 && (
          <div className="no-scrollbar flex max-w-full gap-1 overflow-x-auto border-b border-line">
            {inGroup.map((t) => {
              const on = tab === t.id;
              return (
                <button key={t.id} onClick={() => !on && go(t.id, cur.group === "plant")} title={t.hint} aria-current={on ? "page" : undefined}
                  className={cn("relative flex shrink-0 items-center gap-1.5 px-3 pb-2.5 pt-1 text-[13px] font-semibold transition",
                    on ? "text-ink" : "text-ink-muted hover:text-ink")}>
                  <t.icon size={15} className={on ? "text-gold-600" : ""} />
                  <span className="whitespace-nowrap">{t.short}</span>
                  {on && <motion.span layoutId="pg-tab" className="absolute inset-x-2 -bottom-px h-0.5 rounded-full bg-night-900" transition={{ type: "spring", stiffness: 500, damping: 38 }} />}
                </button>
              );
            })}
          </div>)}
      </div>
      {(tab === "explore" || tab === "ledger") && <div className="mb-5"><FilterBar f={f} set={setF} /></div>}
      {/* the two plant-data views share one mount, so switching keeps the molecule, uploads and a replay in progress */}
      <motion.div key={plant ? "plant-data" : tab} initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.25 }}>
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
        {plant && <PlantData view={tab === "line" ? "live" : "batches"} onView={(v) => go(v === "live" ? "line" : "plant-data", true)} />}
        {tab === "monitor" && <PlantMonitor />}
        {tab === "reactions" && <ReactionLab />}
      </motion.div>
    </>
  );
}
