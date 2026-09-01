// Provenance badge — the rigour gate made visible. Port of diagnostics.py
// _provenance_badge. When provenance is null, the caption says "no provenance
// — do not treat as authoritative" (provenance-first tone). Otherwise it
// renders [tier] source_ref (url) retrieved date n=… with a TODO flag.

import type { Provenance } from "../../lib/types";

export function ProvenanceBadge({
  prov,
  label = "Source",
}: {
  prov: Provenance | null;
  label?: string;
}) {
  if (prov === null) {
    return (
      <p className="text-xs text-muted-foreground">
        {label}: no provenance — do not treat as authoritative.
      </p>
    );
  }
  const bits = [`${label}: [${prov.authority_tier}] ${prov.source_ref || "(no ref)"}`];
  if (prov.reference_url) bits.push(`(${prov.reference_url})`);
  if (prov.retrieved_at) bits.push(`retrieved ${prov.retrieved_at}`);
  if (prov.n) bits.push(`n=${prov.n}`);
  if (prov.notes && prov.notes.includes("TODO")) bits.push("· citation TODO");
  return <p className="text-xs text-muted-foreground">{bits.join(" ")}</p>;
}