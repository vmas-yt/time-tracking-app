"use client";

import { useEffect } from "react";
import type { SessionToast } from "@/board/session";

interface ToastProps {
  toast: SessionToast | null;
  dismissToast: () => void;
}

// Floating overlay feedback for rejected actions (invalid drag target, timer
// guard failure, a real 403/409 from the API, etc.) — disabled/blocked
// actions must give a visible reason rather than a silent no-op. A toast is
// one of the few places in this design system a shadow is legitimate: it
// isn't an in-flow page card (whose elevation model is pure surface
// contrast) — it's literally floating above the page. Takes props (rather
// than reading `useBoard()` directly) so it's reusable on the standalone
// task detail page, which has its own `useTimerSession` and no `BoardProvider`.
export function Toast({ toast, dismissToast }: ToastProps) {
  useEffect(() => {
    if (!toast) return;
    const id = setTimeout(dismissToast, 4200);
    return () => clearTimeout(id);
  }, [toast, dismissToast]);

  if (!toast) return null;

  return (
    <div
      role="status"
      aria-live="polite"
      key={toast.id}
      className="fixed bottom-6 left-1/2 z-50 w-[min(90vw,420px)] -translate-x-1/2 animate-[toast-in_0.2s_ease-out]"
    >
      <div className="flex items-start gap-3 rounded-xl bg-ink px-4 py-3 text-sm text-canvas shadow-lg shadow-ink/20">
        <span className="mt-0.5 flex h-4 w-4 shrink-0 items-center justify-center rounded-full bg-negative text-[10px] font-bold text-canvas">
          !
        </span>
        <span className="flex-1 leading-snug">{toast.message}</span>
        <button
          type="button"
          onClick={dismissToast}
          className="text-canvas-soft/70 hover:text-canvas"
          aria-label="Dismiss"
        >
          ✕
        </button>
      </div>
      <style jsx global>{`
        @keyframes toast-in {
          from {
            opacity: 0;
            transform: translate(-50%, 8px);
          }
          to {
            opacity: 1;
            transform: translate(-50%, 0);
          }
        }
      `}</style>
    </div>
  );
}
