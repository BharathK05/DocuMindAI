"use client";

import { LazyMotion, MotionConfig, domAnimation, m } from "motion/react";
import type { ReactNode } from "react";

/** Fades and lifts its children into view once. Honours prefers-reduced-motion. */
export function Reveal({
  children,
  className,
  delay = 0,
}: {
  children: ReactNode;
  className?: string;
  delay?: number;
}) {
  return (
    <LazyMotion features={domAnimation} strict>
      <MotionConfig reducedMotion="user">
        <m.div
          className={className}
          initial={{ opacity: 0, y: 24 }}
          whileInView={{ opacity: 1, y: 0 }}
          viewport={{ once: true, amount: 0.25 }}
          transition={{ duration: 0.6, ease: [0.2, 0.7, 0.2, 1], delay }}
        >
          {children}
        </m.div>
      </MotionConfig>
    </LazyMotion>
  );
}
