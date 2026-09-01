// GMP corridor — port of diagnostics.py _render_gmp_corridor. The curated
// optimal process + critical processing corridor (ParamSpec table) + ideal
// excipient profile (Table). Uncurated products get the ICH Q7/Q9 fallback
// narrative.

import type { Diagnosis } from "../../../lib/types";
import { ProvenanceBadge } from "../ProvenanceBadge";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "../../ui/table";

export function GmpCorridor({ diag }: { diag: Diagnosis }) {
  if (diag.drug === null) {
    return (
      <p className="text-sm text-muted-foreground">
        No curated GMP corridor for this product's active ingredient. Apply ICH Q7/Q9
        risk-based manufacturing controls and the dosage form's general compendial chapters
        (e.g. Ph. Eur. 2.9.3 dissolution, 2.9.6 uniformity) until a product-specific corridor
        is sourced.
      </p>
    );
  }
  const drug = diag.drug;
  return (
    <div className="space-y-2 text-sm text-foreground">
      <p>
        <strong>Optimal process:</strong> {drug.optimal_process || "—"}
      </p>
      <ProvenanceBadge prov={drug.optimal_process_prov} label="Process" />

      {Object.keys(drug.ideal_parameters).length > 0 ? (
        <>
          <p className="pt-1 font-semibold">Critical processing corridor</p>
          <ul className="list-disc space-y-1 pl-5">
            {Object.values(drug.ideal_parameters).map((p) => (
              <li key={p.label}>
                {p.label}: {p.min}–{p.max} {p.unit} (target {p.ideal} {p.unit})
              </li>
            ))}
          </ul>
          <ProvenanceBadge
            prov={Object.values(drug.ideal_parameters)[0]?.provenance ?? null}
            label="GMP corridor"
          />
        </>
      ) : drug.gmp_note ? (
        <p>
          <strong>GMP</strong> — {drug.gmp_note}
        </p>
      ) : (
        <p>
          <strong>GMP corridor</strong> — not specified in the curated catalog.
        </p>
      )}

      {drug.ideal_excipients.length > 0 && (
        <>
          <p className="pt-1 font-semibold">Formulation (ideal excipient profile)</p>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Excipient</TableHead>
                <TableHead>Role</TableHead>
                <TableHead>% w/w</TableHead>
                <TableHead>Rationale</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {drug.ideal_excipients.map((e) => (
                <TableRow key={e.name}>
                  <TableCell>{e.name}</TableCell>
                  <TableCell>{e.role}</TableCell>
                  <TableCell>{e.ratio}</TableCell>
                  <TableCell>{e.description}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </>
      )}
    </div>
  );
}