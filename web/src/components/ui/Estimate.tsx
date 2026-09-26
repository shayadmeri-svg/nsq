// Disclaimer icon: marks a value that is an estimate / inferred / frozen and
// explains, on hover or tap, what is present today and what is missing. Text
// comes from the backend registry (core/field_provenance.py).
import { AnimatePresence, motion } from "motion/react";
import { AlertTriangle, Info } from "lucide-react";
import { useState } from "react";
import { cn } from "../../lib/cn";
import { useProvenance } from "../../lib/provenance";

const TONE: Record<string, { icon: string; chip: string; word: string }> = {
  estimate: { icon: "text-amber-500 hover:text-amber-600", chip: "bg-amber-50 text-amber-700", word: "Estimate" },
  inferred: { icon: "text-sky-500 hover:text-sky-600", chip: "bg-sky-50 text-sky-700", word: "Inferred" },
  frozen: { icon: "text-slate-400 hover:text-slate-600", chip: "bg-slate-100 text-slate-700", word: "Snapshot" },
  sourced: { icon: "text-emerald-500 hover:text-emerald-600", chip: "bg-emerald-50 text-emerald-700", word: "Sourced" },
};

export function Estimate({ field, className, align = "left" }: { field: string; className?: string; align?: "left" | "right" }) {
  const { data } = useProvenance();
  const [open, setOpen] = useState(false);
  const f = data?.fields[field];
  if (!f) return null;
  const t = TONE[f.status] ?? TONE.estimate;
  const Icon = f.status === "estimate" ? AlertTriangle : Info;
  return (
    <span className={cn("relative inline-flex align-middle", className)} onMouseEnter={() => setOpen(true)} onMouseLeave={() => setOpen(false)}>
      <button
        type="button"
        aria-label={`${f.label}: ${t.word.toLowerCase()} — details`}
        onClick={(e) => { e.stopPropagation(); setOpen((o) => !o); }}
        className={cn("inline-grid h-4 w-4 place-items-center transition", t.icon)}
      >
        <Icon size={13} strokeWidth={2.4} />
      </button>
      <AnimatePresence>
        {open && (
          <motion.span
            key="pop"
            initial={{ opacity: 0, y: 4 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: 4 }} transition={{ duration: 0.15 }}
            className={cn("absolute top-5 z-50 block w-72 rounded-xl bg-white p-3 text-left text-xs font-normal normal-case tracking-normal text-ink shadow-lift ring-1 ring-line", align === "right" ? "right-0" : "left-0")}
            onClick={(e) => e.stopPropagation()}
          >
            <span className="mb-2 flex items-center justify-between gap-2">
              <span className="font-semibold">{f.label}</span>
              <span className={cn("rounded-full px-2 py-0.5 text-[10px] font-bold uppercase tracking-wider", t.chip)}>{t.word}</span>
            </span>
            <span className="block text-ink-soft"><b className="text-ink">Present: </b>{f.present}</span>
            <span className="mt-1.5 block text-ink-soft"><b className="text-ink">Gap: </b>{f.gap}</span>
          </motion.span>
        )}
      </AnimatePresence>
    </span>
  );
}
