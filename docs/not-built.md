# Not built

What I cut, what I would build next, and what breaks first at 100 shops. Everything here is a
deliberate choice against the 8-hour budget, not something I forgot.

## Cut from this submission

- **Channel adapters.** The ingest endpoint and the outbound_messages table are the contract;
  the email webhook mapping (Message-ID → message_id, recipient → shop, In-Reply-To →
  in_reply_to) and actually sending the follow-up question are not implemented.
- **Customer identity.** Replies are correlated by an explicit `in_reply_to`. A reply with no
  reference, and cancellation matching, fall back to the extracted sign-off name within the same
  shop and day, flagged for staff rather than acted on. A real system needs a customer record
  keyed by channel identity.
- **Staff actions.** There is no API to accept, cancel, transfer, or edit an order, or to raise a
  cap. Those are a SQL update today (documented in `failure-demos.md`). An admin surface with its
  own auth is the first thing a shop would ask for.
- **Operator view across shops.** By design the tenant API cannot aggregate across shops; an
  internal dashboard with a bypass role is not built.
- **Shared breaker state.** The circuit breaker is per worker instance. Fine at one instance;
  at scale it belongs in a shared store so all instances open together.
- **Reservation reconciliation.** If a worker dies between reserving budget and settling it, the
  reservation row stays `reserved`. A sweep that releases reservations older than the lease is
  a ten-line addition I did not get to.
- **Content-hash duplicate detection.** Same text under a different message id is treated as a
  new message, which is the contract. A soft "possible duplicate" flag for staff would be cheap.
- **Per-shop fairness in the worker.** See below.
- **Evaluation beyond the 40 samples.** The samples run is the regression suite for a prompt or
  model change; there is no graded eval set with expected extractions per message.
- **Infra polish.** Cloud SQL on a private IP with a VPC connector (the connector path is used
  instead), Terraform remote state, a CI pipeline running the tests, queue-depth as a custom
  metric, key rotation for shop API keys, rate limiting on ingest.
- **A second model provider.** The interface is one file per provider; only Azure OpenAI and the
  fake exist.

## Build next, in order

1. Email adapter and outbound delivery, because without it the follow-up question never
   reaches anyone.
2. Staff actions API (confirm, cancel, raise cap) with its own role, because every needs-review
   state currently ends at a SQL prompt.
3. Customer identity, so replies and cancellations match on something stronger than a name.
4. A graded eval set from the first few hundred real messages, with the per-message expected
   outcome, so model and prompt changes are measured instead of eyeballed.
5. LangGraph or equivalent, only if the product grows into multi-turn triage with tools
   (availability lookup, customer history). That is the written trigger.

## What breaks first at 100 shops

1. **Fairness.** One shop's burst fills every worker slot and the other 99 wait. Fix: a per-shop
   in-flight cap in the claim path, or Cloud Tasks queues per shop with rate limits.
2. **Database connections.** Cloud Run instances × pool size exceeds Cloud SQL's limit well
   before CPU does. Fix: a pooler (Cloud SQL has one built in) and smaller per-instance pools.
3. **The breaker and the degraded signal** are per instance and per shop respectively; at
   scale both need a shared view, or one outage looks like 100 separate ones.
4. **The sweeper** loops over shops for expiry every minute. Fix: one statement under a bypass
   role, or a per-shop schedule.
5. **One global catalog.** Shops will want their own prices. The order already pins a catalog
   version; the catalog needs a shop dimension.
6. **One subscription.** Urgent and routine work share a queue. Fix: a subscription per priority
   class, which the dispatcher interface already allows.

Tenancy is not on this list. The data boundary holds unchanged at 100 shops; shared compute is
what gives way.
