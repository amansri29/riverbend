# Cloud SQL for PostgreSQL 16: the system of record and the outbox. Row-level security lives
# inside it, which is why the app connects as riverbend_app (not the owner) in production too.
resource "google_sql_database_instance" "pg" {
  name             = "riverbend-pg"
  database_version = "POSTGRES_16"
  region           = var.region
  settings {
    tier              = var.db_tier
    availability_type = "ZONAL" # REGIONAL (HA) is a one-line change once the shop count justifies it
    backup_configuration {
      enabled                        = true
      point_in_time_recovery_enabled = true
    }
    ip_configuration {
      ipv4_enabled = true # reached only via the Cloud SQL connector; no authorized networks
      ssl_mode     = "ENCRYPTED_ONLY"
    }
    database_flags {
      name  = "max_connections"
      value = "100"
    }
  }
  deletion_protection = true
  depends_on          = [google_project_service.apis]
}

resource "google_sql_database" "riverbend" {
  name     = "riverbend"
  instance = google_sql_database_instance.pg.name
}

# Owner role for migrations. The app role (riverbend_app) is created BY the migration with the
# password from Secret Manager, so Terraform never sees it.
data "google_secret_manager_secret_version" "db_root" {
  secret     = google_secret_manager_secret.secrets["db-root-password"].id
  depends_on = [google_secret_manager_secret.secrets]
}

resource "google_sql_user" "root" {
  name     = "riverbend_owner"
  instance = google_sql_database_instance.pg.name
  password = data.google_secret_manager_secret_version.db_root.secret_data
}
