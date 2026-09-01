// Chart grid — donut + line on the top row (2-col), bar full-width, heatmap
// full-width. Mirrors the Streamlit dashboard layout (ui/charts.py builders
// rendered in the same arrangement).

import type { PlotlyFigure } from "../../lib/types";
import { PlotlyChart } from "../charts/PlotlyChart";
import { Card } from "../ui/card";

export function ChartsGrid({
  charts,
}: {
  charts: { by_type: PlotlyFigure; over_time: PlotlyFigure; by_form: PlotlyFigure; form_vs_issue: PlotlyFigure };
}) {
  return (
    <div className="space-y-4">
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <Card className="p-4">
          <PlotlyChart figure={charts.by_type} title="Alerts by failure type" />
        </Card>
        <Card className="p-4">
          <PlotlyChart figure={charts.over_time} title="Alerts over time" />
        </Card>
      </div>
      <Card className="p-4">
        <PlotlyChart figure={charts.by_form} title="Alerts by dosage form" />
      </Card>
      <Card className="p-4">
        <PlotlyChart figure={charts.form_vs_issue} title="Form × failure-category heatmap" />
      </Card>
    </div>
  );
}