import type { HTMLAttributes } from "react";
import { cn } from "@/lib/cn";

type Tone = "gray" | "brand" | "red" | "amber" | "green" | "blue" | "manual";

// Wise-Inspired-design-analysis: badge-positive / badge-negative, extended
// with adjacent tones from the same palette for cases the spec doesn't name.
const TONE_CLASSES: Record<Tone, string> = {
  gray: "bg-canvas-soft text-body ring-mute/30",
  brand: "bg-primary-pale text-ink-deep ring-primary-neutral",
  green: "bg-primary-pale text-positive-deep ring-primary-neutral",
  red: "bg-negative-bg text-canvas ring-negative-bg",
  amber: "bg-warning/20 text-warning-content ring-warning/40",
  blue: "bg-accent-cyan/15 text-[#0b6478] ring-accent-cyan/30",
  // Deliberately the odd one out: every other tone above is a light fill
  // with a matching-hue ring (Wise's default badge chrome). `manual` instead
  // borrows the brand's `card-feature-dark` polarity-flip treatment (ink
  // surface, lime text) — reserved elsewhere for "promotional moments" — so
  // a self-reported entry reads as visually distinct from every status/
  // category/ad-hoc/expedite badge on the same card, not just a different
  // hue of the same light-chip pattern.
  manual: "bg-ink text-primary ring-ink",
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

function ManualEntryIcon() {
  return (
    <svg width="9" height="9" viewBox="0 0 24 24" fill="none" aria-hidden>
      <path
        d="M4 20h4L18.5 9.5a2.121 2.121 0 10-3-3L5 17v3z"
        stroke="currentColor"
        strokeWidth="2.5"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

/** The "self-reported, not live-tracked" tag — one shared implementation for
 * the board card, task detail panel, and standalone task page so the icon +
 * copy + tone never drift between the three places it appears. */
export function ManualEntryBadge({ className }: { className?: string }) {
  return (
    <Badge tone="manual" className={cn("gap-1", className)} title="Time was logged manually, not tracked live">
      <ManualEntryIcon />
      Manually logged
    </Badge>
  );
}
