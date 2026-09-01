// Issue header — port of diagnostics.py _render_issue_header. A bordered
// card with the product, batch/lab/month/form, the NSQ-result chip, the
// failure category, and a caption counting the manufacturer's alerts.

import type { Diagnosis } from "../../lib/types";

export function IssueHeader({ diag }: { diag: Diagnosis }) {
  return (
    <div className="rounded-lg border border-border bg-card p-4">
      <div className="grid grid-cols-[1fr_auto] items-center gap-x-3 gap-y-1.5">
        <div>
          <div className="text-lg font-bold text-foreground">{diag.product}</div>
          <div className="mt-1 text-xs text-muted-foreground">
            Batch {diag.batch} · {diag.lab} · {diag.month} · {diag.form}
          </div>
        </div>
        <div className="flex flex-col items-end gap-1.5">
          <span className="rounded border border-border px-2.5 py-1 text-xs font-semibold text-destructive">
            {diag.nsq_result}
          </span>
          <span className="text-xs text-foreground/80">
            Failure category: <strong>{diag.failure_category}</strong>
          </span>
        </div>
      </div>
      <p className="mt-2 text-xs text-muted-foreground">
        Deep dive on one of {diag.tenant_alert_count} NSQ alerts for this manufacturer.
      </p>
    </div>
  );
}