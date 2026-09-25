"use client";

import { AnimatePresence, LazyMotion, MotionConfig, domAnimation, m } from "motion/react";
import { Check, FileText, LoaderCircle, UploadCloud } from "lucide-react";
import { useEffect, useState } from "react";

type Status = "pending" | "processing" | "ready";

// The real statuses a document moves through after upload (see the API's DocumentStatus).
const FILES: { name: string; pages: number; start: number }[] = [
  { name: "NIST.CSWP.29.pdf", pages: 32, start: 2 },
  { name: "NIST.SP.800-61r3.pdf", pages: 48, start: 1 },
  { name: "NIST.SP.800-63b.pdf", pages: 80, start: 0 },
];
const ORDER: Status[] = ["pending", "processing", "ready"];

function StatusChip({ status }: { status: Status }) {
  const styles: Record<Status, string> = {
    pending: "bg-ink/5 text-muted",
    processing: "bg-accent-soft text-accent",
    ready: "bg-ready/12 text-ready",
  };
  return (
    <m.span
      key={status}
      initial={{ opacity: 0, scale: 0.9 }}
      animate={{ opacity: 1, scale: 1 }}
      exit={{ opacity: 0, scale: 0.9 }}
      transition={{ duration: 0.25 }}
      className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-medium ${styles[status]}`}
    >
      {status === "processing" && <LoaderCircle className="size-3 animate-spin" aria-hidden />}
      {status === "ready" && <Check className="size-3" aria-hidden />}
      {status}
    </m.span>
  );
}

export function UploadDemo() {
  const [tick, setTick] = useState(0);
  useEffect(() => {
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;
    const timer = window.setInterval(() => setTick((t) => (t + 1) % 5), 1400);
    return () => window.clearInterval(timer);
  }, []);

  return (
    <LazyMotion features={domAnimation} strict>
      <MotionConfig reducedMotion="user">
        <div className="flex flex-col items-center justify-center gap-2 rounded-2xl border-2 border-dashed border-line-strong px-4 py-6 text-center">
          <UploadCloud className="size-6 text-muted" aria-hidden />
          <p className="text-sm text-muted">Drop PDFs here, up to 20&nbsp;MB each</p>
        </div>
        <ul className="mt-4 space-y-2" aria-label="Example upload queue">
          {FILES.map((f) => {
            const status = ORDER[Math.min(2, Math.max(0, tick - f.start + 1))] ?? "pending";
            return (
              <li
                key={f.name}
                className="flex items-center gap-3 rounded-xl bg-paper px-3 py-2.5 text-sm"
              >
                <FileText className="size-4 shrink-0 text-muted" aria-hidden />
                <span className="min-w-0 flex-1 truncate">{f.name}</span>
                <span className="hidden font-mono text-xs text-muted sm:inline">{f.pages} pp</span>
                <AnimatePresence mode="wait" initial={false}>
                  <StatusChip status={status} />
                </AnimatePresence>
              </li>
            );
          })}
        </ul>
      </MotionConfig>
    </LazyMotion>
  );
}
