// Mirrors backend/src/documind/api/schemas.py.

export type DocumentStatus = "awaiting_upload" | "pending" | "processing" | "ready" | "failed";

export interface DocumentOut {
  document_id: string;
  filename: string;
  status: DocumentStatus;
  size_bytes: number | null;
  page_count: number | null;
  chunk_count: number | null;
  error: string | null;
  created_at: string;
  updated_at: string;
}

export interface UploadTarget {
  url: string;
  fields: Record<string, string>;
  expires_in: number;
}

export interface Citation {
  source_id: number;
  document_id: string;
  filename: string;
  page: number;
  score: number;
  snippet: string;
}

export interface ContextFigures {
  tokens: number;
  limit: number;
  fraction: number;
  notice: string | null;
}

export interface AccountFigures {
  tokens_used_today: number;
  daily_quota: number;
  remaining: number;
  reset_at: string;
  cost_usd_today: number;
}

export interface Conversation {
  conversation_id: string;
  title: string;
  message_count: number;
  document_ids: string[];
  created_at: string;
  updated_at: string;
}

export interface StoredMessage {
  index: number;
  role: "user" | "assistant";
  content: string;
  citations: Citation[];
  created_at: string;
}

export interface Usage {
  account: AccountFigures;
  context: ContextFigures | null;
}

export type StreamEvent =
  | { type: "sources"; citations: Citation[] }
  | { type: "token"; text: string }
  | {
      type: "done";
      usage: { input_tokens: number; output_tokens: number };
      context: ContextFigures;
      account: AccountFigures;
    }
  | { type: "title"; title: string }
  | { type: "error"; code: string; message: string };
