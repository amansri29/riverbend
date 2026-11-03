# Architecture decisions

Short records of the decisions that shape this service, in the order they were made.
Each one says what was decided, why, what it rules out, and what it costs. The three I most
want challenged are marked with ⚑.

## ADR-1 Runtime: Python 3.12, FastAPI, Pydantic v2, psycopg 3 with plain SQL, no ORM
Tenant isolation and queue bookkeeping are database features (row-level security, composite
foreign keys, conditional updates). Plain DDL in `migrations/` lets a reviewer audit them
directly. Cost: hand-written SQL and no automatic schema diffing.

## ADR-2 Two processes from one image: `api` and `worker`
The API only inserts and reads. The worker owns every model call. Both are FastAPI apps so the
worker can receive Pub/Sub push requests. Cost: one more container locally and on Cloud Run.

## ADR-3 ⚑ Tenancy: one shared schema, enforced three times
1. The API key resolves the shop; the path shop id must match it (404 otherwise, so shops
   cannot be enumerated). The request body is never trusted for tenant identity.
2. Every tenant table carries `shop_id`; uniqueness and foreign keys are composite, so a
   cross-shop reference is unrepresentable.
3. Row-level security is enabled and forced on every tenant table, keyed on a transaction-local
   setting. A forgotten WHERE clause returns only the caller's rows; a forgotten setting
   returns zero rows. Both fail closed.
The worker is scoped per job, not per process: it claims the job (ids only, outside RLS) and
then opens a tenant transaction for everything else, so even the prompt builder cannot read
another shop's messages.
Rejected: application-level filtering only (one missed clause is a leak); schema-per-shop
(migrations × shops, small isolation gain); database-per-shop (justified only by regulation).

## ADR-4 ⚑ Queue: Google Pub/Sub for delivery, Postgres outbox as the source of truth
The message row and its job row commit in one transaction (transactional outbox); the job id is
published after commit and a sweeper republishes anything left unpublished. Pub/Sub pushes into
the worker on Cloud Run, which scales on backlog with no polling. The subscription owns the
normal retry path (exponential backoff, five attempts, dead-letter topic). Two conditions
deliberately leave the broker: a budget stop and an open circuit breaker acknowledge the message
and park the job row with a run-after time, released by the sweeper, so neither burns delivery
attempts. The envelope carries ids only; customer text never enters the broker.
Locally the official emulator runs in Compose with the same client code.
Rejected: Postgres-only SKIP LOCKED queue (fewer parts, but a different mechanism locally vs
production and the first thing to replace at scale, see `ai-decisions-log.md`); RabbitMQ
(self-hosted on GCP); Redis/Celery (Memorystore + VPC connector, not durable by default);
Cloud Tasks (no official emulator, though its per-queue rate limits are the right tool for
per-shop fairness later).

## ADR-5 ⚑ LLM integration: one structured call, no agent framework
The "agent" makes one decision per message: produce a work order, ask one question, flag for
staff, or no work order. That is a flat Pydantic schema returned through Azure OpenAI
structured outputs, behind a `LLMProvider` interface (Azure implementation, fake
implementation for tests, record/replay for offline runs). Policy lives in `decide()`, a pure
function, not in the prompt. The conversation state that must survive between a question and a
reply is a work-order row, which must exist anyway.
Rejected: LangGraph (a second state machine with its own checkpointer next to the row we already
need; the right tool if this grows into open-ended multi-turn triage with tools); LangChain,
Instructor, Semantic Kernel (dependency weight for one call). Model portability comes from the
interface plus the 40-sample run as a regression suite, not from a framework.

## ADR-6 The model picks, code computes: prices and dates
The prompt contains catalog codes and names, never prices. The model returns codes with
quantities; `pricing.estimate()` computes line items and the total from the catalog file,
whose hash is pinned on every order. The model also never resolves a date: it classifies the
phrase into a typed expression (weekday + part of day, relative days, absolute, month, vague)
and `dates.resolve()` computes the date against the received timestamp. Validation rejects
unknown codes, quantities outside 1–4, and past dates. The injection sample (m-1024) is a test:
total stays 45.00 and urgency stays normal.

## ADR-7 Follow-up: one question, enforced by the state machine
Required fields are at least one mappable service and some date information (month-level
counts). `questions_asked` on the order is the invariant; the prompt cannot override it. The
reply arrives through the same ingest endpoint with `in_reply_to`; the resume job rebuilds the
transcript from stored rows as real chat turns and re-extracts the whole order (no merge
logic). A second question is unreachable; the next stop is needs-review.

## ADR-8 Special intents go to staff, never auto-acted
Wrong shop → needs review in the receiving shop (moving it would be the only cross-tenant write
in the system). Cancellation → match an open same-shop order by extracted customer name within
the day, flag for confirmation. Price inquiry → no work order; the priced answer is recorded.

## ADR-9 Spend cap: a ledger with atomic reservation
Every call writes an `llm_calls` row (tokens, cost from a config price table, latency,
outcome, validation errors). Before a call, one conditional UPDATE on the shop's monthly
budget row reserves the worst case (prompt tokens + max output tokens) and fails if it would
exceed the cap; after the call it settles to actual. At the cap the job parks, the order goes
to needs review with reason `budget_cap`, the customer sees "received, a staff member will
review", and the shop's list shows cap, spent, exhausted.

## ADR-10 Provider failure: timeouts, bounded retries, breaker that defers
SDK auto-retry is off so the policy is ours. Per-call timeout; Pub/Sub retries with backoff
up to five attempts, then dead-letters into a failed outcome on the message. Three consecutive
provider failures open an in-process breaker for 60 s; while open, jobs park instead of
retrying. The customer always gets a 202 and a status page; the shop's list carries
`ai.degraded` and the number of messages waiting. `LLM_FAULT=down|slow|garbage` reproduces
all of it.

## ADR-11 Config and secrets from the environment only
pydantic-settings with a committed `.env.example`. Locally Compose reads an uncommitted
`.env`; on GCP Secret Manager injects into Cloud Run. No key is ever in the repo.

## ADR-12 Observability is the ledger plus structured logs
Every log line and ledger row carries shop, message, and job ids. The results table is
generated from the ledger and order statuses by `scripts/run_samples.py`, never typed.
