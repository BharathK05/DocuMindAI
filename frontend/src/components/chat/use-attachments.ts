"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { ApiError, uploadToS3, type Api } from "@/lib/api";
import type { DocumentOut } from "@/lib/types";

export const MAX_UPLOAD_BYTES = 20 * 1024 * 1024; // matches the API's upload_max_bytes
const POLL_MS = [1000, 1500, 2000, 3000];

export type AttachmentStatus = "uploading" | "pending" | "processing" | "ready" | "failed";

export interface Attachment {
  localId: string;
  filename: string;
  documentId: string | null;
  status: AttachmentStatus;
  progress: number; // upload progress, 0..1
  pages: number | null;
  error: string | null;
}

/** An attachment's fields from the API's view of the document (everything but localId). */
function documentFields(doc: DocumentOut): Omit<Attachment, "localId"> {
  return {
    filename: doc.filename,
    documentId: doc.document_id,
    status: doc.status === "awaiting_upload" ? "uploading" : doc.status,
    progress: 1,
    pages: doc.page_count,
    error: doc.error,
  };
}

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

/**
 * PDFs being attached to the next message: upload straight to S3, confirm, then poll until
 * ingestion finishes. Reports every document change so the library stays in sync.
 */
export function useAttachments(api: Api | null, onDocument: (doc: DocumentOut) => void) {
  const [attachments, setAttachments] = useState<Attachment[]>([]);
  const alive = useRef(true);
  useEffect(() => {
    alive.current = true;
    return () => {
      alive.current = false;
    };
  }, []);

  const patch = useCallback((localId: string, changes: Partial<Attachment>) => {
    if (!alive.current) return;
    setAttachments((list) => list.map((a) => (a.localId === localId ? { ...a, ...changes } : a)));
  }, []);

  const track = useCallback(
    async (localId: string, documentId: string) => {
      for (let i = 0; alive.current; i++) {
        await sleep(POLL_MS[Math.min(i, POLL_MS.length - 1)]);
        if (!api || !alive.current) return;
        try {
          const doc = await api.getDocument(documentId);
          onDocument(doc);
          patch(localId, documentFields(doc));
          if (doc.status === "ready" || doc.status === "failed") return;
        } catch (err) {
          if (err instanceof ApiError && err.status === 404) {
            patch(localId, { status: "failed", error: "This document was deleted." });
            return;
          }
          // transient error: keep polling
        }
      }
    },
    [api, onDocument, patch],
  );

  const addFiles = useCallback(
    (files: Iterable<File>) => {
      if (!api) return;
      for (const file of files) {
        const localId = crypto.randomUUID();
        const isPdf = file.type === "application/pdf" || file.name.toLowerCase().endsWith(".pdf");
        const error = !isPdf
          ? "Only PDF files are supported."
          : file.size > MAX_UPLOAD_BYTES
            ? "This PDF is over the 20 MB limit."
            : file.size === 0
              ? "This file is empty."
              : null;
        setAttachments((list) => [
          ...list,
          {
            localId,
            filename: file.name,
            documentId: null,
            status: error ? "failed" : "uploading",
            progress: 0,
            pages: null,
            error,
          },
        ]);
        if (error) continue;
        void (async () => {
          try {
            const { document, upload } = await api.createUpload(file.name, file.size);
            patch(localId, { documentId: document.document_id });
            onDocument(document);
            await uploadToS3(upload, file, (progress) => patch(localId, { progress }));
            const confirmed = await api.completeUpload(document.document_id);
            onDocument(confirmed);
            patch(localId, documentFields(confirmed));
            await track(localId, document.document_id);
          } catch (err) {
            patch(localId, {
              status: "failed",
              error: err instanceof Error ? err.message : "The upload failed.",
            });
          }
        })();
      }
    },
    [api, onDocument, patch, track],
  );

  /** Attach PDFs that were uploaded earlier (from the library). */
  const addExisting = useCallback((docs: DocumentOut[]) => {
    setAttachments((list) => [
      ...list,
      ...docs
        .filter((d) => !list.some((a) => a.documentId === d.document_id))
        .map((d) => ({ localId: d.document_id, ...documentFields(d) })),
    ]);
  }, []);

  const remove = useCallback((localId: string) => {
    setAttachments((list) => list.filter((a) => a.localId !== localId));
  }, []);

  const clear = useCallback(() => setAttachments([]), []);

  return { attachments, addFiles, addExisting, remove, clear };
}
