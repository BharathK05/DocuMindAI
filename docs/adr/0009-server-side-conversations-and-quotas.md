# 9. Server-side conversations, a context budget, and check-then-charge quotas

- **Status:** accepted (2026-09-25)

## Context
Multi-turn chat needs history, and there are three risks:
- **Forged history.** If the client sends it, it can invent past "assistant" turns (a prompt-injection path).
- **Growing cost.** Resending history grows the prompt, and the bill, with every turn.
- **Abuse.** Each user, and all users together, must be held to a daily budget without a lock or a reservation system.

## Decision
- **History on the server.** Conversations and messages are stored in DynamoDB (`CONV#`, `MSG#<id>#<index>`).
  - Message indexes are allocated with an atomic counter, so concurrent turns can't collide.
  - Clients may still send stateless `history`, but never system messages.
- **Context budget of 16k tokens,** counted with `tiktoken`:
  - at 90% of the budget, older turns are **summarised by the model** into a running summary;
  - if that fails, the oldest turns are dropped;
  - the response then carries a notice, and the UI shows it.
  - The summary is given the *assistant* role, not *system*, so text derived from user content never gains system authority.
- **Auto titles.** After a conversation's first answer, a low-effort model call writes a 3–7 word title. It's charged to the user and falls back to the question.
- **Quotas: check, then charge.**
  - Before a request, the user's daily tokens are checked, and the service-wide total if a cap is set.
  - After the request, the real usage is added with DynamoDB `ADD`, which is atomic.
  - A user can overshoot by at most one request, and the service cap by the requests in flight. That trade avoids reservations or locks.
  - Aborted streams are charged an estimate, because OpenAI bills generated tokens anyway.
- **Rate limits.** Fixed-window counters in DynamoDB with conditional updates, so they hold across Lambda instances.

## Consequences
**Good:**
- **Nothing to forge.** History can't be tampered with.
- **Bounded prompt size and cost per turn.**
- **Clear, honest limits.** `429` responses with `Retry-After` and the reset time. The context and quota bars in the UI come straight from these numbers.

**Bad:**
- **Extra reads and writes.** Every question does a few small DynamoDB operations (~4 ms each, measured).
- **Summaries lose detail.** Very long chats may forget specifics.

## Alternatives considered
| Option | Why not |
|---|---|
| Client-held history only | Forgeable; the server can't measure or manage context |
| Reserve an estimate before each request | More writes and refund logic, for a one-request precision gain |
| Token-bucket rate limiting | More state per user; a fixed window is enough at this scale |
