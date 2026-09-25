import { describe, expect, it } from "vitest";

import { parseConfig } from "./config";

describe("parseConfig", () => {
  it("normalises the API URL", () => {
    expect(parseConfig({ apiUrl: "https://x.on.aws", auth: { mode: "local" } }).apiUrl).toBe(
      "https://x.on.aws/",
    );
  });
  it("rejects incomplete Cognito settings", () => {
    expect(() => parseConfig({ apiUrl: "https://x/", auth: { mode: "cognito" } })).toThrow();
    expect(() => parseConfig(null)).toThrow();
  });
});
