import { useQuery } from "@tanstack/react-query";
import { useParams } from "react-router-dom";
import { api } from "../../lib/api";

export type Org = { id: number; slug: string; name: string; city: string; country: string; ontology_keys: string[]; plant_ids: string[]; notes: string; is_active: boolean };

export function useOrg() {
  const { slug = "" } = useParams();
  const q = useQuery({ queryKey: ["org", slug], queryFn: () => api<{ org: Org; can_manage: boolean }>(`/api/orgs/${slug}`), enabled: !!slug });
  return { slug, org: q.data?.org, canManage: q.data?.can_manage ?? false, ...q };
}

export function useOrgData<T = any>(part: string, extra: unknown[] = []) {
  const { slug = "" } = useParams();
  return useQuery<T>({ queryKey: ["org", slug, part, ...extra], queryFn: () => api<T>(`/api/orgs/${slug}/${part}`), enabled: !!slug });
}

export const STATUS_STYLE: Record<string, { label: string; cls: string; dot: string }> = {
  met: { label: "Met", cls: "bg-emerald-50 text-emerald-700 ring-emerald-200", dot: "bg-emerald-500" },
  attention: { label: "Check", cls: "bg-amber-50 text-amber-700 ring-amber-200", dot: "bg-amber-500" },
  gap: { label: "Gap", cls: "bg-rose-50 text-rose-700 ring-rose-200", dot: "bg-rose-500" },
  na: { label: "N/A", cls: "bg-slate-50 text-slate-500 ring-slate-200", dot: "bg-slate-300" },
};

export const VERDICT: Record<string, { label: string; color: string }> = {
  ready: { label: "Ready", color: "#059669" },
  close: { label: "Within reach", color: "#d97706" },
  far: { label: "Far", color: "#e11d48" },
};
