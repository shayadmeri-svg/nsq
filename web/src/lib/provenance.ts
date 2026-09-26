import { useQuery } from "@tanstack/react-query";
import { api } from "./api";

export type FieldProv = { label: string; status: "sourced" | "frozen" | "estimate" | "inferred"; present: string; gap: string };

export function useProvenance() {
  return useQuery({
    queryKey: ["provenance"],
    queryFn: () => api<{ fields: Record<string, FieldProv> }>("/api/meta/provenance"),
    staleTime: Infinity,
  });
}
