// Synthesis route — port of diagnostics.py _render_synthesis_gap. Always an
// honest gap: the synthesis-route steps (patent US7943781B2) are not in the
// GMP knowledge core yet. No chemistry is invented here.

export function SynthesisGap() {
  return (
    <div className="rounded-md border border-info/40 bg-info/[0.06] p-3 text-sm text-foreground">
      Synthesis-route steps with patent cites (e.g. the Figma's Hydrogenation → Hydrolysis →
      Condensation → N-Alkylation → Final Hydrolysis → Purification, patent US7943781B2) are{" "}
      <strong>not yet in the GMP knowledge core</strong>. This section is a placeholder until
      that data is curated — no chemistry is invented here.
    </div>
  );
}