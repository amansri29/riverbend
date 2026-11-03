# AI decisions log

Every place where an AI tool (the coding assistant, or the extraction model itself) proposed
something and I rejected or changed it. Kept as it happened, for the Loom and for the
follow-up call. Newest at the bottom.

## 1. Queue: assistant proposed a Postgres-only job table; I chose Pub/Sub with an outbox
**Proposal.** Claude Code recommended a `jobs` table claimed with `SELECT … FOR UPDATE SKIP
LOCKED`, woken by LISTEN/NOTIFY, as the whole queue: "one less piece of infrastructure, the
message insert and the job insert commit together, swap to Pub/Sub at 100 shops." It argued
that a broker without an outbox has the dual-write problem and that Postgres queues are now
mainstream (Rails 8 default, Oban, pg-boss).
**What was wrong with it.** The transactional argument was right, but the conclusion
optimised for the fewest moving parts in an 8-hour build rather than for the system I'd
actually be asked to defend. It meant a different delivery mechanism locally (polling) versus
production (the brief wants a GCP plan), and it made the queue itself the first thing to
replace at scale, which is a bad place for the first thing to be. A polling worker on Cloud
Run also needs always-allocated CPU, which quietly removes scale-to-zero.
**What I did instead.** Keep the outbox table as the source of truth (the assistant's good
half) and use Pub/Sub for delivery: emulator in Compose locally, push subscription into the
worker on GCP, identical client code in both. Budget stops and breaker-open conditions park
the row and leave the broker, so they don't burn delivery attempts. The assistant then
restated the design correctly and we proceeded.

## 2. Model: assistant defaulted to Anthropic Claude; I chose Azure OpenAI
Minor. The assistant's recommendation was driven by its own defaults; the deciding factor was
that we hold Azure credentials and the provider sits behind an interface either way.

## 3. Framework: I proposed LangGraph; assistant argued against; I agreed
Recorded for completeness because it went the other way. I wanted model portability and a
clear way to decide when to ask a follow-up and how to feed history. The assistant showed
that portability comes from the provider interface, the ask/no-ask policy is a pure function
over persisted state, and history is three rows we already store. LangGraph stays on the
"build next" list with a stated trigger: open-ended multi-turn triage with tools.
