// Diagnostics page — single-issue root-cause deep dive. Handles the
// /diagnostics/random nav-tab entry point by resolving a random issue id
// from the cached dashboard issue list and redirecting. For a concrete id,
// fetches the diagnosis and renders DiagnosticsView; "Pick another issue"
// draws a different id from the same list.

import { useEffect } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { DiagnosticsView } from "../components/diagnostics/DiagnosticsView";
import { NavPills } from "../components/layout/NavPills";
import { Skeleton } from "../components/ui/skeleton";
import { useDashboard, useDiagnostics } from "../lib/api";
import { useSession } from "../state/session";

function randomIssueId(ids: string[], exclude?: string): string {
  if (ids.length === 0) return "random";
  if (ids.length === 1) return ids[0];
  const pool = exclude ? ids.filter((id) => id !== exclude) : ids;
  const pick = pool.length ? pool : ids;
  return pick[Math.floor(Math.random() * pick.length)];
}

export function Diagnostics() {
  const navigate = useNavigate();
  const { issueId } = useParams<{ issueId: string }>();
  const tenantKey = useSession((s) => s.tenantKey);
  const persona = useSession((s) => s.persona);
  const dash = useDashboard(tenantKey);

  // Resolve /diagnostics/random -> a real issue id from the dashboard list.
  useEffect(() => {
    if (issueId !== "random") return;
    if (!dash.data || dash.data.issues.length === 0) return;
    const id = randomIssueId(dash.data.issues.map((i) => i.id));
    navigate(`/diagnostics/${id}`, { replace: true });
  }, [issueId, dash.data, navigate]);

  const { data, isLoading, error } = useDiagnostics(
    tenantKey,
    issueId && issueId !== "random" ? issueId : null,
    persona,
  );

  const pickAnother = () => {
    const ids = dash.data?.issues.map((i) => i.id) ?? [];
    navigate(`/diagnostics/${randomIssueId(ids, issueId)}`);
  };

  return (
    <div className="mx-auto max-w-[1100px] px-6 py-6">
      <NavPills
        items={[
          { key: "dashboard", label: "Dashboard", onClick: () => navigate("/dashboard") },
          { key: "diagnostics", label: "Diagnostics", active: true },
          { key: "simulator", label: "Simulator", disabled: true },
        ]}
      />

      <h1 className="mt-4 text-xl font-bold text-foreground">Diagnostics</h1>

      {error && (
        <p className="mt-6 text-sm text-destructive">
          Could not load the diagnosis. {String(error.message)}
        </p>
      )}

      {issueId === "random" && dash.isLoading && (
        <p className="mt-6 text-sm text-muted-foreground">Selecting an issue…</p>
      )}

      {isLoading && (
        <div className="mt-6 space-y-4">
          <Skeleton className="h-24" />
          <Skeleton className="h-10" />
          <Skeleton className="h-40" />
        </div>
      )}

      {data && persona && <DiagnosticsView diag={data.diagnosis} persona={persona} onPickAnother={pickAnother} />}
    </div>
  );
}