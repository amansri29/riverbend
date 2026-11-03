# Riverbend work orders on GCP. Every resource is named with the reason it exists.
# Secrets are created here but their VALUES are added out-of-band (see docs/gcp.md), so no
# secret ever passes through tfvars or state in plain text.

locals {
  services = [
    "run.googleapis.com", "sqladmin.googleapis.com", "pubsub.googleapis.com",
    "secretmanager.googleapis.com", "artifactregistry.googleapis.com", "cloudbuild.googleapis.com",
    "cloudscheduler.googleapis.com", "monitoring.googleapis.com", "logging.googleapis.com",
  ]
}

resource "google_project_service" "apis" {
  for_each           = toset(local.services)
  service            = each.value
  disable_on_destroy = false
}

# One image for api, worker and the migrate job.
resource "google_artifact_registry_repository" "images" {
  location      = var.region
  repository_id = "riverbend"
  format        = "DOCKER"
  depends_on    = [google_project_service.apis]
}

# Three identities, least privilege each.
resource "google_service_account" "api" {
  account_id   = "riverbend-api"
  display_name = "Riverbend API (ingest + reads)"
}
resource "google_service_account" "worker" {
  account_id   = "riverbend-worker"
  display_name = "Riverbend worker (model calls)"
}
resource "google_service_account" "pubsub_push" {
  account_id   = "riverbend-pubsub-push"
  display_name = "Identity Pub/Sub uses to push into the worker"
}

# Secrets: values added with `gcloud secrets versions add`, never through Terraform.
resource "google_secret_manager_secret" "secrets" {
  for_each  = toset(["azure-openai-api-key", "db-app-password", "db-root-password"])
  secret_id = "riverbend-${each.value}"
  replication {
    auto {}
  }
  depends_on = [google_project_service.apis]
}

resource "google_secret_manager_secret_iam_member" "api_reads" {
  for_each  = toset(["db-app-password"])
  secret_id = google_secret_manager_secret.secrets[each.value].id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.api.email}"
}
resource "google_secret_manager_secret_iam_member" "worker_reads" {
  for_each  = toset(["db-app-password", "azure-openai-api-key"])
  secret_id = google_secret_manager_secret.secrets[each.value].id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.worker.email}"
}

# Both services reach Cloud SQL through the connector (IAM-authenticated, TLS, no exposed IP).
resource "google_project_iam_member" "cloudsql_clients" {
  for_each = { api = google_service_account.api.email, worker = google_service_account.worker.email }
  project  = var.project_id
  role     = "roles/cloudsql.client"
  member   = "serviceAccount:${each.value}"
}

# The API publishes job ids; the worker republishes from the outbox (sweeper).
resource "google_pubsub_topic_iam_member" "publishers" {
  for_each = { api = google_service_account.api.email, worker = google_service_account.worker.email }
  topic    = google_pubsub_topic.jobs.name
  role     = "roles/pubsub.publisher"
  member   = "serviceAccount:${each.value}"
}
