import { readEvents } from "./sse";
import type {
  Conversation,
  DocumentOut,
  StoredMessage,
  StreamEvent,
  UploadTarget,
  Usage,
} from "./types";

export class ApiError extends Error {
  constructor(
    readonly status: number,
    readonly code: string,
    message: string,
    readonly retryAfter: number | null = null,
  ) {
    super(message);
  }
}

export type TokenSource = () => Promise<string | null>;

/** Typed client for the DocuMind API. Every call carries the signed-in user's access token. */
export class Api {
  constructor(
    private readonly baseUrl: string,
    private readonly token: TokenSource,
    private readonly onUnauthorized: () => void = () => {},
  ) {}

  private async request(path: string, init: RequestInit = {}): Promise<Response> {
    const token = await this.token();
    const headers = new Headers(init.headers);
    if (token) headers.set("Authorization", `Bearer ${token}`);
    if (init.body && !headers.has("Content-Type")) headers.set("Content-Type", "application/json");
    let response: Response;
    try {
      response = await fetch(new URL(path, this.baseUrl), { ...init, headers });
    } catch (err) {
      if (err instanceof DOMException && err.name === "AbortError") throw err;
      throw new ApiError(0, "network", "Can't reach DocuMind. Check your connection and retry.");
    }
    if (response.ok) return response;
    if (response.status === 401) this.onUnauthorized();
    const body = (await response.json().catch(() => null)) as {
      error?: { code?: string; message?: string };
    } | null;
    const retry = response.headers.get("Retry-After");
    throw new ApiError(
      response.status,
      body?.error?.code ?? "http_error",
      body?.error?.message ?? `Request failed (HTTP ${response.status}).`,
      retry ? Number(retry) : null,
    );
  }

  private async json<T>(path: string, init?: RequestInit): Promise<T> {
    return (await this.request(path, init)).json() as Promise<T>;
  }

  // Documents
  listDocuments() {
    return this.json<{ documents: DocumentOut[] }>("v1/documents").then((r) => r.documents);
  }
  getDocument(id: string) {
    return this.json<DocumentOut>(`v1/documents/${id}`);
  }
  createUpload(filename: string, sizeBytes: number) {
    return this.json<{ document: DocumentOut; upload: UploadTarget }>("v1/documents", {
      method: "POST",
      body: JSON.stringify({ filename, size_bytes: sizeBytes }),
    });
  }
  completeUpload(id: string) {
    return this.json<DocumentOut>(`v1/documents/${id}/complete`, { method: "POST" });
  }
  async deleteDocument(id: string) {
    await this.request(`v1/documents/${id}`, { method: "DELETE" });
  }

  // Conversations
  listConversations() {
    return this.json<{ conversations: Conversation[] }>("v1/conversations").then(
      (r) => r.conversations,
    );
  }
  getConversation(id: string) {
    return this.json<{ conversation: Conversation; messages: StoredMessage[] }>(
      `v1/conversations/${id}`,
    );
  }
  createConversation(documentIds: string[]) {
    return this.json<Conversation>("v1/conversations", {
      method: "POST",
      body: JSON.stringify({ document_ids: documentIds }),
    });
  }
  renameConversation(id: string, title: string) {
    return this.json<Conversation>(`v1/conversations/${id}`, {
      method: "PATCH",
      body: JSON.stringify({ title }),
    });
  }
  async deleteConversation(id: string) {
    await this.request(`v1/conversations/${id}`, { method: "DELETE" });
  }

  usage(conversationId?: string) {
    const query = conversationId ? `?conversation_id=${conversationId}` : "";
    return this.json<Usage>(`v1/usage${query}`);
  }

  /** Streams an answer: sources, then tokens, then done (and title on a chat's first answer). */
  async *ask(
    question: string,
    conversationId: string,
    documentIds: string[],
    signal: AbortSignal,
  ): AsyncGenerator<StreamEvent> {
    const response = await this.request("v1/query/stream", {
      method: "POST",
      body: JSON.stringify({
        question,
        conversation_id: conversationId,
        ...(documentIds.length ? { document_ids: documentIds } : {}),
      }),
      signal,
    });
    if (!response.body) throw new ApiError(0, "no_body", "The answer stream was empty.");
    yield* readEvents(response.body);
  }
}

/**
 * Uploads straight to S3 with the presigned form (the file never passes through the API).
 * XMLHttpRequest rather than fetch, because only XHR reports upload progress.
 */
export function uploadToS3(
  target: UploadTarget,
  file: File,
  onProgress: (fraction: number) => void,
  signal?: AbortSignal,
): Promise<void> {
  return new Promise((resolve, reject) => {
    const form = new FormData();
    for (const [key, value] of Object.entries(target.fields)) form.append(key, value);
    form.append("file", file); // S3 requires the file to be the last field
    const xhr = new XMLHttpRequest();
    xhr.open("POST", target.url);
    xhr.upload.onprogress = (e) => e.lengthComputable && onProgress(e.loaded / e.total);
    xhr.onload = () =>
      xhr.status >= 200 && xhr.status < 300
        ? resolve()
        : reject(new ApiError(xhr.status, "upload_failed", "The upload was rejected."));
    xhr.onerror = () => reject(new ApiError(0, "network", "The upload failed. Retry."));
    xhr.onabort = () => reject(new DOMException("Upload cancelled", "AbortError"));
    signal?.addEventListener("abort", () => xhr.abort());
    xhr.send(form);
  });
}
