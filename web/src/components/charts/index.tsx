import { motion } from "motion/react";
import {
  Area, AreaChart, Bar as RBar, BarChart, CartesianGrid, Cell, Legend, Pie, PieChart, PolarAngleAxis, PolarGrid,
  Radar, RadarChart, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from "recharts";
import { fmtMonth, PALETTE } from "../../lib/format";
import { itemVariants, listVariants } from "../ui";

type Series = { months: string[]; series: { name: string; values: number[] }[] };

function TooltipBox({ active, payload, label, labelFmt }: any) {
  if (!active || !payload?.length) return null;
  const rows = payload.filter((p: any) => p.value);
  const total = rows.reduce((s: number, p: any) => s + (p.value || 0), 0);
  return (
    <div className="min-w-[160px] rounded-xl bg-night-900/95 px-3 py-2.5 text-xs text-white shadow-lift backdrop-blur">
      <div className="mb-1.5 font-semibold">{labelFmt ? labelFmt(label) : label}</div>
      {rows.map((p: any) => (
        <div key={p.dataKey} className="flex items-center justify-between gap-4 py-0.5">
          <span className="flex items-center gap-1.5 text-slate-300"><span className="h-2 w-2 rounded-full" style={{ background: p.color || p.fill }} />{p.name}</span>
          <span className="font-semibold tabular-nums">{p.value}</span>
        </div>
      ))}
      {rows.length > 1 && <div className="mt-1 flex justify-between border-t border-white/10 pt-1 text-slate-300"><span>Total</span><span className="font-semibold text-white">{total}</span></div>}
    </div>
  );
}

export function TrendArea({ data, height = 260, stacked = true }: { data: Series; height?: number; stacked?: boolean }) {
  const rows = data.months.map((m, i) => {
    const r: Record<string, any> = { month: m };
    data.series.forEach((s) => (r[s.name] = s.values[i]));
    return r;
  });
  return (
    <ResponsiveContainer width="100%" height={height}>
      <AreaChart data={rows} margin={{ top: 10, right: 8, left: -6, bottom: 0 }}>
        <defs>
          {data.series.map((s, i) => (
            <linearGradient key={s.name} id={`g${i}`} x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor={PALETTE[i % PALETTE.length]} stopOpacity={0.55} />
              <stop offset="100%" stopColor={PALETTE[i % PALETTE.length]} stopOpacity={0.05} />
            </linearGradient>
          ))}
        </defs>
        <CartesianGrid vertical={false} stroke="#eef1f6" />
        <XAxis dataKey="month" tickFormatter={(m) => fmtMonth(m).replace(/ 20/, " '")} tickLine={false} axisLine={false} minTickGap={28} />
        <YAxis allowDecimals={false} tickLine={false} axisLine={false} width={40} />
        <Tooltip content={<TooltipBox labelFmt={fmtMonth} />} cursor={{ stroke: "#cbd5e1", strokeDasharray: "3 3" }} />
        {data.series.map((s, i) => (
          <Area key={s.name} type="monotone" dataKey={s.name} stackId={stacked ? "1" : undefined} stroke={PALETTE[i % PALETTE.length]} strokeWidth={1.6}
            fill={`url(#g${i})`} animationDuration={1100} />
        ))}
      </AreaChart>
    </ResponsiveContainer>
  );
}

export function TrendBars({ data, height = 260 }: { data: Series; height?: number }) {
  const rows = data.months.map((m, i) => {
    const r: Record<string, any> = { month: m };
    data.series.forEach((s) => (r[s.name] = s.values[i]));
    return r;
  });
  return (
    <ResponsiveContainer width="100%" height={height}>
      <BarChart data={rows} margin={{ top: 10, right: 8, left: -6, bottom: 0 }} barCategoryGap={1}>
        <CartesianGrid vertical={false} stroke="#eef1f6" />
        <XAxis dataKey="month" tickFormatter={(m) => fmtMonth(m).replace(/ 20/, " '")} tickLine={false} axisLine={false} minTickGap={28} />
        <YAxis allowDecimals={false} tickLine={false} axisLine={false} width={40} />
        <Tooltip content={<TooltipBox labelFmt={fmtMonth} />} cursor={{ fill: "#f1f5f9" }} />
        {data.series.map((s, i) => (
          <RBar key={s.name} dataKey={s.name} stackId="1" fill={PALETTE[i % PALETTE.length]} animationDuration={900}
            radius={i === data.series.length - 1 ? [3, 3, 0, 0] : 0} />
        ))}
      </BarChart>
    </ResponsiveContainer>
  );
}

export function Legendary({ items }: { items: { name: string }[] }) {
  return (
    <div className="flex flex-wrap gap-x-4 gap-y-1.5">
      {items.map((s, i) => (
        <span key={s.name} className="flex items-center gap-1.5 text-xs text-ink-soft"><span className="h-2 w-2 rounded-full" style={{ background: PALETTE[i % PALETTE.length] }} />{s.name}</span>
      ))}
    </div>
  );
}

export function RankBars({ rows, color = "#0a9a7d", max, onClick, format }: { rows: { name: string; count: number; sub?: string }[]; color?: string; max?: number; onClick?: (name: string) => void; format?: (n: number) => string }) {
  const m = max ?? Math.max(1, ...rows.map((r) => r.count));
  return (
    <motion.ul variants={listVariants} initial="hidden" animate="show" className="space-y-2.5">
      {rows.map((r, i) => (
        <motion.li key={r.name} variants={itemVariants} className={onClick ? "cursor-pointer" : ""} onClick={() => onClick?.(r.name)}>
          <div className="mb-1 flex items-baseline justify-between gap-3 text-[13px]">
            <span className="truncate font-medium text-ink-soft" title={r.name}>{r.name}{r.sub && <span className="ml-1.5 text-xs text-ink-faint">{r.sub}</span>}</span>
            <span className="tabular-nums font-semibold text-ink">{format ? format(r.count) : r.count.toLocaleString("en-IN")}</span>
          </div>
          <div className="h-2 overflow-hidden rounded-full bg-slate-100">
            <motion.div className="h-full rounded-full" style={{ background: color, opacity: 1 - i * 0.05 }} initial={{ width: 0 }} animate={{ width: `${(100 * r.count) / m}%` }} transition={{ duration: 0.9, delay: 0.1 + i * 0.03, ease: [0.22, 1, 0.36, 1] }} />
          </div>
        </motion.li>
      ))}
    </motion.ul>
  );
}

export function Donut({ rows, height = 220, center }: { rows: { name: string; count: number }[]; height?: number; center?: React.ReactNode }) {
  return (
    <div className="relative" style={{ height }}>
      <ResponsiveContainer width="100%" height="100%">
        <PieChart>
          <Pie data={rows} dataKey="count" nameKey="name" innerRadius="64%" outerRadius="92%" paddingAngle={2} stroke="none" animationDuration={1000}>
            {rows.map((_, i) => <Cell key={i} fill={PALETTE[i % PALETTE.length]} />)}
          </Pie>
          <Tooltip content={<TooltipBox />} />
        </PieChart>
      </ResponsiveContainer>
      {center && <div className="pointer-events-none absolute inset-0 grid place-items-center text-center">{center}</div>}
    </div>
  );
}

export function CompareBars({ rows, height = 240 }: { rows: { name: string; org_pct: number; national_pct: number }[]; height?: number }) {
  return (
    <ResponsiveContainer width="100%" height={height}>
      <BarChart data={rows} layout="vertical" margin={{ top: 0, right: 16, left: 8, bottom: 0 }} barGap={2}>
        <CartesianGrid horizontal={false} stroke="#eef1f6" />
        <XAxis type="number" unit="%" tickLine={false} axisLine={false} />
        <YAxis type="category" dataKey="name" width={150} tickLine={false} axisLine={false} tick={{ fontSize: 12, fill: "#334155" }} />
        <Tooltip content={<TooltipBox />} cursor={{ fill: "#f1f5f9" }} />
        <Legend iconType="circle" iconSize={8} wrapperStyle={{ fontSize: 12 }} />
        <RBar dataKey="org_pct" name="Your alerts %" fill="#0a9a7d" radius={[0, 6, 6, 0]} barSize={10} animationDuration={900} />
        <RBar dataKey="national_pct" name="All India %" fill="#cbd5e1" radius={[0, 6, 6, 0]} barSize={10} animationDuration={900} />
      </BarChart>
    </ResponsiveContainer>
  );
}

export function PillarRadar({ scores, height = 240 }: { scores: Record<string, number>; height?: number }) {
  const LABEL: Record<string, string> = { gmp: "GMP readiness", infrastructure: "Infrastructure", talent: "Talent", certification: "Certification" };
  const rows = Object.entries(scores).map(([k, v]) => ({ k: LABEL[k] ?? k.charAt(0).toUpperCase() + k.slice(1), v }));
  return (
    <ResponsiveContainer width="100%" height={height}>
      <RadarChart data={rows} outerRadius="72%">
        <PolarGrid stroke="#e2e8f0" />
        <PolarAngleAxis dataKey="k" tick={{ fontSize: 11, fill: "#475569" }} />
        <Radar dataKey="v" stroke="#0a9a7d" fill="#0a9a7d" fillOpacity={0.25} animationDuration={900} />
        <Tooltip content={<TooltipBox />} />
      </RadarChart>
    </ResponsiveContainer>
  );
}
