"use client";

import { FileText } from "lucide-react";
import { useEffect, useId, useRef, useState } from "react";

export interface CitationInfo {
  n: number;
  filename: string;
  page: number;
  snippet?: string;
}

/**
 * An inline "[n]" citation, placed right where the answer makes the claim. Hover, focus or tap
 * shows which document and page it came from, plus the quoted passage.
 */
export function CitationChip({ n, filename, page, snippet }: CitationInfo) {
  const [open, setOpen] = useState(false);
  const [align, setAlign] = useState<"center" | "start" | "end">("center");
  const id = useId();
  const ref = useRef<HTMLSpanElement>(null);

  useEffect(() => {
    if (!open) return;
    const close = (e: Event) => {
      if (
        e instanceof KeyboardEvent ? e.key === "Escape" : !ref.current?.contains(e.target as Node)
      ) {
        setOpen(false);
      }
    };
    document.addEventListener("keydown", close);
    document.addEventListener("pointerdown", close);
    return () => {
      document.removeEventListener("keydown", close);
      document.removeEventListener("pointerdown", close);
    };
  }, [open]);

  // Keep the card on screen when the chip sits near the left or right edge.
  function show() {
    const rect = ref.current?.getBoundingClientRect();
    const room = 160; // half the card's width, plus a margin
    if (rect) {
      setAlign(
        rect.left < room ? "start" : window.innerWidth - rect.right < room ? "end" : "center",
      );
    }
    setOpen(true);
  }

  return (
    <span
      ref={ref}
      className="relative inline-block align-baseline"
      onMouseEnter={show}
      onMouseLeave={() => setOpen(false)}
    >
      <button
        type="button"
        aria-describedby={open ? id : undefined}
        aria-label={`Source ${n}: ${filename}, page ${page}`}
        onClick={show}
        onFocus={show}
        onBlur={() => setOpen(false)}
        className="mx-0.5 inline-flex h-[1.35em] min-w-[1.35em] -translate-y-px items-center justify-center rounded-md bg-marker-soft px-1 font-mono text-[0.7em] leading-none text-ink ring-1 ring-marker/60 transition-colors hover:bg-marker hover:text-on-marker"
      >
        {n}
      </button>
      {open && (
        <span
          id={id}
          role="tooltip"
          className={`absolute bottom-full z-30 mb-2 block w-72 max-w-[80vw] rounded-2xl ${
            align === "center"
              ? "left-1/2 -translate-x-1/2"
              : align === "start"
                ? "left-0"
                : "right-0"
          } border border-line bg-card p-3.5 text-left font-sans text-sm leading-snug text-ink shadow-xl shadow-ink/10`}
        >
          <span className="flex items-center gap-2 font-medium">
            <FileText className="size-4 shrink-0 text-accent" aria-hidden />
            <span className="truncate">{filename}</span>
          </span>
          <span className="mt-0.5 block font-mono text-xs text-muted">page {page}</span>
          {snippet && (
            <span className="mt-2 line-clamp-5 block border-l-2 border-marker pl-2.5 text-[0.8125rem] text-muted">
              {snippet}
            </span>
          )}
        </span>
      )}
    </span>
  );
}
