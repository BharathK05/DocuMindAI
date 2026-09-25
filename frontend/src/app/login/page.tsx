import type { Metadata } from "next";
import { Suspense } from "react";

import { Logo } from "@/components/ui/logo";
import { ThemeToggle } from "@/components/ui/theme-toggle";

import { LoginForm } from "./login-form";

export const metadata: Metadata = { title: "Sign in" };

export default function LoginPage() {
  return (
    <div className="flex min-h-dvh flex-col">
      <header className="flex items-center justify-between px-4 py-3 sm:px-6">
        <Logo />
        <ThemeToggle />
      </header>
      <main className="flex flex-1 flex-col items-center justify-center px-4 pb-16">
        <p className="mb-6 max-w-sm text-center font-display text-2xl tracking-tight text-balance">
          Answers from your PDFs, with the page they came from.
        </p>
        <div className="w-full max-w-sm rounded-card border border-line bg-card p-6 shadow-sm sm:p-8">
          <Suspense>
            <LoginForm />
          </Suspense>
        </div>
      </main>
    </div>
  );
}
