// KPI tiles — the Figma metric-card shape. Mirrors the Streamlit mq-kpi in
// palette.py: uppercase label, large value, muted help line.

import type { Kpi } from "../../lib/types";
import { Card } from "../ui/card";

export function KpiRow({ kpis }: { kpis: Kpi[] }) {
  return (
    <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
      {kpis.map((k) => (
        <Card key={k.label} className="px-4 py-4">
          <div className="text-xs uppercase tracking-wide text-muted-foreground">{k.label}</div>
          <div className="mt-1.5 text-3xl font-bold leading-tight text-foreground">{k.value}</div>
          <div className="mt-1.5 text-xs text-muted-foreground">{k.help}</div>
        </Card>
      ))}
    </div>
  );
}