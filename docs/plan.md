# Build plan

Target: about 8 hours of build time, honest log in `time-log.md`. Order chosen so that the
riskiest boundaries (tenancy, idempotency, model output validation) exist and are tested before
anything cosmetic.

- [x] 1. Scaffold: pyproject, Makefile, env example, catalog, samples, decisions, logs
- [x] 2. Migrations: shops, inbound_messages, work_orders, jobs (outbox), llm_calls,
      shop_budgets, outbound_messages, RLS policies, app role
- [x] 3. Core pure modules + unit tests: catalog, pricing, dates, extraction schema,
      validation rules, decide()
- [x] 4. Data layer: pool, tenant transaction, repositories
- [x] 5. Ingest API: POST message (idempotent, outbox), GET message status, GET work orders,
      health; tenancy tests against Postgres
- [x] 6. Worker: push endpoint, pipeline (budget → provider → validate → decide → price →
      write), parked states, DLQ endpoint, sweeper; fake provider with fault injection
- [x] 7. Dispatcher: Pub/Sub publisher + emulator setup script; inline dispatcher for tests
- [x] 8. Docker Compose + Dockerfile + init container (migrate, seed, topics)
- [ ] 9. Azure OpenAI provider with record mode; run the 40 samples; results table
- [x] 10. Failure demos: duplicate, provider down, budget cap (documented commands)
- [x] 11. Terraform for GCP + deployment note
- [ ] 12. Architecture note (2 pages), not-built list, README, time log final
- [ ] 13. Loom: pick the override from `ai-decisions-log.md`, record (user)
