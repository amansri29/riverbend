# Delivery (ADR-4). The topic carries job ids only. The push subscription owns the normal retry
# path; the dead-letter topic receives what five attempts could not deliver.
resource "google_pubsub_topic" "jobs" {
  name       = "work-order-jobs"
  depends_on = [google_project_service.apis]
}

resource "google_pubsub_topic" "jobs_dlq" {
  name = "work-order-jobs-dlq"
}

resource "google_pubsub_subscription" "jobs_push" {
  name  = "work-order-jobs-push"
  topic = google_pubsub_topic.jobs.id

  ack_deadline_seconds = 120 # one model call with a corrective retry fits comfortably

  push_config {
    push_endpoint = "${google_cloud_run_v2_service.worker.uri}/pubsub/push"
    oidc_token {
      service_account_email = google_service_account.pubsub_push.email
    }
  }

  retry_policy {
    minimum_backoff = "10s"
    maximum_backoff = "600s"
  }

  dead_letter_policy {
    dead_letter_topic     = google_pubsub_topic.jobs_dlq.id
    max_delivery_attempts = 5
  }

  expiration_policy {
    ttl = "" # never expire
  }
}

resource "google_pubsub_subscription" "dlq_push" {
  name                 = "work-order-jobs-dlq-push"
  topic                = google_pubsub_topic.jobs_dlq.id
  ack_deadline_seconds = 60
  push_config {
    push_endpoint = "${google_cloud_run_v2_service.worker.uri}/pubsub/dlq"
    oidc_token {
      service_account_email = google_service_account.pubsub_push.email
    }
  }
  expiration_policy {
    ttl = ""
  }
}

# Pub/Sub's own service agent needs to publish to the DLQ and to ack on the main subscription.
data "google_project" "this" {}

resource "google_pubsub_topic_iam_member" "dlq_publisher" {
  topic  = google_pubsub_topic.jobs_dlq.name
  role   = "roles/pubsub.publisher"
  member = "serviceAccount:service-${data.google_project.this.number}@gcp-sa-pubsub.iam.gserviceaccount.com"
}

resource "google_pubsub_subscription_iam_member" "dlq_subscriber" {
  subscription = google_pubsub_subscription.jobs_push.name
  role         = "roles/pubsub.subscriber"
  member       = "serviceAccount:service-${data.google_project.this.number}@gcp-sa-pubsub.iam.gserviceaccount.com"
}
