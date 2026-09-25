// Writes public/config.json from environment variables when a host builds the site itself
// (e.g. Vercel). Without them the committed local-development config is left untouched; on AWS,
// Terraform uploads each environment's config.json instead.
//   DOCUMIND_API_URL, DOCUMIND_COGNITO_USER_POOL_ID, DOCUMIND_COGNITO_CLIENT_ID
//   DOCUMIND_ALLOW_SIGN_UP (optional, default true)
import { writeFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const env = process.env;
if (!env.DOCUMIND_API_URL) {
  console.log("config.json: DOCUMIND_API_URL not set, keeping public/config.json");
  process.exit(0);
}
const missing = ["DOCUMIND_COGNITO_USER_POOL_ID", "DOCUMIND_COGNITO_CLIENT_ID"].filter(
  (k) => !env[k],
);
if (missing.length) {
  throw new Error(`config.json: set ${missing.join(" and ")} as well`);
}
const config = {
  apiUrl: env.DOCUMIND_API_URL,
  auth: {
    mode: "cognito",
    userPoolId: env.DOCUMIND_COGNITO_USER_POOL_ID,
    clientId: env.DOCUMIND_COGNITO_CLIENT_ID,
    allowSignUp: env.DOCUMIND_ALLOW_SIGN_UP !== "false",
  },
};
const root = resolve(dirname(fileURLToPath(import.meta.url)), "..");
writeFileSync(resolve(root, "public/config.json"), `${JSON.stringify(config, null, 2)}\n`);
console.log(`config.json: API ${config.apiUrl}`);
