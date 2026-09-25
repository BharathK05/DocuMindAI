// Copies the headline numbers (and one real answer) from the evaluation harness's results
// file into src/data/eval.json, so the landing page's "proof" section can't drift from what
// was measured. Runs before every dev/build; CI fails if the committed copy is stale.
import { existsSync, readFileSync, writeFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const RESULTS = "../backend/evals/results/structured-hybrid-prompt2-rerank.json";
const SAMPLE_ID = "id-05"; // a real, correct, single-source answer for the demo card

const root = resolve(dirname(fileURLToPath(import.meta.url)), "..");
if (!existsSync(resolve(root, RESULTS))) {
  // Hosts that build only the frontend/ folder (e.g. Vercel) can't see backend/; the committed
  // copy is used as is. CI builds with the full repo, so it still catches a stale copy.
  console.log(`eval.json: ${RESULTS} not found, keeping the committed copy`);
  process.exit(0);
}
const run = JSON.parse(readFileSync(resolve(root, RESULTS), "utf8"));
const s = run.summary;
const row = run.rows.find((r) => r.id === SAMPLE_ID);
if (!row) throw new Error(`sample ${SAMPLE_ID} not found in ${RESULTS}`);
const [file, page] = row.retrieved[0];

const data = {
  source: RESULTS.replace("../", ""),
  runAt: run.created_at,
  questions: s.questions.answerable + s.questions.unanswerable,
  documents: s.corpus.documents,
  recallAt5: s.retrieval["recall@5"],
  mrrAt10: s.retrieval["mrr@10"],
  correctness: s.answers.correctness,
  faithfulness: s.answers.faithfulness,
  declinesUnanswerable: s.answers.declines_unanswerable,
  p50LatencyMs: s.latency_ms.end_to_end_p50,
  p95LatencyMs: s.latency_ms.end_to_end_p95,
  usdPerQuery: s.tokens_per_query.usd,
  sample: { question: row.question, answer: row.answer, citation: { file, page } },
};

writeFileSync(resolve(root, "src/data/eval.json"), `${JSON.stringify(data, null, 2)}\n`);
console.log(`eval.json ← ${data.source}`);
