import {
  ArrowRight,
  ArrowUpRight,
  Download,
  FileSearch,
  KeyRound,
  Layers,
  Lock,
  MessagesSquare,
  ScrollText,
  Trash2,
  UserRound,
} from "lucide-react";
import Link from "next/link";
import type { ReactNode } from "react";

import evalData from "@/data/eval.json";
import { CitationChip } from "@/components/ui/citation-chip";
import { Logo } from "@/components/ui/logo";
import { Reveal } from "@/components/ui/reveal";
import { SplitText } from "@/components/ui/split-text";
import { ThemeToggle } from "@/components/ui/theme-toggle";
import { UploadDemo } from "@/components/landing/upload-demo";

export const REPO_URL = "https://github.com/BharathK05/DocuMindAI";
const EVAL_URL = `${REPO_URL}/blob/main/docs/evaluation.md`;
const OPENAI_POLICY_URL = "https://developers.openai.com/api/docs/guides/your-data";

const primaryButton =
  "inline-flex items-center gap-2 rounded-full bg-ink px-5 py-3 text-sm font-medium text-paper transition-transform hover:-translate-y-0.5 active:translate-y-0";
const secondaryButton =
  "inline-flex items-center gap-2 rounded-full border border-line-strong px-5 py-3 text-sm font-medium text-ink transition-colors hover:bg-ink/5";

function Card({ children, className = "" }: { children: ReactNode; className?: string }) {
  return (
    <div className={`rounded-card border border-line bg-card p-6 sm:p-8 ${className}`}>
      {children}
    </div>
  );
}

function Eyebrow({ children }: { children: ReactNode }) {
  return <p className="mb-4 font-mono text-xs tracking-wide text-muted uppercase">{children}</p>;
}

export function Nav() {
  return (
    <header className="sticky top-0 z-40 border-b border-transparent bg-paper/80 backdrop-blur-md">
      <nav
        aria-label="Main"
        className="mx-auto flex max-w-6xl items-center justify-between gap-4 px-4 py-3 sm:px-6"
      >
        <Logo />
        <div className="flex items-center gap-1 sm:gap-2">
          <a
            href="#how"
            className="hidden rounded-full px-3 py-2 text-sm text-muted hover:text-ink md:inline"
          >
            How it works
          </a>
          <a
            href="#privacy"
            className="hidden rounded-full px-3 py-2 text-sm text-muted hover:text-ink md:inline"
          >
            Privacy
          </a>
          <a
            href={REPO_URL}
            className="hidden rounded-full px-3 py-2 text-sm text-muted hover:text-ink md:inline"
          >
            GitHub
          </a>
          <ThemeToggle />
          <Link
            href="/chat"
            className="rounded-full bg-ink px-4 py-2 text-sm font-medium text-paper"
          >
            Start asking
          </Link>
        </div>
      </nav>
    </header>
  );
}

export function Hero() {
  return (
    <section className="mx-auto max-w-6xl px-4 pt-16 pb-20 sm:px-6 sm:pt-24 sm:pb-28">
      <p className="mb-8 inline-flex items-center gap-2 rounded-full border border-line bg-card px-3 py-1.5 text-xs text-muted">
        <span className="size-1.5 rounded-full bg-ready" aria-hidden />
        Answers cite the page they came from
      </p>
      <SplitText
        as="h1"
        immediate
        text="Your documents, finally remembered."
        emphasis={["finally"]}
        className="max-w-5xl font-display text-display tracking-tight text-balance"
      />
      <p className="mt-8 max-w-xl text-lg leading-relaxed text-muted sm:text-xl">
        Upload your PDFs and ask questions in plain language. DocuMind finds the right passages and
        answers with a citation to the exact page.
      </p>
      <div className="mt-10 flex flex-wrap gap-3">
        <Link href="/chat" className={primaryButton}>
          Start asking <ArrowRight className="size-4" aria-hidden />
        </Link>
        <a href="#how" className={secondaryButton}>
          See how it works
        </a>
      </div>
    </section>
  );
}

export function Showcase() {
  const { sample } = evalData;
  const [before] = sample.answer.split(" [1]");
  return (
    <section aria-labelledby="showcase-title" className="mx-auto max-w-6xl px-4 pb-24 sm:px-6">
      <SplitText
        text="From a pile of PDFs to a straight answer."
        className="mb-10 max-w-3xl font-display text-headline tracking-tight text-balance"
      />
      <span id="showcase-title" className="sr-only">
        Upload your documents and ask anything
      </span>
      <div className="grid gap-4 lg:grid-cols-5">
        <Reveal className="lg:col-span-2">
          <Card className="h-full">
            <Eyebrow>01 · Upload your documents</Eyebrow>
            <h3 className="mb-6 font-display text-2xl tracking-tight">
              Drop in PDFs. We read every page.
            </h3>
            <UploadDemo />
          </Card>
        </Reveal>
        <Reveal className="lg:col-span-3" delay={0.1}>
          <Card className="h-full">
            <Eyebrow>02 · Ask anything</Eyebrow>
            <h3 className="mb-6 font-display text-2xl tracking-tight">
              Answers you can check, page by page.
            </h3>
            <div className="space-y-4">
              <p className="ml-auto w-fit max-w-[85%] rounded-2xl rounded-br-md bg-paper-deep px-4 py-2.5 text-[0.95rem]">
                {sample.question}
              </p>
              <p className="font-display text-lg leading-relaxed">
                {before}
                <CitationChip n={1} filename={sample.citation.file} page={sample.citation.page} />
              </p>
            </div>
            <p className="mt-6 border-t border-line pt-4 text-xs text-muted">
              A real answer from our evaluation run. Hover or tap the{" "}
              <span className="rounded bg-marker-soft px-1 font-mono text-ink">1</span> to see its
              source.
            </p>
          </Card>
        </Reveal>
      </div>
    </section>
  );
}

const INSIGHTS = [
  {
    icon: ScrollText,
    title: "Summaries on request",
    body: "Ask for a summary of a document or a section and get one, cited page by page.",
    example: "Summarize the incident response phases in SP 800-61r3",
    span: "md:col-span-2",
  },
  {
    icon: Layers,
    title: "Search across documents",
    body: "Attach several PDFs to one chat and ask questions that span them.",
    example: "How does CSF 2.0 relate to SP 800-61r3?",
    span: "",
  },
  {
    icon: MessagesSquare,
    title: "Follow-up questions",
    body: "Each chat remembers what you asked. Long chats are summarized to stay within the model's limit, and you're told when that happens.",
    span: "",
  },
  {
    icon: Download,
    title: "Export answers",
    body: "Copy any answer, or download it as Markdown with its sources listed.",
    span: "md:col-span-2",
  },
] as const;

export function Insights() {
  return (
    <section className="mx-auto max-w-6xl px-4 pb-24 sm:px-6">
      <Eyebrow>03 · Act on insights</Eyebrow>
      <SplitText
        text="Read less. Understand more."
        className="mb-10 font-display text-headline tracking-tight"
      />
      <div className="grid gap-4 md:grid-cols-3">
        {INSIGHTS.map((item, i) => (
          <Reveal key={item.title} className={item.span} delay={i * 0.06}>
            <Card className="flex h-full flex-col">
              <item.icon className="mb-5 size-6 text-accent" aria-hidden />
              <h3 className="font-display text-xl tracking-tight">{item.title}</h3>
              <p className="mt-2 leading-relaxed text-muted">{item.body}</p>
              {"example" in item && (
                <p className="mt-5 w-fit rounded-full border border-line bg-paper px-3.5 py-1.5 text-sm">
                  “{item.example}”
                </p>
              )}
            </Card>
          </Reveal>
        ))}
      </div>
    </section>
  );
}

const pct = (x: number) => `${Math.round(x * 100)}%`;

export function Proof() {
  const e = evalData;
  const stats = [
    {
      value: pct(e.recallAt5),
      label: "Recall@5",
      detail: "The right passage is in the top 5 results",
    },
    {
      value: pct(e.faithfulness),
      label: "Faithfulness",
      detail: "Answers stick to what the sources say",
    },
    {
      value: pct(e.correctness),
      label: "Correctness",
      detail: "Answers match the reference answer",
    },
    {
      value: `${(e.p95LatencyMs / 1000).toFixed(1)} s`,
      label: "p95 latency",
      detail: "Question to complete answer",
    },
  ];
  const runDate = new Date(e.runAt).toLocaleDateString("en-GB", {
    day: "numeric",
    month: "short",
    year: "numeric",
    timeZone: "UTC",
  });
  return (
    <section aria-labelledby="proof-title" className="border-y border-line bg-paper-deep">
      <div className="mx-auto max-w-6xl px-4 py-24 sm:px-6">
        <Eyebrow>Measured, not claimed</Eyebrow>
        <SplitText
          text="Numbers from our evaluation run."
          className="mb-10 max-w-3xl font-display text-headline tracking-tight"
        />
        <span id="proof-title" className="sr-only">
          Evaluation results
        </span>
        <dl className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          {stats.map((s, i) => (
            <Reveal key={s.label} delay={i * 0.06}>
              <div className="h-full rounded-card border border-line bg-card p-6">
                <dt className="font-mono text-xs text-muted uppercase">{s.label}</dt>
                <dd className="mt-3 font-display text-5xl tracking-tight">{s.value}</dd>
                <dd className="mt-3 text-sm text-muted">{s.detail}</dd>
              </div>
            </Reveal>
          ))}
        </dl>
        <p className="mt-6 max-w-3xl text-sm text-muted">
          Measured on {e.questions} questions about {e.documents} NIST publications ({runDate}). It
          declined {pct(e.declinesUnanswerable)} of the questions the documents can&apos;t answer,
          and cost about ${e.usdPerQuery.toFixed(4)} per question.{" "}
          <a
            href={EVAL_URL}
            className="inline-flex items-center gap-0.5 text-ink underline underline-offset-4"
          >
            Read the method <ArrowUpRight className="size-3.5" aria-hidden />
          </a>
        </p>
      </div>
    </section>
  );
}

const STEPS = [
  {
    title: "Create an account",
    body: "Sign up with your email. Your documents and chats are visible only to you.",
  },
  {
    title: "Upload PDFs",
    body: "Attach PDFs to a chat. Each one is read, split into passages and indexed in seconds.",
  },
  {
    title: "Ask questions",
    body: "Ask in plain language. Every answer cites the document and page it came from.",
  },
];

export function HowItWorks() {
  return (
    <section id="how" className="mx-auto max-w-6xl scroll-mt-20 px-4 py-24 sm:px-6">
      <Eyebrow>How it works</Eyebrow>
      <SplitText
        text="Three steps. No setup."
        className="mb-12 font-display text-headline tracking-tight"
      />
      <ol className="grid gap-4 md:grid-cols-3">
        {STEPS.map((step, i) => (
          <Reveal key={step.title} delay={i * 0.08}>
            <li className="h-full list-none rounded-card border border-line bg-card p-6 sm:p-8">
              <span className="font-display text-6xl text-accent italic" aria-hidden>
                {i + 1}
              </span>
              <h3 className="mt-6 font-display text-xl tracking-tight">{step.title}</h3>
              <p className="mt-2 leading-relaxed text-muted">{step.body}</p>
            </li>
          </Reveal>
        ))}
      </ol>
    </section>
  );
}

// Every claim here is true of the implementation; see infra/ and backend/ for each one.
const PRIVACY = [
  {
    icon: UserRound,
    title: "Yours alone",
    body: "Every document, passage and chat is stored under your account ID. No request can read another user's data.",
  },
  {
    icon: Lock,
    title: "Encrypted at rest",
    body: "Uploads are encrypted in Amazon S3, and the index and chats in Amazon DynamoDB. Traffic uses HTTPS only.",
  },
  {
    icon: FileSearch,
    title: "PDFs aren't kept",
    body: "The original file is deleted once it's indexed. Anything left in the upload area expires after a day.",
  },
  {
    icon: Trash2,
    title: "Delete anytime",
    body: "Deleting a document removes its indexed text. Deleting a chat removes its messages.",
  },
  {
    icon: KeyRound,
    title: "Model provider",
    body: "Answers are written by OpenAI's API, which doesn't train on API data by default. OpenAI keeps abuse-monitoring logs for up to 30 days.",
    link: OPENAI_POLICY_URL,
  },
];

export function Privacy() {
  return (
    <section id="privacy" className="mx-auto max-w-6xl scroll-mt-20 px-4 pb-24 sm:px-6">
      <Card className="bg-ink text-paper sm:p-12">
        <p className="mb-4 font-mono text-xs tracking-wide text-paper/60 uppercase">
          Private by design
        </p>
        <SplitText
          text="Your documents stay yours."
          className="mb-10 max-w-3xl font-display text-headline tracking-tight"
        />
        <ul className="grid gap-x-8 gap-y-8 sm:grid-cols-2 lg:grid-cols-3">
          {PRIVACY.map((p) => (
            <li key={p.title}>
              <p.icon className="mb-3 size-5 text-marker" aria-hidden />
              <h3 className="font-medium">{p.title}</h3>
              <p className="mt-1.5 text-sm leading-relaxed text-paper/70">
                {p.body}
                {p.link && (
                  <>
                    {" "}
                    <a href={p.link} className="text-paper underline underline-offset-4">
                      OpenAI&apos;s policy
                    </a>
                  </>
                )}
              </p>
            </li>
          ))}
        </ul>
      </Card>
    </section>
  );
}

export function Closing() {
  return (
    <section className="mx-auto max-w-6xl px-4 pb-24 text-center sm:px-6">
      <SplitText
        text="Ask your first question."
        emphasis={["first"]}
        className="mx-auto max-w-3xl font-display text-headline tracking-tight"
      />
      <p className="mx-auto mt-5 max-w-md text-muted">
        Free to try, with a daily allowance of questions for every account.
      </p>
      <div className="mt-8 flex justify-center">
        <Link href="/chat" className={primaryButton}>
          Start asking <ArrowRight className="size-4" aria-hidden />
        </Link>
      </div>
    </section>
  );
}

export function Footer() {
  return (
    <footer className="border-t border-line">
      <div className="mx-auto flex max-w-6xl flex-col gap-4 px-4 py-10 text-sm text-muted sm:flex-row sm:items-center sm:justify-between sm:px-6">
        <Logo />
        <nav aria-label="Footer" className="flex flex-wrap gap-x-6 gap-y-2">
          <a href={REPO_URL} className="hover:text-ink">
            Source code
          </a>
          <a href={EVAL_URL} className="hover:text-ink">
            Evaluation
          </a>
          <a href="#privacy" className="hover:text-ink">
            Privacy
          </a>
        </nav>
        <p>Built on the AWS free tier.</p>
      </div>
    </footer>
  );
}
