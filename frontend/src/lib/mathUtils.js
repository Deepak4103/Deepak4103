import { parse, create, all } from "mathjs";

const math = create(all);

// Names that should NOT be treated as user variables
const RESERVED_CONSTANTS = new Set([
  "pi", "e", "tau", "phi", "Infinity", "NaN", "true", "false", "i",
  "LN2", "LN10", "LOG2E", "LOG10E", "SQRT1_2", "SQRT2",
]);

/**
 * Extract free variables from an expression string, excluding:
 *  - The independent variable (e.g. "x")
 *  - Mathematical constants (pi, e, ...)
 *  - Function names (sin, cos, log, ...)
 *
 * Returns sorted array of unique symbol names. Throws on parse error.
 */
export function extractVariables(expression, independentVar = "x") {
  const node = parse(expression);
  const vars = new Set();

  node.traverse((n, _path, parent) => {
    if (!n.isSymbolNode) return;
    // Skip function-name symbol nodes (the `fn` of a FunctionNode)
    if (parent && parent.isFunctionNode && parent.fn === n) return;
    const name = n.name;
    if (name === independentVar) return;
    if (RESERVED_CONSTANTS.has(name)) return;
    // Skip names that resolve to mathjs functions/constants in scope
    const resolved = math[name];
    if (typeof resolved === "function") return;
    vars.add(name);
  });

  return Array.from(vars).sort();
}

/**
 * Compile an expression once; returns { ok, compiled, error }.
 */
export function safeCompile(expression) {
  try {
    const compiled = parse(expression).compile();
    return { ok: true, compiled, error: null };
  } catch (err) {
    return { ok: false, compiled: null, error: err.message || String(err) };
  }
}

/**
 * Sample a compiled expression over [xMin, xMax] with `samples` points,
 * substituting the independent variable and variable scope values.
 * Returns { xs, ys } where invalid points become null (so Plotly leaves gaps).
 */
export function sampleFunction(compiled, indepVar, xMin, xMax, samples, scope) {
  const xs = new Array(samples);
  const ys = new Array(samples);
  const step = (xMax - xMin) / (samples - 1);
  const localScope = { ...scope };
  for (let i = 0; i < samples; i++) {
    const x = xMin + i * step;
    localScope[indepVar] = x;
    xs[i] = x;
    try {
      const v = compiled.evaluate(localScope);
      if (typeof v === "number" && Number.isFinite(v)) {
        ys[i] = v;
      } else if (v && typeof v === "object" && "re" in v) {
        // mathjs Complex — show only real-valued points
        ys[i] = Math.abs(v.im) < 1e-9 ? v.re : null;
      } else {
        ys[i] = null;
      }
    } catch {
      ys[i] = null;
    }
  }
  return { xs, ys };
}
