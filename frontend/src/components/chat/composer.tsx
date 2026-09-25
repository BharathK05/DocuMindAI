"use client";

import {
  AlertCircle,
  ArrowUp,
  Check,
  FileText,
  Library,
  LoaderCircle,
  Paperclip,
  Square,
  X,
} from "lucide-react";
import {
  useEffect,
  useRef,
  useState,
  type FormEvent,
  type KeyboardEvent as ReactKeyboardEvent,
} from "react";

import type { DocumentOut } from "@/lib/types";

import type { Attachment } from "./use-attachments";

function AttachmentChip({ a, onRemove }: { a: Attachment; onRemove: () => void }) {
  const label =
    a.status === "uploading"
      ? `Uploading ${Math.round(a.progress * 100)}%`
      : a.status === "ready"
        ? a.pages
          ? `${a.pages} pages`
          : "Ready"
        : a.status === "failed"
          ? (a.error ?? "Failed")
          : a.status === "pending"
            ? "Queued"
            : "Reading…";
  return (
    <li
      className={`flex max-w-full items-center gap-2 rounded-xl border px-2.5 py-1.5 text-sm ${
        a.status === "failed" ? "border-danger/40 bg-danger/5" : "border-line bg-paper"
      }`}
    >
      {a.status === "ready" ? (
        <FileText className="size-4 shrink-0 text-accent" aria-hidden />
      ) : a.status === "failed" ? (
        <AlertCircle className="size-4 shrink-0 text-danger" aria-hidden />
      ) : (
        <LoaderCircle className="size-4 shrink-0 animate-spin text-muted" aria-hidden />
      )}
      <span className="min-w-0">
        <span className="block max-w-48 truncate leading-tight">{a.filename}</span>
        <span
          className={`block text-xs leading-tight ${a.status === "failed" ? "text-danger" : "text-muted"}`}
        >
          {label}
        </span>
      </span>
      <button
        type="button"
        onClick={onRemove}
        aria-label={`Remove ${a.filename}`}
        className="ml-1 rounded-md p-0.5 text-muted hover:bg-ink/5 hover:text-ink"
      >
        <X className="size-3.5" aria-hidden />
      </button>
    </li>
  );
}

function LibraryMenu({
  documents,
  attachedIds,
  onPick,
  onClose,
}: {
  documents: DocumentOut[];
  attachedIds: Set<string>;
  onPick: (doc: DocumentOut) => void;
  onClose: () => void;
}) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const close = (e: Event) => {
      if (
        e instanceof KeyboardEvent ? e.key === "Escape" : !ref.current?.contains(e.target as Node)
      )
        onClose();
    };
    document.addEventListener("pointerdown", close);
    document.addEventListener("keydown", close);
    return () => {
      document.removeEventListener("pointerdown", close);
      document.removeEventListener("keydown", close);
    };
  }, [onClose]);
  const ready = documents.filter((d) => d.status === "ready");
  return (
    <div
      ref={ref}
      className="absolute bottom-full left-0 z-30 mb-2 w-80 max-w-[calc(100vw-2rem)] rounded-2xl border border-line bg-card p-2 shadow-xl shadow-ink/10"
    >
      <p className="px-2 pt-1 pb-2 text-xs text-muted">Your documents</p>
      {ready.length === 0 ? (
        <p className="px-2 pb-2 text-sm text-muted">Nothing uploaded yet.</p>
      ) : (
        <ul className="max-h-64 overflow-y-auto">
          {ready.map((d) => {
            const attached = attachedIds.has(d.document_id);
            return (
              <li key={d.document_id}>
                <button
                  type="button"
                  disabled={attached}
                  onClick={() => onPick(d)}
                  className="flex w-full items-center gap-2 rounded-xl px-2 py-2 text-left text-sm hover:bg-ink/5 disabled:opacity-60"
                >
                  <FileText className="size-4 shrink-0 text-muted" aria-hidden />
                  <span className="min-w-0 flex-1 truncate">{d.filename}</span>
                  {attached ? (
                    <Check className="size-4 text-ready" aria-label="Attached" />
                  ) : (
                    <span className="font-mono text-xs text-muted">{d.page_count} pp</span>
                  )}
                </button>
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}

export function Composer({
  attachments,
  documents,
  chatDocumentIds,
  streaming,
  disabledReason,
  autoFocus,
  onFiles,
  onPickExisting,
  onRemoveAttachment,
  onSend,
  onStop,
}: {
  attachments: Attachment[];
  documents: DocumentOut[];
  chatDocumentIds: string[];
  streaming: boolean;
  disabledReason: string | null;
  autoFocus?: boolean;
  onFiles: (files: File[]) => void;
  onPickExisting: (doc: DocumentOut) => void;
  onRemoveAttachment: (localId: string) => void;
  onSend: (text: string) => void;
  onStop: () => void;
}) {
  const [text, setText] = useState("");
  const [libraryOpen, setLibraryOpen] = useState(false);
  const fileInput = useRef<HTMLInputElement>(null);
  const textarea = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    const el = textarea.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${Math.min(el.scrollHeight, 240)}px`;
  }, [text]);

  useEffect(() => {
    if (autoFocus) textarea.current?.focus();
  }, [autoFocus]);

  const waiting = attachments.some((a) => a.status !== "ready" && a.status !== "failed");
  const blocked = disabledReason ?? (waiting ? "Waiting for your PDFs to finish reading…" : null);
  const canSend = text.trim().length > 0 && !blocked && !streaming;

  function submit(e?: FormEvent) {
    e?.preventDefault();
    if (!canSend) return;
    onSend(text.trim());
    setText("");
  }

  function onKeyDown(e: ReactKeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
      e.preventDefault();
      submit();
    }
  }

  const attachedIds = new Set([
    ...chatDocumentIds,
    ...attachments.map((a) => a.documentId).filter((id): id is string => Boolean(id)),
  ]);

  return (
    <form
      onSubmit={submit}
      className="rounded-3xl border border-line-strong bg-card p-2 shadow-lg shadow-ink/5 transition-shadow focus-within:shadow-ink/10"
    >
      {attachments.length > 0 && (
        <ul className="flex flex-wrap gap-2 px-1 pt-1 pb-2" aria-label="Attached PDFs">
          {attachments.map((a) => (
            <AttachmentChip key={a.localId} a={a} onRemove={() => onRemoveAttachment(a.localId)} />
          ))}
        </ul>
      )}
      <label htmlFor="question" className="sr-only">
        Ask a question about your documents
      </label>
      <textarea
        id="question"
        ref={textarea}
        rows={1}
        value={text}
        onChange={(e) => setText(e.target.value)}
        onKeyDown={onKeyDown}
        maxLength={2000}
        placeholder={
          chatDocumentIds.length || attachments.length
            ? "Ask about your PDFs…"
            : "Attach a PDF, or ask across all your documents…"
        }
        className="block max-h-60 w-full resize-none bg-transparent px-3 py-2 text-base outline-none placeholder:text-muted"
      />
      <div className="flex items-center gap-1 px-1 pt-1">
        <input
          ref={fileInput}
          type="file"
          accept="application/pdf,.pdf"
          multiple
          hidden
          onChange={(e) => {
            if (e.target.files?.length) onFiles([...e.target.files]);
            e.target.value = "";
          }}
        />
        <button
          type="button"
          onClick={() => fileInput.current?.click()}
          aria-label="Upload PDFs"
          title="Upload PDFs"
          className="inline-flex size-9 items-center justify-center rounded-xl text-muted hover:bg-ink/5 hover:text-ink"
        >
          <Paperclip className="size-4.5" aria-hidden />
        </button>
        <div className="relative">
          <button
            type="button"
            onClick={() => setLibraryOpen((v) => !v)}
            aria-label="Add from your documents"
            aria-expanded={libraryOpen}
            title="Add from your documents"
            className="inline-flex size-9 items-center justify-center rounded-xl text-muted hover:bg-ink/5 hover:text-ink"
          >
            <Library className="size-4.5" aria-hidden />
          </button>
          {libraryOpen && (
            <LibraryMenu
              documents={documents}
              attachedIds={attachedIds}
              onPick={(d) => {
                onPickExisting(d);
                setLibraryOpen(false);
              }}
              onClose={() => setLibraryOpen(false)}
            />
          )}
        </div>
        <p className="min-w-0 flex-1 truncate px-2 text-xs text-muted" aria-live="polite">
          {blocked ?? ""}
        </p>
        {streaming ? (
          <button
            type="button"
            onClick={onStop}
            aria-label="Stop answering"
            className="inline-flex size-9 items-center justify-center rounded-full bg-ink text-paper"
          >
            <Square className="size-3.5 fill-current" aria-hidden />
          </button>
        ) : (
          <button
            type="submit"
            disabled={!canSend}
            aria-label="Send"
            className="inline-flex size-9 items-center justify-center rounded-full bg-ink text-paper transition-opacity disabled:opacity-30"
          >
            <ArrowUp className="size-4.5" aria-hidden />
          </button>
        )}
      </div>
    </form>
  );
}
