// Dashboard page — KPIs, charts, scrollable issue list. Mirrors the
// Streamlit dashboard: the strapline is verbatim from the Figma /
// dashboard.py, KPIs are NSQ alerts / Products / Period, and the issue list's
// Deep-dive navigates to /diagnostics/:id with the stable record_id.

import { useNavigate } from "react-router-dom";
import { KpiRow } from "../components/dashboard/KpiRow";
import { ChartsGrid } from "../components/dashboard/ChartsGrid";
import { IssueList } from "../components/dashboard/IssueList";
import { NavPills } from "../components/layout/NavPills";
import { Skeleton } from "../components/ui/skeleton";
import { useDashboard } from "../lib/api";
import { useSession } from "../state/session";

export function Dashboard() {
  const navigate = useNavigate();
  const tenantKey = useSession((s) => s.tenantKey);
  const tenant = useSession((s) => s.tenant);
  const { data, isLoading, error } = useDashboard(tenantKey);

  return (
    <div className="mx-auto max-w-[1200px] px-6 py-6">
      <NavPills
        items={[
          { key: "dashboard", label: "Dashboard", active: true },
          { key: "diagnostics", label: "Diagnostics", onClick: () => navigate("/diagnostics/random") },
          { key: "simulator", label: "Simulator", disabled: true },
        ]}
      />

      <h1 className="mt-4 text-xl font-bold text-foreground">
        {tenant ? `${tenant.canonical} — ${tenant.city}` : "Dashboard"}
      </h1>
      <p className="mt-2 text-sm text-foreground/80">
        Use Q-engine to deep dive into root cause analysis as well as corrective &amp; preventive
        actions.
      </p>

      {error && (
        <p className="mt-6 text-sm text-destructive">
          Could not load the dashboard. {String(error.message)}
        </p>
      )}

      {isLoading && (
        <div className="mt-6 space-y-6">
          <div className="grid grid-cols-3 gap-4">
            <Skeleton className="h-24" />
            <Skeleton className="h-24" />
            <Skeleton className="h-24" />
          </div>
          <Skeleton className="h-72" />
          <Skeleton className="h-72" />
        </div>
      )}

      {data && (
        <div className="mt-6 space-y-6">
          {data.empty && (
            <p className="text-sm text-muted-foreground">
              No NSQ records found for this manufacturer.
            </p>
          )}
          <KpiRow kpis={data.kpis} />
          <ChartsGrid charts={data.charts} />
          <div>
            <h2 className="mb-2 text-sm font-semibold text-foreground">
              NSQ alerts ({data.issue_count})
            </h2>
            <IssueList issues={data.issues} />
          </div>
        </div>
      )}
    </div>
  );
}