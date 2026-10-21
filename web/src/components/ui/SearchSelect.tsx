// One search component for the whole app.
//   SearchSelect — pick one value from a list (replaces native <select>): type to filter, arrows + Enter, grouped,
//                  matches highlighted, a clear option.
//   SearchBox    — free text with live suggestions (from a server search); the text stays editable and in sync with
//                  the value the page filters on.
// The dropdown is portalled to <body> with fixed positioning, so cards with overflow-hidden never clip it.
import { useQuery } from "@tanstack/react-query";
import { Check, ChevronDown, Loader2, Search, X } from "lucide-react";
import { type ReactNode, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { cn } from "../../lib/cn";

export type Opt = { value: string; label: string; sub?: string; group?: string; badge?: ReactNode; disabled?: boolean };

const norm = (s: string) => s.toLowerCase().normalize("NFKD").replace(/[̀-ͯ]/g, "");

function score(o: Opt, q: string): number {
  if (!q) return 1;
  const hay = norm(`${o.label} ${o.sub ?? ""}`);
  const toks = norm(q).split(/\s+/).filter(Boolean);
  if (!toks.every((t) => hay.includes(t))) return 0;
  const l = norm(o.label);
  return l.startsWith(toks[0]) ? 3 : l.split(/\s+/).some((w) => w.startsWith(toks[0])) ? 2 : 1;
}

function Highlight({ text, q }: { text: string; q: string }) {
  const t = norm(q).split(/\s+/).filter(Boolean)[0];
  if (!t) return <>{text}</>;
  const i = norm(text).indexOf(t);
  if (i < 0) return <>{text}</>;
  return <>{text.slice(0, i)}<mark className="rounded bg-gold-100 px-0.5 text-ink">{text.slice(i, i + t.length)}</mark>{text.slice(i + t.length)}</>;
}

function usePopover(open: boolean, anchor: React.RefObject<HTMLElement>, minWidth = 280) {
  const [pos, setPos] = useState<{ left: number; top: number; width: number; up: boolean } | null>(null);
  useLayoutEffect(() => {
    if (!open) return;
    const place = () => {
      const r = anchor.current?.getBoundingClientRect();
      if (!r) return;
      const width = Math.max(r.width, minWidth);
      const left = Math.min(r.left, window.innerWidth - width - 8);
      const up = r.bottom + 360 > window.innerHeight && r.top > 360;
      setPos({ left: Math.max(8, left), top: up ? r.top - 6 : r.bottom + 6, width, up });
    };
    place();
    window.addEventListener("scroll", place, true);
    window.addEventListener("resize", place);
    return () => { window.removeEventListener("scroll", place, true); window.removeEventListener("resize", place); };
  }, [open, anchor, minWidth]);
  return pos;
}

function List({ items, q, active, setActive, onPick, value, loading, emptyText }: {
  items: Opt[]; q: string; active: number; setActive: (i: number) => void; onPick: (o: Opt) => void; value?: string; loading?: boolean; emptyText?: string;
}) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => { ref.current?.querySelector(`[data-i="${active}"]`)?.scrollIntoView({ block: "nearest" }); }, [active]);
  let lastGroup: string | undefined;
  return (
    <div ref={ref} className="max-h-[320px] overflow-y-auto py-1 scrollbar-thin" role="listbox">
      {loading && items.length === 0 && <div className="flex items-center gap-2 px-3 py-3 text-xs text-ink-muted"><Loader2 size={13} className="animate-spin" /> Searching…</div>}
      {!loading && items.length === 0 && <div className="px-3 py-3 text-xs text-ink-muted">{emptyText ?? "No matches"}</div>}
      {items.map((o, i) => {
        const head = o.group && o.group !== lastGroup ? o.group : null;
        lastGroup = o.group;
        return (
          <div key={`${o.group ?? ""}:${o.value}`}>
            {head && <div className="px-3 pb-1 pt-2.5 text-[10px] font-bold uppercase tracking-[0.12em] text-gold-600">{head}</div>}
            <button type="button" data-i={i} role="option" aria-selected={o.value === value} disabled={o.disabled}
              onMouseEnter={() => setActive(i)} onMouseDown={(e) => e.preventDefault()} onClick={() => onPick(o)}
              className={cn("flex w-full items-center gap-2 px-3 py-2 text-left text-[13px] transition disabled:opacity-40",
                i === active ? "bg-gold-50" : "hover:bg-slate-50")}>
              <div className="min-w-0 flex-1">
                <div className="truncate font-medium text-ink"><Highlight text={o.label} q={q} /></div>
                {o.sub && <div className="truncate text-[11px] text-ink-muted">{o.sub}</div>}
              </div>
              {o.badge}
              {o.value === value && <Check size={14} className="shrink-0 text-gold-600" />}
            </button>
          </div>
        );
      })}
    </div>
  );
}

export function SearchSelect({ value, options, onChange, placeholder = "Select…", className, searchPlaceholder = "Type to search…", clearLabel, size = "md", emptyText, renderValue }: {
  value: string | null | undefined; options: Opt[]; onChange: (v: string) => void; placeholder?: string; className?: string;
  searchPlaceholder?: string; clearLabel?: string; size?: "sm" | "md" | "lg"; emptyText?: string; renderValue?: (o: Opt) => ReactNode;
}) {
  const [open, setOpen] = useState(false);
  const [q, setQ] = useState("");
  const [active, setActive] = useState(0);
  const btn = useRef<HTMLButtonElement>(null);
  const pop = useRef<HTMLDivElement>(null);
  const pos = usePopover(open, btn);
  const all = useMemo(() => (clearLabel ? [{ value: "", label: clearLabel }, ...options] : options), [options, clearLabel]);
  const items = useMemo(() => {
    const s = all.map((o) => [o, score(o, q)] as const).filter(([, n]) => n > 0);
    if (q) s.sort((a, b) => b[1] - a[1]);
    return s.slice(0, 300).map(([o]) => o);
  }, [all, q]);
  const sel = all.find((o) => o.value === (value ?? ""));
  useEffect(() => { if (open) { setQ(""); setActive(Math.max(0, items.findIndex((o) => o.value === value))); } }, [open]); // eslint-disable-line
  useEffect(() => {
    if (!open) return;
    const off = (e: MouseEvent) => { if (!pop.current?.contains(e.target as Node) && !btn.current?.contains(e.target as Node)) setOpen(false); };
    document.addEventListener("mousedown", off);
    return () => document.removeEventListener("mousedown", off);
  }, [open]);
  const pick = (o: Opt) => { onChange(o.value); setOpen(false); btn.current?.focus(); };
  const key = (e: React.KeyboardEvent) => {
    if (e.key === "ArrowDown") { e.preventDefault(); setActive((a) => Math.min(a + 1, items.length - 1)); }
    else if (e.key === "ArrowUp") { e.preventDefault(); setActive((a) => Math.max(a - 1, 0)); }
    else if (e.key === "Enter") { e.preventDefault(); if (items[active]) pick(items[active]); }
    else if (e.key === "Escape") { setOpen(false); btn.current?.focus(); }
  };
  const h = size === "sm" ? "h-9 text-xs" : size === "lg" ? "h-12 text-[15px]" : "h-10 text-sm";
  return (
    <>
      <button ref={btn} type="button" onClick={() => setOpen((o) => !o)} onKeyDown={(e) => { if (!open && (e.key === "ArrowDown" || e.key === "Enter")) { e.preventDefault(); setOpen(true); } }}
        className={cn("input flex items-center gap-2 text-left", h, open && "border-gold-400 ring-4 ring-gold-300/25", className)} aria-haspopup="listbox" aria-expanded={open}>
        <span className={cn("min-w-0 flex-1 truncate", !sel?.value && !sel?.label && "text-ink-faint")}>{sel ? (renderValue ? renderValue(sel) : sel.label) : placeholder}</span>
        <ChevronDown size={15} className={cn("shrink-0 text-ink-faint transition", open && "rotate-180")} />
      </button>
      {open && pos && createPortal(
        <div ref={pop} style={{ left: pos.left, top: pos.top, width: pos.width, transform: pos.up ? "translateY(-100%)" : undefined }}
          className="fixed z-[100] overflow-hidden rounded-xl border border-line bg-white shadow-lift">
          <div className="relative border-b border-line">
            <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-ink-faint" />
            <input autoFocus value={q} onChange={(e) => { setQ(e.target.value); setActive(0); }} onKeyDown={key} placeholder={searchPlaceholder}
              className="h-10 w-full bg-transparent pl-9 pr-3 text-sm outline-none placeholder:text-ink-faint" />
          </div>
          <List items={items} q={q} active={active} setActive={setActive} onPick={pick} value={value ?? ""} emptyText={emptyText} />
          {options.length > 300 && !q && <div className="border-t border-line px-3 py-1.5 text-[10px] text-ink-faint">Showing 300 of {options.length} — type to narrow</div>}
        </div>, document.body)}
    </>
  );
}

export function SearchBox({ value, onChange, onPick, suggest, staticOptions, placeholder = "Search…", className, size = "md", minChars = 2, queryKey = "searchbox" }: {
  value: string; onChange: (v: string) => void; onPick?: (o: Opt) => void; suggest?: (q: string) => Promise<Opt[]>; staticOptions?: Opt[];
  placeholder?: string; className?: string; size?: "sm" | "md" | "lg"; minChars?: number; queryKey?: string;
}) {
  const [text, setText] = useState(value);
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(0);
  const [dq, setDq] = useState(value);
  const box = useRef<HTMLDivElement>(null);
  const inp = useRef<HTMLInputElement>(null);
  const pop = useRef<HTMLDivElement>(null);
  const pos = usePopover(open, box, 320);
  useEffect(() => { setText(value); }, [value]); // a value set elsewhere (e.g. a chart click) shows in the box
  useEffect(() => { const t = setTimeout(() => setDq(text.trim()), 220); return () => clearTimeout(t); }, [text]);
  useEffect(() => { const t = setTimeout(() => { if (text !== value) onChange(text); }, 400); return () => clearTimeout(t); }, [text]); // eslint-disable-line
  const remote = useQuery({ queryKey: [queryKey, dq], queryFn: () => suggest!(dq), enabled: !!suggest && open && dq.length >= minChars, staleTime: 60_000 });
  const items = useMemo(() => {
    if (staticOptions) return staticOptions.map((o) => [o, score(o, dq)] as const).filter(([, n]) => n > 0).sort((a, b) => b[1] - a[1]).slice(0, 50).map(([o]) => o);
    return dq.length >= minChars ? remote.data ?? [] : [];
  }, [staticOptions, remote.data, dq, minChars]);
  useEffect(() => {
    if (!open) return;
    const off = (e: MouseEvent) => { if (!pop.current?.contains(e.target as Node) && !box.current?.contains(e.target as Node)) setOpen(false); };
    document.addEventListener("mousedown", off);
    return () => document.removeEventListener("mousedown", off);
  }, [open]);
  const pick = (o: Opt) => { setText(o.label); onChange(o.label); onPick?.(o); setOpen(false); };
  const key = (e: React.KeyboardEvent) => {
    if (e.key === "ArrowDown") { e.preventDefault(); setOpen(true); setActive((a) => Math.min(a + 1, items.length - 1)); }
    else if (e.key === "ArrowUp") { e.preventDefault(); setActive((a) => Math.max(a - 1, 0)); }
    else if (e.key === "Enter") { e.preventDefault(); if (open && items[active]) pick(items[active]); else { onChange(text); setOpen(false); } }
    else if (e.key === "Escape") setOpen(false);
  };
  const h = size === "sm" ? "h-9 text-xs" : size === "lg" ? "h-12 text-[15px]" : "h-10 text-sm";
  const showList = open && (dq.length >= minChars || !!staticOptions);
  return (
    <div ref={box} className={cn("relative", className)}>
      <Search size={size === "lg" ? 17 : 14} className={cn("pointer-events-none absolute top-1/2 -translate-y-1/2 text-ink-faint", size === "lg" ? "left-3.5" : "left-3")} />
      <input ref={inp} value={text} onChange={(e) => { setText(e.target.value); setOpen(true); setActive(0); }} onFocus={() => setOpen(true)} onKeyDown={key}
        placeholder={placeholder} className={cn("input pr-8", size === "lg" ? "pl-11" : "pl-9", h)} role="combobox" aria-expanded={showList} />
      {text && <button type="button" onClick={() => { setText(""); onChange(""); inp.current?.focus(); }} className="absolute right-2.5 top-1/2 -translate-y-1/2 rounded p-0.5 text-ink-faint hover:text-ink" aria-label="Clear"><X size={14} /></button>}
      {showList && pos && createPortal(
        <div ref={pop} style={{ left: pos.left, top: pos.top, width: pos.width, transform: pos.up ? "translateY(-100%)" : undefined }}
          className="fixed z-[100] overflow-hidden rounded-xl border border-line bg-white shadow-lift">
          <List items={items} q={dq} active={active} setActive={setActive} onPick={pick} loading={remote.isFetching} />
          <div className="border-t border-line px-3 py-1.5 text-[10px] text-ink-faint">↑ ↓ to move · Enter to choose · Esc to close</div>
        </div>, document.body)}
    </div>
  );
}
