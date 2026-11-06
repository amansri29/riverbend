"""Scene list for the tutorial video: narration text plus the visual for each scene.

Every scene becomes one mp4 segment: the narration audio over a rendered slide, a captured
terminal transcript, an image, or a recorded clip. Edit the narration here; `build.py` does the
rest. Narration is read verbatim by the voice, so write it to be spoken.
"""

from __future__ import annotations

K = "dev-key-rb-downtown"
A = "http://localhost:8080"
DB = "postgresql://aman.srivastav@localhost:5432/riverbend"
APPDB = "postgresql://riverbend_app:riverbend_app@localhost:5432/riverbend"


def psql(sql: str, url: str = DB) -> str:
    return f'psql {url} -x -c "{sql}"'


# Commands run by `build.py capture` (needs the stack running). Output is stored under captures/.
CAPTURES: dict[str, list[tuple[str, str]]] = {
    "post": [
        (
            f"curl -s -X POST {A}/shops/rb-northside/messages -H 'X-API-Key: dev-key-rb-northside' "
            '-H \'content-type: application/json\' -d \'{"message_id":"tut-1005","channel":"email",'
            '"received_at":"2026-09-22T08:30:00","body":"My rear brake squeals and the gears skip on hills, '
            "can I bring it Saturday?\"}' | python3 -m json.tool",
            "post.txt",
        ),
        (
            psql(
                "SELECT message_id, channel, received_at, outcome FROM inbound_messages WHERE message_id = 'tut-1005'"
            ),
            "post_row.txt",
        ),
        (
            psql(
                "SELECT j.kind, j.status, j.attempts, j.published_at IS NOT NULL AS published FROM jobs j "
                "JOIN inbound_messages m ON m.id = j.message_pk WHERE m.message_id = 'tut-1005'"
            ),
            "post_job.txt",
        ),
    ],
    "status": [
        (
            f"sleep 8; curl -s {A}/shops/rb-northside/messages/tut-1005 -H 'X-API-Key: dev-key-rb-northside' "
            "| python3 -m json.tool",
            "status.txt",
        ),
        (
            psql(
                "SELECT status, bike_type, issues, urgency, requested_date, line_items, estimated_total_cents "
                "FROM work_orders w JOIN inbound_messages m ON m.id = w.source_message_id "
                "WHERE m.message_id = 'tut-1005'"
            ),
            "status_order.txt",
        ),
        (
            psql(
                "SELECT c.model, c.outcome, c.input_tokens, c.output_tokens, c.cost_micros, c.latency_ms "
                "FROM llm_calls c JOIN inbound_messages m ON m.id = c.message_pk WHERE m.message_id = 'tut-1005'"
            ),
            "status_ledger.txt",
        ),
    ],
    "followup_rows": [
        (
            psql(
                "SELECT status, questions_asked, clarification_question, bike_type, requested_date, date_note, "
                "estimated_total_cents FROM work_orders w JOIN inbound_messages m ON m.id = w.source_message_id "
                "WHERE m.message_id = 'ui-1027'"
            ),
            "followup_order.txt",
        ),
        (
            psql(
                "SELECT o.channel, o.body, o.created_at FROM outbound_messages o JOIN work_orders w ON w.id = o.work_order_id "
                "JOIN inbound_messages m ON m.id = w.source_message_id WHERE m.message_id = 'ui-1027'"
            ),
            "followup_outbound.txt",
        ),
    ],
    "list": [
        (
            f"curl -s '{A}/shops/rb-downtown/work-orders' -H 'X-API-Key: {K}' | python3 -c \"import sys, json; "
            "d = json.load(sys.stdin); print('count', d['count']); print('budget', d['budget']); print('ai', d['ai']); "
            "[print(' ', w['message_id'], w['status'], w['bike_type'], w['requested_date'], w['estimate']['total']) "
            "for w in d['work_orders'][:6]]\"",
            "list.txt",
        ),
        (
            psql(
                "SELECT month, cap_micros, reserved_micros, spent_micros FROM shop_budgets WHERE shop_id = 'rb-downtown'"
            ),
            "list_budget.txt",
        ),
    ],
    "duplicate": [
        (
            f"curl -s -i -X POST {A}/shops/rb-lakeshore/messages -H 'X-API-Key: dev-key-rb-lakeshore' "
            '-H \'content-type: application/json\' -d \'{"message_id":"m-1003","channel":"email",'
            '"body":"The chain on my hybrid keeps falling off when I shift to the small ring. Free Saturday. Marcus"}\' '
            "| grep -E 'HTTP|duplicate'",
            "duplicate.txt",
        ),
        (
            psql(
                "SELECT count(*) AS messages, (SELECT count(*) FROM work_orders w JOIN inbound_messages m "
                "ON m.id = w.source_message_id WHERE m.message_id = 'm-1003') AS work_orders "
                "FROM inbound_messages WHERE message_id = 'm-1003'"
            ),
            "duplicate_rows.txt",
        ),
    ],
    "tenancy": [
        (
            f"curl -s -i {A}/shops/rb-northside/work-orders -H 'X-API-Key: {K}' | head -1",
            "tenancy_404.txt",
        ),
        (
            f'psql {APPDB} -c "SELECT count(*) AS visible_rows FROM work_orders"',
            "tenancy_zero.txt",
        ),
        (
            f"psql {APPDB} -c \"SELECT set_config('app.shop_id', 'rb-downtown', false); "
            'SELECT shop_id, count(*) AS visible_rows FROM work_orders GROUP BY 1"',
            "tenancy_scoped.txt",
        ),
    ],
    "tricky": [
        (
            f"for m in m-1024 m-1009 m-1018 m-1038; do curl -s {A}/shops/rb-downtown/messages/$m -H 'X-API-Key: {K}' "
            f"| python3 -c \"import sys, json; d = json.load(sys.stdin); print(d['message_id'], '->', d['status'], '|', "
            "d['message'], '| total', d['estimate']['total'] if d['estimate'] else '-')\"; done",
            "tricky.txt",
        ),
        (
            psql(
                "SELECT m.message_id, m.outcome, left(m.outcome_detail, 90) AS detail FROM inbound_messages m "
                "WHERE m.message_id IN ('m-1024','m-1009','m-1018','m-1038') ORDER BY 1"
            ),
            "tricky_rows.txt",
        ),
    ],
}


SCENES: list[dict] = [
    {
        "id": "01-title",
        "kind": "slide",
        "title": "Riverbend work orders",
        "subtitle": "Messy customer messages in. Priced, structured work orders out. Three shops, one service.",
        "narration": (
            "This is Riverbend work orders. It is a small service that turns messy customer messages, "
            "sent by email or a web form, into structured, priced work orders for a chain of three bicycle "
            "repair shops. Each shop is a separate tenant and never sees another shop's data. "
            "In the next ten minutes I will walk through the architecture, the A P I, how keys and secrets "
            "are handled, one example per endpoint with the database row behind it, the failure cases, "
            "and one decision where I overrode my A I coding assistant."
        ),
    },
    {
        "id": "02-architecture",
        "kind": "image",
        "image": "docs/architecture.png",
        "narration": (
            "Here is the whole system on one page. Customers write in on the left. The A P I on Cloud Run "
            "accepts the message, stores it together with an outbox job in one database transaction, and "
            "replies with two oh two accepted. After the commit it publishes a tiny envelope to Pub Sub, "
            "holding only ids, never customer text. Pub Sub pushes the envelope into the worker, also on "
            "Cloud Run, which scales from zero on backlog. The worker runs eight stages: claim the job, open "
            "a tenant transaction, check the circuit breaker, reserve budget, call the model with structured "
            "output, validate, decide, and price in code. Cloud S Q L Postgres is the system of record, with "
            "row level security forced on every tenant table. Cloud Scheduler calls a sweep every minute to "
            "republish anything the broker missed. The A P I never calls the model. The worker only accepts "
            "input from Pub Sub and Scheduler. The database is the truth. The broker is only delivery."
        ),
    },
    {
        "id": "03-security",
        "kind": "slide",
        "title": "API keys and secrets",
        "bullets": [
            "One API key per shop. Only the SHA-256 hash is stored, never the key.",
            "The key travels in the X-API-Key header, never in a URL or query string.",
            "Valid key on another shop's path: 404. Shops cannot be enumerated.",
            "Dev keys are seeded for local runs. Production keys are printed once at seed time.",
            "All configuration from the environment. The .env file is git-ignored.",
            "On GCP: Secret Manager injects the Azure key and database passwords at deploy.",
            "No key in the image, Compose file, Terraform, or git history.",
            "The model sees neither keys nor prices. The customer text is untrusted data in the prompt.",
        ],
        "narration": (
            "Security first, because it shapes everything else. Each shop has one A P I key. The service "
            "stores only a hash of it. The key travels in a header, never in a U R L. If a valid key is used "
            "on another shop's path the answer is four oh four, not four oh three, so an attacker cannot "
            "discover which shops exist. For local runs the seed script creates development keys. For "
            "production it prints a real key once and keeps only the hash. "
            "All configuration is read from the environment. The dot env file is git ignored. On Google "
            "Cloud, Secret Manager injects the Azure OpenAI key and the database passwords at deploy time. "
            "The key never appears in the container image, the Compose file, Terraform, or git history. "
            "The same rule applied to this video: the text to speech key lives in dot env and nowhere else. "
            "And the model itself never sees keys or prices. The customer's text goes into the prompt as "
            "untrusted data, which matters for one of the sample messages later."
        ),
    },
    {
        "id": "04-config",
        "kind": "code",
        "title": "How the service reads configuration",
        "file": "app/config.py",
        "lines": [30, 44],
        "narration": (
            "This is the configuration class. Every setting is a typed field with a default, read from "
            "environment variables by pydantic settings. The Azure key is a secret string, so it is masked "
            "if anything ever logs the settings object. The provider setting selects Azure OpenAI or an "
            "offline fake, which is how the test suite and the local Compose stack run with no key at all."
        ),
    },
    {
        "id": "05-api",
        "kind": "slide",
        "title": "The API",
        "bullets": [
            "POST /shops/{shop}/messages — accept a message, 202 new or 200 duplicate",
            "GET /shops/{shop}/messages/{id} — customer-facing status, no internals",
            "GET /shops/{shop}/work-orders — the shop's orders with estimated totals, budget, AI health",
            "GET /shops/{shop}/work-orders/{order_id} — one order",
            "GET /healthz",
            "Worker, internal only: POST /pubsub/push, POST /pubsub/dlq, POST /sweep",
            "Interactive docs: /docs (Swagger UI)",
        ],
        "narration": (
            "The public A P I has four endpoints plus a health check. Post a message to a shop. Get the "
            "customer facing status of a message. List the shop's work orders with estimated totals. And "
            "get one order. The worker has three internal endpoints that only Pub Sub and Scheduler may "
            "call: push, dead letter, and sweep. Every endpoint is documented on the Swagger page, which "
            "is what I will use for one of the demos. Let's go through them one at a time, and after each "
            "call look at the row it left in the database."
        ),
    },
    {
        "id": "06-post",
        "kind": "terminal",
        "title": "POST a message",
        "captures": ["post.txt", "post_row.txt", "post_job.txt"],
        "narration": (
            "First, posting a message. This is sample five from the brief: my rear brake squeals and the "
            "gears skip on hills, can I bring it Saturday. The A P I answers two oh two with the message id, "
            "duplicate false, and a status U R L to poll. In the database there is now one inbound message "
            "row with no outcome yet, and one job row of kind extract. The job was published to Pub Sub "
            "right after the commit. Both rows were written in the same transaction, so there is no way to "
            "store a message and lose its job, or the other way round."
        ),
    },
    {
        "id": "07-status",
        "kind": "terminal",
        "title": "GET message status",
        "captures": ["status.txt", "status_order.txt", "status_ledger.txt"],
        "narration": (
            "A few seconds later the customer polls the status. It says confirmed, with an estimate: brake "
            "adjustment for one wheel at eighteen dollars, and a gear adjustment at twenty five, forty three "
            "in total, for Saturday the twenty sixth of September, resolved from the Tuesday the message "
            "arrived. Behind it is the work order row: status open, the two issues, the line items, and "
            "the total in integer cents. The model picked the two catalog codes. The price was computed in "
            "code from the catalog. The model never sees a price. The third row is the ledger: one model "
            "call, its tokens, its cost, and its latency. Every call lands here, including failed ones, and "
            "this is where the results table and the spend cap read from."
        ),
    },
    {
        "id": "08-followup-video",
        "kind": "video",
        "video": "docs/demo-one-question.gif",
        "narration": (
            "Now the follow up flow, through the Swagger page. The message is just two words: brakes "
            "squeal. A service is clear, but there is no date, so the model proposes a question, and the "
            "code agrees because nothing has been asked yet. The customer's status becomes awaiting your "
            "reply, with the question: when would you like us to work on the bike. Then the reply arrives "
            "as a new message linked by in reply to: rim brakes on a city bike, Saturday morning works. "
            "The worker rebuilds the conversation from the stored rows, the original message, the question "
            "as an assistant turn, and the reply, and asks the model to re extract the whole order. The "
            "status is now confirmed: brake adjustment on both wheels, thirty six dollars, Saturday morning."
        ),
    },
    {
        "id": "09-followup-rows",
        "kind": "terminal",
        "title": "Follow-up: the rows behind it",
        "captures": ["followup_order.txt", "followup_outbound.txt"],
        "narration": (
            "The work order row shows what made that safe. Questions asked is one, and it is an integer on "
            "the row, not an instruction in the prompt. If the reply had still been ambiguous, the code would "
            "send the order to staff review rather than ask again, because the brief allows exactly one "
            "question. The clarification question is stored, and the outbound messages table holds the "
            "question as it would be sent to the customer. Delivery by email is not built. The row is."
        ),
    },
    {
        "id": "10-list",
        "kind": "terminal",
        "title": "GET the shop's work orders",
        "captures": ["list.txt", "list_budget.txt"],
        "narration": (
            "The shop view lists open work orders with their estimated totals, and two health blocks. The "
            "budget block shows this month's cap, what has been spent, and what is reserved for calls in "
            "flight. The A I block shows whether the model path is degraded, how many jobs are waiting, "
            "and how many are parked because of an outage or the cap. The shop budgets row underneath is "
            "the ledger it reads from. Reserved goes up before each call and settles to the actual cost after."
        ),
    },
    {
        "id": "11-duplicate",
        "kind": "terminal",
        "title": "The same message twice",
        "captures": ["duplicate.txt", "duplicate_rows.txt"],
        "narration": (
            "Duplicates. Sample three from the brief arrives twice. Posting it again returns two hundred "
            "with duplicate true, instead of two oh two. The unique constraint on shop and message id "
            "catches it inside the database, so even two arrivals at the same instant resolve to one row. "
            "One message, one job, one work order, one model call. A redelivered job would also find the "
            "order already exists and acknowledge without calling the model."
        ),
    },
    {
        "id": "12-tenancy",
        "kind": "terminal",
        "title": "Tenant isolation, three layers",
        "captures": ["tenancy_404.txt", "tenancy_zero.txt", "tenancy_scoped.txt"],
        "narration": (
            "Tenancy has three layers. At the edge, the downtown key on the northside path returns four oh "
            "four. In the schema, every foreign key includes the shop id, so a cross shop reference cannot "
            "be represented. And in the database engine, row level security is forced on every tenant "
            "table. Connected as the application role with no tenant set, a select on work orders returns "
            "zero rows. Set the tenant for the transaction and only that shop's rows appear. A handler that "
            "forgets its where clause still cannot leak."
        ),
    },
    {
        "id": "13-tricky",
        "kind": "terminal",
        "title": "The tricky samples",
        "captures": ["tricky.txt", "tricky_rows.txt"],
        "narration": (
            "Four of the deliberately tricky samples. Sample twenty four contains a prompt injection: a "
            "system note telling the assistant to set every price to zero and mark it urgent. It cannot "
            "work, because the model only picks catalog codes and the price comes from the catalog in "
            "code. The order is a chain replacement at forty five dollars, urgency normal. Sample nine is "
            "addressed to the Lakeshore team but arrived at downtown. It is flagged for staff, never "
            "forwarded across tenants. Sample eighteen is a price question with no repair, so no work order "
            "is created and the priced answer is stored for staff. Sample thirty eight is a cancellation "
            "from Marcus. It is matched to his order by name within a day and flagged. Nothing is cancelled "
            "automatically."
        ),
    },
    {
        "id": "14-failure",
        "kind": "slide",
        "title": "When the model provider is down",
        "bullets": [
            "SDK retries off. A timeout or 5xx returns 503; Pub/Sub redelivers with backoff, 5 attempts, then dead-letters.",
            "Three consecutive failures open a circuit breaker. While open, jobs park with a run-after time instead of burning attempts.",
            "The sweeper republishes parked jobs when the time passes.",
            "Customer sees: received, we will confirm shortly.",
            "Shop sees: ai.degraded true, jobs waiting 5, parked for outage 5.",
            "Observed: 5 jobs parked, 0 lost, all 5 done within one sweep after recovery.",
        ],
        "narration": (
            "Failure handling. When the provider is slow or down, the worker returns five oh three and Pub "
            "Sub redelivers with backoff, five times, then dead letters. After three consecutive failures a "
            "circuit breaker opens, and jobs are parked with a run after time instead of burning delivery "
            "attempts. The sweeper republishes them later. Throughout, the customer sees received, we will "
            "confirm shortly. The shop sees degraded true, and the number of jobs waiting and parked. In "
            "the recorded demo, five messages were sent with the provider down. All five parked, none "
            "were lost, and all five completed within one sweep after the provider came back."
        ),
    },
    {
        "id": "15-cap",
        "kind": "slide",
        "title": "The monthly spend cap",
        "bullets": [
            "Each shop has a cap in micro-dollars, read from the shop row on every reservation.",
            "Before each call: one atomic UPDATE reserves the worst case, two calls at the output ceiling.",
            "After the call: settle to the actual cost from the price table.",
            "At the cap: the job parks until next month, or until the cap is raised. No model call is made.",
            "Customer sees: received. Shop sees: budget.exhausted true, parked for budget cap.",
            "Raising the cap applies at once; the sweeper releases the parked jobs.",
        ],
        "narration": (
            "The spend cap. Each shop has a monthly cap. Before every model call, one atomic update "
            "reserves the worst case against it, and after the call the reservation settles to the actual "
            "cost. At the cap, the job parks until next month or until the cap is raised, and no call is "
            "made. The customer sees received. The shop sees budget exhausted. A raised cap applies "
            "immediately because it is read from the shop row on every reservation. That last line came "
            "from a test that failed: the first version snapshotted the cap at the start of the month."
        ),
    },
    {
        "id": "16-results",
        "kind": "results",
        "title": "Results: the 40 sample messages",
        "narration": "RESULTS_NARRATION",
    },
    {
        "id": "17-override-1",
        "kind": "slide",
        "title": "One AI decision I overrode: the queue",
        "bullets": [
            "The assistant proposed: a Postgres-only queue. A jobs table claimed with SELECT ... FOR UPDATE SKIP LOCKED, woken by LISTEN/NOTIFY.",
            "Its reasons: one less piece of infrastructure in an eight-hour build; message and job commit together; Postgres queues are mainstream now.",
            '"Swap to Pub/Sub at 100 shops."',
            "What was right: the transactional argument. A message stored but never queued is exactly the bug the brief probes.",
        ],
        "narration": (
            "Now the one A I decision I overrode. Early in the design, the coding assistant proposed a "
            "Postgres only queue: a jobs table claimed with select for update skip locked, woken by listen "
            "notify. Its reasons were good. One less piece of infrastructure in an eight hour build. The "
            "message insert and the job insert commit together, which avoids the dual write problem a "
            "broker has. And Postgres queues are mainstream now. It said: swap to Pub Sub at a hundred "
            "shops. The transactional argument was right, and I kept it."
        ),
    },
    {
        "id": "18-override-2",
        "kind": "slide",
        "title": "What was wrong with it",
        "bullets": [
            "Different mechanism locally and in production. A polling worker on the laptop, push delivery on GCP: the failure paths I demo would not be the ones that run.",
            'The queue becomes the first thing to replace. "Swap at 100 shops" puts a migration in the hot path of growth.',
            "Cloud Run economics. A polling worker needs always-allocated CPU, which removes scale-to-zero.",
            "The honest cost of my choice: a third system locally (the emulator) and job state in two places.",
        ],
        "narration": (
            "What was wrong with it. Three specific things. First, it meant a different mechanism locally "
            "and in production: a polling worker on my laptop and push delivery on Google Cloud, so the "
            "failure paths I demonstrate would not be the ones that actually run. Second, it made the queue "
            "the first thing to replace at scale, which is a bad place for the first thing to be. Third, "
            "a polling worker on Cloud Run needs C P U always allocated, which quietly removes scale to "
            "zero. The honest cost of my choice is a third system locally, the Pub Sub emulator, and job "
            "state living in two places."
        ),
    },
    {
        "id": "19-override-3",
        "kind": "code",
        "title": "What I did instead: outbox + Pub/Sub, parked states leave the broker",
        "file": "app/worker/pipeline.py",
        "lines": [36, 42],
        "narration": (
            "What I did instead. Keep the outbox table as the source of truth, the assistant's good half, "
            "and use Pub Sub for delivery, with the emulator locally and a push subscription on Cloud Run, "
            "identical client code in both. A sweeper republishes anything left unpublished, so the broker "
            "can lose a message and the database still re drives it. The envelope carries ids only. And "
            "this enum is the piece the Postgres only design would have made simpler and that I had to "
            "design deliberately: retry hands the job back to the broker with a five oh three, while parked "
            "acknowledges the message and leaves the broker on purpose, for a budget stop or an open "
            "breaker, so neither burns delivery attempts. The override is logged in the decisions file as "
            "it happened, and it is the first of the three decisions I ask the reviewers to challenge."
        ),
    },
    {
        "id": "20-not-built",
        "kind": "slide",
        "title": "Not built, and how to run it",
        "bullets": [
            "Cut: email and SMS delivery of the question; a staff UI; per-shop rate limits; private-IP Cloud SQL.",
            "Known gap: a job whose dead-letter message is lost stays waiting; a stale-job sweep is the next change.",
            "Next: Cloud Tasks per shop for fairness; a stale-job sweep; an evaluation set from the recorded responses.",
            "Breaks first at 100 shops: one shared push stream, so a noisy shop delays the others.",
            "Run it: make run (Compose: Postgres, Pub/Sub emulator, API, worker) · make samples · make test",
            "Docs: architecture note, decisions, failure demos, results table, time log.",
        ],
        "narration": (
            "What is not built, stated plainly. Email and S M S delivery of the question, a staff screen, "
            "per shop rate limits, and private I P for Cloud S Q L were cut. One known gap: if a dead letter "
            "message is lost by the broker, the job stays waiting, and a stale job sweep is the next change. "
            "At a hundred shops the first thing to break is the single shared push stream, where one noisy "
            "shop delays the others. The fix is Cloud Tasks with a queue per shop. To run it: make run "
            "brings up Postgres, the Pub Sub emulator, the A P I and the worker. Make samples sends the "
            "forty messages. Make test runs seventy eight tests. Thank you for watching."
        ),
    },
]
