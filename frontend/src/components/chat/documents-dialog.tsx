"use client";

import { AlertCircle, FileText, LoaderCircle, Trash2, X } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import type { DocumentOut } from "@/lib/types";

const size = (bytes: number | null) =>
  bytes == null
    ? ""
    : bytes > 1e6
      ? `${(bytes / 1e6).toFixed(1)} MB`
      : `${Math.ceil(bytes / 1e3)} KB`;

function Row({ doc, onDelete }: { doc: DocumentOut; onDelete: () => Promise<void> }) {
  const [state, setState] = useState<"idle" | "confirm" | "deleting">("idle");
  const busy = doc.status === "pending" || doc.status === "processing";
  return (
    <li className="flex items-center gap-3 py-3">
      {doc.status === "failed" ? (
        <AlertCircle className="size-5 shrink-0 text-danger" aria-hidden />
      ) : busy ? (
        <LoaderCircle className="size-5 shrink-0 animate-spin text-muted" aria-hidden />
      ) : (
        <FileText className="size-5 shrink-0 text-accent" aria-hidden />
      )}
      <div className="min-w-0 flex-1">
        <p className="truncate text-sm font-medium">{doc.filename}</p>
        <p className={`truncate text-xs ${doc.status === "failed" ? "text-danger" : "text-muted"}`}>
          {doc.status === "failed"
            ? (doc.error ?? "Couldn't read this PDF.")
            : doc.status === "ready"
              ? `${doc.page_count} pages · ${size(doc.size_bytes)} · added ${new Date(doc.created_at).toLocaleDateString()}`
              : doc.status === "awaiting_upload"
                ? "Upload not finished"
                : "Reading…"}
        </p>
      </div>
      {state === "confirm" ? (
        <div className="flex items-center gap-1">
          <button
            type="button"
            onClick={() => {
              setState("deleting");
              void onDelete().catch(() => setState("idle"));
            }}
            className="rounded-md bg-danger px-2.5 py-1 text-xs font-medium text-white"
          >
            Delete
          </button>
          <button
            type="button"
            onClick={() => setState("idle")}
            className="rounded-md px-2 py-1 text-xs text-muted hover:text-ink"
          >
            Cancel
          </button>
        </div>
      ) : (
        <button
          type="button"
          disabled={state === "deleting"}
          onClick={() => setState("confirm")}
          aria-label={`Delete ${doc.filename}`}
          className="rounded-lg p-2 text-muted hover:bg-ink/5 hover:text-danger disabled:opacity-40"
        >
          {state === "deleting" ? (
            <LoaderCircle className="size-4 animate-spin" aria-hidden />
          ) : (
            <Trash2 className="size-4" aria-hidden />
          )}
        </button>
      )}
    </li>
  );
}

/** Every PDF the user has uploaded; deleting one removes its indexed text for good. */
export function DocumentsDialog({
  open,
  documents,
  onClose,
  onDelete,
}: {
  open: boolean;
  documents: DocumentOut[];
  onClose: () => void;
  onDelete: (id: string) => Promise<void>;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    const dialog = ref.current;
    if (!dialog) return;
    if (open && !dialog.open) dialog.showModal();
    if (!open && dialog.open) dialog.close();
  }, [open]);

  return (
    <dialog
      ref={ref}
      onClose={onClose}
      onClick={(e) => e.target === ref.current && onClose()}
      aria-labelledby="documents-title"
      className="m-auto w-[min(36rem,calc(100vw-2rem))] rounded-card border border-line bg-card p-0 text-ink shadow-2xl backdrop:bg-ink/30 backdrop:backdrop-blur-sm"
    >
      <div className="flex items-center justify-between border-b border-line px-6 py-4">
        <h2 id="documents-title" className="font-display text-xl">
          Your documents
        </h2>
        <button
          type="button"
          onClick={onClose}
          aria-label="Close"
          className="rounded-lg p-1.5 text-muted hover:bg-ink/5 hover:text-ink"
        >
          <X className="size-4.5" aria-hidden />
        </button>
      </div>
      <div className="max-h-[60vh] overflow-y-auto px-6">
        {documents.length === 0 ? (
          <p className="py-8 text-center text-sm text-muted">
            PDFs you attach to a chat are listed here, so you can reuse them in other chats.
          </p>
        ) : (
          <ul className="divide-y divide-line">
            {documents.map((d) => (
              <Row key={d.document_id} doc={d} onDelete={() => onDelete(d.document_id)} />
            ))}
          </ul>
        )}
      </div>
      <p className="border-t border-line px-6 py-3 text-xs text-muted">
        Original files are deleted once they&apos;re read. Deleting a document removes its indexed
        text too.
      </p>
    </dialog>
  );
}
