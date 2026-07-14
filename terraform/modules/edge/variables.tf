variable "suffix" { type = string }
variable "suffix_global" { type = string }
variable "tags" { type = map(string) }

variable "alb_dns_name" { type = string }
variable "cloudfront_origin_secret" {
  type      = string
  sensitive = true
}

variable "acm_certificate_arn" { type = string }
variable "cloudfront_aliases" { type = list(string) }
variable "waf_rate_limit" { type = number }

# us-east-1 provider is passed in for the WAF WebACL.
