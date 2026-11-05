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
  default = "v1" # OpenAI-compatible surface; or a classic api-version string
}
variable "llm_price_input_usd_per_1m" {
  type    = string
  default = "0.25"
}
variable "llm_price_output_usd_per_1m" {
  type    = string
  default = "2.00"
}
variable "default_monthly_cap_usd" {
  type    = string
  default = "25"
}

variable "llm_reasoning_effort" {
  description = "gpt-5 family reasoning effort (minimal|low|medium|high); empty for other models"
  type        = string
  default     = "low"
}
