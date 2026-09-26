export const fmtInt = (n?: number | null) => (n == null ? "—" : n.toLocaleString("en-IN"));

export function fmtMonth(m?: string | null) {
  if (!m) return "—";
  const [y, mo] = m.split("-");
  const d = new Date(Number(y), Number(mo) - 1, 1);
  return d.toLocaleDateString("en-GB", { month: "short", year: "numeric" });
}

export function fmtDate(iso?: string | null) {
  if (!iso) return "—";
  const d = new Date(iso);
  return d.toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric" });
}

export function fmtDateTime(iso?: string | null) {
  if (!iso) return "—";
  return new Date(iso).toLocaleString("en-GB", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });
}

export function timeAgo(iso?: string | null) {
  if (!iso) return "never";
  const s = (Date.now() - new Date(iso).getTime()) / 1000;
  if (s < 60) return "just now";
  if (s < 3600) return `${Math.floor(s / 60)} min ago`;
  if (s < 86400) return `${Math.floor(s / 3600)} h ago`;
  if (s < 86400 * 30) return `${Math.floor(s / 86400)} d ago`;
  return fmtDate(iso);
}

export const titleCase = (s: string) => s.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());

export const PALETTE = ["#0a9a7d", "#6366f1", "#f59e0b", "#ec4899", "#0ea5e9", "#84cc16", "#a855f7", "#94a3b8"];

export const ROLE_LABEL: Record<string, string> = {
  super_admin: "Super admin",
  admin: "Platform admin",
  org_admin: "Org admin",
  member: "Member",
};

export const TIER_STYLE: Record<string, string> = {
  strategic: "bg-brand-50 text-brand-700 ring-brand-200",
  core: "bg-indigo-50 text-indigo-700 ring-indigo-200",
  adjacent: "bg-amber-50 text-amber-700 ring-amber-200",
  stretch: "bg-slate-100 text-slate-600 ring-slate-200",
};
