import { Eye, EyeOff, Trash2, AlertCircle } from "lucide-react";
import { Button } from "@/components/ui/button";

/**
 * A single editable function row with color swatch, visibility, and remove.
 * Props:
 *  - fn: { id, expr, visible, colorIdx, error }
 *  - color: hex string for the color swatch / accent
 *  - index: int (display label)
 *  - onChangeExpr(id, expr)
 *  - onToggleVisible(id)
 *  - onRemove(id)
 */
export default function FunctionRow({
  fn,
  color,
  index,
  onChangeExpr,
  onToggleVisible,
  onRemove,
}) {
  return (
    <div
      data-testid={`function-row-${fn.id}`}
      className="group rounded-sm border border-border bg-card transition-colors"
    >
      <div className="flex items-stretch">
        {/* Color swatch */}
        <div
          className="w-1.5 rounded-l-sm shrink-0"
          style={{ backgroundColor: fn.visible ? color : "transparent", border: !fn.visible ? `1px dashed ${color}` : undefined }}
          aria-hidden
        />
        <div className="flex-1 min-w-0 flex items-center gap-2 px-2.5 py-2">
          <span
            className="font-mono text-[10px] text-muted-foreground select-none"
            aria-hidden
          >
            f{index}
          </span>
          <input
            data-testid={`function-input-${fn.id}`}
            type="text"
            spellCheck={false}
            value={fn.expr}
            onChange={(e) => onChangeExpr(fn.id, e.target.value)}
            placeholder="e.g. A * sin(B * x + C)"
            className="font-mono text-sm flex-1 bg-transparent outline-none placeholder:text-muted-foreground/60 min-w-0"
            aria-label={`Function ${index} expression`}
          />
          <button
            data-testid={`toggle-visible-${fn.id}`}
            onClick={() => onToggleVisible(fn.id)}
            className="text-muted-foreground hover:text-foreground transition-colors p-1 rounded-sm"
            aria-label={fn.visible ? "Hide function" : "Show function"}
            title={fn.visible ? "Hide" : "Show"}
          >
            {fn.visible ? <Eye className="h-4 w-4" /> : <EyeOff className="h-4 w-4" />}
          </button>
          <button
            data-testid={`remove-function-${fn.id}`}
            onClick={() => onRemove(fn.id)}
            className="text-muted-foreground hover:text-destructive transition-colors p-1 rounded-sm"
            aria-label="Remove function"
            title="Remove"
          >
            <Trash2 className="h-4 w-4" />
          </button>
        </div>
      </div>
      {fn.error && (
        <div
          data-testid={`function-error-${fn.id}`}
          className="flex items-start gap-1.5 px-3 pb-2 pt-0 text-[11px] text-destructive font-mono"
        >
          <AlertCircle className="h-3 w-3 mt-[1px] shrink-0" />
          <span className="break-words">{fn.error}</span>
        </div>
      )}
    </div>
  );
}

export function AddFunctionButton({ onAdd }) {
  return (
    <Button
      data-testid="add-function-button"
      variant="outline"
      size="sm"
      onClick={onAdd}
      className="rounded-sm font-medium"
    >
      + Add function
    </Button>
  );
}
