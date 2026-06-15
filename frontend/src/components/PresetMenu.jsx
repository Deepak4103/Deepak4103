import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Button } from "@/components/ui/button";
import { Sparkles } from "lucide-react";
import { PRESETS } from "@/lib/presets";

export default function PresetMenu({ onPick }) {
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button
          data-testid="presets-trigger"
          variant="outline"
          size="sm"
          className="rounded-sm gap-1.5"
        >
          <Sparkles className="h-3.5 w-3.5" />
          Presets
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent
        align="end"
        className="w-72 rounded-sm"
        data-testid="presets-menu"
      >
        <DropdownMenuLabel className="font-display tracking-tight">
          Demo presets
        </DropdownMenuLabel>
        <DropdownMenuSeparator />
        {PRESETS.map((p) => (
          <DropdownMenuItem
            key={p.id}
            data-testid={`preset-${p.id}`}
            onClick={() => onPick(p)}
            className="flex-col items-start gap-0.5 py-2 cursor-pointer"
          >
            <span className="text-sm font-medium">{p.name}</span>
            <span className="text-[11px] text-muted-foreground font-mono">
              {p.description}
            </span>
          </DropdownMenuItem>
        ))}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
