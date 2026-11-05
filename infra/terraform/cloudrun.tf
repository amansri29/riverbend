locals {
  db_socket = "/cloudsql/${google_sql_database_instance.pg.connection_name}"
  common_env = {
    PUBSUB_PROJECT              = var.project_id
    PUBSUB_TOPIC                = google_pubsub_topic.jobs.name
    DISPATCHER                  = "pubsub"
    DEFAULT_MONTHLY_CAP_USD     = var.default_monthly_cap_usd
    LLM_PRICE_INPUT_USD_PER_1M  = var.llm_price_input_usd_per_1m
    LLM_PRICE_OUTPUT_USD_PER_1M = var.llm_price_output_usd_per_1m
    DEV_API_KEYS                = "false"
    SWEEP_INTERVAL_SECONDS      = "0" # Cloud Scheduler calls /sweep; no in-process loop
  }
}

# ---------------------------------------------------------------- API: ingest + reads
resource "google_cloud_run_v2_service" "api" {
  name     = "riverbend-api"
  location = var.region
  ingress  = "INGRESS_TRAFFIC_ALL" # the shops' channels call it; auth is the per-shop API key

  template {
    service_account = google_service_account.api.email
    scaling {
      min_instance_count = 0
      max_instance_count = 10
    }
    volumes {
      name = "cloudsql"
      cloud_sql_instance { instances = [google_sql_database_instance.pg.connection_name] }
    }
    containers {
      image   = var.image
      command = ["uvicorn", "app.api.main:app", "--host", "0.0.0.0", "--port", "8080"]
      ports { container_port = 8080 }
      resources {
        limits = { cpu = "1", memory = "512Mi" }
      }
      volume_mounts {
        name       = "cloudsql"
        mount_path = "/cloudsql"
      }
      dynamic "env" {
        for_each = local.common_env
        content {
          name  = env.key
          value = env.value
        }
      }
      env {
        name = "DB_APP_PASSWORD"
        value_source {
          secret_key_ref {
            secret  = google_secret_manager_secret.secrets["db-app-password"].secret_id
            version = "latest"
          }
        }
      }
      # psycopg reads the socket directory from host=; the password is interpolated at start-up
      # by the entrypoint from DB_APP_PASSWORD (see docs/gcp.md).
      env {
        name  = "DATABASE_URL_TEMPLATE"
        value = "postgresql://riverbend_app:$${DB_APP_PASSWORD}@/riverbend?host=${local.db_socket}"
      }
      startup_probe {
        http_get { path = "/healthz" }
        initial_delay_seconds = 2
        period_seconds        = 5
        failure_threshold     = 6
      }
    }
  }
  depends_on = [google_project_service.apis]
}

resource "google_cloud_run_v2_service_iam_member" "api_public" {
  name     = google_cloud_run_v2_service.api.name
  location = var.region
  role     = "roles/run.invoker"
  member   = "allUsers" # application-level auth: X-API-Key per shop (ADR-3)
}

# ---------------------------------------------------------------- worker: push target
resource "google_cloud_run_v2_service" "worker" {
  name     = "riverbend-worker"
  location = var.region
  ingress  = "INGRESS_TRAFFIC_INTERNAL_ONLY" # Pub/Sub push and Cloud Scheduler count as internal

  template {
    service_account = google_service_account.worker.email
    scaling {
      min_instance_count = 0 # push delivery: no polling, so the worker can scale to zero
      max_instance_count = 20
    }
    max_instance_request_concurrency = 8 # in-flight model calls per instance; x instances = load on Azure
    timeout                          = "120s"
    volumes {
      name = "cloudsql"
      cloud_sql_instance { instances = [google_sql_database_instance.pg.connection_name] }
    }
    containers {
      image   = var.image
      command = ["uvicorn", "app.worker.main:app", "--host", "0.0.0.0", "--port", "8081"]
      ports { container_port = 8081 }
      resources {
        limits = { cpu = "1", memory = "512Mi" }
      }
      volume_mounts {
        name       = "cloudsql"
        mount_path = "/cloudsql"
      }
      dynamic "env" {
        for_each = merge(local.common_env, {
          LLM_PROVIDER             = "azure"
          AZURE_OPENAI_ENDPOINT    = var.azure_openai_endpoint
          AZURE_OPENAI_DEPLOYMENT  = var.azure_openai_deployment
          AZURE_OPENAI_API_VERSION = var.azure_openai_api_version
          LLM_REASONING_EFFORT     = var.llm_reasoning_effort
          LLM_RECORD_DIR           = ""
        })
        content {
          name  = env.key
          value = env.value
        }
      }
      env {
        name = "AZURE_OPENAI_API_KEY"
        value_source {
          secret_key_ref {
            secret  = google_secret_manager_secret.secrets["azure-openai-api-key"].secret_id
            version = "latest"
          }
        }
      }
      env {
        name = "DB_APP_PASSWORD"
        value_source {
          secret_key_ref {
            secret  = google_secret_manager_secret.secrets["db-app-password"].secret_id
            version = "latest"
          }
        }
      }
      env {
        name  = "DATABASE_URL_TEMPLATE"
        value = "postgresql://riverbend_app:$${DB_APP_PASSWORD}@/riverbend?host=${local.db_socket}"
      }
    }
  }
  depends_on = [google_project_service.apis]
}

# Only Pub/Sub's push identity (and Scheduler, below) may invoke the worker.
resource "google_cloud_run_v2_service_iam_member" "worker_invoker_pubsub" {
  name     = google_cloud_run_v2_service.worker.name
  location = var.region
  role     = "roles/run.invoker"
  member   = "serviceAccount:${google_service_account.pubsub_push.email}"
}

# ---------------------------------------------------------------- migrations: a Cloud Run Job
resource "google_cloud_run_v2_job" "migrate" {
  name     = "riverbend-migrate"
  location = var.region
  template {
    template {
      service_account = google_service_account.worker.email
      volumes {
        name = "cloudsql"
        cloud_sql_instance { instances = [google_sql_database_instance.pg.connection_name] }
      }
      containers {
        image   = var.image
        command = ["python", "scripts/migrate.py"]
        volume_mounts {
          name       = "cloudsql"
          mount_path = "/cloudsql"
        }
        env {
          name  = "DEV_API_KEYS"
          value = "false" # production keys are generated once and printed to the job log
        }
        env {
          name = "DB_ROOT_PASSWORD"
          value_source {
            secret_key_ref {
              secret  = google_secret_manager_secret.secrets["db-root-password"].secret_id
              version = "latest"
            }
          }
        }
        env {
          name = "APP_DB_PASSWORD"
          value_source {
            secret_key_ref {
              secret  = google_secret_manager_secret.secrets["db-app-password"].secret_id
              version = "latest"
            }
          }
        }
        env {
          name  = "MIGRATION_DATABASE_URL_TEMPLATE"
          value = "postgresql://riverbend_owner:$${DB_ROOT_PASSWORD}@/riverbend?host=${local.db_socket}"
        }
      }
    }
  }
}

resource "google_secret_manager_secret_iam_member" "migrate_reads_root" {
  secret_id = google_secret_manager_secret.secrets["db-root-password"].id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.worker.email}"
}
