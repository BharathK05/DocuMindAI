/**
 * Sign-in for the two API auth modes:
 *  - cognito: Amazon Cognito with SRP, so the password itself never leaves the browser. The
 *    Amplify library stores and refreshes the tokens.
 *  - local:   a development token minted by `python -m documind.scripts.dev_token`, pasted in.
 */
import { Amplify } from "aws-amplify";
import * as cognito from "aws-amplify/auth";

import type { AuthConfig } from "./config";

const DEV_TOKEN_KEY = "documind.devToken";

export interface SignedInUser {
  label: string; // shown in the sidebar: email, or the dev token's user id
}

export type SignInOutcome = "done" | "confirm_sign_up" | "unsupported";

let configured: AuthConfig | null = null;

export function configureAuth(auth: AuthConfig): void {
  if (configured) return;
  configured = auth;
  if (auth.mode === "cognito") {
    Amplify.configure({
      Auth: {
        Cognito: {
          userPoolId: auth.userPoolId,
          userPoolClientId: auth.clientId,
          loginWith: { email: true },
        },
      },
    });
  }
}

function mode(): AuthConfig["mode"] {
  if (!configured) throw new Error("configureAuth() must run first");
  return configured.mode;
}

function readDevToken(): string | null {
  try {
    return localStorage.getItem(DEV_TOKEN_KEY);
  } catch {
    return null;
  }
}

/** The JWT's claims, without verifying it (the API does that); used only for display/expiry. */
export function decodeClaims(token: string): Record<string, unknown> | null {
  try {
    const part = token.split(".")[1];
    const json = atob(part.replace(/-/g, "+").replace(/_/g, "/"));
    return JSON.parse(json) as Record<string, unknown>;
  } catch {
    return null;
  }
}

export async function getAccessToken(): Promise<string | null> {
  if (mode() === "local") return readDevToken();
  try {
    const session = await cognito.fetchAuthSession(); // refreshes an expired token
    return session.tokens?.accessToken.toString() ?? null;
  } catch {
    return null;
  }
}

export async function currentUser(): Promise<SignedInUser | null> {
  if (mode() === "local") {
    const token = readDevToken();
    const claims = token ? decodeClaims(token) : null;
    const exp = typeof claims?.exp === "number" ? claims.exp : 0;
    if (!claims || exp * 1000 < Date.now()) return null;
    return { label: String(claims.sub ?? "developer") };
  }
  try {
    await cognito.getCurrentUser();
    const attributes = await cognito.fetchUserAttributes();
    return { label: attributes.email ?? "Signed in" };
  } catch {
    return null;
  }
}

export function saveDevToken(token: string): void {
  const claims = decodeClaims(token.trim());
  if (!claims?.sub) throw new Error("That doesn't look like a DocuMind development token.");
  localStorage.setItem(DEV_TOKEN_KEY, token.trim());
}

export async function signIn(email: string, password: string): Promise<SignInOutcome> {
  const { nextStep } = await cognito.signIn({ username: email, password });
  switch (nextStep.signInStep) {
    case "DONE":
      return "done";
    case "CONFIRM_SIGN_UP":
      return "confirm_sign_up";
    default:
      // e.g. an MFA challenge set up outside this app
      await cognito.signOut().catch(() => {});
      return "unsupported";
  }
}

export async function signUp(email: string, password: string): Promise<void> {
  await cognito.signUp({ username: email, password, options: { userAttributes: { email } } });
}

export async function confirmSignUp(email: string, code: string): Promise<void> {
  await cognito.confirmSignUp({ username: email, confirmationCode: code.trim() });
}

export async function resendCode(email: string): Promise<void> {
  await cognito.resendSignUpCode({ username: email });
}

export async function requestPasswordReset(email: string): Promise<void> {
  await cognito.resetPassword({ username: email });
}

export async function confirmPasswordReset(
  email: string,
  code: string,
  newPassword: string,
): Promise<void> {
  await cognito.confirmResetPassword({
    username: email,
    confirmationCode: code.trim(),
    newPassword,
  });
}

export async function signOut(): Promise<void> {
  if (mode() === "local") {
    try {
      localStorage.removeItem(DEV_TOKEN_KEY);
    } catch {
      // nothing stored
    }
    return;
  }
  await cognito.signOut();
}

/** Cognito's error messages are already user-facing ("Incorrect username or password."). */
export function authErrorMessage(err: unknown): string {
  if (err instanceof Error && err.message) return err.message;
  return "Something went wrong. Try again.";
}
