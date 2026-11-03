# The sweeper: republish outbox rows that never reached the broker, release parked jobs whose
# time has come (budget stop, breaker), expire unanswered follow-ups. Every minute.
resource "google_service_account" "scheduler" {
  account_id   = "riverbend-scheduler"
  display_name = "Cloud Scheduler → worker /sweep"
}

resource "google_cloud_run_v2_service_iam_member" "worker_invoker_scheduler" {
  name     = google_cloud_run_v2_service.worker.name
  location = var.region
  role     = "roles/run.invoker"
  member   = "serviceAccount:${google_service_account.scheduler.email}"
}

resource "google_cloud_scheduler_job" "sweep" {
  name        = "riverbend-sweep"
  description = "Outbox republish, parked-job release, follow-up expiry"
  schedule    = "* * * * *"
  time_zone   = "Etc/UTC"
  http_target {
    http_method = "POST"
    uri         = "${google_cloud_run_v2_service.worker.uri}/sweep"
    oidc_token {
      service_account_email = google_service_account.scheduler.email
    }
  }
  depends_on = [google_project_service.apis]
}
