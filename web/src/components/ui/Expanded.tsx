// Compact tiles that open into a full-screen "expanded view". Long lists and tables live in the expanded
// view (with its own section navigation), so pages stay short: each tile shows the two or three facts that
// matter and an Expand button.
import { Maximize2, X } from "lucide-react";
import { AnimatePresence, motion } from "motion/react";
import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { cn } from "../../lib/cn";
import { Card, CardHeader } from "./index";

export type Section = { id: string; title: string; subtitle?: ReactNode; icon?: ReactNode; render: () => ReactNode };

type Ctx = { open: (id: string) => void };
const ExpandedCtx = createContext<Ctx>({ open: () => undefined });
export const useExpanded = () => useContext(ExpandedCtx);

/** Provides `open(sectionId)` to tiles below it and renders the expanded view over the page. */
export function ExpandedProvider({ sections, title, subtitle, children, active: ctrl, onActive }: {
  sections: Section[]; title: ReactNode; subtitle?: ReactNode; children: ReactNode; active?: string | null; onActive?: (id: string | null) => void;
}) {
  const [own, setOwn] = useState<string | null>(null);
  const active = ctrl !== undefined ? ctrl : own;
  const setActive = onActive ?? setOwn;
  const open = useCallback((id: string) => setActive(id), [setActive]);
  const value = useMemo(() => ({ open }), [open]);
  return (
    <ExpandedCtx.Provider value={value}>
      {children}
      <ExpandedView sections={sections} active={active} onChange={setActive} title={title} subtitle={subtitle} />
    </ExpandedCtx.Provider>
  );
}

export function ExpandedView({ sections, active, onChange, title, subtitle }: {
  sections: Section[]; active: string | null; onChange: (id: string | null) => void; title: ReactNode; subtitle?: ReactNode;
}) {
  const cur = sections.find((s) => s.id === active);
  useEffect(() => {
    if (!active) return;
    const idx = sections.findIndex((s) => s.id === active);
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onChange(null);
      if ((e.key === "ArrowDown" || e.key === "ArrowUp") && e.altKey) {
        e.preventDefault();
        const n = sections[(idx + (e.key === "ArrowDown" ? 1 : sections.length - 1)) % sections.length];
        onChange(n.id);
      }
    };
    window.addEventListener("keydown", onKey);
    const prev = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => { window.removeEventListener("keydown", onKey); document.body.style.overflow = prev; };
  }, [active, sections, onChange]);
  return (
    <AnimatePresence>
      {cur && (
        <motion.div key="expanded" className="fixed inset-0 z-50" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} transition={{ duration: 0.18 }}>
          <div className="absolute inset-0 bg-night-900/40 backdrop-blur-sm" onClick={() => onChange(null)} />
          <motion.div
            className="absolute inset-2 flex overflow-hidden rounded-2xl bg-canvas shadow-lift ring-1 ring-line md:inset-6"
            initial={{ scale: 0.98, y: 12 }} animate={{ scale: 1, y: 0 }} exit={{ scale: 0.98, y: 12 }} transition={{ type: "spring", damping: 30, stiffness: 320 }}
          >
            {sections.length > 1 && (
              <nav className="scrollbar-thin hidden w-60 shrink-0 flex-col gap-0.5 overflow-y-auto border-r border-line bg-white p-3 md:flex">
                <div className="px-2 pb-3 pt-1">
                  <div className="truncate font-display text-[15px] font-bold">{title}</div>
                  {subtitle && <div className="mt-0.5 text-[11px] text-ink-muted">{subtitle}</div>}
                </div>
                {sections.map((s) => (
                  <button key={s.id} onClick={() => onChange(s.id)}
                    className={cn("flex items-center gap-2.5 rounded-lg px-2.5 py-2 text-left text-[13px] transition",
                      s.id === cur.id ? "bg-night-900 font-medium text-white" : "text-ink-soft hover:bg-slate-50")}>
                    <span className={cn("shrink-0", s.id === cur.id ? "text-brand-400" : "text-ink-muted")}>{s.icon}</span>
                    <span className="truncate">{s.title}</span>
                  </button>
                ))}
                <div className="mt-auto px-2 pt-4 text-[10.5px] text-ink-faint">Esc to close · Alt + ↑/↓ to move between sections</div>
              </nav>
            )}
            <div className="flex min-w-0 flex-1 flex-col">
              <div className="flex items-start justify-between gap-4 border-b border-line bg-white px-6 py-4">
                <div className="min-w-0">
                  <div className="flex items-center gap-2 font-display text-lg font-bold">{cur.icon}<span className="truncate">{cur.title}</span></div>
                  {cur.subtitle && <div className="mt-0.5 text-xs text-ink-muted">{cur.subtitle}</div>}
                </div>
                <div className="flex items-center gap-2">
                  {sections.length > 1 && (
                    <select className="input h-9 md:hidden" value={cur.id} onChange={(e) => onChange(e.target.value)}>
                      {sections.map((s) => <option key={s.id} value={s.id}>{s.title}</option>)}
                    </select>
                  )}
                  <button onClick={() => onChange(null)} className="rounded-lg p-2 text-ink-muted hover:bg-slate-100" title="Close (Esc)"><X size={18} /></button>
                </div>
              </div>
              <motion.div key={cur.id} initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.18 }}
                className="scrollbar-thin flex-1 overflow-y-auto p-5 md:p-6">
                {cur.render()}
              </motion.div>
            </div>
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>
  );
}

/** A compact card: the few facts that matter, the whole thing one click away in the expanded view. */
export function Tile({ id, title, subtitle, icon, children, className, footer, accent, action, clickable = true }: {
  id?: string; title: ReactNode; subtitle?: ReactNode; icon?: ReactNode; children: ReactNode; className?: string; footer?: ReactNode; accent?: string;
  action?: ReactNode; clickable?: boolean;
}) {
  const { open } = useExpanded();
  return (
    <motion.div initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.3 }}
      className={cn("group relative flex min-w-0 flex-col rounded-2xl bg-white ring-1 ring-inset ring-line transition hover:shadow-card hover:ring-slate-300", id && clickable && "cursor-pointer", className)}
      onClick={id && clickable ? () => open(id) : undefined}>
      {accent && <div className="absolute inset-x-0 top-0 h-1 rounded-t-2xl" style={{ background: accent }} />}
      <div className="flex items-start justify-between gap-3 px-4 pt-4">
        <div className="min-w-0">
          <div className="flex items-start gap-2 text-[13px] font-semibold leading-snug text-ink">{icon && <span className="mt-0.5 text-ink-muted">{icon}</span>}<span className="line-clamp-2">{title}</span></div>
          {subtitle && <div className="mt-0.5 truncate text-[11px] text-ink-muted">{subtitle}</div>}
        </div>
        {(action || id) && <div className="flex shrink-0 items-center gap-1" onClick={(e) => e.stopPropagation()}>{action}{id && (
          <button onClick={(e) => { e.stopPropagation(); open(id); }} title="Open the expanded view"
            className="shrink-0 rounded-lg p-1.5 text-ink-faint opacity-60 transition group-hover:bg-slate-50 group-hover:text-brand-700 group-hover:opacity-100">
            <Maximize2 size={14} />
          </button>
        )}</div>}
      </div>
      <div className="min-w-0 flex-1 px-4 pb-4 pt-3">{children}</div>
      {footer && <div className="border-t border-line px-4 py-2.5 text-[11px] text-ink-muted">{footer}</div>}
    </motion.div>
  );
}

/** A big number with a label, for tiles. */
export function Figure({ value, label, tone }: { value: ReactNode; label: ReactNode; tone?: string }) {
  return (
    <div className="min-w-0">
      <div className="font-display text-xl font-extrabold tabular-nums" style={tone ? { color: tone } : undefined}>{value}</div>
      <div className="truncate text-[11px] text-ink-muted">{label}</div>
    </div>
  );
}

/** Inline list that shows the first `n` items and a "+k more" chip that opens the expanded view. */
export function MoreList({ items, n = 5, sectionId, render }: { items: string[]; n?: number; sectionId?: string; render?: (s: string) => ReactNode }) {
  const { open } = useExpanded();
  const rest = items.length - n;
  return (
    <div className="flex flex-wrap gap-1">
      {items.slice(0, n).map((s) => <span key={s} className="rounded-md bg-slate-100 px-1.5 py-0.5 text-[11px] text-ink-soft">{render ? render(s) : s}</span>)}
      {rest > 0 && (
        <button onClick={(e) => { e.stopPropagation(); sectionId && open(sectionId); }}
          className="rounded-md px-1.5 py-0.5 text-[11px] font-medium text-brand-700 ring-1 ring-inset ring-brand-200 hover:bg-brand-50">+{rest} more</button>
      )}
    </div>
  );
}

/** A card on the page, or just its body inside the expanded view (which already shows the title). */
export function Frame({ bare, title, subtitle, children }: { bare?: boolean; title: ReactNode; subtitle?: ReactNode; children: ReactNode }) {
  if (bare) return <div className="-m-5 md:-m-6">{subtitle && <p className="px-5 pt-4 text-xs text-ink-muted md:px-6">{subtitle}</p>}{children}</div>;
  return <Card><CardHeader title={title} subtitle={subtitle} />{children}</Card>;
}
