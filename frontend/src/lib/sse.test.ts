import { describe, expect, it } from "vitest";

import { parseBlock, readEvents } from "./sse";

const LF = String.fromCharCode(10);
const CRLF = String.fromCharCode(13, 10);

function streamOf(...chunks: string[]): ReadableStream<Uint8Array> {
  const encoder = new TextEncoder();
  return new ReadableStream({
    start(controller) {
      chunks.forEach((c) => controller.enqueue(encoder.encode(c)));
      controller.close();
    },
  });
}

describe("readEvents", () => {
  it("reassembles events split across network chunks", async () => {
    const body = [
      "event: sources",
      'data: [{"source_id":1}]',
      "",
      "event: token",
      'data: {"text":"Hi"}',
      "",
      "event: done",
      'data: {"usage":{},"context":{},"account":{}}',
      "",
      "event: title",
      'data: {"title":"Greeting"}',
      "",
      "",
    ].join(LF);
    const cut = [body.slice(0, 17), body.slice(17, 60), body.slice(60)];
    const events = [];
    for await (const e of readEvents(streamOf(...cut))) events.push(e.type);
    expect(events).toEqual(["sources", "token", "done", "title"]);
  });

  it("accepts CRLF line endings", async () => {
    const events = [];
    for await (const e of readEvents(
      streamOf(`event: token${CRLF}data: {"text":"a"}${CRLF}${CRLF}`),
    ))
      events.push(e);
    expect(events).toEqual([{ type: "token", text: "a" }]);
  });
});

describe("parseBlock", () => {
  it("ignores unknown events and comments", () => {
    expect(parseBlock(`event: ping${LF}data: {}`)).toBeNull();
    expect(parseBlock(": keep-alive")).toBeNull();
  });
  it("parses errors", () => {
    expect(parseBlock(`event: error${LF}data: {"code":"x","message":"Nope"}`)).toEqual({
      type: "error",
      code: "x",
      message: "Nope",
    });
  });
});
