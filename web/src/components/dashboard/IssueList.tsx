// Scrollable issue list + per-issue card. Mirrors the Streamlit mq-issue-list
// / mq-issue-card: all cards in one scrollable container (no pagination), a
// grid of product/meta + a result chip, and a Deep-dive button that navigates
// to /diagnostics/:id with the stable record_id.

import { useNavigate } from "react-router-dom";
import type { Issue } from "../../lib/types";
import { Button } from "../ui/button";
import { ScrollArea } from "../ui/scroll-area";

export function IssueCard({ issue, onDeepDive }: { issue: Issue; onDeepDive: () => void }) {
  return (
    <div className="grid grid-cols-[1fr_auto] items-center gap-x-3 gap-y-1 rounded-lg border border-border bg-card px-4 py-3">
      <div className="min-w-0">
        <div className="truncate font-semibold text-foreground">{issue.product}</div>
        <div className="text-xs text-muted-foreground">
          Batch {issue.batch} · {issue.lab} · {issue.month} · {issue.form}
        </div>
        <Button variant="link" size="sm" className="mt-1 h-auto p-0 text-xs" onClick={onDeepDive}>
          Deep dive
        </Button>
      </div>
      <div className="flex flex-col items-end gap-1.5">
        <span className="rounded border border-border px-2 py-0.5 text-xs font-semibold text-destructive">
          {issue.nsq_result}
        </span>
        <span className="text-xs text-foreground/80">
          Failure category: <strong>{issue.failure_category}</strong>
        </span>
      </div>
    </div>
  );
}

export function IssueList({ issues }: { issues: Issue[] }) {
  const navigate = useNavigate();
  return (
    <ScrollArea className="max-h-[520px] rounded-lg border border-border bg-muted/40 p-2.5">
      <div className="space-y-2">
        {issues.map((it) => (
          <IssueCard key={it.id} issue={it} onDeepDive={() => navigate(`/diagnostics/${it.id}`)} />
        ))}
      </div>
    </ScrollArea>
  );
}