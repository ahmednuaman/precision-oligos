locals {
  # Public URL: prefer a configured custom domain; otherwise the deployer supplies
  # the CloudFront domain after the first apply (see README two-phase note).
  public_base_url = length(var.cloudfront_aliases) > 0 ? "https://${var.cloudfront_aliases[0]}" : var.public_base_url_override
}

module "network" {
  source     = "./modules/network"
  suffix     = local.suffix
  aws_region = var.aws_region
  vpc_cidr   = var.vpc_cidr
  az_count   = var.az_count
  tags       = local.common_tags
}

module "auth" {
  source                   = "./modules/auth"
  suffix                   = local.suffix
  suffix_global            = local.suffix_global
  aws_region               = var.aws_region
  tags                     = local.common_tags
  public_base_url          = local.public_base_url
  cognito_domain_prefix    = var.cognito_domain_prefix
  saml_provider_name       = var.saml_provider_name
  entra_saml_metadata_url  = var.entra_saml_metadata_url
  entra_saml_metadata_file = var.entra_saml_metadata_file
  log_retention_days       = var.log_retention_days
}

module "backend" {
  source                    = "./modules/backend"
  suffix                    = local.suffix
  suffix_global             = local.suffix_global
  aws_region                = var.aws_region
  environment               = var.environment
  tags                      = local.common_tags
  vpc_id                    = module.network.vpc_id
  private_subnet_ids        = module.network.private_subnet_ids
  public_subnet_ids         = module.network.public_subnet_ids
  alb_sg_id                 = module.network.alb_sg_id
  service_sg_id             = module.network.service_sg_id
  container_image           = var.container_image
  log_retention_days        = var.log_retention_days
  audit_retention_years     = var.audit_retention_years
  use_spot                  = var.use_spot
  api_desired_count         = var.api_desired_count
  router_model              = var.router_model
  extraction_model          = var.extraction_model
  drafting_model            = var.drafting_model
  knowledge_base_id         = var.knowledge_base_id
  knowledge_base_region     = var.knowledge_base_region
  kb_assume_role_arn        = var.kb_assume_role_arn
  lims_base_url             = var.lims_base_url
  public_base_url           = local.public_base_url
  acm_certificate_arn       = var.acm_certificate_arn
  cognito_user_pool_id      = module.auth.user_pool_id
  cognito_client_id         = module.auth.client_id
  cognito_client_secret_arn = module.auth.client_secret_arn
  cognito_domain_url        = module.auth.domain_url
  cognito_region            = var.aws_region
  saml_provider_name        = module.auth.saml_provider_name
  service_version           = var.service_version
  logfire_token             = var.logfire_token
  otel_capture_content      = var.otel_capture_content
  traces_retention_days     = var.traces_retention_days
}

module "edge" {
  source = "./modules/edge"
  providers = {
    aws.us_east_1 = aws.us_east_1
  }
  suffix                   = local.suffix
  suffix_global            = local.suffix_global
  tags                     = local.common_tags
  alb_dns_name             = module.backend.alb_dns_name
  cloudfront_origin_secret = module.backend.cloudfront_origin_secret
  acm_certificate_arn      = var.acm_certificate_arn
  cloudfront_aliases       = var.cloudfront_aliases
  waf_rate_limit           = var.waf_rate_limit
}
