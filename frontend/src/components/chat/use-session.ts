"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { Api } from "@/lib/api";
import { configureAuth, currentUser, getAccessToken, signOut, type SignedInUser } from "@/lib/auth";
import { loadConfig, type AppConfig } from "@/lib/config";

export type Session =
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "ready"; api: Api; user: SignedInUser; config: AppConfig };

export function loginUrl(): string {
  const next = `${window.location.pathname}${window.location.search}`;
  return `/login/?next=${encodeURIComponent(next)}`;
}

/** Loads config, restores the signed-in user, and sends signed-out visitors to /login. */
export function useSession(): Session {
  const router = useRouter();
  const [session, setSession] = useState<Session>({ status: "loading" });

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const config = await loadConfig();
        configureAuth(config.auth);
        const user = await currentUser();
        if (cancelled) return;
        if (!user) {
          router.replace(loginUrl());
          return;
        }
        const api = new Api(config.apiUrl, getAccessToken, () => {
          // The token was rejected (expired or revoked): sign in again.
          void signOut().finally(() => router.replace(loginUrl()));
        });
        setSession({ status: "ready", api, user, config });
      } catch (err) {
        if (!cancelled) {
          setSession({
            status: "error",
            message: err instanceof Error ? err.message : "Couldn't start the app.",
          });
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [router]);

  return session;
}
