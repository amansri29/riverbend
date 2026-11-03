output "api_url" { value = google_cloud_run_v2_service.api.uri }
output "worker_url" { value = google_cloud_run_v2_service.worker.uri }
output "cloudsql_connection_name" { value = google_sql_database_instance.pg.connection_name }
output "artifact_registry" { value = "${var.region}-docker.pkg.dev/${var.project_id}/${google_artifact_registry_repository.images.repository_id}" }
output "pubsub_topic" { value = google_pubsub_topic.jobs.name }
