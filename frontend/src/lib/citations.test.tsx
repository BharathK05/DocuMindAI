import { renderToStaticMarkup } from "react-dom/server";
import ReactMarkdown, { type Components } from "react-markdown";
import { describe, expect, it } from "vitest";

import { answerToMarkdown, citedNumbers, remarkCitations, splitCitations } from "./citations";
import type { Citation } from "./types";

const cite = (source_id: number, page: number): Citation => ({
  source_id,
  document_id: "d".repeat(32),
  filename: "NIST.SP.800-63b.pdf",
  page,
  score: 0.9,
  snippet: "  Reauthentication   at AAL2 ",
});

describe("splitCitations", () => {
  it("handles single, adjacent and comma-separated markers", () => {
    expect(splitCitations("A [1] B [2][3] C [4, 5].")).toEqual([
      "A ",
      1,
      " B ",
      2,
      3,
      " C ",
      4,
      5,
      ".",
    ]);
  });
  it("leaves text without markers alone", () => {
    expect(splitCitations("No sources [here].")).toEqual(["No sources [here]."]);
  });
});

describe("remarkCitations", () => {
  const render = (md: string) =>
    renderToStaticMarkup(
      <ReactMarkdown
        remarkPlugins={[remarkCitations]}
        components={{ "cite-ref": ({ n }: { n?: string }) => <b>#{n}</b> } as Components}
      >
        {md}
      </ReactMarkdown>,
    );

  it("renders markers as citation elements right where they appear", () => {
    expect(render("Every **12 hours** [1][2].")).toBe(
      "<p>Every <strong>12 hours</strong> <b>#1</b><b>#2</b>.</p>",
    );
  });
  it("finds markers inside list items", () => {
    expect(render("- one [3]")).toContain("<li>one <b>#3</b></li>");
  });
  it("ignores markers in code", () => {
    expect(render("`arr[1]`")).toBe("<p><code>arr[1]</code></p>");
  });
});

describe("exporting", () => {
  it("lists only the sources the answer cites, in order of use", () => {
    expect(citedNumbers("x [2] y [1] z [2]")).toEqual([2, 1]);
    const md = answerToMarkdown("How often?", "Every 12 hours [2].", [cite(1, 5), cite(2, 19)]);
    expect(md).toContain("## How often?");
    expect(md).toContain("- [2] NIST.SP.800-63b.pdf, page 19");
    expect(md).toContain("> Reauthentication at AAL2");
    expect(md).not.toContain("page 5");
  });
});
