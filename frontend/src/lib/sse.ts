import type { StreamEvent } from "./types";

const LF = String.fromCharCode(10);
const CRLF = String.fromCharCode(13, 10);
const BLANK_LINE = LF + LF; // events are separated by an empty line

/**
 * Parses a Server-Sent Events body. (The browser's EventSource can't send a POST body or an
 * Authorization header, so the stream is read with fetch instead.)
 */
export async function* readEvents(body: ReadableStream<Uint8Array>): AsyncGenerator<StreamEvent> {
  const reader = body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  try {
    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true }).replaceAll(CRLF, LF);
      let end: number;
      while ((end = buffer.indexOf(BLANK_LINE)) !== -1) {
        const event = parseBlock(buffer.slice(0, end));
        buffer = buffer.slice(end + BLANK_LINE.length);
        if (event) yield event;
      }
    }
    const last = parseBlock(buffer);
    if (last) yield last;
  } finally {
    reader.releaseLock();
  }
}

export function parseBlock(block: string): StreamEvent | null {
  let name = "message";
  const data: string[] = [];
  for (const line of block.split(LF)) {
    if (line.startsWith("event:")) name = line.slice(6).trim();
    else if (line.startsWith("data:")) data.push(line.slice(5).replace(/^ /, ""));
  }
  if (data.length === 0) return null;
  const payload: unknown = JSON.parse(data.join(LF));
  switch (name) {
    case "sources":
      return {
        type: "sources",
        citations: payload as Extract<StreamEvent, { type: "sources" }>["citations"],
      };
    case "token":
    case "done":
    case "title":
    case "error":
      return { type: name, ...(payload as object) } as StreamEvent;
    default:
      return null; // unknown events are ignored, so the server can add new ones safely
  }
}
