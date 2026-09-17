import type { HTMLAttributes } from "react";
import { cn } from "@/lib/cn";

type Tone = "gray" | "brand" | "red" | "amber" | "green" | "blue";

// Wise-Inspired-design-analysis: badge-positive / badge-negative, extended
// with adjacent tones from the same palette for cases the spec doesn't name.
const TONE_CLASSES: Record<Tone, string> = {
  gray: "bg-canvas-soft text-body ring-mute/30",
  brand: "bg-primary-pale text-ink-deep ring-primary-neutral",
  green: "bg-primary-pale text-positive-deep ring-primary-neutral",
  red: "bg-negative-bg text-canvas ring-negative-bg",
  amber: "bg-warning/20 text-warning-content ring-warning/40",
  blue: "bg-accent-cyan/15 text-[#0b6478] ring-accent-cyan/30",
};

interface BadgeProps extends HTMLAttributes<HTMLSpanElement> {
  tone?: Tone;
}

export function Badge({ className, tone = "gray", ...props }: BadgeProps) {
  return (
    <span
      className={cn(
        "inline-flex items-center rounded-full px-2 py-0.5 text-[11px] font-semibold ring-1 ring-inset",
        TONE_CLASSES[tone],
        className
      )}
      {...props}
    />
  );
}
