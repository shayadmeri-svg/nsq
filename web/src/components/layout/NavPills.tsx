// Navigation pills — the Figma "Navigation Pill List" shape. Mirrors the
// Streamlit mq-nav / mq-pill in palette.py. Diagnostics is reached from the
// dashboard's Deep-dive button (a specific issue); the Simulator pill is a
// placeholder (the CPP-slider screens are a later phase, as in the Streamlit
// app).

import { ChartIcon, MicroscopeIcon, RocketIcon } from "../icons/BioIcon";
import { cn } from "../../lib/utils";

export interface NavItem {
  key: string;
  label: string;
  active?: boolean;
  disabled?: boolean;
  onClick?: () => void;
}

export function NavPills({ items }: { items: NavItem[] }) {
  return (
    <nav className="flex flex-wrap gap-2">
      {items.map((it) => (
        <button
          key={it.key}
          disabled={it.disabled}
          onClick={it.onClick}
          className={cn(
            "inline-flex items-center gap-1.5 rounded-full border px-3.5 py-1.5 text-xs font-medium transition-colors",
            it.active
              ? "border-primary bg-primary/[0.06] text-primary"
              : "border-border bg-card text-muted-foreground hover:border-primary/40",
            it.disabled && "cursor-not-allowed opacity-60",
          )}
        >
          {it.key === "dashboard" && <ChartIcon size={14} />}
          {it.key === "diagnostics" && <MicroscopeIcon size={14} />}
          {it.key === "simulator" && <RocketIcon size={14} />}
          {it.label}
        </button>
      ))}
    </nav>
  );
}