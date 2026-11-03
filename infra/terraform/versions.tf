terraform {
  required_version = ">= 1.6"
  required_providers {
    google = { source = "hashicorp/google", version = "~> 6.0" }
  }
  # State: keep it out of the repo. Uncomment and point at a bucket you own.
  # backend "gcs" { bucket = "riverbend-tfstate", prefix = "workorders" }
}

provider "google" {
  project = var.project_id
  region  = var.region
}
