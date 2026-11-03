variable "project_id" { type = string }
variable "region" {
  type    = string
  default = "europe-west1"
}
variable "image" {
  type        = string
  description = "Container image for api, worker and the migrate job (built by Cloud Build)."
}
variable "alert_email" {
  type        = string
  description = "Where Cloud Monitoring sends alerts."
}
variable "db_tier" {
  type    = string
  default = "db-f1-micro" # 3 shops. db-custom-2-7680 is the first step up.
}
variable "azure_openai_endpoint" { type = string }
variable "azure_openai_deployment" { type = string }
variable "azure_openai_api_version" {
  type    = string
  default = "2024-10-21"
}
variable "llm_price_input_usd_per_1m" {
  type    = string
  default = "2.50"
}
variable "llm_price_output_usd_per_1m" {
  type    = string
  default = "10.00"
}
variable "default_monthly_cap_usd" {
  type    = string
  default = "25"
}
