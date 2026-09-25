"use client";

import { useEffect, useRef, type ElementType } from "react";

interface SplitTextProps {
  text: string;
  as?: ElementType;
  className?: string;
  /** Words (exact match) set in italic accent, e.g. "finally". */
  emphasis?: string[];
  /** Animate on page load (hero) instead of when scrolled into view. */
  immediate?: boolean;
}

/**
 * A headline revealed letter by letter.
 *
 * Accessibility: screen readers get the whole sentence from a visually hidden copy; the
 * animated letters are aria-hidden, so they aren't read out one by one. The animation is pure
 * CSS and is switched off by prefers-reduced-motion (see globals.css).
 */
export function SplitText({
  text,
  as: Tag = "h2",
  className,
  emphasis = [],
  immediate,
}: SplitTextProps) {
  const ref = useRef<HTMLElement>(null);

  useEffect(() => {
    const el = ref.current;
    if (immediate || !el) return;
    const rect = el.getBoundingClientRect();
    if (rect.top < window.innerHeight) {
      el.dataset.split = "play"; // already on screen when the page loaded
      return;
    }
    el.dataset.split = "armed";
    const observer = new IntersectionObserver(
      ([entry]) => {
        if (entry.isIntersecting) {
          el.dataset.split = "play";
          observer.disconnect();
        }
      },
      { threshold: 0.4 },
    );
    observer.observe(el);
    return () => observer.disconnect();
  }, [immediate]);

  let index = 0;
  const words = text.split(" ");
  return (
    <Tag ref={ref} className={className} data-split={immediate ? "play" : undefined}>
      <span className="sr-only">{text}</span>
      <span aria-hidden>
        {words.map((word, w) => {
          const accent = emphasis.includes(word.replace(/[.,!?]$/, ""));
          return (
            <span key={w}>
              <span
                className={`inline-block whitespace-nowrap ${accent ? "italic text-accent" : ""}`}
              >
                {[...word].map((ch, c) => (
                  <span key={c} className="split-letter" style={{ ["--i" as string]: index++ }}>
                    {ch}
                  </span>
                ))}
              </span>
              {w < words.length - 1 ? " " : null}
            </span>
          );
        })}
      </span>
    </Tag>
  );
}
