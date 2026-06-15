import { useCallback, useMemo, useRef, useState } from "react";
import { Download, Activity, Github } from "lucide-react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

import PlotCanvas from "@/components/PlotCanvas";
import FunctionRow, { AddFunctionButton } from "@/components/FunctionRow";
import SliderRow from "@/components/SliderRow";
import ThemeToggle from "@/components/ThemeToggle";
import PresetMenu from "@/components/PresetMenu";

import { useTheme } from "@/hooks/useTheme";
import { colorForIndex } from "@/lib/colors";
import { extractVariables, safeCompile } from "@/lib/mathUtils";

const DEFAULT_VAR_RANGE = { min: -10, max: 10, step: 0.1 };
const defaultVar = () => ({ value: 1, ...DEFAULT_VAR_RANGE });
const INITIAL_FUNCTIONS = [
  { id: 1, expr: "A * sin(B * x + C)", visible: true, colorIdx: 0 },
];
const INITIAL_VARS = {
  A: { value: 1, ...DEFAULT_VAR_RANGE },
  B: { value: 1, ...DEFAULT_VAR_RANGE },
  C: { value: 0, ...DEFAULT_VAR_RANGE },
};

let nextId = 2;
const newId = () => nextId++;

export default function GraphingCalculator() {
  const { theme } = useTheme();
  const plotRef = useRef(null);

  const [indepVar, setIndepVar] = useState("x");
  const [xRange, setXRange] = useState([-10, 10]);
  const [functions, setFunctions] = useState(INITIAL_FUNCTIONS);
  // varStore holds all variable configs the user has touched (never deleted automatically)
  const [varStore, setVarStore] = useState(INITIAL_VARS);

  // Compile every function and detect variable set whenever fn list or indepVar changes
  const compiledFns = useMemo(() => {
    return functions.map((fn) => {
      const { ok, compiled, error } = safeCompile(fn.expr);
      let detected = [];
      if (ok) {
        try {
          detected = extractVariables(fn.expr, indepVar);
        } catch {
          detected = [];
        }
      }
      return {
        ...fn,
        compiled: ok ? compiled : null,
        error: ok ? null : error,
        detected,
        color: colorForIndex(fn.colorIdx),
      };
    });
  }, [functions, indepVar]);

  // Union of detected variables across all functions
  const allDetectedVars = useMemo(() => {
    const set = new Set();
    for (const f of compiledFns) for (const v of f.detected) set.add(v);
    return Array.from(set).sort();
  }, [compiledFns]);

  // Render-time variable map: detected vars get their stored config, or defaults.
  const variables = useMemo(() => {
    const out = {};
    for (const name of allDetectedVars) out[name] = varStore[name] ?? defaultVar();
    return out;
  }, [allDetectedVars, varStore]);

  // Map variable → accent color from the first function that uses it
  const varColor = useCallback(
    (name) => {
      for (const f of compiledFns) {
        if (f.detected.includes(name)) return f.color;
      }
      return "#525252";
    },
    [compiledFns]
  );

  const handleChangeExpr = (id, expr) =>
    setFunctions((fns) => fns.map((f) => (f.id === id ? { ...f, expr } : f)));

  const handleToggleVisible = (id) =>
    setFunctions((fns) =>
      fns.map((f) => (f.id === id ? { ...f, visible: !f.visible } : f))
    );

  const handleRemove = (id) =>
    setFunctions((fns) => fns.filter((f) => f.id !== id));

  const handleAdd = () =>
    setFunctions((fns) => [
      ...fns,
      {
        id: newId(),
        expr: "",
        visible: true,
        colorIdx: fns.length,
      },
    ]);

  const handleVarChange = (name, value) =>
    setVarStore((v) => ({
      ...v,
      [name]: { ...(v[name] ?? defaultVar()), value },
    }));

  const handleVarRangeChange = (name, partial) =>
    setVarStore((v) => {
      const cur = v[name] ?? defaultVar();
      const next = { ...cur, ...partial };
      if (next.value < next.min) next.value = next.min;
      if (next.value > next.max) next.value = next.max;
      return { ...v, [name]: next };
    });

  const handlePickPreset = (preset) => {
    nextId = 1;
    const newFns = preset.functions.map((expr, i) => ({
      id: nextId++,
      expr,
      visible: true,
      colorIdx: i,
    }));
    setIndepVar(preset.indepVar);
    setFunctions(newFns);
    const seed = {};
    for (const [k, val] of Object.entries(preset.defaults || {})) {
      seed[k] = { value: val, ...DEFAULT_VAR_RANGE };
    }
    setVarStore(seed);
    setXRange([-10, 10]);
    toast.success(`Loaded preset: ${preset.name}`);
  };

  const handleResetView = () => setXRange([-10, 10]);

  const handleExport = async () => {
    try {
      await plotRef.current?.downloadPNG("plotlab-graph");
      toast.success("Graph exported as PNG");
    } catch (e) {
      toast.error("Export failed");
    }
  };

  const visibleCount = compiledFns.filter((f) => f.visible && f.compiled).length;

  return (
    <div className="min-h-screen w-full flex flex-col lg:flex-row bg-background text-foreground">
      {/* SIDEBAR */}
      <aside
        data-testid="sidebar"
        className="w-full lg:w-[400px] lg:h-screen lg:overflow-y-auto thin-scroll border-b lg:border-b-0 lg:border-r border-border bg-card flex flex-col"
      >
        {/* Header */}
        <header className="px-6 pt-6 pb-4 flex items-center justify-between gap-3 sticky top-0 bg-card/80 backdrop-blur z-10 border-b border-border">
          <div className="flex items-center gap-2.5 min-w-0">
            <div className="h-8 w-8 rounded-sm bg-foreground text-background grid place-items-center shrink-0">
              <Activity className="h-4 w-4" strokeWidth={2.5} />
            </div>
            <div className="min-w-0">
              <h1 className="font-display text-lg font-black tracking-tighter leading-none">
                Plotlab
              </h1>
              <p className="text-[10px] text-muted-foreground font-mono tracking-tight mt-0.5">
                interactive graphing calculator
              </p>
            </div>
          </div>
          <ThemeToggle />
        </header>

        {/* Body */}
        <div className="px-6 py-6 flex flex-col gap-7 flex-1">
          {/* Settings row */}
          <section className="space-y-3">
            <div className="flex items-center justify-between">
              <h2 className="font-display text-xs uppercase tracking-[0.18em] text-muted-foreground">
                Workspace
              </h2>
              <PresetMenu onPick={handlePickPreset} />
            </div>
            <div className="grid grid-cols-2 gap-3">
              <label className="space-y-1.5 block">
                <span className="text-[11px] text-muted-foreground font-mono">
                  Independent var
                </span>
                <Input
                  data-testid="indep-var-input"
                  value={indepVar}
                  onChange={(e) =>
                    setIndepVar(e.target.value.trim() || "x")
                  }
                  maxLength={6}
                  className="font-mono h-9 rounded-sm"
                  aria-label="Independent variable"
                />
              </label>
              <div className="space-y-1.5">
                <span className="text-[11px] text-muted-foreground font-mono">
                  Domain
                </span>
                <div className="flex items-center gap-1.5">
                  <Input
                    data-testid="x-min-input"
                    type="number"
                    value={xRange[0]}
                    onChange={(e) => {
                      const v = parseFloat(e.target.value);
                      if (Number.isFinite(v) && v < xRange[1])
                        setXRange([v, xRange[1]]);
                    }}
                    className="font-mono h-9 rounded-sm text-xs"
                    aria-label="X minimum"
                  />
                  <span className="text-muted-foreground text-xs">→</span>
                  <Input
                    data-testid="x-max-input"
                    type="number"
                    value={xRange[1]}
                    onChange={(e) => {
                      const v = parseFloat(e.target.value);
                      if (Number.isFinite(v) && v > xRange[0])
                        setXRange([xRange[0], v]);
                    }}
                    className="font-mono h-9 rounded-sm text-xs"
                    aria-label="X maximum"
                  />
                </div>
              </div>
            </div>
          </section>

          {/* Functions */}
          <section className="space-y-3">
            <div className="flex items-center justify-between">
              <h2 className="font-display text-xs uppercase tracking-[0.18em] text-muted-foreground">
                Functions
              </h2>
              <span
                data-testid="function-count"
                className="font-mono text-[10px] text-muted-foreground"
              >
                {functions.length} total · {visibleCount} active
              </span>
            </div>
            <div className="space-y-2" data-testid="function-list">
              {compiledFns.map((fn, idx) => (
                <FunctionRow
                  key={fn.id}
                  fn={fn}
                  color={fn.color}
                  index={idx + 1}
                  onChangeExpr={handleChangeExpr}
                  onToggleVisible={handleToggleVisible}
                  onRemove={handleRemove}
                />
              ))}
              {functions.length === 0 && (
                <p
                  data-testid="empty-functions"
                  className="text-xs text-muted-foreground font-mono italic px-1"
                >
                  No functions yet — add one to start plotting.
                </p>
              )}
            </div>
            <AddFunctionButton onAdd={handleAdd} />
          </section>

          {/* Variables */}
          <section className="space-y-3" data-testid="variables-section">
            <div className="flex items-center justify-between">
              <h2 className="font-display text-xs uppercase tracking-[0.18em] text-muted-foreground">
                Parameters
              </h2>
              <span
                data-testid="variable-count"
                className="font-mono text-[10px] text-muted-foreground"
              >
                {allDetectedVars.length} detected
              </span>
            </div>
            {allDetectedVars.length === 0 ? (
              <p
                data-testid="no-variables"
                className="text-xs text-muted-foreground font-mono italic px-1"
              >
                No free variables detected. Add params like A, B, C in your
                expressions to get interactive sliders.
              </p>
            ) : (
              <div className="space-y-5">
                {allDetectedVars.map(
                  (name) =>
                    variables[name] && (
                      <SliderRow
                        key={name}
                        name={name}
                        value={variables[name].value}
                        min={variables[name].min}
                        max={variables[name].max}
                        step={variables[name].step}
                        accent={varColor(name)}
                        onChange={handleVarChange}
                        onRangeChange={handleVarRangeChange}
                      />
                    )
                )}
              </div>
            )}
          </section>
        </div>

        {/* Footer */}
        <footer className="px-6 py-4 border-t border-border flex items-center gap-2 text-[10px] text-muted-foreground font-mono">
          <Github className="h-3 w-3" />
          <span>powered by mathjs · plotly</span>
        </footer>
      </aside>

      {/* MAIN CANVAS */}
      <main className="flex-1 relative flex flex-col bg-background min-h-[60vh] lg:min-h-screen">
        {/* Top toolbar */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-border">
          <div className="flex items-baseline gap-3 min-w-0">
            <h2 className="font-display text-xl font-bold tracking-tight">
              Canvas
            </h2>
            <span className="text-[11px] font-mono text-muted-foreground hidden sm:inline">
              drag to pan · scroll to zoom · double-click to reset
            </span>
          </div>
          <div className="flex items-center gap-2">
            <Button
              data-testid="reset-view-button"
              variant="ghost"
              size="sm"
              onClick={handleResetView}
              className="rounded-sm"
            >
              Reset view
            </Button>
            <Button
              data-testid="export-png-button"
              size="sm"
              onClick={handleExport}
              className="rounded-sm gap-1.5"
            >
              <Download className="h-3.5 w-3.5" />
              Export PNG
            </Button>
          </div>
        </div>

        {/* Plot */}
        <div className="flex-1 p-3 lg:p-4">
          <div
            className="w-full h-full rounded-sm border border-border bg-card"
            style={{ minHeight: 400 }}
          >
            <PlotCanvas
              ref={plotRef}
              functions={compiledFns}
              variables={variables}
              indepVar={indepVar}
              xRange={xRange}
              theme={theme}
              onXRangeChange={setXRange}
            />
          </div>
        </div>
      </main>
    </div>
  );
}
