import type { Parent, PhrasingContent, Root, Text } from "mdast";

import type { Citation } from "./types";

/** "[1]", "[1][2]" and "[1, 2]" markers written by the model after the claim they support. */
const MARKER = /\[(\d{1,2}(?:\s*,\s*\d{1,2})*)\]/g;

/** Splits text into plain runs and citation numbers. */
export function splitCitations(text: string): (string | number)[] {
  const parts: (string | number)[] = [];
  let last = 0;
  for (const match of text.matchAll(MARKER)) {
    if (match.index > last) parts.push(text.slice(last, match.index));
    for (const n of match[1].split(",")) parts.push(Number(n.trim()));
    last = match.index + match[0].length;
  }
  if (last < text.length) parts.push(text.slice(last));
  return parts;
}

/**
 * remark plugin: turns citation markers in the answer's text into <cite-ref n="1"> elements,
 * which the chat renders as inline citation chips. Code spans are left alone.
 */
export function remarkCitations() {
  return (tree: Root) => {
    const visit = (node: Parent) => {
      const children: unknown[] = [];
      for (const child of node.children) {
        if (child.type === "text") {
          children.push(...expand(child));
        } else {
          if ("children" in child) visit(child as Parent);
          children.push(child);
        }
      }
      node.children = children as Parent["children"];
    };
    visit(tree);
  };
}

function expand(node: Text): PhrasingContent[] {
  const parts = splitCitations(node.value);
  if (parts.length === 1 && typeof parts[0] === "string") return [node];
  return parts.map((part) =>
    typeof part === "string"
      ? ({ type: "text", value: part } satisfies Text)
      : ({
          type: "text",
          value: "",
          data: { hName: "cite-ref", hProperties: { n: String(part) } },
        } as Text),
  );
}

/** The citation numbers an answer actually uses, in order of first use. */
export function citedNumbers(answer: string): number[] {
  return [...new Set(splitCitations(answer).filter((p): p is number => typeof p === "number"))];
}

/** One question and answer as Markdown, with the cited sources listed underneath. */
export function answerToMarkdown(question: string, answer: string, citations: Citation[]): string {
  const bySource = new Map(citations.map((c) => [c.source_id, c]));
  const sources = citedNumbers(answer)
    .map((n) => bySource.get(n))
    .filter((c): c is Citation => Boolean(c))
    .map(
      (c) =>
        `[${c.source_id}] ${c.filename}, page ${c.page}\n    > ${c.snippet.replace(/\s+/g, " ").trim()}`,
    );
  return [
    `## ${question.trim()}`,
    "",
    answer.trim(),
    ...(sources.length ? ["", "### Sources", "", ...sources.map((s) => `- ${s}`)] : []),
    "",
  ].join("\n");
}
