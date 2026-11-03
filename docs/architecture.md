# Architecture note

Riverbend work orders turns free-text customer messages into priced, structured work orders for
three bike shops that must never see each other's data. This note covers the shape of the
system, the module boundaries, the data model, how tenancy is enforced, and the three decisions
I most want challenged. Decision records with alternatives are in `decisions.md`.

## Shape

```
 web form ──┐                       ┌──────────────────────────── API (Cloud Run) ────────────────────────────┐
            ├─► POST /shops/{id}/messages  X-API-Key → shop ──► [one tx: inbound_message + job(outbox)] ─► 202 │
 email hook ┘   GET  /shops/{id}/messages/{mid}      (customer status, no internals)                         │
                GET  /shops/{id}/work-orders        (shop list + estimated total + ai/budget health)        │
                └────────────────────────────┬──────────────────────────────────────────────────────────────┘
                                             │ publish {job_id, shop_id, kind}  (ids only, after commit)
                                             ▼
                                  Pub/Sub topic ──push──► worker /pubsub/push (Cloud Run, scale 0..N)
                                        │   retry 10s..600s ×5 ──► DLQ topic ──push──► worker /pubsub/dlq
                                        │
   Cloud Scheduler ─every minute─► worker /sweep: republish unpublished outbox rows,
                                                 release parked jobs (budget stop, breaker), expire questions
                                             │
                                             ▼
   worker pipeline:  claim job (ids) → tenant tx(shop) → breaker? → reserve budget → model (Azure OpenAI,
                     structured output) → validate (schema + rules, 1 corrective retry) → decide() →
                     price in code → write order / question / review → settle budget → ack
                                             │
                                             ▼
                     Postgres (Cloud SQL): shops · inbound_messages · work_orders · jobs(outbox) ·
                                           llm_calls (ledger) · shop_budgets · outbound_messages
                                           row-level security on every tenant table
```

Two processes from one image. The API never calls the model. The worker never accepts input
from outside Pub/Sub and Scheduler.

## Module boundaries

| Module | Owns | May call | Must not |
|---|---|---|---|
| `api/` | HTTP contract, tenant resolution from the API key | `ingest`, repositories (reads) | touch the model, trust the body for tenant identity |
| `ingest.py` | the accept transaction (message + outbox job), publish after commit | repositories, `dispatch` | block on the broker (publish failure is tolerated; the sweeper retries) |
| `dispatch.py` | moving a job id to the worker (Pub/Sub, inline, test doubles) | the broker client | carry customer text |
| `worker/pipeline.py` | the stages above, retry/park policy | `extraction`, `pricing`, `dates`, `decide`, `budget`, repositories | compute a price or a date itself |
| `extraction/` | prompt, model-facing schema, validation rules, provider interface + Azure/fake | the provider SDK | decide policy (ask/not ask) |
| `decide.py` | policy: order, one question, review, or no order | nothing (pure) | call anything |
| `pricing.py`, `dates.py` | arithmetic the model is not allowed to do | catalog | call anything |
| `repo/` | SQL per table; tenant tables are only reachable inside `tenant_tx` | psycopg | cross-table policy |

The line that matters most: **the model proposes, code disposes.** The model returns codes,
quantities, a classified date phrase, and a proposed outcome. Everything that costs money or
changes state is computed or decided by tested code.

## Data model

`shops` (id, api_key_hash, timezone, monthly_cap_micros) is the tenant. Every other table starts
with `shop_id`. `inbound_messages` is unique on `(shop_id, message_id)`, which is the
idempotency key the sender controls. `work_orders` is unique on `(shop_id, source_message_id)`,
which makes a job that runs twice a no-op. Both foreign keys are composite, so an order in one
shop cannot reference a message in another even by accident. `jobs` is the outbox and the
processing record (status, attempts, published_at, run_after, park_reason) and holds ids only.
`llm_calls` is the ledger: tokens, cost computed from a config price table, latency, outcome,
validation errors, raw output. `shop_budgets` holds spent and reserved per month; the cap is
read from `shops` on every reservation so raising it applies at once.

A work order moves `queued → processing → open | awaiting_customer | needs_review`, then
`awaiting_customer → (reply) processing → open | needs_review`, or `→ expired` after seven days.
Output that fails validation never becomes a row; the failure is recorded on the message.

## Tenancy

Three layers, each catching a different mistake. (1) The API key resolves the shop and must
match the path; a valid key on another shop's path is a 404, so shops cannot be enumerated.
(2) Composite keys make cross-shop references unrepresentable. (3) Row-level security is
enabled and *forced* on every tenant table, keyed on a transaction-local setting. A handler that
forgets its WHERE clause gets only its own rows; a code path that forgets to set the tenant
gets zero rows and can write none. The worker claims the job across shops (ids only), then
opens a tenant transaction for everything else, so even the prompt builder cannot read another
shop's text. Tests prove each layer at the SQL and HTTP level.

## Failure handling in one paragraph each

**Duplicates.** The second arrival of m-1003 hits the unique constraint and returns the existing
status with a 200. Concurrent duplicates are resolved by the database. A redelivered job finds
the order already exists and acks without a second model call.

**Provider down.** The SDK's retry is off; the worker returns 503 and Pub/Sub redelivers with
backoff, five times, then dead-letters into a failed outcome. Three consecutive failures open a
breaker; while open, jobs are acked and parked with a run-after instead of burning attempts,
and the sweeper republishes them. The customer sees "received, confirming shortly" throughout;
the shop sees `ai.degraded`, the number waiting, and the number parked.

**Spend cap.** Before each call one conditional UPDATE reserves the worst case (two calls at
max output) against the shop's month; after the call it settles to actual. At the cap the job
parks until next month or until the cap is raised, the customer sees "received", the shop sees
`budget.exhausted` and `ai.parked_budget_cap`. Every call, including failed ones, is in the
ledger, which is where the results table's spend figure comes from.

## Three decisions to challenge

1. **Pub/Sub for delivery with a Postgres outbox as the truth.** The assistant proposed a
   Postgres-only SKIP LOCKED queue; I overrode it (see `ai-decisions-log.md`). I kept the outbox
   because the dual-write problem is real, and added the broker for push delivery, backlog
   scaling, and dead-lettering. The cost is a third system locally (the emulator) and two places
   where job state lives: Pub/Sub for normal retries, the row for parked states. Challenge: is
   that split clearer or murkier than one mechanism?

2. **No agent framework; a flat structured-output schema plus a pure `decide()` function.** The
   one-question rule is an integer on the row, not a prompt instruction, and history on resume
   is three stored rows replayed as chat turns. Challenge: at what point does this stop being
   enough? My answer is when the conversation becomes open-ended and tool-driven, and the
   trigger is written down. Someone may think that point is closer than I do.

3. **Row-level security in one shared schema rather than schema-per-shop.** It makes tenant
   scoping a database guarantee rather than a code convention and costs almost nothing at this
   size. Challenge: the worker and the sweeper run under one database role and switch tenants
   per transaction. A reviewer may prefer a separate role per shop or per-shop schemas for
   auditability at 100 shops.
