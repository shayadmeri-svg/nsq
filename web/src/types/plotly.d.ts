// Ambient declarations for the plotly factory + full dist, which ship no
// bundled .d.ts (the @types/react-plotly.js default export is the full-plotly
// Plot class, not the createPlotlyComponent factory). The factory subpath
// react-plotly.js/factory.js exports plotComponentFactory as its CJS default.

declare module "plotly.js-dist-min" {
  const Plotly: any;
  export default Plotly;
}

declare module "react-plotly.js/factory.js" {
  import type { ComponentClass, CSSProperties } from "react";
  interface PlotParams {
    data: unknown[];
    layout: unknown;
    frames?: unknown[];
    config?: Record<string, unknown>;
    useResizeHandler?: boolean;
    style?: CSSProperties;
    className?: string;
    divId?: string;
    [key: string]: unknown;
  }
  function createPlotlyComponent(plotly: unknown): ComponentClass<PlotParams>;
  export default createPlotlyComponent;
}