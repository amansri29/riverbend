resource "google_monitoring_notification_channel" "email" {
  display_name = "Riverbend on-call"
  type         = "email"
  labels       = { email_address = var.alert_email }
}

# 1. Anything in the dead-letter queue means a message the shop will never see processed.
resource "google_monitoring_alert_policy" "dlq" {
  display_name = "Riverbend: dead-lettered jobs"
  combiner     = "OR"
  conditions {
    display_name = "DLQ has undelivered messages"
    condition_threshold {
      filter          = "resource.type = \"pubsub_subscription\" AND resource.labels.subscription_id = \"${google_pubsub_subscription.dlq_push.name}\" AND metric.type = \"pubsub.googleapis.com/subscription/num_undelivered_messages\""
      comparison      = "COMPARISON_GT"
      threshold_value = 0
      duration        = "60s"
      aggregations {
        alignment_period   = "60s"
        per_series_aligner = "ALIGN_MAX"
      }
    }
  }
  notification_channels = [google_monitoring_notification_channel.email.id]
}

# 2. Backlog age: the provider is slow or the worker is not keeping up.
resource "google_monitoring_alert_policy" "backlog_age" {
  display_name = "Riverbend: jobs waiting > 10 minutes"
  combiner     = "OR"
  conditions {
    display_name = "Oldest unacked message age"
    condition_threshold {
      filter          = "resource.type = \"pubsub_subscription\" AND resource.labels.subscription_id = \"${google_pubsub_subscription.jobs_push.name}\" AND metric.type = \"pubsub.googleapis.com/subscription/oldest_unacked_message_age\""
      comparison      = "COMPARISON_GT"
      threshold_value = 600
      duration        = "120s"
      aggregations {
        alignment_period   = "60s"
        per_series_aligner = "ALIGN_MAX"
      }
    }
  }
  notification_channels = [google_monitoring_notification_channel.email.id]
}

# 3. Worker 5xx = provider errors being handed back to the broker (see pipeline RETRY).
resource "google_monitoring_alert_policy" "worker_5xx" {
  display_name = "Riverbend: worker returning 5xx (provider trouble)"
  combiner     = "OR"
  conditions {
    display_name = "5xx responses on the worker"
    condition_threshold {
      filter          = "resource.type = \"cloud_run_revision\" AND resource.labels.service_name = \"${google_cloud_run_v2_service.worker.name}\" AND metric.type = \"run.googleapis.com/request_count\" AND metric.labels.response_code_class = \"5xx\""
      comparison      = "COMPARISON_GT"
      threshold_value = 10
      duration        = "300s"
      aggregations {
        alignment_period   = "300s"
        per_series_aligner = "ALIGN_RATE"
        cross_series_reducer = "REDUCE_SUM"
      }
    }
  }
  notification_channels = [google_monitoring_notification_channel.email.id]
}
