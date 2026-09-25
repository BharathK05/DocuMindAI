"use client";

import type { AccountFigures, ContextFigures } from "@/lib/types";

const compact = new Intl.NumberFormat("en", { notation: "compact", maximumFractionDigits: 1 });

function tone(fraction: number): string {
  if (fraction >= 0.9) return "bg-danger";
  if (fraction >= 0.7) return "bg-warn";
  return "bg-accent";
}

function Bar({ label, fraction, detail }: { label: string; fraction: number; detail: string }) {
  const pct = Math.round(Math.min(1, Math.max(0, fraction)) * 100);
  return (
    <div className="group relative flex items-center gap-2" title={detail}>
      <span className="hidden text-xs text-muted lg:inline">{label}</span>
      <div
        role="meter"
        aria-label={label}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={pct}
        aria-valuetext={detail}
        className="h-1.5 w-14 overflow-hidden rounded-full bg-ink/10 sm:w-20"
      >
        <div
          className={`h-full rounded-full transition-[width] duration-500 ${tone(fraction)}`}
          style={{ width: `${Math.max(pct, fraction > 0 ? 3 : 0)}%` }}
        />
      </div>
      <span className="w-8 font-mono text-[0.7rem] text-muted tabular-nums">{pct}%</span>
    </div>
  );
}

/** The context-window and daily-quota bars from the API's usage figures. */
export function UsageBars({
  context,
  account,
}: {
  context: ContextFigures | null;
  account: AccountFigures | null;
}) {
  if (!account) return null;
  const resets = new Date(account.reset_at).toLocaleTimeString([], {
    hour: "numeric",
    minute: "2-digit",
  });
  return (
    <div className="flex items-center gap-3 sm:gap-5">
      {context && (
        <Bar
          label="Context"
          fraction={context.fraction}
          detail={`This chat uses ${compact.format(context.tokens)} of ${compact.format(context.limit)} tokens of context`}
        />
      )}
      <Bar
        label="Today"
        fraction={account.tokens_used_today / account.daily_quota}
        detail={`${compact.format(account.tokens_used_today)} of ${compact.format(account.daily_quota)} tokens used today; resets at ${resets}`}
      />
    </div>
  );
}
