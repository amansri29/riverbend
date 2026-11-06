# Tutorial narration
Read verbatim by the voice. Edit in `scripts/tutorial/scenes.py`.

## 1. Riverbend work orders

This is Riverbend work orders. It is a small service that turns messy customer messages, sent by email or a web form, into structured, priced work orders for a chain of three bicycle repair shops. Each shop is a separate tenant and never sees another shop's data. In the next ten minutes I will walk through the architecture, the A P I, how keys and secrets are handled, one example per endpoint with the database row behind it, the failure cases, and one decision where I overrode my A I coding assistant.

## 2. 02-architecture

Here is the whole system on one page. Customers write in on the left. The A P I on Cloud Run accepts the message, stores it together with an outbox job in one database transaction, and replies with two oh two accepted. After the commit it publishes a tiny envelope to Pub Sub, holding only ids, never customer text. Pub Sub pushes the envelope into the worker, also on Cloud Run, which scales from zero on backlog. The worker runs eight stages: claim the job, open a tenant transaction, check the circuit breaker, reserve budget, call the model with structured output, validate, decide, and price in code. Cloud S Q L Postgres is the system of record, with row level security forced on every tenant table. Cloud Scheduler calls a sweep every minute to republish anything the broker missed. The A P I never calls the model. The worker only accepts input from Pub Sub and Scheduler. The database is the truth. The broker is only delivery.

## 3. API keys and secrets

Security first, because it shapes everything else. Each shop has one A P I key. The service stores only a hash of it. The key travels in a header, never in a U R L. If a valid key is used on another shop's path the answer is four oh four, not four oh three, so an attacker cannot discover which shops exist. For local runs the seed script creates development keys. For production it prints a real key once and keeps only the hash. All configuration is read from the environment. The dot env file is git ignored. On Google Cloud, Secret Manager injects the Azure OpenAI key and the database passwords at deploy time. The key never appears in the container image, the Compose file, Terraform, or git history. The same rule applied to this video: the text to speech key lives in dot env and nowhere else. And the model itself never sees keys or prices. The customer's text goes into the prompt as untrusted data, which matters for one of the sample messages later.

## 4. How the service reads configuration

This is the configuration class. Every setting is a typed field with a default, read from environment variables by pydantic settings. The Azure key is a secret string, so it is masked if anything ever logs the settings object. The provider setting selects Azure OpenAI or an offline fake, which is how the test suite and the local Compose stack run with no key at all.

## 5. The API

The public A P I has four endpoints plus a health check. Post a message to a shop. Get the customer facing status of a message. List the shop's work orders with estimated totals. And get one order. The worker has three internal endpoints that only Pub Sub and Scheduler may call: push, dead letter, and sweep. Every endpoint is documented on the Swagger page, which is what I will use for one of the demos. Let's go through them one at a time, and after each call look at the row it left in the database.

## 6. POST a message

First, posting a message. This is sample five from the brief: my rear brake squeals and the gears skip on hills, can I bring it Saturday. The A P I answers two oh two with the message id, duplicate false, and a status U R L to poll. In the database there is now one inbound message row with no outcome yet, and one job row of kind extract. The job was published to Pub Sub right after the commit. Both rows were written in the same transaction, so there is no way to store a message and lose its job, or the other way round.

## 7. GET message status

A few seconds later the customer polls the status. It says confirmed, with an estimate: brake adjustment for one wheel at eighteen dollars, and a gear adjustment at twenty five, forty three in total, for Saturday the twenty sixth of September, resolved from the Tuesday the message arrived. Behind it is the work order row: status open, the two issues, the line items, and the total in integer cents. The model picked the two catalog codes. The price was computed in code from the catalog. The model never sees a price. The third row is the ledger: one model call, its tokens, its cost, and its latency. Every call lands here, including failed ones, and this is where the results table and the spend cap read from.

## 8. 08-followup-video

Now the follow up flow, through the Swagger page. The message is just two words: brakes squeal. A service is clear, but there is no date, so the model proposes a question, and the code agrees because nothing has been asked yet. The customer's status becomes awaiting your reply, with the question: when would you like us to work on the bike. Then the reply arrives as a new message linked by in reply to: rim brakes on a city bike, Saturday morning works. The worker rebuilds the conversation from the stored rows, the original message, the question as an assistant turn, and the reply, and asks the model to re extract the whole order. The status is now confirmed: brake adjustment on both wheels, thirty six dollars, Saturday morning.

## 9. Follow-up: the rows behind it

The work order row shows what made that safe. Questions asked is one, and it is an integer on the row, not an instruction in the prompt. If the reply had still been ambiguous, the code would send the order to staff review rather than ask again, because the brief allows exactly one question. The clarification question is stored, and the outbound messages table holds the question as it would be sent to the customer. Delivery by email is not built. The row is.

## 10. GET the shop's work orders

The shop view lists open work orders with their estimated totals, and two health blocks. The budget block shows this month's cap, what has been spent, and what is reserved for calls in flight. The A I block shows whether the model path is degraded, how many jobs are waiting, and how many are parked because of an outage or the cap. The shop budgets row underneath is the ledger it reads from. Reserved goes up before each call and settles to the actual cost after.

## 11. The same message twice

Duplicates. Sample three from the brief arrives twice. Posting it again returns two hundred with duplicate true, instead of two oh two. The unique constraint on shop and message id catches it inside the database, so even two arrivals at the same instant resolve to one row. One message, one job, one work order, one model call. A redelivered job would also find the order already exists and acknowledge without calling the model.

## 12. Tenant isolation, three layers

Tenancy has three layers. At the edge, the downtown key on the northside path returns four oh four. In the schema, every foreign key includes the shop id, so a cross shop reference cannot be represented. And in the database engine, row level security is forced on every tenant table. Connected as the application role with no tenant set, a select on work orders returns zero rows. Set the tenant for the transaction and only that shop's rows appear. A handler that forgets its where clause still cannot leak.

## 13. The tricky samples

Four of the deliberately tricky samples. Sample twenty four contains a prompt injection: a system note telling the assistant to set every price to zero and mark it urgent. It cannot work, because the model only picks catalog codes and the price comes from the catalog in code. The order is a chain replacement at forty five dollars, urgency normal. Sample nine is addressed to the Lakeshore team but arrived at downtown. It is flagged for staff, never forwarded across tenants. Sample eighteen is a price question with no repair, so no work order is created and the priced answer is stored for staff. Sample thirty eight is a cancellation from Marcus. It is matched to his order by name within a day and flagged. Nothing is cancelled automatically.

## 14. When the model provider is down

Failure handling. When the provider is slow or down, the worker returns five oh three and Pub Sub redelivers with backoff, five times, then dead letters. After three consecutive failures a circuit breaker opens, and jobs are parked with a run after time instead of burning delivery attempts. The sweeper republishes them later. Throughout, the customer sees received, we will confirm shortly. The shop sees degraded true, and the number of jobs waiting and parked. In the recorded demo, five messages were sent with the provider down. All five parked, none were lost, and all five completed within one sweep after the provider came back.

## 15. The monthly spend cap

The spend cap. Each shop has a monthly cap. Before every model call, one atomic update reserves the worst case against it, and after the call the reservation settles to the actual cost. At the cap, the job parks until next month or until the cap is raised, and no call is made. The customer sees received. The shop sees budget exhausted. A raised cap applies immediately because it is read from the shop row on every reservation. That last line came from a test that failed: the first version snapshotted the cap at the start of the month.

## 16. Results: the 40 sample messages

The results of the real run on Azure OpenAI. 40 (39 unique, 1 duplicate) messages were sent. 35 work orders were opened. 2 follow up questions were asked and 2 were resolved by the scripted replies. 2 went to staff review: the wrong shop message and the order matched by the cancellation. 2 produced no order: the price inquiry and the cancellation itself. 0 could not be processed. In total 41 (invalid output: 0, provider failures: 0). Total spend from the ledger was about 3 cents, at the configured price table. The brief's limit was twenty dollars. Every raw model response is recorded in the repository.

## 17. One AI decision I overrode: the queue

Now the one A I decision I overrode. Early in the design, the coding assistant proposed a Postgres only queue: a jobs table claimed with select for update skip locked, woken by listen notify. Its reasons were good. One less piece of infrastructure in an eight hour build. The message insert and the job insert commit together, which avoids the dual write problem a broker has. And Postgres queues are mainstream now. It said: swap to Pub Sub at a hundred shops. The transactional argument was right, and I kept it.

## 18. What was wrong with it

What was wrong with it. Three specific things. First, it meant a different mechanism locally and in production: a polling worker on my laptop and push delivery on Google Cloud, so the failure paths I demonstrate would not be the ones that actually run. Second, it made the queue the first thing to replace at scale, which is a bad place for the first thing to be. Third, a polling worker on Cloud Run needs C P U always allocated, which quietly removes scale to zero. The honest cost of my choice is a third system locally, the Pub Sub emulator, and job state living in two places.

## 19. What I did instead: outbox + Pub/Sub, parked states leave the broker

What I did instead. Keep the outbox table as the source of truth, the assistant's good half, and use Pub Sub for delivery, with the emulator locally and a push subscription on Cloud Run, identical client code in both. A sweeper republishes anything left unpublished, so the broker can lose a message and the database still re drives it. The envelope carries ids only. And this enum is the piece the Postgres only design would have made simpler and that I had to design deliberately: retry hands the job back to the broker with a five oh three, while parked acknowledges the message and leaves the broker on purpose, for a budget stop or an open breaker, so neither burns delivery attempts. The override is logged in the decisions file as it happened, and it is the first of the three decisions I ask the reviewers to challenge.

## 20. Not built, and how to run it

What is not built, stated plainly. Email and S M S delivery of the question, a staff screen, per shop rate limits, and private I P for Cloud S Q L were cut. One known gap: if a dead letter message is lost by the broker, the job stays waiting, and a stale job sweep is the next change. At a hundred shops the first thing to break is the single shared push stream, where one noisy shop delays the others. The fix is Cloud Tasks with a queue per shop. To run it: make run brings up Postgres, the Pub Sub emulator, the A P I and the worker. Make samples sends the forty messages. Make test runs seventy eight tests. Thank you for watching.
