// Suggested mitigations (preview) — port of diagnostics.py
// _render_mitigation_preview. Each curated mitigation carries a Provenance;
// uncategorised failures get the ICH Q9 fallback note. Full CAPA lands in
// the mitigation tab (phase 3).

import type { Diagnosis } from "../../../lib/types";
import { ProvenanceBadge } from "../ProvenanceBadge";

export function MitigationPreview({ diag }: { diag: Diagnosis }) {
  return (
    <div className="space-y-2 text-sm text-foreground">
      {diag.mitigations.length > 0 ? (
        <ul className="list-disc space-y-2 pl-5">
          {diag.mitigations.map((m, i) => (
            <li key={i}>
              {m.text}
              <ProvenanceBadge prov={m.provenance} label="Mitigation" />
            </li>
          ))}
        </ul>
      ) : (
        <p className="text-xs text-muted-foreground">
          No curated mitigation playbook for this failure category.
        </p>
      )}
      <p className="text-xs text-muted-foreground">
        Full CAPA plan — per-excipient actions + critical processing spec windows — lands in
        the Q-engine mitigation tab (phase 3).
      </p>
    </div>
  );
}