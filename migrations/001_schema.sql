-- Riverbend work orders: schema v1.
-- Applied by scripts/migrate.py as the owner role. The application connects as
-- riverbend_app, which does NOT own these tables, so row-level security applies to it.
-- Every tenant table carries shop_id; uniqueness and foreign keys are composite so a
-- cross-shop reference is unrepresentable (see docs/decisions.md ADR-3).

CREATE TABLE shops (
  id                 text PRIMARY KEY,
  name               text NOT NULL,
  timezone           text NOT NULL DEFAULT 'America/New_York',
  api_key_hash       text NOT NULL UNIQUE,          -- sha256 of the shop's API key
  monthly_cap_micros bigint NOT NULL,               -- LLM spend cap, USD * 1e6
  created_at         timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE inbound_messages (
  shop_id        text NOT NULL REFERENCES shops(id),
  id             uuid NOT NULL DEFAULT gen_random_uuid(),
  message_id     text NOT NULL,                     -- sender's id, the idempotency key
  channel        text NOT NULL CHECK (channel IN ('email', 'web')),
  received_at    timestamptz NOT NULL,
  body           text NOT NULL,
  in_reply_to    uuid,                              -- parent inbound row for replies
  outcome        text,                              -- set when processing finishes
  outcome_detail text,
  created_at     timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (shop_id, id),
  UNIQUE (shop_id, message_id),
  FOREIGN KEY (shop_id, in_reply_to) REFERENCES inbound_messages(shop_id, id)
);

CREATE TABLE work_orders (
  shop_id                text NOT NULL REFERENCES shops(id),
  id                     uuid NOT NULL DEFAULT gen_random_uuid(),
  source_message_id      uuid NOT NULL,
  status                 text NOT NULL CHECK (status IN ('awaiting_customer', 'open', 'needs_review', 'expired')),
  review_reason          text,
  customer_name          text,
  language               text NOT NULL DEFAULT 'en',
  bike_type              text,
  bike_count             int  NOT NULL DEFAULT 1,
  issues                 jsonb NOT NULL DEFAULT '[]',
  urgency                text NOT NULL DEFAULT 'normal' CHECK (urgency IN ('normal', 'urgent')),
  requested_date         date,
  date_note              text,
  line_items             jsonb NOT NULL DEFAULT '[]',
  estimated_total_cents  int,
  requires_inspection    boolean NOT NULL DEFAULT false,
  catalog_version        text NOT NULL,
  clarification_question text,
  questions_asked        int NOT NULL DEFAULT 0,     -- the one-question invariant
  asked_at               timestamptz,
  resolved_by_message_id uuid,
  amendments             jsonb NOT NULL DEFAULT '[]',
  created_at             timestamptz NOT NULL DEFAULT now(),
  updated_at             timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (shop_id, id),
  UNIQUE (shop_id, source_message_id),               -- one order per message, even if a job runs twice
  FOREIGN KEY (shop_id, source_message_id)      REFERENCES inbound_messages(shop_id, id),
  FOREIGN KEY (shop_id, resolved_by_message_id) REFERENCES inbound_messages(shop_id, id)
);
CREATE INDEX work_orders_shop_status ON work_orders (shop_id, status);

-- Outbox + processing record. Holds ids and bookkeeping only, never customer text, so it is
-- deliberately outside row-level security: the worker claims across shops, then scopes itself.
CREATE TABLE jobs (
  id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  shop_id      text NOT NULL REFERENCES shops(id),
  kind         text NOT NULL CHECK (kind IN ('extract', 'resume')),
  message_pk   uuid NOT NULL,
  status       text NOT NULL DEFAULT 'queued'
               CHECK (status IN ('queued', 'published', 'processing', 'done', 'failed', 'parked')),
  attempts     int NOT NULL DEFAULT 0,
  published_at timestamptz,
  run_after    timestamptz,                          -- for parked jobs
  park_reason  text,                                 -- budget_exceeded | provider_unavailable | parent_pending
  last_error   text,
  created_at   timestamptz NOT NULL DEFAULT now(),
  updated_at   timestamptz NOT NULL DEFAULT now(),
  UNIQUE (shop_id, message_pk, kind),
  FOREIGN KEY (shop_id, message_pk) REFERENCES inbound_messages(shop_id, id)
);
CREATE INDEX jobs_status_run_after ON jobs (status, run_after);
CREATE INDEX jobs_unpublished ON jobs (created_at) WHERE status = 'queued';

CREATE TABLE llm_calls (
  shop_id           text NOT NULL REFERENCES shops(id),
  id                uuid NOT NULL DEFAULT gen_random_uuid(),
  job_id            uuid REFERENCES jobs(id),
  message_pk        uuid NOT NULL,
  provider          text NOT NULL,
  model             text NOT NULL,
  input_tokens      int NOT NULL DEFAULT 0,
  output_tokens     int NOT NULL DEFAULT 0,
  cost_micros       bigint NOT NULL DEFAULT 0,       -- computed in code from the price table
  latency_ms        int NOT NULL DEFAULT 0,
  outcome           text NOT NULL CHECK (outcome IN ('ok', 'invalid_output', 'provider_error', 'timeout')),
  validation_errors jsonb,
  raw_output        text,
  attempt           int NOT NULL DEFAULT 1,
  created_at        timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (shop_id, id)
);
CREATE INDEX llm_calls_shop_created ON llm_calls (shop_id, created_at);

CREATE TABLE shop_budgets (
  shop_id         text NOT NULL REFERENCES shops(id),
  month           date NOT NULL,                     -- first day of the month, shop-local
  cap_micros      bigint NOT NULL,
  reserved_micros bigint NOT NULL DEFAULT 0,
  spent_micros    bigint NOT NULL DEFAULT 0,
  PRIMARY KEY (shop_id, month),
  CHECK (reserved_micros >= 0 AND spent_micros >= 0)
);

CREATE TABLE budget_reservations (
  shop_id   text NOT NULL REFERENCES shops(id),
  job_id    uuid NOT NULL REFERENCES jobs(id),
  attempt   int NOT NULL,
  month     date NOT NULL,
  micros    bigint NOT NULL,
  status    text NOT NULL DEFAULT 'reserved' CHECK (status IN ('reserved', 'settled', 'released')),
  created_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (shop_id, job_id, attempt)
);

-- What the channel adapter should deliver to the customer (the follow-up question).
CREATE TABLE outbound_messages (
  shop_id       text NOT NULL REFERENCES shops(id),
  id            uuid NOT NULL DEFAULT gen_random_uuid(),
  work_order_id uuid NOT NULL,
  channel       text NOT NULL CHECK (channel IN ('email', 'web')),
  body          text NOT NULL,
  status        text NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'sent')),
  created_at    timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (shop_id, id),
  FOREIGN KEY (shop_id, work_order_id) REFERENCES work_orders(shop_id, id)
);

-- ---------------------------------------------------------------------------
-- Row-level security. current_setting(..., true) returns NULL when unset, so a transaction
-- that never set app.shop_id sees zero rows and can write none. Fails closed.
-- ---------------------------------------------------------------------------
DO $$
DECLARE t text;
BEGIN
  FOREACH t IN ARRAY ARRAY['inbound_messages', 'work_orders', 'llm_calls', 'shop_budgets',
                           'budget_reservations', 'outbound_messages']
  LOOP
    EXECUTE format('ALTER TABLE %I ENABLE ROW LEVEL SECURITY', t);
    EXECUTE format('ALTER TABLE %I FORCE ROW LEVEL SECURITY', t);
    EXECUTE format(
      'CREATE POLICY tenant_isolation ON %I '
      'USING (shop_id = current_setting(''app.shop_id'', true)) '
      'WITH CHECK (shop_id = current_setting(''app.shop_id'', true))', t);
  END LOOP;
END $$;

GRANT USAGE ON SCHEMA public TO riverbend_app;
GRANT SELECT, INSERT, UPDATE ON ALL TABLES IN SCHEMA public TO riverbend_app;
