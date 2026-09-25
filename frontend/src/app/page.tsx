import {
  Closing,
  Footer,
  Hero,
  HowItWorks,
  Insights,
  Nav,
  Privacy,
  Proof,
  Showcase,
} from "@/components/landing/sections";

export default function Home() {
  return (
    <>
      <a
        href="#main"
        className="sr-only focus:not-sr-only focus:fixed focus:top-3 focus:left-3 focus:z-50 focus:rounded-full focus:bg-ink focus:px-4 focus:py-2 focus:text-paper"
      >
        Skip to content
      </a>
      <Nav />
      <main id="main">
        <Hero />
        <Showcase />
        <Insights />
        <Proof />
        <HowItWorks />
        <Privacy />
        <Closing />
      </main>
      <Footer />
    </>
  );
}
