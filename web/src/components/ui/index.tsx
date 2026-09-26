import { animate, AnimatePresence, motion, useInView, useMotionValue, useTransform } from "motion/react";
import { X } from "lucide-react";
import { forwardRef, useEffect, useRef, type ButtonHTMLAttributes, type ReactNode } from "react";
import { cn } from "../../lib/cn";

// --- Button ------------------------------------------------------------------
type Variant = "primary" | "secondary" | "ghost" | "danger";
const VARIANTS: Record<Variant, string> = {
  primary: "bg-ink text-white hover:bg-night-700 shadow-sm",
  secondary: "bg-white text-ink ring-1 ring-inset ring-line hover:bg-slate-50",
  ghost: "text-ink-soft hover:bg-slate-100",
  danger: "bg-gap text-white hover:bg-rose-700",
};

export const Button = forwardRef<HTMLButtonElement, ButtonHTMLAttributes<HTMLButtonElement> & { variant?: Variant; size?: "sm" | "md"; loading?: boolean }>(
  ({ className, variant = "primary", size = "md", loading, children, disabled, ...rest }, ref) => (
    <button
      ref={ref}
      disabled={disabled || loading}
      className={cn(
        "inline-flex items-center justify-center gap-2 rounded-xl font-medium transition active:scale-[0.98] disabled:pointer-events-none disabled:opacity-50",
        size === "sm" ? "h-8 px-3 text-xs" : "h-10 px-4 text-sm",
        VARIANTS[variant],
        className,
      )}
      {...rest}
    >
      {loading && <span className="h-3.5 w-3.5 animate-spin rounded-full border-2 border-current border-t-transparent" />}
      {children}
    </button>
  ),
);

// --- Card ----------------------------------------------------------------------
export function Card({ className, children, delay = 0, ...rest }: { className?: string; children: ReactNode; delay?: number } & React.HTMLAttributes<HTMLDivElement>) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.45, delay, ease: [0.22, 1, 0.36, 1] }}
      className={cn("card", className)}
      {...(rest as any)}
    >
      {children}
    </motion.div>
  );
}

export function CardHeader({ title, subtitle, action, icon }: { title: ReactNode; subtitle?: ReactNode; action?: ReactNode; icon?: ReactNode }) {
  return (
    <div className="flex items-start justify-between gap-4 px-5 pt-5">
      <div className="flex items-start gap-3">
        {icon && <div className="mt-0.5 grid h-8 w-8 place-items-center rounded-lg bg-brand-50 text-brand-700">{icon}</div>}
        <div>
          <h3 className="font-display text-[15px] font-bold text-ink">{title}</h3>
          {subtitle && <p className="mt-0.5 text-xs text-ink-muted">{subtitle}</p>}
        </div>
      </div>
      {action}
    </div>
  );
}

// --- Badge -----------------------------------------------------------------------
export function Badge({ className, children, tone = "slate" }: { className?: string; children: ReactNode; tone?: "slate" | "brand" | "amber" | "rose" | "indigo" | "sky" }) {
  const tones = {
    slate: "bg-slate-100 text-slate-700 ring-slate-200",
    brand: "bg-brand-50 text-brand-700 ring-brand-200",
    amber: "bg-amber-50 text-amber-700 ring-amber-200",
    rose: "bg-rose-50 text-rose-700 ring-rose-200",
    indigo: "bg-indigo-50 text-indigo-700 ring-indigo-200",
    sky: "bg-sky-50 text-sky-700 ring-sky-200",
  };
  return <span className={cn("inline-flex items-center gap-1 whitespace-nowrap rounded-full px-2 py-0.5 text-[11px] font-semibold ring-1 ring-inset", tones[tone], className)}>{children}</span>;
}

// --- Animated number ------------------------------------------------------------------
export function CountUp({ value, decimals = 0, suffix = "" }: { value: number; decimals?: number; suffix?: string }) {
  const ref = useRef<HTMLSpanElement>(null);
  const inView = useInView(ref, { once: true });
  const mv = useMotionValue(0);
  const text = useTransform(mv, (v) => v.toLocaleString("en-IN", { maximumFractionDigits: decimals, minimumFractionDigits: decimals }) + suffix);
  useEffect(() => {
    if (!inView) return;
    const c = animate(mv, value, { duration: 1.1, ease: [0.22, 1, 0.36, 1] });
    return () => c.stop();
  }, [inView, value, mv]);
  return <motion.span ref={ref}>{text}</motion.span>;
}

export function Stat({ label, value, hint, icon, tone = "brand", delay = 0, decimals = 0, suffix = "" }: {
  label: string; value: number | string | null | undefined; hint?: ReactNode; icon?: ReactNode; tone?: "brand" | "indigo" | "amber" | "rose"; delay?: number; decimals?: number; suffix?: string;
}) {
  const tones = { brand: "from-brand-500/15 text-brand-700", indigo: "from-indigo-500/15 text-indigo-700", amber: "from-amber-500/15 text-amber-700", rose: "from-rose-500/15 text-rose-700" };
  return (
    <Card delay={delay} className="relative overflow-hidden p-5">
      <div className={cn("pointer-events-none absolute -right-8 -top-8 h-28 w-28 rounded-full bg-gradient-to-br to-transparent", tones[tone])} />
      <div className="flex items-center justify-between">
        <span className="label">{label}</span>
        {icon && <span className={cn("opacity-80", tones[tone].split(" ")[1])}>{icon}</span>}
      </div>
      <div className="mt-3 font-display text-3xl font-extrabold tracking-tight text-ink">
        {typeof value === "number" ? <CountUp value={value} decimals={decimals} suffix={suffix} /> : value ?? "—"}
      </div>
      {hint && <div className="mt-1.5 text-xs text-ink-muted">{hint}</div>}
    </Card>
  );
}

// --- Skeleton / empty -------------------------------------------------------------------
export function Skeleton({ className }: { className?: string }) {
  return <div className={cn("animate-pulse rounded-xl bg-slate-200/70", className)} />;
}

export function PageSkeleton() {
  return (
    <div className="space-y-5">
      <Skeleton className="h-10 w-72" />
      <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">{[0, 1, 2, 3].map((i) => <Skeleton key={i} className="h-28" />)}</div>
      <Skeleton className="h-80" />
    </div>
  );
}

export function Empty({ icon, title, children }: { icon?: ReactNode; title: string; children?: ReactNode }) {
  return (
    <div className="grid place-items-center rounded-2xl border border-dashed border-line bg-white/60 px-6 py-14 text-center">
      {icon && <div className="mb-3 grid h-12 w-12 place-items-center rounded-2xl bg-slate-100 text-ink-muted">{icon}</div>}
      <div className="font-display text-base font-bold">{title}</div>
      {children && <div className="mt-1 max-w-md text-sm text-ink-muted">{children}</div>}
    </div>
  );
}

export function ErrorNote({ error }: { error: unknown }) {
  if (!error) return null;
  return <div className="rounded-xl bg-rose-50 px-4 py-3 text-sm text-rose-700 ring-1 ring-inset ring-rose-200">{(error as Error).message}</div>;
}

// --- Page header --------------------------------------------------------------------------
export function PageHeader({ eyebrow, title, subtitle, actions }: { eyebrow?: ReactNode; title: ReactNode; subtitle?: ReactNode; actions?: ReactNode }) {
  return (
    <motion.div initial={{ opacity: 0, y: -6 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.4 }} className="mb-6 flex flex-wrap items-end justify-between gap-4">
      <div>
        {eyebrow && <div className="label mb-1.5 text-brand-700">{eyebrow}</div>}
        <h1 className="font-display text-[26px] font-extrabold leading-tight tracking-tight text-ink">{title}</h1>
        {subtitle && <p className="mt-1.5 max-w-3xl text-sm text-ink-muted">{subtitle}</p>}
      </div>
      {actions && <div className="flex items-center gap-2">{actions}</div>}
    </motion.div>
  );
}

// --- Drawer + Modal -------------------------------------------------------------------------
// Overlays: ONE keyed motion child per AnimatePresence, with the inner panel
// driven by variants so its exit is awaited. The closed state also turns off
// pointer events immediately, so a half-finished exit can never leave an
// invisible layer on top of the page swallowing clicks.
const overlay = {
  open: { opacity: 1, pointerEvents: "auto" as const },
  closed: { opacity: 0, pointerEvents: "none" as const },
};

export function Drawer({ open, onClose, title, subtitle, children, width = 720 }: { open: boolean; onClose: () => void; title: ReactNode; subtitle?: ReactNode; children: ReactNode; width?: number }) {
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);
  return (
    <AnimatePresence>
      {open && (
        <motion.div key="drawer" className="fixed inset-0 z-40" variants={overlay} initial="closed" animate="open" exit="closed" transition={{ duration: 0.2 }}>
          <div className="absolute inset-0 bg-night-900/30 backdrop-blur-[2px]" onClick={onClose} />
          <motion.aside
            className="absolute inset-y-0 right-0 flex w-full flex-col bg-white shadow-lift"
            style={{ maxWidth: width }}
            variants={{ open: { x: 0 }, closed: { x: "100%" } }}
            transition={{ type: "spring", damping: 32, stiffness: 320 }}
          >
            <div className="flex items-start justify-between gap-4 border-b border-line px-6 py-5">
              <div>
                <div className="font-display text-lg font-bold">{title}</div>
                {subtitle && <div className="mt-0.5 text-xs text-ink-muted">{subtitle}</div>}
              </div>
              <button onClick={onClose} className="rounded-lg p-1.5 text-ink-muted hover:bg-slate-100"><X size={18} /></button>
            </div>
            <div className="scrollbar-thin flex-1 overflow-y-auto px-6 py-5">{children}</div>
          </motion.aside>
        </motion.div>
      )}
    </AnimatePresence>
  );
}

export function Modal({ open, onClose, title, children, footer }: { open: boolean; onClose: () => void; title: ReactNode; children: ReactNode; footer?: ReactNode }) {
  return (
    <AnimatePresence>
      {open && (
        <motion.div key="modal" className="fixed inset-0 z-50 grid place-items-center bg-night-900/40 p-4 backdrop-blur-sm" variants={overlay} initial="closed" animate="open" exit="closed" transition={{ duration: 0.18 }} onMouseDown={onClose}>
          <motion.div
            onMouseDown={(e) => e.stopPropagation()}
            variants={{ open: { opacity: 1, scale: 1, y: 0 }, closed: { opacity: 0, scale: 0.97, y: 8 } }}
            transition={{ type: "spring", damping: 26, stiffness: 340 }}
            className="w-full max-w-lg rounded-2xl bg-white shadow-lift"
          >
            <div className="flex items-center justify-between border-b border-line px-6 py-4">
              <div className="font-display text-base font-bold">{title}</div>
              <button onClick={onClose} className="rounded-lg p-1.5 text-ink-muted hover:bg-slate-100"><X size={18} /></button>
            </div>
            <div className="px-6 py-5">{children}</div>
            {footer && <div className="flex justify-end gap-2 border-t border-line bg-slate-50/60 px-6 py-3.5">{footer}</div>}
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>
  );
}

// --- Tabs ------------------------------------------------------------------------------------
export function Segmented<T extends string>({ value, onChange, options }: { value: T; onChange: (v: T) => void; options: { value: T; label: ReactNode }[] }) {
  return (
    <div className="inline-flex rounded-xl bg-slate-100 p-1">
      {options.map((o) => (
        <button key={o.value} onClick={() => onChange(o.value)} className={cn("relative rounded-lg px-3 py-1.5 text-xs font-semibold transition", value === o.value ? "text-ink" : "text-ink-muted hover:text-ink")}>
          {value === o.value && <motion.span layoutId={`seg-${options.map((x) => x.value).join()}`} className="absolute inset-0 rounded-lg bg-white shadow-sm" transition={{ type: "spring", damping: 30, stiffness: 400 }} />}
          <span className="relative">{o.label}</span>
        </button>
      ))}
    </div>
  );
}

// --- Field --------------------------------------------------------------------------------------
export function Field({ label, children, hint }: { label: string; children: ReactNode; hint?: ReactNode }) {
  return (
    <label className="block space-y-1.5">
      <span className="label">{label}</span>
      {children}
      {hint && <span className="block text-xs text-ink-muted">{hint}</span>}
    </label>
  );
}

// --- Progress ring --------------------------------------------------------------------------------
export function Ring({ value, size = 64, stroke = 7, color = "#0a9a7d", children }: { value: number; size?: number; stroke?: number; color?: string; children?: ReactNode }) {
  const r = (size - stroke) / 2;
  const c = 2 * Math.PI * r;
  return (
    <div className="relative grid place-items-center" style={{ width: size, height: size }}>
      <svg width={size} height={size} className="-rotate-90">
        <circle cx={size / 2} cy={size / 2} r={r} stroke="#eef1f6" strokeWidth={stroke} fill="none" />
        <motion.circle
          cx={size / 2} cy={size / 2} r={r} stroke={color} strokeWidth={stroke} fill="none" strokeLinecap="round"
          strokeDasharray={c} initial={{ strokeDashoffset: c }} animate={{ strokeDashoffset: c * (1 - Math.max(0, Math.min(100, value)) / 100) }}
          transition={{ duration: 1.1, ease: [0.22, 1, 0.36, 1] }}
        />
      </svg>
      <div className="absolute inset-0 grid place-items-center text-center">{children}</div>
    </div>
  );
}

export function Bar({ value, color = "#0a9a7d", className }: { value: number; color?: string; className?: string }) {
  return (
    <div className={cn("h-1.5 w-full overflow-hidden rounded-full bg-slate-100", className)}>
      <motion.div className="h-full rounded-full" style={{ background: color }} initial={{ width: 0 }} animate={{ width: `${Math.max(0, Math.min(100, value))}%` }} transition={{ duration: 0.9, ease: [0.22, 1, 0.36, 1] }} />
    </div>
  );
}

// --- Stagger list ---------------------------------------------------------------------------------
export const listVariants = { hidden: {}, show: { transition: { staggerChildren: 0.04 } } };
export const itemVariants = { hidden: { opacity: 0, y: 8 }, show: { opacity: 1, y: 0, transition: { duration: 0.35, ease: [0.22, 1, 0.36, 1] } } };
