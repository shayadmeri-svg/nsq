// Pharmacopeial methods & cross-monograph diff — port of diagnostics.py
// _render_pharmacopeia. IP 2026 + Ph. Eur. method summaries with provenance,
// then a cross-pharmacopeia diff Table (IP 2026 / Ph. Eur. / USP / ICH Q4B /
// verdict) and NSQ-relevant rationales.

import type { Diagnosis } from "../../../lib/types";
import { ProvenanceBadge } from "../ProvenanceBadge";
import { fmtMethod, verdictLabel } from "../format";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "../../ui/table";

export function Pharmacopeial({ diag }: { diag: Diagnosis }) {
  if (diag.drug === null) {
    return (
      <p className="text-sm text-muted-foreground">
        No curated compendial method set for this product. Consult the relevant IP 2026 /
        Ph. Eur. monograph for the active substance; if not monographed, follow the dosage
        form's general chapters.
      </p>
    );
  }
  const drug = diag.drug;
  return (
    <div className="space-y-2 text-sm text-foreground">
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
        <div>
          <p className="font-semibold">IP 2026</p>
          <ul className="list-disc space-y-1 pl-5">
            <li>Assay: {drug.ip2026.assay}</li>
            <li>Dissolution: {drug.ip2026.dissolution}</li>
            <li>Impurities: {drug.ip2026.impurities}</li>
          </ul>
          <ProvenanceBadge prov={drug.ip2026.provenance} label="IP 2026" />
        </div>
        <div>
          <p className="font-semibold">Ph. Eur.</p>
          <ul className="list-disc space-y-1 pl-5">
            <li>Assay: {drug.ph_eur.assay}</li>
            <li>Dissolution: {drug.ph_eur.dissolution}</li>
            <li>Impurities: {drug.ph_eur.impurities}</li>
          </ul>
          <ProvenanceBadge prov={drug.ph_eur.provenance} label="Ph. Eur." />
        </div>
      </div>

      <p className="pt-2 font-semibold">
        Cross-pharmacopeia method diff — {diag.nsq_relevant_method_diffs}/3 sections
        NSQ-relevant (IP 2026 vs Ph. Eur.)
      </p>
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>Section</TableHead>
            <TableHead>IP 2026</TableHead>
            <TableHead>Ph. Eur.</TableHead>
            <TableHead>USP</TableHead>
            <TableHead>ICH Q4B</TableHead>
            <TableHead>Verdict</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {diag.method_diffs.map((d) => (
            <TableRow key={d.section}>
              <TableCell>{d.section}</TableCell>
              <TableCell>{fmtMethod(d.methods["IP 2026"] ?? null, d.section)}</TableCell>
              <TableCell>{fmtMethod(d.methods["Ph. Eur."] ?? null, d.section)}</TableCell>
              <TableCell>{fmtMethod(d.methods["USP"] ?? null, d.section)}</TableCell>
              <TableCell>
                {d.ich_harmonisation
                  ? "Annex 7(R2) — general ch.; prod.-specific outside scope"
                  : "—"}
              </TableCell>
              <TableCell>{verdictLabel(d.significance)}</TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>

      {diag.method_diffs.some((d) => d.significance === "NSQ_RELEVANT") && (
        <>
          <p className="pt-1 font-semibold">NSQ-relevant differences:</p>
          <ul className="list-disc space-y-1 pl-5">
            {diag.method_diffs
              .filter((d) => d.significance === "NSQ_RELEVANT")
              .map((d) => (
                <li key={d.section}>
                  <strong>{d.section}</strong>: {d.rationale}
                </li>
              ))}
          </ul>
        </>
      )}
      <ProvenanceBadge prov={drug.ich_harmonisation_prov} label="ICH Q4B harmonisation" />
    </div>
  );
}