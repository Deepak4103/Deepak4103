import * as SliderPrimitive from "@radix-ui/react-slider";
import { useState } from "react";

/**
 * A single slider row tied to a variable name with an accent color.
 * Props:
 *  - name: string
 *  - value, min, max, step: numbers
 *  - accent: hex color
 *  - onChange(name, value)
 *  - onRangeChange(name, { min, max, step })
 */
export default function SliderRow({
  name,
  value,
  min,
  max,
  step,
  accent,
  onChange,
  onRangeChange,
}) {
  // Local string state so users can type freely without re-clamping mid-edit.
  // Resync to props when external value changes (React docs pattern instead of useEffect).
  const [minStr, setMinStr] = useState(String(min));
  const [maxStr, setMaxStr] = useState(String(max));
  const [prevMin, setPrevMin] = useState(min);
  const [prevMax, setPrevMax] = useState(max);
  if (prevMin !== min) {
    setPrevMin(min);
    setMinStr(String(min));
  }
  if (prevMax !== max) {
    setPrevMax(max);
    setMaxStr(String(max));
  }

  const commitMin = () => {
    const v = parseFloat(minStr);
    if (Number.isFinite(v) && v < max) onRangeChange(name, { min: v });
    else setMinStr(String(min));
  };
  const commitMax = () => {
    const v = parseFloat(maxStr);
    if (Number.isFinite(v) && v > min) onRangeChange(name, { max: v });
    else setMaxStr(String(max));
  };

  const accentStyle = { "--accent": accent };

  return (
    <div
      data-testid={`variable-slider-${name}`}
      className="space-y-1.5"
      style={accentStyle}
    >
      <div className="flex items-baseline justify-between gap-2">
        <span
          className="font-mono text-sm font-medium"
          style={{ color: accent }}
        >
          {name}
        </span>
        <span
          data-testid={`variable-value-${name}`}
          className="font-mono text-xs text-muted-foreground tabular-nums"
        >
          {Number.isInteger(value) ? value.toFixed(0) : value.toFixed(2)}
        </span>
      </div>

      <SliderPrimitive.Root
        data-testid={`slider-root-${name}`}
        value={[value]}
        min={min}
        max={max}
        step={step}
        onValueChange={(vals) => onChange(name, vals[0])}
        className="relative flex w-full touch-none select-none items-center h-5"
      >
        <SliderPrimitive.Track
          className="relative h-1 w-full grow overflow-hidden rounded-full"
          style={{ backgroundColor: `${accent}33` }}
        >
          <SliderPrimitive.Range
            className="absolute h-full"
            style={{ backgroundColor: accent }}
          />
        </SliderPrimitive.Track>
        <SliderPrimitive.Thumb
          aria-label={`${name} value`}
          className="block h-4 w-4 rounded-full bg-background shadow transition-transform hover:scale-110 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-1"
          style={{ border: `2px solid ${accent}` }}
        />
      </SliderPrimitive.Root>

      <div className="flex items-center justify-between gap-2 text-[10px] text-muted-foreground">
        <input
          data-testid={`slider-min-${name}`}
          type="number"
          className="mini-num"
          value={minStr}
          onChange={(e) => setMinStr(e.target.value)}
          onBlur={commitMin}
          onKeyDown={(e) => e.key === "Enter" && e.currentTarget.blur()}
          aria-label={`${name} minimum`}
        />
        <span className="font-mono">step {step}</span>
        <input
          data-testid={`slider-max-${name}`}
          type="number"
          className="mini-num text-right"
          value={maxStr}
          onChange={(e) => setMaxStr(e.target.value)}
          onBlur={commitMax}
          onKeyDown={(e) => e.key === "Enter" && e.currentTarget.blur()}
          aria-label={`${name} maximum`}
        />
      </div>
    </div>
  );
}
