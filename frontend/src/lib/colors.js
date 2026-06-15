// Curated, high-contrast palette suitable for projectors (light + dark backgrounds)
export const TRACE_COLORS = [
  "#2563EB", // blue
  "#E11D48", // rose
  "#059669", // emerald
  "#D97706", // amber
  "#9333EA", // violet
  "#0891B2", // cyan
  "#DB2777", // pink
  "#65A30D", // lime
];

export function colorForIndex(i) {
  return TRACE_COLORS[i % TRACE_COLORS.length];
}
