// Capability chips and the 7-section coverage view, shared by the org Infrastructure page
// and the Playground plant registry. A chip's style says how we know the plant has it.

import { Bar } from "./ui";
import { Estimate } from "./ui/Estimate";
import { cn } from "../lib/cn";

const BASIS_TITLE: Record<string, string> = {
  stated: "Stated by a source for this plant",
  required: "Required by GMP rules for what CDSCO lists this plant as making — not an inspection record",
  inferred: "Usual for a form the plant makes — not evidenced",
  user: "Entered in the app",
};

export function CapChip({ label, basis, why }: { label: string; basis: string; why?: string | string[] | null }) {
  const reason = Array.isArray(why) ? why.join(" ") : why;
  return (
    <span title={[BASIS_TITLE[basis] ?? "Derived", reason].filter(Boolean).join(" — ")}
      className={cn("rounded-md px-1.5 py-0.5 text-[11px]",
        basis === "stated" ? "bg-brand-50 font-medium text-brand-700 ring-1 ring-inset ring-brand-200"
          : basis === "required" ? "bg-indigo-50 font-medium text-indigo-700 ring-1 ring-inset ring-indigo-200"
            : basis === "inferred" ? "border border-dashed border-sky-400 text-sky-700"
              : basis === "user" ? "bg-slate-100 font-medium text-ink-soft" : "bg-slate-100 text-slate-600")}>
      {label}
    </span>
  );
}

export function BasisLegend({ required = true }: { required?: boolean }) {
  return (
    <div className="flex flex-wrap items-center gap-3 text-[11px] text-ink-muted">
      <span className="flex items-center gap-1"><span className="h-2.5 w-2.5 rounded-sm bg-brand-500" /> stated</span>
      {required && <span className="flex items-center gap-1" title={BASIS_TITLE.required}><span className="h-2.5 w-2.5 rounded-sm bg-indigo-400" /> required by its licence</span>}
      <span className="flex items-center gap-1"><span className="h-2.5 w-2.5 rounded-sm border border-dashed border-sky-500" /> inferred <Estimate field="capability_inferred" align="right" /></span>
    </div>
  );
}

export function CoverageSections({ sections, other }: { sections: any[]; other?: any[] }) {
  return (
    <div className="space-y-3">
      {sections.map((s: any) => {
        const pct = s.total ? (100 * s.have.length) / s.total : 0;
        return (
          <div key={s.id}>
            <div className="mb-1 flex justify-between text-xs"><span className="font-medium text-ink-soft">{s.title}</span><span className="tabular-nums text-ink-muted">{s.have.length}/{s.total}</span></div>
            <Bar value={pct} color={pct > 40 ? "#0a9a7d" : pct > 0 ? "#f59e0b" : "#e2e8f0"} />
            {s.have.length > 0 && <div className="mt-1.5 flex flex-wrap gap-1">{s.have.map((h: any) => <CapChip key={h.token} label={h.label} basis={h.basis} why={h.why} />)}</div>}
          </div>
        );
      })}
      {other && other.length > 0 && (
        <div><div className="mb-1 text-xs font-medium text-ink-soft">Other process capabilities</div>
          <div className="flex flex-wrap gap-1">{other.map((h: any) => <CapChip key={h.token} label={h.label} basis={h.basis} why={h.why} />)}</div></div>
      )}
    </div>
  );
}
