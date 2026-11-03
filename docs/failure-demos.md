# Failure demos

Three commands-and-observations runs, reproduced on 2026-11-03 against the native stack
(Postgres + Pub/Sub emulator + API + worker). Each works the same on Compose; set the env on
the worker container instead of the process.

Shop keys in dev are `dev-key-<shop_id>`. `K='X-API-Key: dev-key-rb-downtown'`.

## 1. The same message twice

```
curl -s -X POST localhost:8080/shops/rb-lakeshore/messages -H "X-API-Key: dev-key-rb-lakeshore" \
  -H 'content-type: application/json' \
  -d '{"message_id":"m-1003","channel":"email","body":"The chain on my hybrid keeps falling off. Free Saturday. Marcus"}'
# → 202 {"duplicate": false, ...}
# same command again
# → 200 {"duplicate": true, ...}     one job, one work order, one model call
```

In the 40-sample run: 40 sent, 39 unique, 1 duplicate, 39 jobs.

## 2. The model provider is down

Start the worker with the fake provider failing, a breaker that opens after 3 failures for 20 s:

```
LLM_FAULT=down BREAKER_FAILURE_THRESHOLD=3 BREAKER_OPEN_SECONDS=20 uvicorn app.worker.main:app --port 8081
# send five messages, wait 25 s
```

Observed:

```
jobs:       parked | provider_unavailable | 5
llm_calls:  provider_error | 4            (4 attempts handed back to the broker before the breaker opened)
customer:   received - We received your message and will confirm shortly.
shop:       {'degraded': True, 'waiting': 5, 'parked_provider_outage': 5, 'parked_budget_cap': 0, 'recent_provider_failures': 4}
worker log: 4 provider.retry, 4 job.retry (503 → Pub/Sub redelivery), 10 job.parked, 1 sweep
```

Restart the worker healthy; within one sweep interval:

```
jobs:       done | 5
customer:   awaiting_your_reply - We have one question before we can confirm.
shop:       {'degraded': False, 'waiting': 0, ...}
```

Nothing was lost, no attempt was burned while the breaker was open, and the customer never saw
an error.

## 3. The monthly spend cap

```
psql "$DB" -c "UPDATE shops SET monthly_cap_micros = 1 WHERE id = 'rb-northside'"   # ~0 USD
# send a message to rb-northside
```

Observed: the job parks with `budget_exceeded` and a `run_after` of the first of next month, no
model call is made, the customer status is `received`, and the shop list shows
`budget.exhausted: true` and `ai.parked_budget_cap: 1`.

Raise the cap and release:

```
psql "$DB" -c "UPDATE shops SET monthly_cap_micros = 25000000 WHERE id = 'rb-northside'"
psql "$DB" -c "UPDATE jobs SET run_after = now() WHERE status = 'parked' AND park_reason = 'budget_exceeded'"
# next sweep republishes; the job completes
```

The cap is read from the shop row on every reservation, so the raise applies immediately. The
test `test_budget_cap_parks_job_and_raising_cap_releases_it` covers the same path.
