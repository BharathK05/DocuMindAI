import Link from "next/link";

/** Wordmark: an ink "page" with a highlighter stripe, then the name. */
export function Logo({ href = "/" }: { href?: string }) {
  return (
    <Link href={href} className="group inline-flex items-center gap-2.5">
      <svg viewBox="0 0 24 24" className="size-7" aria-hidden>
        <rect x="4" y="2.5" width="16" height="19" rx="3.5" className="fill-ink" />
        <rect x="7.5" y="8" width="9" height="3" rx="1.2" className="fill-marker" />
        <rect x="7.5" y="13" width="6" height="1.6" rx="0.8" className="fill-paper" opacity="0.7" />
        <rect
          x="7.5"
          y="16"
          width="7.5"
          height="1.6"
          rx="0.8"
          className="fill-paper"
          opacity="0.7"
        />
      </svg>
      <span className="font-display text-xl tracking-tight">
        DocuMind<span className="text-muted"> AI</span>
      </span>
    </Link>
  );
}
