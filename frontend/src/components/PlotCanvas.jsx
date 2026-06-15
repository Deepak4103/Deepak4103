import { useMemo, useRef, useEffect, forwardRef, useImperativeHandle } from "react";
import createPlotlyComponent from "react-plotly.js/factory";
import Plotly from "plotly.js-basic-dist-min";
import { sampleFunction } from "@/lib/mathUtils";

const Plot = createPlotlyComponent(Plotly);

const SAMPLES = 600;
const PNG_EXPORT_OPTIONS = {
  format: "png",
  filename: "plotlab-graph",
  width: 1600,
  height: 1000,
  scale: 2,
};

/**
 * Plot canvas exposing imperative methods via ref:
 *  - downloadPNG(filename)
 * Props:
 *  - functions: [{ id, expr, compiled, visible, color, error }]
 *  - variables: { name: { value } }
 *  - indepVar: string
 *  - xRange: [min, max]
 *  - theme: 'light' | 'dark'
 *  - onXRangeChange(newRange)
 */
const PlotCanvas = forwardRef(function PlotCanvas(
  { functions, variables, indepVar, xRange, theme, onXRangeChange },
  ref
) {
  const plotRef = useRef(null);

  useImperativeHandle(
    ref,
    () => ({
      downloadPNG: async (filename = PNG_EXPORT_OPTIONS.filename) => {
        const node = plotRef.current?.el;
        if (!node) return;
        await Plotly.downloadImage(node, { ...PNG_EXPORT_OPTIONS, filename });
      },
    }),
    []
  );

  const scope = useMemo(() => {
    const s = {};
    for (const [k, v] of Object.entries(variables)) s[k] = v.value;
    return s;
  }, [variables]);

  const traces = useMemo(() => {
    const out = [];
    const [xMin, xMax] = xRange;
    for (const fn of functions) {
      if (!fn.visible || !fn.compiled) continue;
      const { xs, ys } = sampleFunction(
        fn.compiled,
        indepVar,
        xMin,
        xMax,
        SAMPLES,
        scope
      );
      out.push({
        x: xs,
        y: ys,
        mode: "lines",
        type: "scatter",
        name: fn.expr,
        line: { color: fn.color, width: 2.25, shape: "spline" },
        hovertemplate: `<b>${fn.expr}</b><br>${indepVar}=%{x:.4f}<br>y=%{y:.4f}<extra></extra>`,
        connectgaps: false,
      });
    }
    return out;
  }, [functions, scope, indepVar, xRange]);

  const isDark = theme === "dark";
  const fg = isDark ? "#FAFAFA" : "#0A0A0A";
  const muted = isDark ? "#A1A1AA" : "#525252";
  const grid = isDark ? "#27272A" : "#E5E7EB";
  const zero = isDark ? "#52525B" : "#9CA3AF";

  const layout = useMemo(
    () => ({
      autosize: true,
      margin: { l: 56, r: 24, t: 24, b: 48 },
      paper_bgcolor: "rgba(0,0,0,0)",
      plot_bgcolor: "rgba(0,0,0,0)",
      font: {
        family: "JetBrains Mono, monospace",
        size: 12,
        color: muted,
      },
      hoverlabel: {
        bgcolor: isDark ? "#18181B" : "#FFFFFF",
        bordercolor: isDark ? "#3F3F46" : "#D4D4D8",
        font: {
          family: "JetBrains Mono, monospace",
          color: fg,
          size: 12,
        },
      },
      xaxis: {
        title: { text: indepVar, font: { color: fg, size: 13 } },
        range: xRange,
        gridcolor: grid,
        zerolinecolor: zero,
        zerolinewidth: 1.5,
        linecolor: grid,
        tickcolor: grid,
        tickfont: { color: muted },
        showspikes: true,
        spikethickness: 1,
        spikedash: "dot",
        spikecolor: zero,
        spikemode: "across",
      },
      yaxis: {
        title: { text: "y", font: { color: fg, size: 13 } },
        gridcolor: grid,
        zerolinecolor: zero,
        zerolinewidth: 1.5,
        linecolor: grid,
        tickcolor: grid,
        tickfont: { color: muted },
        showspikes: true,
        spikethickness: 1,
        spikedash: "dot",
        spikecolor: zero,
        spikemode: "across",
      },
      showlegend: traces.length > 1,
      legend: {
        orientation: "h",
        x: 0,
        y: 1.06,
        bgcolor: "rgba(0,0,0,0)",
        font: { color: fg, family: "JetBrains Mono, monospace", size: 11 },
      },
      dragmode: "pan",
      hovermode: "closest",
    }),
    [xRange, indepVar, isDark, fg, muted, grid, zero, traces.length]
  );

  const config = useMemo(
    () => ({
      responsive: true,
      displaylogo: false,
      scrollZoom: true,
      doubleClick: "reset",
      displayModeBar: true,
      modeBarButtonsToRemove: [
        "select2d",
        "lasso2d",
        "autoScale2d",
        "toggleSpikelines",
      ],
      toImageButtonOptions: PNG_EXPORT_OPTIONS,
    }),
    []
  );

  const handleRelayout = (e) => {
    if (
      e &&
      e["xaxis.range[0]"] !== undefined &&
      e["xaxis.range[1]"] !== undefined
    ) {
      onXRangeChange?.([e["xaxis.range[0]"], e["xaxis.range[1]"]]);
    } else if (e && e["xaxis.autorange"]) {
      onXRangeChange?.([-10, 10]);
    }
  };

  // Refresh plot styles when theme switches (Plotly caches layout)
  useEffect(() => {
    const node = plotRef.current?.el;
    if (node) Plotly.Plots.resize(node);
  }, [theme]);

  return (
    <div
      data-testid="plot-canvas"
      className="w-full h-full"
      style={{ minHeight: 300 }}
    >
      <Plot
        ref={plotRef}
        data={traces}
        layout={layout}
        config={config}
        onRelayout={handleRelayout}
        useResizeHandler
        style={{ width: "100%", height: "100%" }}
      />
    </div>
  );
});

export default PlotCanvas;
