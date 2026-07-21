terraform {
  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 4.0"
    }
  }
}

provider "google" {
  project = var.gcp_project_id
  region  = "asia-east1" # Geolocation specifically covering Hong Kong/Asia bounds for PDPO
}

variable "gcp_project_id" {
  description = "The GCP project ID"
  type        = string
  default     = "clax-beta-project"
}

# ==========================================
# 1. GCP Bucket with Object Lock (WORM Enforcement)
# ==========================================
resource "google_storage_bucket" "clax_compliance_vault" {
  name          = "clax-compliance-audit-vault-prod"
  location      = "ASIA-EAST1"
  force_destroy = false
  
  # Crucial for PDPO / WORM compliance auditing (7 Years = 2555 Days = 220752000 Seconds)
  retention_policy {
    retention_period = 220752000
    is_locked        = true 
  }

  versioning {
    enabled = true
  }

  public_access_prevention = "enforced"

  # Uniform bucket-level access is highly recommended for compliant buckets
  uniform_bucket_level_access = true
}

# ==========================================
# 2. Service Account for Backend Worker
# ==========================================
resource "google_service_account" "clax_backend_worker" {
  account_id   = "clax-backend-worker"
  display_name = "Clax Backend Microservice Execution Role"
}

# ==========================================
# 3. Restrictive IAM Permissions
# ==========================================
# Requirement: objectCreator ONLY. Disallow delete/admin access entirely.
resource "google_storage_bucket_iam_member" "worm_object_creator" {
  bucket = google_storage_bucket.clax_compliance_vault.name
  role   = "roles/storage.objectCreator"
  member = "serviceAccount:${google_service_account.clax_backend_worker.email}"
}