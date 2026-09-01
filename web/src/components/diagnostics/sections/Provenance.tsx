// Regulatory provenance — port of diagnostics.py _render_provenance. Patent
// + FDA Orange Book (real US regulatory-equivalence data, or an honest
// "no entry" caption) + the authority-tier legend.

import type { Diagnosis } from "../../../lib/types";
import { ProvenanceBadge } from "../ProvenanceBadge";
import { fmtTeCodes } from "../format";
import { Table, TableBody, TableCell, TableRow } from "../../ui/table";

export function Provenance({ diag }: { diag: Diagnosis }) {
  if (diag.drug === null) {
    return <p className="text-sm text-muted-foreground">No curated regulatory provenance for this product.</p>;
  }
  const drug = diag.drug;
  return (
    <div className="space-y-2 text-sm text-foreground">
      <p>
        <strong>Patent:</strong> {drug.patent_ref || "—"}
        {drug.patent_link && (
          <>
            {" — "}
            <a className="text-primary underline" href={drug.patent_link} target="_blank" rel="noreferrer">
              link
            </a>
          </>
        )}
      </p>
      <ProvenanceBadge prov={drug.patent_prov} label="Patent" />

      {drug.orange_book === null ? (
        <p className="text-xs text-muted-foreground">
          FDA Orange Book: no entry (not FDA-approved in the US) — honestly absent, not faked.
        </p>
      ) : (
        <>
          <p className="pt-1 font-semibold">FDA Orange Book — real US regulatory-equivalence data</p>
          <Table>
            <TableBody>
              <ObRow label="Active ingredient (US)" value={drug.orange_book.active_ingredient} />
              <ObRow label="TE codes" value={fmtTeCodes(drug.orange_book.te_codes)} />
              <ObRow label="RLD applicant" value={drug.orange_book.rld_applicant || "—"} />
              <ObRow label="RLD application" value={drug.orange_book.rld_app_number || "—"} />
              <ObRow label="RLD approval date" value={drug.orange_book.rld_approval_date || "—"} />
              <ObRow label="Reference standard" value={drug.orange_book.reference_standard ? "yes" : "no"} />
              <ObRow label="Dosage forms" value={drug.orange_book.dosage_forms.join(", ") || "—"} />
              <ObRow label="Marketing status" value={drug.orange_book.marketing_statuses.join(", ") || "—"} />
            </TableBody>
          </Table>
          <ProvenanceBadge prov={drug.orange_book.provenance} label="FDA Orange Book" />
        </>
      )}

      <p className="pt-1 text-xs text-muted-foreground">
        <strong>Authority tiers</strong> — [monograph] compendial spec · [ich_guideline] ICH
        Q4B/Q8/Q9/Q10 · [regulatory_registry] FDA Orange Book / EMA / CDSCO · [patent]
        registry-cited · [empirical_cohort] cohort n+query · [expert_corridor] illustrative ·
        [uncited] citation TODO.
      </p>
    </div>
  );
}

function ObRow({ label, value }: { label: string; value: string }) {
  return (
    <TableRow>
      <TableCell className="w-1/3 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
        {label}
      </TableCell>
      <TableCell>{value}</TableCell>
    </TableRow>
  );
}