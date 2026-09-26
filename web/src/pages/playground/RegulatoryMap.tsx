import { useQuery } from "@tanstack/react-query";
import { ExternalLink, Info } from "lucide-react";
import { useMemo, useState } from "react";
import { Badge, Card, CardHeader, ErrorNote, PageSkeleton, Segmented } from "../../components/ui";
import { WorldMap } from "../../components/viz";
import { api } from "../../lib/api";
import { cn } from "../../lib/cn";
import { fmtDate } from "../../lib/format";

type Metric = "strictness" | "pics" | "exclusivity" | "linkage" | "molecule";
const STATUS_COLOR: Record<string, string> = { off_patent: "#10b996", loe_pending: "#f59e0b", patented: "#e11d48" };
const STRICT = ["#f1f5f9", "#dbeafe", "#93c5fd", "#60a5fa", "#2563eb", "#1e3a8a"];
const REGION_ORDER = ["North America", "Europe", "East Asia", "Oceania", "Latin America", "Middle East", "South Asia", "Africa"];

export function RegulatoryMap() {
  const [metric, setMetric] = useState<Metric>("strictness");
  const [molecule, setMolecule] = useState("");
  const [picked, setPicked] = useState<string | null>("IN");
  const { data: d, isLoading, error } = useQuery({ queryKey: ["pg-world", molecule], queryFn: () => api<any>(`/api/playground/world?molecule=${encodeURIComponent(molecule)}`) });
  const eu = useMemo(() => new Set<string>(d?.eu_members ?? []), [d]);
  if (isLoading) return <PageSkeleton />;
  if (error) return <ErrorNote error={error} />;
  const marketOf = (code: string | null) => (code ? (eu.has(code) ? "EU" : code) : null);
  const mk = (code: string | null) => { const m = marketOf(code); return m ? d.markets[m] : null; };

  const colorFor = (code: string | null) => {
    const m = mk(code);
    if (!m) return "#e2e8f0";
    switch (metric) {
      case "strictness": return STRICT[m.strictness ?? 0];
      case "pics": return m.pics_member ? "#10b996" : "#fbbf24";
      case "exclusivity": { const y = m.data_exclusivity_years; return y == null ? "#cbd5e1" : y === 0 ? "#10b996" : y <= 5 ? "#fbbf24" : "#e11d48"; }
      case "linkage": return m.patent_linkage == null ? "#cbd5e1" : m.patent_linkage ? "#e11d48" : "#10b996";
      case "molecule": { const st = d.molecule?.countries?.[marketOf(code)!]?.status; return st ? STATUS_COLOR[st] ?? "#cbd5e1" : "#e2e8f0"; }
    }
  };
  const legend: Record<Metric, [string, string][]> = {
    strictness: [["#dbeafe", "lighter"], ["#60a5fa", "moderate"], ["#1e3a8a", "most stringent"]],
    pics: [["#10b996", "PIC/S member"], ["#fbbf24", "not a member"]],
    exclusivity: [["#10b996", "none"], ["#fbbf24", "≤ 5 years"], ["#e11d48", "8+ years"], ["#cbd5e1", "check"]],
    linkage: [["#e11d48", "patent linkage"], ["#10b996", "no linkage"], ["#cbd5e1", "check"]],
    molecule: [["#10b996", "off-patent"], ["#f59e0b", "LOE within 5 y"], ["#e11d48", "patented"], ["#e2e8f0", "no data"]],
  };
  const sel = picked ? d.markets[picked] : null;
  const counts = picked ? d.molecule_counts[picked] : null;
  const facts = picked ? d.facts[picked] : null;
  const molRow = picked && d.molecule ? d.molecule.countries[picked] : null;
  const byRegion = REGION_ORDER.map((r) => ({ region: r, codes: Object.keys(d.markets).filter((c) => d.markets[c].region === r) })).filter((r) => r.codes.length);
  const yes = (v: any) => (v == null ? <span className="text-ink-faint">check</span> : v === true ? "Yes" : v === false ? "No" : v);

  return (
    <div className="space-y-5">
      <Card>
        <CardHeader title="Generic-medicine regulation by market" subtitle="How hard each market is to enter, and what blocks a generic — click a country"
          action={<Segmented value={metric} onChange={setMetric} options={[{ value: "strictness", label: "Stringency" }, { value: "pics", label: "PIC/S GMP" }, { value: "exclusivity", label: "Data exclusivity" }, { value: "linkage", label: "Patent linkage" }, { value: "molecule", label: "A molecule" }]} />} />
        <div className="grid gap-4 p-4 xl:grid-cols-[1.9fr_1fr]">
          <div>
            {metric === "molecule" && (
              <select className="input mb-3 h-9 w-72 text-sm" value={molecule} onChange={(e) => setMolecule(e.target.value)}>
                <option value="">Pick a tracked molecule…</option>{d.molecules.map((m: any) => <option key={m.key} value={m.key}>{m.name}</option>)}
              </select>
            )}
            <WorldMap height={470} colorFor={colorFor} isSelected={(c) => marketOf(c) === picked} onPick={(c) => setPicked(marketOf(c))}
              tooltip={(code) => { const m = mk(code); const k = marketOf(code)!; return m ? <div>{m.regulator}{metric === "molecule" && d.molecule?.countries?.[k] ? ` · ${d.molecule.countries[k].status.replace("_", " ")}` : ""}{metric === "exclusivity" ? ` · ${m.data_exclusivity ?? "check"}` : ""}</div> : null; }} />
            <div className="mt-2 flex flex-wrap items-center gap-3 text-[11px] text-ink-muted">{legend[metric].map(([c, l]) => <span key={l} className="flex items-center gap-1"><span className="h-2.5 w-2.5 rounded-sm" style={{ background: c }} />{l}</span>)}
              {metric === "strictness" && <span className="text-ink-faint">· a 1–5 editorial score from PIC/S & ICH status, data exclusivity and patent linkage</span>}</div>
          </div>
          <div>
            {sel ? (
              <div className="max-h-[560px] overflow-auto rounded-2xl border border-line p-4 scrollbar-thin">
                <div className="flex items-start justify-between gap-2"><div><div className="font-display text-lg font-bold">{sel.name}</div><div className="text-xs text-ink-muted">{sel.regulator} · {sel.region}</div></div><Badge tone="indigo">stringency {sel.strictness}/5</Badge></div>
                <dl className="mt-3 space-y-2 text-xs">
                  {d.fields.filter((f: any) => f.key !== "regulator").map((f: any) => (
                    <div key={f.key}><dt className="text-[10.5px] font-semibold uppercase tracking-wider text-ink-faint">{f.label}</dt><dd className="font-medium text-ink-soft">{f.key === "pics_member" ? yes(sel.pics_member) : f.key === "patent_linkage" ? yes(sel.patent_linkage) : yes(sel[f.key])}</dd></div>
                  ))}
                </dl>
                {sel.notes && <div className="mt-3 rounded-lg bg-slate-50 p-2.5 text-[11.5px] text-ink-soft">{sel.notes}</div>}
                {counts && <div className="mt-3"><div className="label mb-1.5">Tracked molecules here ({d.molecule_total})</div>
                  <div className="flex flex-wrap gap-1.5">{Object.entries(counts).filter(([k]) => k !== "export_eligible").map(([k, v]: any) => <span key={k} className="rounded-full px-2 py-0.5 text-[11px] font-semibold text-white" style={{ background: STATUS_COLOR[k] ?? "#64748b" }}>{k.replace("_", " ")} {v}</span>)}
                    {counts.export_eligible != null && <Badge tone="brand">export-eligible {counts.export_eligible}</Badge>}</div></div>}
                {facts && <div className="mt-3 space-y-1">{Object.entries(facts).map(([k, v]: any) => <div key={k} className="flex justify-between text-xs"><span className="text-ink-muted">{k}</span><b className="tabular-nums">{Number(v).toLocaleString("en-IN")}</b></div>)}</div>}
                {molRow && <div className="mt-3 rounded-lg bg-slate-50 p-2.5 text-xs"><b>{d.molecule.name}:</b> {molRow.status.replace("_", " ")}{molRow.loe ? `, LOE ${fmtDate(molRow.loe)}` : ""}{molRow.barrier && molRow.barrier !== "none" ? `, barrier: ${molRow.barrier}` : ""}{molRow.notes ? ` — ${molRow.notes}` : ""}</div>}
              </div>
            ) : <div className="rounded-2xl border border-dashed border-line p-6 text-center text-sm text-ink-muted">This country is not in the reference yet.</div>}
          </div>
        </div>
      </Card>

      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        {byRegion.filter((r) => ["North America", "Europe", "South Asia", "Africa", "Latin America", "East Asia"].includes(r.region)).map((r, i) => {
          const ms = r.codes.map((c) => d.markets[c]);
          const pics = ms.filter((m: any) => m.pics_member).length;
          const excl = ms.map((m: any) => m.data_exclusivity_years).filter((x: any) => x != null);
          const link = ms.filter((m: any) => m.patent_linkage).length;
          const avgS = ms.reduce((a: number, m: any) => a + (m.strictness || 0), 0) / ms.length;
          const entry = r.region === "Africa" ? "WHO-GMP + WHO PQ / reliance pathways — fastest entry for Indian generics; little patent friction."
            : r.region === "South Asia" ? "Home market: state licence + Revised Schedule M; NSQ surveillance is the quality gate."
            : r.region === "Europe" ? "EU GMP inspection, QP release, FMD serialisation; SPCs and 8+2 years protection delay entry."
            : r.region === "North America" ? "FDA pre-approval inspection, ANDA with Orange Book patent certification, DSCSA."
            : r.region === "Latin America" ? "PIC/S-level GMP; reliance on FDA/EMA approvals shortens review."
            : "Mixed: stringent regulators with local BE / consistency requirements.";
          return (
            <Card key={r.region} delay={i * 0.04} className="p-4">
              <div className="flex items-center justify-between"><div className="font-display text-[15px] font-bold">{r.region}</div><Badge tone="indigo">{avgS.toFixed(1)}/5</Badge></div>
              <div className="mt-1 text-[11px] text-ink-muted">{ms.map((m: any) => m.name).join(" · ")}</div>
              <div className="mt-3 grid grid-cols-3 gap-2 text-center">
                <div className="rounded-lg bg-slate-50 p-2"><div className="font-display text-lg font-bold">{pics}/{ms.length}</div><div className="text-[10px] text-ink-muted">PIC/S</div></div>
                <div className="rounded-lg bg-slate-50 p-2"><div className="font-display text-lg font-bold">{excl.length ? `${Math.min(...excl)}–${Math.max(...excl)}` : "?"}</div><div className="text-[10px] text-ink-muted">yrs exclusivity</div></div>
                <div className="rounded-lg bg-slate-50 p-2"><div className="font-display text-lg font-bold">{link}/{ms.length}</div><div className="text-[10px] text-ink-muted">patent linkage</div></div>
              </div>
              <p className="mt-3 text-[11.5px] leading-relaxed text-ink-soft">{entry}</p>
            </Card>
          );
        })}
      </div>

      <Card>
        <CardHeader title="Side by side" subtitle="India vs the markets Indian generics export to — grouped by region" />
        <div className="overflow-x-auto">
          <table className="w-full text-xs">
            <thead><tr className="border-y border-line bg-slate-50/70 text-left text-[10.5px] uppercase tracking-wider text-ink-muted">
              <th className="px-4 py-2.5">Market</th>{d.fields.filter((f: any) => f.key !== "regulator").map((f: any) => <th key={f.key} className="px-3 py-2.5">{f.label}</th>)}</tr></thead>
            <tbody>
              {byRegion.map((r) => [
                <tr key={r.region}><td colSpan={d.fields.length + 1} className="bg-slate-50/50 px-4 py-1.5 text-[10.5px] font-bold uppercase tracking-wider text-ink-faint">{r.region}</td></tr>,
                ...r.codes.map((c) => { const m = d.markets[c]; return (
                  <tr key={c} onClick={() => setPicked(c)} className={cn("cursor-pointer border-b border-line/60 align-top hover:bg-slate-50", picked === c && "bg-brand-50/40", c === "IN" && "font-semibold")}>
                    <td className="whitespace-nowrap px-4 py-2">{m.name}<div className="font-normal text-ink-faint">{m.regulator}</div></td>
                    {d.fields.filter((f: any) => f.key !== "regulator").map((f: any) => <td key={f.key} className="min-w-[120px] px-3 py-2 text-ink-soft">{f.key === "pics_member" || f.key === "patent_linkage" ? yes(m[f.key]) : yes(m[f.key])}</td>)}
                  </tr>); }),
              ])}
            </tbody>
          </table>
        </div>
        <div className="flex flex-wrap items-center gap-x-4 gap-y-1 border-t border-line px-5 py-3 text-[11px] text-ink-muted">
          <span className="flex items-center gap-1"><Info size={12} /> {d.disclaimer} Compiled {d.as_of}.</span>
          {Object.values(d.sources).map((s: any) => <a key={s.url} href={s.url} target="_blank" rel="noreferrer" className="flex items-center gap-0.5 text-brand-700 hover:underline">{s.label}<ExternalLink size={10} /></a>)}
        </div>
      </Card>
    </div>
  );
}
