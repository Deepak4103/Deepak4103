# Plotlab — Interactive Graphing Calculator

## Problem Statement
Build a single-page interactive graphing calculator web app for classroom demos: users type math expressions, the app auto-detects free variables and renders interactive sliders, and the plot updates in real-time. Built with React + mathjs + Plotly + Tailwind/shadcn.

## User Choices
- Plotting library: Plotly.js (basic-dist-min for bundle size)
- Theme: Light + Dark with toggle (system preference initially)
- Extras: Export PNG, Preset functions library
- Custom independent variable allowed (default `x`, can be `t`, `theta`, etc.)

## Architecture
- Pure frontend SPA — no backend involvement.
- Entry: `App.js → /pages/GraphingCalculator.jsx`
- State (Calculator):
  - `functions`: `[{id, expr, visible, colorIdx}]`
  - `varStore`: `{name: {value, min, max, step}}` — preserves user-set ranges across edits
  - `indepVar`, `xRange`, `theme`
- `compiledFns` is `useMemo`-derived: compiles each expression with mathjs and detects free variables (excluding constants, function names, and the chosen independent var).
- `variables` (render-time map) merges detected vars with stored configs or defaults.
- `PlotCanvas` uses Plotly factory pattern with `plotly.js-basic-dist-min` for fast compile.
- Theme persisted in localStorage; classlist `.dark` toggled on `<html>`.

## Implemented (Feb 2026 — initial release)
- Function list with inline add / remove / show-hide / per-trace color swatch.
- Live `mathjs` parsing with friendly inline error display per row.
- Dynamic variable detection → auto-generated colored sliders per variable.
- Per-slider editable min/max boxes (commit on blur/Enter).
- Plotly canvas with pan, scroll-zoom, hover spike lines, scatter line traces.
- Custom independent variable (defaults to `x`).
- Editable domain (xMin → xMax) inputs.
- Light/dark theme toggle (persists, system-default first load).
- Six curated presets (sine family, quadratic, damped oscillator, gaussian, trig trio, logistic).
- Export PNG via Plotly downloadImage (1600×1000 @ 2× scale).
- Reset view button.
- Full data-testid coverage (used by test agent — 15/15 features pass).

## Files
- `/app/frontend/src/pages/GraphingCalculator.jsx` — orchestration & state.
- `/app/frontend/src/components/PlotCanvas.jsx` — Plotly wrapper.
- `/app/frontend/src/components/FunctionRow.jsx`
- `/app/frontend/src/components/SliderRow.jsx`
- `/app/frontend/src/components/ThemeToggle.jsx`
- `/app/frontend/src/components/PresetMenu.jsx`
- `/app/frontend/src/lib/mathUtils.js` — variable extraction + safe compile + sampler.
- `/app/frontend/src/lib/colors.js` — trace palette.
- `/app/frontend/src/lib/presets.js`
- `/app/frontend/src/hooks/useTheme.js`

## Backlog (post-v1)
- P1: Persist sessions to localStorage (functions, sliders, theme, indep var).
- P1: Shareable URLs (encode state in hash) for classroom links.
- P1: Inline LaTeX rendering of typed expressions (KaTeX).
- P2: Tangent / derivative / integral overlay tools.
- P2: Touch-friendly mobile gesture polish.
- P2: Trace style options (dashed, point markers, fill under curve).
- P2: Per-function color picker.
