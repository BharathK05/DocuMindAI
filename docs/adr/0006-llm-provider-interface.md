# 6. LLM provider behind an interface; OpenAI models from config

- **Status:** accepted (2026-09-24)

## Context
The prototype called Gemini directly from the app code. The upgrade moves to OpenAI, but the choice of vendor and model will keep changing, for price, quality or data-residency reasons. The tests must also run without network access or API keys.

## Decision
- **Interfaces.** Business logic depends only on two small protocols in `providers/base.py`:
  - `EmbeddingProvider.embed(texts)`;
  - `LLMProvider.complete(...)` and `LLMProvider.stream(...)`.
- **Implementations:** `openai_provider.py`, and `fake.py`, a deterministic offline provider for tests, local runs and load tests.
- **Models from config:**
  - answers: `chat_model=gpt-6-luna`, a reasoning model run with effort `low`;
  - reranking: effort `none`;
  - embeddings: `embedding_model=text-embedding-3-small` at 1,536 dimensions.
- **Prices from config too,** so cost logging and quotas follow a model change.
- **Resilience.** SDK retries with backoff for 408/409/429/5xx, a 30 s timeout, and bounded concurrency for embedding batches. Provider errors map to a single `ProviderError`, which the API returns as 503.

## Consequences
**Good:**
- **Switching vendor is one class plus one line in the factory.** Amazon Bedrock, for example.
- **Tests are fast and deterministic, and need no keys.**
- **Load tests cost $0.** The fake provider takes a simulated delay and a vector size.

**Bad:**
- **Lowest-common-denominator API.** Provider-specific features, such as structured outputs or prompt caching controls, need interface changes.
- **Old vectors are incompatible with a new embedding model.** Changing it means re-embedding every document; there's no mixed-model index.

## Alternatives considered
| Option | Why not |
|---|---|
| LangChain / LlamaIndex | Large dependency trees that would break the Lambda package budget; the pipeline is small enough to own |
| Direct SDK calls in services | Couples business logic to one vendor; tests would need network mocks |
