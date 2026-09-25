"use client";

import { AlertCircle, Check, Copy, Download, RotateCcw } from "lucide-react";
import { memo, useState } from "react";
import ReactMarkdown, { type Components } from "react-markdown";
import remarkGfm from "remark-gfm";

import { CitationChip } from "@/components/ui/citation-chip";
import { answerToMarkdown, remarkCitations } from "@/lib/citations";
import type { Citation } from "@/lib/types";

export interface UiMessage {
  key: string;
  role: "user" | "assistant";
  content: string;
  citations: Citation[];
  status: "done" | "streaming" | "stopped" | "error";
  error?: string;
  notice?: string | null; // e.g. "older messages were summarized"
}

function markdownComponents(citations: Citation[]): Components {
  const bySource = new Map(citations.map((c) => [c.source_id, c]));
  return {
    "cite-ref": ({ n }: { n?: string }) => {
      const c = bySource.get(Number(n));
      if (!c) return <sup className="font-mono text-xs text-muted">[{n}]</sup>;
      return (
        <CitationChip n={c.source_id} filename={c.filename} page={c.page} snippet={c.snippet} />
      );
    },
    a: ({ href, children }) => (
      <a href={href} target="_blank" rel="noopener noreferrer">
        {children}
      </a>
    ),
  } as Components;
}

/** The model's answer as Markdown, with "[n]" markers turned into inline citation chips. */
export const AnswerText = memo(function AnswerText({
  content,
  citations,
}: {
  content: string;
  citations: Citation[];
}) {
  return (
    <div className="answer font-display text-[1.0625rem] leading-[1.7]">
      <ReactMarkdown
        remarkPlugins={[remarkGfm, remarkCitations]}
        components={markdownComponents(citations)}
      >
        {content}
      </ReactMarkdown>
    </div>
  );
});

function IconButton({
  label,
  onClick,
  children,
}: {
  label: string;
  onClick: () => void;
  children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      aria-label={label}
      title={label}
      onClick={onClick}
      className="inline-flex size-8 items-center justify-center rounded-lg text-muted transition-colors hover:bg-ink/5 hover:text-ink"
    >
      {children}
    </button>
  );
}

function download(filename: string, text: string) {
  const url = URL.createObjectURL(new Blob([text], { type: "text/markdown;charset=utf-8" }));
  const link = Object.assign(document.createElement("a"), { href: url, download: filename });
  link.click();
  URL.revokeObjectURL(url);
}

function slug(text: string): string {
  return (
    text
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, "-")
      .replace(/^-|-$/g, "")
      .slice(0, 50) || "answer"
  );
}

function AnswerActions({ question, message }: { question: string; message: UiMessage }) {
  const [copied, setCopied] = useState(false);
  const markdown = () => answerToMarkdown(question, message.content, message.citations);
  return (
    <div className="mt-2 -ml-2 flex items-center gap-0.5">
      <IconButton
        label={copied ? "Copied" : "Copy answer"}
        onClick={() => {
          void navigator.clipboard.writeText(markdown()).then(() => {
            setCopied(true);
            window.setTimeout(() => setCopied(false), 1500);
          });
        }}
      >
        {copied ? (
          <Check className="size-4" aria-hidden />
        ) : (
          <Copy className="size-4" aria-hidden />
        )}
      </IconButton>
      <IconButton
        label="Download as Markdown"
        onClick={() => download(`${slug(question)}.md`, markdown())}
      >
        <Download className="size-4" aria-hidden />
      </IconButton>
    </div>
  );
}

export function MessageView({
  message,
  question,
  onRetry,
}: {
  message: UiMessage;
  question: string;
  onRetry?: () => void;
}) {
  if (message.role === "user") {
    return (
      <div className="flex justify-end">
        <p className="max-w-[85%] rounded-3xl rounded-br-lg bg-paper-deep px-4 py-2.5 whitespace-pre-wrap ring-1 ring-line">
          {message.content}
        </p>
      </div>
    );
  }

  const thinking = message.status === "streaming" && !message.content;
  return (
    <div className="group">
      {message.notice && (
        <p className="mb-3 rounded-xl bg-accent-soft px-3 py-2 text-xs text-accent">
          {message.notice}
        </p>
      )}
      {thinking ? (
        <p className="flex items-center gap-2 text-sm text-muted" role="status">
          <span className="flex gap-1" aria-hidden>
            <span className="size-1.5 animate-bounce rounded-full bg-muted [animation-delay:-0.3s]" />
            <span className="size-1.5 animate-bounce rounded-full bg-muted [animation-delay:-0.15s]" />
            <span className="size-1.5 animate-bounce rounded-full bg-muted" />
          </span>
          Reading your documents…
        </p>
      ) : (
        <AnswerText content={message.content} citations={message.citations} />
      )}
      {message.status === "stopped" && (
        <p className="mt-2 text-xs text-muted">Stopped. This partial answer won&apos;t be saved.</p>
      )}
      {message.status === "error" && (
        <div className="mt-2 flex flex-wrap items-center gap-3 rounded-xl border border-danger/30 bg-danger/5 px-3 py-2 text-sm text-danger">
          <AlertCircle className="size-4 shrink-0" aria-hidden />
          <span className="flex-1">{message.error}</span>
          {onRetry && (
            <button
              type="button"
              onClick={onRetry}
              className="inline-flex items-center gap-1 font-medium underline-offset-4 hover:underline"
            >
              <RotateCcw className="size-3.5" aria-hidden /> Retry
            </button>
          )}
        </div>
      )}
      {message.status === "done" && message.content && (
        <AnswerActions question={question} message={message} />
      )}
    </div>
  );
}
