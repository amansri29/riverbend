# Deployment path: GCP

Infrastructure-as-code is in `infra/terraform/`; the build and deploy pipeline is
`cloudbuild.yaml`. No live deployment was made (no credits). This page names each service and
why, then the steps.

## Services and why

| Service | Role | Why this one |
|---|---|---|
| Cloud Run, `riverbend-api` | ingest + reads, public ingress, app-level API-key auth | stateless, scales to zero, no servers |
| Cloud Run, `riverbend-worker` | Pub/Sub push target, internal ingress, invoker = Pub/Sub and Scheduler identities only | push delivery means no polling and real scale-to-zero |
| Cloud Run Job, `riverbend-migrate` | applies SQL migrations as the owner role, seeds shops | migrations run with a different identity than the app |
| Pub/Sub topic + push subscription + DLQ | delivery with backoff and five attempts, dead-letter topic pushed to `/pubsub/dlq` | managed, no broker to run |
| Cloud SQL for PostgreSQL 16 | system of record, outbox, ledger, row-level security | the design leans on Postgres features |
| Secret Manager | Azure key, app DB password, owner DB password | injected as env vars; nothing in the image or tfvars |
| Cloud Scheduler | `POST /sweep` every minute | outbox republish, parked-job release, expiry without an always-on process |
| Artifact Registry + Cloud Build | one image, built on push, deployed to both services after the migrate job | one artefact, one pipeline |
| Cloud Monitoring + Logging | alerts on DLQ depth, backlog age, worker 5xx; structured JSON logs with shop/message/job ids | the three signals that map to the brief's failure cases |

Cloud SQL is reached through the Cloud SQL connector (Unix socket mounted into Cloud Run):
IAM-authenticated and encrypted, no exposed IP, no VPC plumbing. Private IP with a VPC
connector is the hardening step and is listed in `not-built.md`.

## Steps

1. `terraform apply -var-file=example.tfvars` (after editing it). Terraform creates the secrets
   but not their values.
2. Add secret values out of band:
   ```
   printf '%s' "$AZURE_KEY" | gcloud secrets versions add riverbend-azure-openai-api-key --data-file=-
   printf '%s' "$APP_PW"    | gcloud secrets versions add riverbend-db-app-password --data-file=-
   printf '%s' "$ROOT_PW"   | gcloud secrets versions add riverbend-db-root-password --data-file=-
   ```
   Re-run `terraform apply` so the Cloud SQL owner user picks up the root password.
3. `gcloud builds submit` (or connect the repo as a trigger). Cloud Build builds the image,
   runs the migrate job, then rolls the worker and the API.
4. The first migrate job generates the three shop API keys and prints them once in its log
   (`DEV_API_KEYS=false`). Hand them to the shops' channel integrations.
5. Point the web form and the email webhook at `POST {api_url}/shops/{shop_id}/messages`.

## Configuration on Cloud Run

Passwords arrive as their own env vars from Secret Manager; the app builds the connection
string from `DATABASE_URL_TEMPLATE` with `${DB_APP_PASSWORD}` expanded at start-up, so no
secret is ever spliced into a URL by hand or stored in Terraform state.

## Scaling knobs

- Worker: `max_instance_request_concurrency` × `max_instance_count` = in-flight model calls =
  load on Azure. Start at 8 × 20.
- Subscription: `ack_deadline_seconds` 120 covers one call plus a corrective retry.
- Cloud SQL: `db-f1-micro` for three shops; `db-custom-2-7680` and the built-in pooler are the
  first steps up.

## Cost at this size

Roughly: Cloud SQL micro ≈ 10 USD/month, Cloud Run near zero at this traffic, Pub/Sub and
Scheduler within free tiers, Secret Manager cents. The model spend is the budget that matters
and it is capped per shop by the service itself.

## Known gaps

Cloud SQL private IP, Terraform remote state, CI for tests, and a custom queue-depth metric are
not done. The model is in Azure, so every call leaves GCP; the provider interface is where a
GCP-hosted model would go.
