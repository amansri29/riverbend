# Loom talk track: "one AI decision I overrode"

Target 7 minutes. Screen: this repo in the editor, a terminal, and `docs/ai-decisions-log.md`
open. Speak plainly; the brief says they watch this before reading any code.

## 0:00 – 0:40  Frame it

- "The brief asks for one AI decision I overrode. Mine is the job queue. The coding assistant
  proposed a Postgres-only queue. I kept half of its argument and rejected the other half."
- Show `docs/ai-decisions-log.md`, entry 1, so they see it was logged as it happened.

## 0:40 – 2:10  The proposal, fairly

Show the assistant's proposal as it was made (quote the log):

- A `jobs` table claimed with `SELECT … FOR UPDATE SKIP LOCKED`, woken by `LISTEN/NOTIFY`.
- Its reasons: one less piece of infrastructure in an eight-hour build; the message insert and
  the job insert commit together, which avoids the dual-write problem a broker has; Postgres
  queues are mainstream now (Rails 8 default, Oban, pg-boss); "swap to Pub/Sub at 100 shops".
- Say what was right: the transactional argument. A message accepted but never queued, or
  queued but never stored, is exactly the duplicate-and-loss bug the brief is probing.

## 2:10 – 4:00  What was wrong with it

Three specific reasons, not a taste preference:

1. **Different mechanism locally and in production.** The brief wants a GCP deployment path.
   A polling worker locally and a push subscription on GCP means the failure paths I demo on my
   laptop are not the ones that run in production. I wanted one client code path in both.
2. **The queue would be the first thing to replace.** "Swap at 100 shops" puts the replacement
   in the hot path of growth. The not-built list should name what breaks first; it should not
   be the queue.
3. **Cloud Run economics.** A polling worker needs always-allocated CPU, which quietly removes
   scale-to-zero. Push delivery scales the worker on backlog and idles at zero.

Mention the honest cost: a third system locally (the emulator), and job state in two places.

## 4:00 – 6:00  What I did instead, in the code

Walk the path with the editor open:

- `app/ingest.py`: one transaction inserts the message and the outbox job; publish happens
  after commit; a failed publish is tolerated.
- `app/worker/sweeper.py`: republishes anything left unpublished, so the outbox is the truth
  and the broker is only delivery.
- `app/dispatch.py`: the envelope is `{job_id, shop_id, kind}`. Customer text never enters the
  broker.
- `app/worker/pipeline.py`, `JobResult`: `RETRY` returns 503 and lets Pub/Sub back off and
  dead-letter; `PARKED` acks and leaves the broker for a budget stop or an open breaker, so
  neither burns delivery attempts. This is the piece the Postgres-only design would have made
  simpler, and the piece I had to design deliberately.
- `infra/terraform/pubsub.tf`: the same topic, push subscription, retry policy and dead-letter
  topic, as code.

## 6:00 – 6:45  Show it running

Terminal, from `docs/failure-demos.md` section 2 or 3: worker started with `LLM_FAULT=down`,
five messages, jobs parked, customer sees "received", shop sees `degraded: true` and the count
parked; restart healthy, all five done. Thirty seconds of real output beats a slide.

## 6:45 – 7:15  Close

- "The assistant was right about the transaction and wrong about the conclusion, because it
  optimised for the fewest parts in eight hours rather than for the system I would defend."
- "The override is logged, the alternative is in the decisions file as rejected with reasons,
  and the three decisions I most want challenged in the note start with this one."

## If asked on the call

- Why not Cloud Tasks? No official emulator; its per-queue rate limits are the right tool for
  per-shop fairness later, and it is on the build-next list.
- Why not Redis or RabbitMQ on GCP? Memorystore needs a VPC connector and is not durable by
  default; RabbitMQ is self-hosted. Both are more operations for less than Pub/Sub gives here.
- Where does the design strain? Job state in two places. The row says parked, the broker says
  nothing; the row says published, the broker owns retries. The sweeper is the reconciler.
