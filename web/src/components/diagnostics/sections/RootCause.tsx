// Root cause analysis — port of diagnostics.py _render_root_cause. Two
// evidence modes: data-informed aggregate signals over the tenant frame
// (dominant failures, form span, geo concentration, temporal clusters) and
// API-informed OOS insights (curated Drug common_alerts / vigibase_risks, or
// the generic pharmacopeial fallback). The *(this issue)* marker flags the
// matching category. Provenance captions mark the narrative fields.

import type { Diagnosis } from "../../../lib/types";
import { ProvenanceBadge } from "../ProvenanceBadge";

export function RootCause({ diag }: { diag: Diagnosis }) {
  return (
    <div className="space-y-2 text-sm text-foreground">
      <p className="font-semibold">Data-informed issues</p>
      {diag.dominant_failures.length > 0 ? (
        <ul className="list-disc space-y-1 pl-5">
          {diag.dominant_failures.map(([cat, n, pct]) => (
            <li key={cat}>
              <strong>{cat}</strong> — a dominant failure mode ({n} alerts, {pct}%)
              {cat === diag.failure_category && <span className="italic"> (this issue)</span>}
            </li>
          ))}
        </ul>
      ) : (
        <p className="text-xs text-muted-foreground">
          No dominant failure-mode signal for this manufacturer.
        </p>
      )}
      {diag.form_span > 1 && (
        <p>Issues span <strong>{diag.form_span} dosage forms</strong>.</p>
      )}
      {diag.geo_concentration.length > 0 && (
        <p>
          Geographic concentration:{" "}
          {diag.geo_concentration.map(([s, n]) => `${s} (${n})`).join(", ")}.
        </p>
      )}
      {diag.temporal_clusters.length > 0 && (
        <p>
          Temporal clusters:{" "}
          {diag.temporal_clusters.map(([m, n]) => `${m} (${n})`).join(", ")}.
        </p>
      )}
      {!diag.is_dominant_failure && diag.failure_category !== "—" && (
        <p className="text-xs text-muted-foreground">
          This issue's category ({diag.failure_category}) is an outlier, not a dominant mode
          for this manufacturer — review case-specific factors.
        </p>
      )}

      <p className="pt-2 font-semibold">API-informed OOS insights</p>
      {diag.drug ? (
        <>
          <p className="text-xs text-muted-foreground">
            Curated typical-defect lists are authored narrative (uncited, no denominator) —
            review against the empirical cohort, not as grounded fact.
          </p>
          {diag.drug.common_alerts.length > 0 && (
            <ul className="list-disc space-y-1 pl-5">
              {diag.drug.common_alerts.map((a) => (
                <li key={a}>{a}</li>
              ))}
            </ul>
          )}
          <ProvenanceBadge prov={diag.drug.common_alerts_prov} label="Typical causes" />
          {diag.drug.vigibase_risks.length > 0 && (
            <>
              <p className="pt-1 font-semibold">Post-market risk signals (VigiBase):</p>
              <ul className="list-disc space-y-1 pl-5">
                {diag.drug.vigibase_risks.map((r) => (
                  <li key={r.hazard}>
                    <strong>{r.hazard ?? "—"}</strong> — {r.desc ?? ""}
                  </li>
                ))}
              </ul>
              <ProvenanceBadge prov={diag.drug.vigibase_risks_prov} label="VigiBase risks" />
            </>
          )}
        </>
      ) : (
        <>
          <p>
            This product's active ingredient is not in the curated GMP catalog, so no
            API-specific defect mechanism is available.
          </p>
          {diag.generic_text && (
            <>
              <p>
                <strong>Scientific context</strong> — {diag.generic_text.scientific}
              </p>
              <p>
                <strong>Regulatory guidelines</strong> — {diag.generic_text.regulatory}
              </p>
              <p className="text-xs text-muted-foreground">
                Generic pharmacopeial fallback — no fabricated specifics.
              </p>
            </>
          )}
        </>
      )}
    </div>
  );
}