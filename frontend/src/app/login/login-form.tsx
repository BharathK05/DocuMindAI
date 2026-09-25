"use client";

import { LoaderCircle } from "lucide-react";
import { useRouter, useSearchParams } from "next/navigation";
import { useEffect, useState, type FormEvent, type ReactNode } from "react";

import {
  authErrorMessage,
  configureAuth,
  confirmPasswordReset,
  confirmSignUp,
  currentUser,
  requestPasswordReset,
  resendCode,
  saveDevToken,
  signIn,
  signUp,
} from "@/lib/auth";
import { loadConfig, type AuthConfig } from "@/lib/config";

type Step = "sign_in" | "sign_up" | "confirm" | "forgot" | "reset";

const input =
  "block w-full rounded-control border border-line-strong bg-card px-3.5 py-2.5 text-base outline-none transition-shadow focus:border-accent focus:ring-2 focus:ring-accent/20";
const button =
  "inline-flex w-full items-center justify-center gap-2 rounded-full bg-ink px-5 py-3 text-sm font-medium text-paper transition-opacity disabled:opacity-50";
const link = "font-medium text-ink underline underline-offset-4";

/** Only allow redirects within this site (never to another origin). */
function safeNext(next: string | null): string {
  return next && next.startsWith("/") && !next.startsWith("//") ? next : "/chat/";
}

function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <label className="block space-y-1.5">
      <span className="text-sm font-medium">{label}</span>
      {children}
    </label>
  );
}

export function LoginForm() {
  const router = useRouter();
  const next = safeNext(useSearchParams().get("next"));
  const [auth, setAuth] = useState<AuthConfig | null>(null);
  const [step, setStep] = useState<Step>("sign_in");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [code, setCode] = useState("");
  const [token, setToken] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [info, setInfo] = useState<string | null>(null);

  useEffect(() => {
    loadConfig()
      .then(async (config) => {
        configureAuth(config.auth);
        if (await currentUser()) router.replace(next);
        else setAuth(config.auth);
      })
      .catch((err) => setError(authErrorMessage(err)));
  }, [next, router]);

  async function run(action: () => Promise<void>) {
    setBusy(true);
    setError(null);
    setInfo(null);
    try {
      await action();
    } catch (err) {
      setError(authErrorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  const onSubmit = (e: FormEvent) => {
    e.preventDefault();
    void run(async () => {
      switch (step) {
        case "sign_in": {
          const outcome = await signIn(email, password);
          if (outcome === "done") router.replace(next);
          else if (outcome === "confirm_sign_up") {
            await resendCode(email);
            setStep("confirm");
            setInfo("Verify your email first. We've sent you a new code.");
          } else setError("This account needs a sign-in step this app doesn't support yet.");
          break;
        }
        case "sign_up":
          await signUp(email, password);
          setStep("confirm");
          setInfo(`We've emailed a 6-digit code to ${email}.`);
          break;
        case "confirm":
          await confirmSignUp(email, code);
          if (password) {
            await signIn(email, password);
            router.replace(next);
          } else {
            setStep("sign_in");
            setInfo("Email verified. Sign in to continue.");
          }
          break;
        case "forgot":
          await requestPasswordReset(email);
          setStep("reset");
          setInfo(`If ${email} has an account, we've emailed it a reset code.`);
          break;
        case "reset":
          await confirmPasswordReset(email, code, password);
          setStep("sign_in");
          setPassword("");
          setInfo("Password changed. Sign in with your new password.");
          break;
      }
    });
  };

  if (!auth) {
    return (
      <div className="flex justify-center py-10 text-muted">
        {error ? (
          <p role="alert" className="text-danger">
            {error}
          </p>
        ) : (
          <LoaderCircle className="size-5 animate-spin" aria-label="Loading" />
        )}
      </div>
    );
  }

  if (auth.mode === "local") {
    return (
      <form
        className="space-y-5"
        onSubmit={(e) => {
          e.preventDefault();
          try {
            saveDevToken(token);
            router.replace(next);
          } catch (err) {
            setError(authErrorMessage(err));
          }
        }}
      >
        <h1 className="font-display text-3xl tracking-tight">Local development</h1>
        <p className="text-sm text-muted">
          This build talks to a local API. Mint a development token, then paste it here:
        </p>
        <pre className="overflow-x-auto rounded-xl bg-paper-deep px-3 py-2.5 font-mono text-xs">
          cd backend && python -m documind.scripts.dev_token --user alice
        </pre>
        <Field label="Development token">
          <textarea
            required
            rows={4}
            value={token}
            onChange={(e) => setToken(e.target.value)}
            className={`${input} font-mono text-xs`}
          />
        </Field>
        {error && (
          <p role="alert" className="text-sm text-danger">
            {error}
          </p>
        )}
        <button type="submit" className={button}>
          Continue
        </button>
      </form>
    );
  }

  const titles: Record<Step, string> = {
    sign_in: "Welcome back",
    sign_up: "Create your account",
    confirm: "Check your email",
    forgot: "Reset your password",
    reset: "Choose a new password",
  };
  const actions: Record<Step, string> = {
    sign_in: "Sign in",
    sign_up: "Create account",
    confirm: "Verify email",
    forgot: "Send reset code",
    reset: "Change password",
  };
  const needsPassword = step === "sign_in" || step === "sign_up" || step === "reset";
  const needsCode = step === "confirm" || step === "reset";
  const allowSignUp = auth.allowSignUp !== false;

  return (
    <form className="space-y-5" onSubmit={onSubmit}>
      <h1 className="font-display text-3xl tracking-tight">{titles[step]}</h1>
      {info && (
        <p role="status" className="rounded-xl bg-accent-soft px-3 py-2 text-sm text-accent">
          {info}
        </p>
      )}
      <Field label="Email">
        <input
          type="email"
          required
          autoComplete="email"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          readOnly={step === "confirm" || step === "reset"}
          className={input}
        />
      </Field>
      {needsCode && (
        <Field label="Code from the email">
          <input
            required
            inputMode="numeric"
            autoComplete="one-time-code"
            pattern="[0-9]{6}"
            maxLength={6}
            value={code}
            onChange={(e) => setCode(e.target.value)}
            className={`${input} font-mono tracking-[0.3em]`}
          />
        </Field>
      )}
      {needsPassword && (
        <Field label={step === "reset" ? "New password" : "Password"}>
          <input
            type="password"
            required
            minLength={step === "sign_in" ? undefined : 12}
            autoComplete={step === "sign_in" ? "current-password" : "new-password"}
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            className={input}
          />
          {step !== "sign_in" && (
            <span className="block text-xs text-muted">
              At least 12 characters, with upper- and lowercase letters and a number.
            </span>
          )}
        </Field>
      )}
      {error && (
        <p role="alert" className="text-sm text-danger">
          {error}
        </p>
      )}
      <button type="submit" disabled={busy} className={button}>
        {busy && <LoaderCircle className="size-4 animate-spin" aria-hidden />}
        {actions[step]}
      </button>

      <div className="space-y-2 text-center text-sm text-muted">
        {step === "sign_in" && (
          <>
            <button type="button" className={link} onClick={() => setStep("forgot")}>
              Forgot your password?
            </button>
            {allowSignUp && (
              <p>
                New here?{" "}
                <button type="button" className={link} onClick={() => setStep("sign_up")}>
                  Create an account
                </button>
              </p>
            )}
          </>
        )}
        {step === "confirm" && (
          <button
            type="button"
            className={link}
            onClick={() =>
              void run(async () => {
                await resendCode(email);
                setInfo("We've sent a new code.");
              })
            }
          >
            Send a new code
          </button>
        )}
        {step !== "sign_in" && (
          <p>
            <button type="button" className={link} onClick={() => setStep("sign_in")}>
              Back to sign in
            </button>
          </p>
        )}
      </div>
    </form>
  );
}
