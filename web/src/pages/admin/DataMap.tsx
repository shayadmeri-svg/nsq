import { useQuery } from "@tanstack/react-query";
import { ArrowRight, Database, FileText, Globe2, MousePointerClick, Server, Workflow, X } from "lucide-react";
import { useMemo, useState } from "react";
import { Badge, Card, CardHeader, ErrorNote, PageHeader, PageSkeleton, Segmented } from "../../components/ui";
import { api } from "../../lib/api";
import { cn } from "../../lib/cn";
import { timeAgo } from "../../lib/format";

type Node = { id: string; col: string; kind: string; label: string; sub: string; detail: string; group: string; keys: string[]; jobs: string[]; route: string; endpoints: string[] };
type Edge = { from: string; to: string; kind: "flow" | "write" | "trigger"; label: string; when: string };
type Stat = { ok: boolean; text: string; updated_at?: string | null; count?: number };
type Mutation = { store: string; store_label: string; store_kind: string; by: string; by_label: string; by_kind: string; what: string; when: string };
type Graph = { columns: { key: string; label: string; hint: string }[]; nodes: Node[]; edges: Edge[]; mutations: Mutation[]; stats: Record<string, Stat>; checked_at: string };

const KIND: Record<string, { label: string; fill: string; bar: string; text: string }> = {
  external: { label: "External source", fill: "#f8fafc", bar: "#64748b", text: "#0f172a" },
  actor: { label: "Scheduler / runner", fill: "#f5f3ff", bar: "#7c3aed", text: "#2e1065" },
  script: { label: "Script (job step)", fill: "#eef2ff", bar: "#6366f1", text: "#1e1b4b" },
  file: { label: "File on server", fill: "#fffbeb", bar: "#d97706", text: "#451a03" },
  redis: { label: "Redis", fill: "#fff1f2", bar: "#e11d48", text: "#4c0519" },
  postgres: { label: "Postgres", fill: "#eff6ff", bar: "#2563eb", text: "#172554" },
  service: { label: "API service", fill: "#ecfdf5", bar: "#059669", text: "#022c22" },
  page: { label: "Screen", fill: "#ffffff", bar: "#0f172a", text: "#0f172a" },
};
const EDGE: Record<Edge["kind"], { color: string; label: string; dash?: string }> = {
  flow: { color: "#94a3b8", label: "reads / derives" },
  write: { color: "#e11d48", label: "writes (mutation)" },
  trigger: { color: "#8b5cf6", label: "starts a job", dash: "4 3" },
};

const COL_W = 200, NODE_W = 174, NODE_H = 42, GAP = 7, GROUP_GAP = 24, TOP = 40, PAD = 10;

function layout(g: Graph) {
  const pos: Record<string, { x: number; y: number; ci: number }> = {};
  const headers: { x: number; y: number; text: string }[] = [];
  const heights = g.columns.map((c) => {
    let h = 0, last = "";
    for (const n of g.nodes.filter((n) => n.col === c.key)) {
      if (n.group && n.group !== last) { h += GROUP_GAP; last = n.group; }
      h += NODE_H + GAP;
    }
    return h;
  });
  const H = Math.max(...heights) + TOP + 16;
  g.columns.forEach((c, ci) => {
    const x = PAD + ci * COL_W;
    let y = TOP + (H - TOP - 16 - heights[ci]) / 2, last = "";
    for (const n of g.nodes.filter((n) => n.col === c.key)) {
      if (n.group && n.group !== last) { headers.push({ x, y: y + GROUP_GAP - 7, text: n.group }); y += GROUP_GAP; last = n.group; }
      pos[n.id] = { x, y, ci };
      y += NODE_H + GAP;
    }
  });
  return { pos, headers, W: PAD * 2 + g.columns.length * COL_W - (COL_W - NODE_W), H };
}

function edgePath(a: { x: number; y: number; ci: number }, b: { x: number; y: number; ci: number }) {
  const ay = a.y + NODE_H / 2, by = b.y + NODE_H / 2;
  if (b.ci > a.ci) {
    const x1 = a.x + NODE_W, x2 = b.x, dx = Math.max(40, (x2 - x1) / 2);
    return `M${x1},${ay} C${x1 + dx},${ay} ${x2 - dx},${by} ${x2},${by}`;
  }
  if (b.ci < a.ci) {
    const x1 = a.x, x2 = b.x + NODE_W, dx = 50;
    return `M${x1},${ay} C${x1 - dx},${ay + 30} ${x2 + dx},${by + 30} ${x2},${by}`;
  }
  const x = a.x + NODE_W, bulge = 26 + Math.min(40, Math.abs(by - ay) / 6);
  return `M${x},${ay} C${x + bulge},${ay} ${x + bulge},${by} ${x},${by}`;
}

function trace(g: Graph, start: string, dir: "up" | "down" | "both", kinds: Set<string>) {
  const nodes = new Set([start]);
  const edges = new Set<number>();
  const walk = (d: "up" | "down") => {
    const seen = new Set([start]);
    const q = [start];
    while (q.length) {
      const cur = q.shift()!;
      g.edges.forEach((e, i) => {
        if (!kinds.has(e.kind) || e.kind === "trigger") return;
        const next = d === "down" ? (e.from === cur ? e.to : null) : (e.to === cur ? e.from : null);
        if (next == null) return;
        edges.add(i);
        nodes.add(next);
        if (!seen.has(next)) { seen.add(next); q.push(next); }
      });
    }
  };
  if (dir !== "down") walk("up");
  if (dir !== "up") walk("down");
  // direct triggers of / by the selected node are shown too
  g.edges.forEach((e, i) => { if (e.kind === "trigger" && kinds.has("trigger") && (e.from === start || e.to === start)) { edges.add(i); nodes.add(e.from); nodes.add(e.to); } });
  return { nodes, edges };
}

function StatusDot({ s }: { s?: Stat }) {
  if (!s) return null;
  return <span className={cn("inline-block h-2 w-2 shrink-0 rounded-full", s.ok ? "bg-emerald-500" : "bg-amber-500")} />;
}

function FlowMap({ g, selected, setSelected }: { g: Graph; selected: string | null; setSelected: (id: string | null) => void }) {
  const [dir, setDir] = useState<"both" | "up" | "down">("both");
  const [kinds, setKinds] = useState(new Set<string>(["flow", "write"]));
  const [hover, setHover] = useState<number | null>(null);
  const L = useMemo(() => layout(g), [g]);
  const byId = useMemo(() => Object.fromEntries(g.nodes.map((n) => [n.id, n])), [g]);
  const hl = useMemo(() => (selected ? trace(g, selected, dir, kinds) : null), [g, selected, dir, kinds]);
  const sel = selected ? byId[selected] : null;
  const toggle = (k: string) => { const s = new Set(kinds); s.has(k) ? s.delete(k) : s.add(k); setKinds(s); };
  const inE = sel ? g.edges.filter((e) => e.to === sel.id) : [];
  const outE = sel ? g.edges.filter((e) => e.from === sel.id) : [];
  const st = sel ? g.stats[sel.id] : undefined;

  return (
    <Card>
      <div className="sticky top-0 z-20 space-y-3 rounded-t-2xl border-b border-line bg-white/95 p-4 backdrop-blur">
        <div className="flex flex-wrap items-center gap-2">
          <select className="input h-9 w-64 text-xs" value={sel?.kind === "page" ? sel.id : ""} onChange={(e) => { setSelected(e.target.value || null); if (e.target.value) setDir("up"); }}>
            <option value="">Trace a screen back to its sources…</option>
            {g.nodes.filter((n) => n.kind === "page").map((n) => <option key={n.id} value={n.id}>{n.label}</option>)}
          </select>
          <Segmented value={dir} onChange={setDir} options={[{ value: "both", label: "Both ways" }, { value: "up", label: "Where from" }, { value: "down", label: "Where to" }]} />
          <div className="flex gap-1.5">
            {(Object.keys(EDGE) as Edge["kind"][]).map((k) => (
              <button key={k} onClick={() => toggle(k)} className={cn("flex items-center gap-1.5 rounded-full px-2.5 py-1 text-[11px] font-medium ring-1 ring-inset transition", kinds.has(k) ? "bg-white text-ink ring-slate-300" : "text-ink-faint ring-line")}>
                <svg width="18" height="6"><line x1="0" y1="3" x2="18" y2="3" stroke={EDGE[k].color} strokeWidth="2" strokeDasharray={EDGE[k].dash} opacity={kinds.has(k) ? 1 : 0.3} /></svg>{EDGE[k].label}
              </button>
            ))}
          </div>
          {selected && <button onClick={() => setSelected(null)} className="ml-auto flex items-center gap-1 text-xs text-ink-muted hover:text-ink"><X size={13} /> Clear</button>}
        </div>
        {sel ? (
          <div className="grid gap-4 text-xs lg:grid-cols-[1.3fr_1fr_1fr]">
            <div>
              <div className="flex items-center gap-2"><span className="h-3 w-3 rounded" style={{ background: KIND[sel.kind]?.bar }} /><b className="text-[13px]">{sel.label}</b><Badge>{KIND[sel.kind]?.label}</Badge>{st && <span className="flex items-center gap-1.5 text-ink-muted"><StatusDot s={st} />{st.text}{st.updated_at && ` · ${timeAgo(st.updated_at)}`}</span>}</div>
              {sel.detail && <p className="mt-1.5 leading-relaxed text-ink-soft">{sel.detail}</p>}
              {(sel.keys.length > 0 || sel.endpoints.length > 0) && <div className="mt-2 flex flex-wrap gap-1">{[...sel.keys, ...sel.endpoints].map((k) => <code key={k} className="rounded bg-slate-100 px-1.5 py-0.5 text-[10.5px]">{k}</code>)}</div>}
              {sel.jobs.length > 0 && <div className="mt-2 text-ink-muted">Runs in jobs: {sel.jobs.join(", ")}</div>}
            </div>
            <EdgeList title="Comes from" edges={inE} other={(e) => byId[e.from]} onPick={setSelected} />
            <EdgeList title="Goes to / changes" edges={outE} other={(e) => byId[e.to]} onPick={setSelected} />
          </div>
        ) : (
          <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-[11px] text-ink-muted">
            <span className="flex items-center gap-1.5"><MousePointerClick size={13} /> Click any box to trace where its data comes from and where it goes.</span>
            {Object.entries(KIND).map(([k, v]) => <span key={k} className="flex items-center gap-1"><span className="h-2.5 w-2.5 rounded-sm" style={{ background: v.bar }} />{v.label}</span>)}
            <span className="flex items-center gap-1"><span className="h-2 w-2 rounded-full bg-emerald-500" />live: healthy</span>
            <span className="flex items-center gap-1"><span className="h-2 w-2 rounded-full bg-amber-500" />missing / failing</span>
          </div>
        )}
      </div>
      <div className="overflow-x-auto p-3">
        <svg viewBox={`0 0 ${L.W} ${L.H}`} className="block w-full min-w-[980px]" onClick={() => setSelected(null)}>
          <defs>
            {(Object.keys(EDGE) as Edge["kind"][]).map((k) => (
              <marker key={k} id={`arr-${k}`} viewBox="0 0 8 8" refX="7" refY="4" markerWidth="6" markerHeight="6" orient="auto-start-reverse"><path d="M0,0 L8,4 L0,8 z" fill={EDGE[k].color} /></marker>
            ))}
          </defs>
          {g.columns.map((c, i) => (
            <g key={c.key}>
              <text x={PAD + i * COL_W} y={14} fontSize="11" fontWeight={700} fill="#0f172a" style={{ textTransform: "uppercase", letterSpacing: "0.06em" }}>{c.label}</text>
              <text x={PAD + i * COL_W} y={27} fontSize="9" fill="#94a3b8">{c.hint.length > 40 ? c.hint.slice(0, 39) + "…" : c.hint}</text>
            </g>
          ))}
          {L.headers.map((h) => <text key={h.text + h.x} x={h.x + 2} y={h.y} fontSize="9.5" fontWeight={700} fill="#64748b" style={{ textTransform: "uppercase", letterSpacing: "0.08em" }}>{h.text}</text>)}
          {g.edges.map((e, i) => {
            if (!kinds.has(e.kind)) return null;
            const a = L.pos[e.from], b = L.pos[e.to];
            if (!a || !b) return null;
            const on = hl ? hl.edges.has(i) : false;
            const op = hl ? (on ? 0.95 : 0.04) : e.kind === "write" ? 0.5 : e.kind === "trigger" ? 0.35 : 0.22;
            return (
              <path key={i} d={edgePath(a, b)} fill="none" stroke={EDGE[e.kind].color} strokeWidth={on || hover === i ? 2 : 1.2} strokeDasharray={EDGE[e.kind].dash}
                opacity={hover === i ? 1 : op} markerEnd={`url(#arr-${e.kind})`} onMouseEnter={() => setHover(i)} onMouseLeave={() => setHover(null)} style={{ transition: "opacity .2s" }}>
                <title>{`${byId[e.from]?.label} → ${byId[e.to]?.label}${e.label ? `: ${e.label}` : ""}${e.when ? ` (${e.when})` : ""}`}</title>
              </path>
            );
          })}
          {g.nodes.map((n) => {
            const p = L.pos[n.id];
            const k = KIND[n.kind] ?? KIND.page;
            const dim = hl && !hl.nodes.has(n.id);
            const s = g.stats[n.id];
            return (
              <g key={n.id} transform={`translate(${p.x},${p.y})`} opacity={dim ? 0.18 : 1} className="cursor-pointer" style={{ transition: "opacity .2s" }}
                onClick={(ev) => { ev.stopPropagation(); setSelected(n.id === selected ? null : n.id); }}>
                <rect width={NODE_W} height={NODE_H} rx={8} fill={k.fill} stroke={n.id === selected ? "#0f172a" : "#e2e8f0"} strokeWidth={n.id === selected ? 1.8 : 1} />
                <rect width={4} height={NODE_H} rx={2} fill={k.bar} />
                <text x={11} y={17} fontSize="11" fontWeight={650} fill={k.text}>{n.label.length > 27 ? n.label.slice(0, 26) + "…" : n.label}</text>
                <text x={11} y={31} fontSize="9.2" fill="#64748b">{n.sub.length > 33 ? n.sub.slice(0, 32) + "…" : n.sub}</text>
                {s && <circle cx={NODE_W - 9} cy={10} r={3.5} fill={s.ok ? "#10b981" : "#f59e0b"}><title>{s.text}</title></circle>}
                <title>{`${n.label}\n${n.sub}${s ? `\n${s.text}` : ""}`}</title>
              </g>
            );
          })}
        </svg>
      </div>
    </Card>
  );
}

function EdgeList({ title, edges, other, onPick }: { title: string; edges: Edge[]; other: (e: Edge) => Node | undefined; onPick: (id: string) => void }) {
  return (
    <div>
      <div className="label mb-1.5">{title}</div>
      {edges.length === 0 ? <div className="text-ink-faint">—</div> : (
        <div className="max-h-40 space-y-1 overflow-auto pr-1 scrollbar-thin">
          {edges.map((e, i) => {
            const n = other(e);
            return (
              <button key={i} onClick={() => n && onPick(n.id)} className="flex w-full items-start gap-2 rounded-lg px-1.5 py-1 text-left hover:bg-slate-50">
                <span className="mt-1 h-2 w-2 shrink-0 rounded-full" style={{ background: EDGE[e.kind].color }} />
                <span className="min-w-0"><b className="font-semibold">{n?.label}</b>{e.label && <span className="text-ink-muted"> · {e.label}</span>}{e.when && <span className="block text-[10.5px] text-ink-faint">{e.when}</span>}</span>
              </button>
            );
          })}
        </div>
      )}
    </div>
  );
}

function Mutations({ g, pick }: { g: Graph; pick: (id: string) => void }) {
  const [kind, setKind] = useState<"" | "redis" | "postgres" | "file" | "external">("");
  const rows = g.mutations.filter((m) => !kind || m.store_kind === kind);
  let last = "";
  return (
    <Card>
      <CardHeader title="Every place data changes" subtitle="Each row is one write path: the store that changes, what changes it, and when. Click a row to see it on the map."
        action={<Segmented value={kind} onChange={setKind} options={[{ value: "", label: "All" }, { value: "postgres", label: "Postgres" }, { value: "redis", label: "Redis" }, { value: "file", label: "Files" }, { value: "external", label: "External" }]} />} />
      <div className="overflow-x-auto">
        <table className="w-full text-xs">
          <thead><tr className="border-y border-line bg-slate-50/70 text-left text-[10.5px] font-semibold uppercase tracking-wider text-ink-muted">
            <th className="px-5 py-2.5">Store</th><th className="px-3 py-2.5">Changed by</th><th className="px-3 py-2.5">What changes</th><th className="px-5 py-2.5">When / who</th></tr></thead>
          <tbody>
            {rows.map((m, i) => {
              const first = m.store !== last; last = m.store;
              const s = g.stats[m.store];
              return (
                <tr key={i} onClick={() => pick(m.store)} className={cn("cursor-pointer hover:bg-slate-50", first && "border-t border-line")}>
                  <td className="px-5 py-2 align-top">{first && <div className="flex items-center gap-2"><span className="h-2.5 w-2.5 rounded-sm" style={{ background: KIND[m.store_kind]?.bar }} /><b>{m.store_label}</b>{s && <StatusDot s={s} />}</div>}</td>
                  <td className="px-3 py-2"><span className="flex items-center gap-1.5"><span className="h-2 w-2 rounded-sm" style={{ background: KIND[m.by_kind]?.bar }} />{m.by_label}</span></td>
                  <td className="px-3 py-2 text-ink-soft">{m.what}</td>
                  <td className="px-5 py-2 text-ink-muted">{m.when}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      <p className="px-5 py-3 text-[11px] text-ink-muted">Every change made through the API is also written to the audit log. Jobs record their status and full log in job_runs.</p>
    </Card>
  );
}

function Stores({ g, pick }: { g: Graph; pick: (id: string) => void }) {
  const byId = Object.fromEntries(g.nodes.map((n) => [n.id, n]));
  const groups: { kind: string; title: string; icon: React.ReactNode; hint: string }[] = [
    { kind: "postgres", title: "Postgres", icon: <Database size={16} />, hint: "App state: people, organisations, edits, jobs, audit. Durable; backed up by Neon." },
    { kind: "redis", title: "Redis", icon: <Server size={16} />, hint: "Analytics data: NSQ alerts, the enriched frame, molecule intelligence, live plants. Rebuildable from files and jobs." },
    { kind: "file", title: "Files on the API server", icon: <FileText size={16} />, hint: "Downloads, normalised sources, generated universe, snapshot. Under data/ (mounted volume)." },
    { kind: "external", title: "External sources", icon: <Globe2 size={16} />, hint: "Where public data comes from, with the status of the last fetch." },
  ];
  return (
    <div className="space-y-6">
      {groups.map((gr) => (
        <div key={gr.kind}>
          <div className="mb-2 flex items-center gap-2"><span style={{ color: KIND[gr.kind].bar }}>{gr.icon}</span><h3 className="font-display text-[15px] font-bold">{gr.title}</h3><span className="text-xs text-ink-muted">{gr.hint}</span></div>
          <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
            {g.nodes.filter((n) => n.kind === gr.kind).map((n) => {
              const s = g.stats[n.id];
              const writers = g.edges.filter((e) => e.to === n.id && e.kind === "write").map((e) => byId[e.from]?.label);
              const readers = g.edges.filter((e) => e.from === n.id && e.kind === "flow").map((e) => byId[e.to]?.label);
              return (
                <Card key={n.id} className="cursor-pointer p-4 transition hover:shadow-lift" onClick={() => pick(n.id)}>
                  <div className="flex items-start justify-between gap-2"><div><b className="text-[13px]">{n.label}</b><div className="text-[11px] text-ink-muted">{n.sub}</div></div>
                    {s && <span className={cn("flex shrink-0 items-center gap-1.5 rounded-full px-2 py-0.5 text-[10.5px] ring-1 ring-inset", s.ok ? "bg-emerald-50 text-emerald-800 ring-emerald-200" : "bg-amber-50 text-amber-800 ring-amber-200")}><StatusDot s={s} />{s.text}</span>}</div>
                  {s?.updated_at && <div className="mt-1 text-[10.5px] text-ink-faint">updated {timeAgo(s.updated_at)}</div>}
                  <div className="mt-2 flex flex-wrap gap-1">{n.keys.map((k) => <code key={k} className="rounded bg-slate-100 px-1.5 py-0.5 text-[10px]">{k}</code>)}</div>
                  <p className="mt-2 text-[11.5px] leading-relaxed text-ink-soft">{n.detail}</p>
                  <div className="mt-2 grid grid-cols-2 gap-2 text-[10.5px]">
                    <div><div className="font-semibold text-rose-700">Written by</div><div className="text-ink-muted">{writers.length ? [...new Set(writers)].join(", ") : "—"}</div></div>
                    <div><div className="font-semibold text-slate-600">Read by</div><div className="text-ink-muted">{readers.length ? [...new Set(readers)].join(", ") : "—"}</div></div>
                  </div>
                </Card>
              );
            })}
          </div>
        </div>
      ))}
    </div>
  );
}

export function DataMap() {
  const { data: g, error, isLoading } = useQuery({ queryKey: ["datamap"], queryFn: () => api<Graph>("/api/platform/datamap"), staleTime: 60_000 });
  const [view, setView] = useState<"map" | "mutations" | "stores">("map");
  const [selected, setSelected] = useState<string | null>(() => new URLSearchParams(window.location.search).get("node"));
  if (isLoading) return <PageSkeleton />;
  if (error || !g) return <ErrorNote error={error} />;
  const pick = (id: string) => { setSelected(id); setView("map"); window.scrollTo({ top: 0, behavior: "smooth" }); };
  const counts = { stores: g.nodes.filter((n) => ["redis", "postgres"].includes(n.kind)).length, writes: g.mutations.length, pages: g.nodes.filter((n) => n.kind === "page").length };
  return (
    <div>
      <PageHeader title="Data map"
        subtitle={<>Where every dataset comes from, where it is stored, what changes it, and which screens read it. Status dots and counts are live (checked {timeAgo(g.checked_at)}).</>}
        actions={<Segmented value={view} onChange={setView} options={[{ value: "map", label: <span className="flex items-center gap-1.5"><Workflow size={13} /> Flow map</span> }, { value: "mutations", label: `Mutations (${counts.writes})` }, { value: "stores", label: "Stores" }]} />} />
      {view === "map" && (
        <div className="mb-4 flex flex-wrap items-center gap-2 text-xs text-ink-muted">
          <Badge tone="slate">{g.nodes.filter((n) => n.kind === "external").length} external sources</Badge><ArrowRight size={12} />
          <Badge tone="indigo">{g.nodes.filter((n) => n.kind === "script").length} scripts</Badge><ArrowRight size={12} />
          <Badge tone="amber">{g.nodes.filter((n) => n.kind === "file").length} file sets</Badge><ArrowRight size={12} />
          <Badge tone="rose">{counts.stores} Redis / Postgres stores</Badge><ArrowRight size={12} />
          <Badge tone="brand">{g.nodes.filter((n) => n.kind === "service").length} API services</Badge><ArrowRight size={12} />
          <Badge>{counts.pages} screens</Badge>
        </div>
      )}
      {view === "map" && <FlowMap g={g} selected={selected} setSelected={setSelected} />}
      {view === "mutations" && <Mutations g={g} pick={pick} />}
      {view === "stores" && <Stores g={g} pick={pick} />}
    </div>
  );
}
