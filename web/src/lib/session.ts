import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api, ApiError, post } from "./api";

export type Me = {
  id: number; email: string; name: string; role: string; persona: string;
  org: { id: number; slug: string; name: string; city: string; country: string } | null;
  must_change_password: boolean; is_platform: boolean;
  permissions: { admin: boolean; manage_users: boolean; run_jobs: boolean; run_destructive_jobs: boolean; platform_analytics: boolean };
  last_login_at: string | null;
};

export function useMe() {
  return useQuery<Me | null>({
    queryKey: ["me"],
    queryFn: async () => {
      try {
        return (await api<{ user: Me }>("/api/auth/me")).user;
      } catch (e) {
        if (e instanceof ApiError && e.status === 401) return null;
        throw e;
      }
    },
    staleTime: 60_000,
    retry: false,
  });
}

export function useLogout() {
  const qc = useQueryClient();
  return async () => {
    await post("/api/auth/logout");
    qc.clear();
    qc.setQueryData(["me"], null);
  };
}
