// Thin wrapper around react-plotly.js. The backend builds the exact Plotly
// Figure objects (ui/charts.py) and serialises them with fig.to_json(); this
// renders them verbatim, so the charts are identical to the Streamlit app
// with zero rework. plotly.js-basic-dist-min keeps the bundle slim (the four
// chart types — bar/donut(pie)/line/heatmap — are all in the basic dist).

import { useMemo } from "react";
import createPlotlyComponent from "react-plotly.js/factory.js";
import Plotly from "plotly.js-dist-min";
import type { PlotlyFigure } from "../../lib/types";

// Build the Plot component from the full plotly.js dist. The basic-dist
// bundle omits the standalone Heatmap trace (it ships only scatter / bar /
// pie / histogram-family), and the dashboard's form × issue chart is a
// go.Heatmap, so the full bundle is required for it to render correctly.
// react-plotly.js/factory.js exports the createPlotlyComponent factory as
// its CJS default.
const Plot = createPlotlyComponent(Plotly);

interface PlotlyChartProps {
  figure: PlotlyFigure;
  className?: string;
  title?: string;
}

export function PlotlyChart({ figure, className, title }: PlotlyChartProps) {
  const fig = useMemo(() => {
    if (!figure) return null;
    // The serialised figure is { data: [...], layout: {...}, config? } —
    // pass straight through. Force the Inter font so the React charts match
    // the Streamlit charts (ui/charts.py sets layout.font.family = Inter).
    const f = figure as Record<string, unknown>;
    const layout = { ...(f.layout as object), font: { family: "Inter, sans-serif" } };
    return { data: (f.data as object[]) ?? [], layout };
  }, [figure]);

  if (!fig) {
    return (
      <div className="flex items-center justify-center py-10 text-sm text-muted-foreground">
        No chart data for this manufacturer.
      </div>
    );
  }

  return (
    <div className={className}>
      {title && <div className="mb-2 text-sm font-semibold text-foreground">{title}</div>}
      <Plot
        data={fig.data}
        layout={fig.layout}
        config={{ displayModeBar: false, responsive: true }}
        useResizeHandler
        style={{ width: "100%", height: "100%", minHeight: 260 }}
      />
    </div>
  );
}