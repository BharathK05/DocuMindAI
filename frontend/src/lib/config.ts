/**
 * Runtime settings, read from /config.json. The same static build is deployed to dev and prod;
 * Terraform writes each environment's config.json next to it (API URL, Cognito ids), so
 * nothing environment-specific is baked into the JavaScript.
 */

export type AuthConfig =
  | { mode: "local" }
  | { mode: "cognito"; userPoolId: string; clientId: string; allowSignUp?: boolean };

export interface AppConfig {
  apiUrl: string; // always ends with "/"
  auth: AuthConfig;
}

let cached: Promise<AppConfig> | null = null;

export function parseConfig(raw: unknown): AppConfig {
  const data = raw as Partial<AppConfig> | null;
  if (!data || typeof data.apiUrl !== "string" || !data.auth) {
    throw new Error("config.json is missing apiUrl or auth");
  }
  const apiUrl = data.apiUrl.endsWith("/") ? data.apiUrl : `${data.apiUrl}/`;
  const auth = data.auth;
  if (auth.mode === "cognito" && !(auth.userPoolId && auth.clientId)) {
    throw new Error("config.json: cognito auth needs userPoolId and clientId");
  }
  return { apiUrl, auth };
}

export function loadConfig(): Promise<AppConfig> {
  cached ??= fetch("/config.json", { cache: "no-store" })
    .then((r) => {
      if (!r.ok) throw new Error(`config.json: HTTP ${r.status}`);
      return r.json();
    })
    .then(parseConfig)
    .catch((err) => {
      cached = null; // allow a retry
      throw err;
    });
  return cached;
}
