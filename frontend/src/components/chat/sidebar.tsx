"use client";

import { AnimatePresence, LazyMotion, domAnimation, m } from "motion/react";
import { Files, LogOut, PanelLeftClose, SquarePen, Trash2 } from "lucide-react";
import { useState } from "react";

import { Logo } from "@/components/ui/logo";
import { ThemeToggle } from "@/components/ui/theme-toggle";
import type { Conversation } from "@/lib/types";

const DAY = 24 * 60 * 60 * 1000;

function groupByDate(conversations: Conversation[]): [string, Conversation[]][] {
  const startOfToday = new Date().setHours(0, 0, 0, 0);
  const groups = new Map<string, Conversation[]>();
  for (const c of conversations) {
    const t = new Date(c.updated_at).getTime();
    const label =
      t >= startOfToday
        ? "Today"
        : t >= startOfToday - DAY
          ? "Yesterday"
          : t >= startOfToday - 7 * DAY
            ? "Previous 7 days"
            : "Older";
    groups.set(label, [...(groups.get(label) ?? []), c]);
  }
  return [...groups];
}

function ChatItem({
  conversation,
  active,
  onSelect,
  onDelete,
}: {
  conversation: Conversation;
  active: boolean;
  onSelect: () => void;
  onDelete: () => void;
}) {
  const [confirming, setConfirming] = useState(false);
  return (
    <li className="group relative">
      <button
        type="button"
        onClick={onSelect}
        aria-current={active ? "page" : undefined}
        className={`block w-full truncate rounded-xl py-2 pr-9 pl-3 text-left text-sm transition-colors ${
          active ? "bg-ink/8 text-ink" : "text-ink/80 hover:bg-ink/5"
        }`}
      >
        {/* The title arrives after the first answer; fade it in like it was just written. */}
        <AnimatePresence mode="wait" initial={false}>
          <m.span
            key={conversation.title}
            initial={{ opacity: 0, x: -4 }}
            animate={{ opacity: 1, x: 0 }}
            transition={{ duration: 0.35 }}
            className="block truncate"
          >
            {conversation.title}
          </m.span>
        </AnimatePresence>
      </button>
      {confirming ? (
        <div className="absolute inset-y-0 right-1 flex items-center gap-1 rounded-lg bg-paper-deep pl-2">
          <button
            type="button"
            onClick={onDelete}
            className="rounded-md bg-danger px-2 py-1 text-xs font-medium text-white"
          >
            Delete
          </button>
          <button
            type="button"
            onClick={() => setConfirming(false)}
            className="rounded-md px-2 py-1 text-xs text-muted hover:text-ink"
          >
            Cancel
          </button>
        </div>
      ) : (
        <button
          type="button"
          onClick={() => setConfirming(true)}
          aria-label={`Delete chat: ${conversation.title}`}
          className="absolute top-1/2 right-1.5 hidden -translate-y-1/2 rounded-lg p-1.5 text-muted group-focus-within:block group-hover:block hover:bg-ink/5 hover:text-danger"
        >
          <Trash2 className="size-3.5" aria-hidden />
        </button>
      )}
    </li>
  );
}

export function Sidebar({
  conversations,
  activeId,
  userLabel,
  loading,
  onNewChat,
  onSelect,
  onDelete,
  onOpenDocuments,
  onSignOut,
  onClose,
}: {
  conversations: Conversation[];
  activeId: string | null;
  userLabel: string;
  loading: boolean;
  onNewChat: () => void;
  onSelect: (id: string) => void;
  onDelete: (id: string) => void;
  onOpenDocuments: () => void;
  onSignOut: () => void;
  onClose: () => void;
}) {
  return (
    <LazyMotion features={domAnimation} strict>
      <nav aria-label="Chats" className="flex h-full flex-col bg-paper-deep">
        <div className="flex items-center justify-between px-4 pt-4 pb-3">
          <Logo href="/" />
          <button
            type="button"
            onClick={onClose}
            aria-label="Close sidebar"
            className="rounded-lg p-1.5 text-muted hover:bg-ink/5 hover:text-ink"
          >
            <PanelLeftClose className="size-4.5" aria-hidden />
          </button>
        </div>
        <div className="space-y-0.5 px-2">
          <button
            type="button"
            onClick={onNewChat}
            className="flex w-full items-center gap-2.5 rounded-xl px-3 py-2 text-sm font-medium hover:bg-ink/5"
          >
            <SquarePen className="size-4 text-accent" aria-hidden /> New chat
          </button>
          <button
            type="button"
            onClick={onOpenDocuments}
            className="flex w-full items-center gap-2.5 rounded-xl px-3 py-2 text-sm hover:bg-ink/5"
          >
            <Files className="size-4 text-muted" aria-hidden /> Your documents
          </button>
        </div>

        <div className="mt-4 min-h-0 flex-1 overflow-y-auto px-2 pb-4">
          {loading ? (
            <ul className="space-y-2 px-3 pt-2" aria-label="Loading chats">
              {[70, 55, 80, 60].map((w) => (
                <li
                  key={w}
                  className="h-3 animate-pulse rounded bg-ink/8"
                  style={{ width: `${w}%` }}
                />
              ))}
            </ul>
          ) : conversations.length === 0 ? (
            <p className="px-3 text-sm text-muted">
              Your chats appear here, named after what you asked.
            </p>
          ) : (
            groupByDate(conversations).map(([label, items]) => (
              <section key={label} className="mb-4">
                <h2 className="px-3 pb-1 text-xs text-muted">{label}</h2>
                <ul className="space-y-0.5">
                  {items.map((c) => (
                    <ChatItem
                      key={c.conversation_id}
                      conversation={c}
                      active={c.conversation_id === activeId}
                      onSelect={() => onSelect(c.conversation_id)}
                      onDelete={() => onDelete(c.conversation_id)}
                    />
                  ))}
                </ul>
              </section>
            ))
          )}
        </div>

        <div className="flex items-center gap-2 border-t border-line px-3 py-3">
          <span
            className="flex size-8 shrink-0 items-center justify-center rounded-full bg-accent-soft font-medium text-accent uppercase"
            aria-hidden
          >
            {userLabel.slice(0, 1)}
          </span>
          <span className="min-w-0 flex-1 truncate text-sm" title={userLabel}>
            {userLabel}
          </span>
          <ThemeToggle />
          <button
            type="button"
            onClick={onSignOut}
            aria-label="Sign out"
            title="Sign out"
            className="inline-flex size-9 items-center justify-center rounded-full text-muted hover:bg-ink/5 hover:text-ink"
          >
            <LogOut className="size-4" aria-hidden />
          </button>
        </div>
      </nav>
    </LazyMotion>
  );
}
