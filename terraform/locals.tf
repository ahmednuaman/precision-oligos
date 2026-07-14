locals {
  # Per the workspace AWS naming standard:
  #   region-specific:     <ResourceName>-<region>-<envid>
  #   non-region-specific: <ResourceName>-<envid>
  suffix        = "${var.aws_region}-${var.envid}"
  suffix_global = var.envid

  common_tags = {
    Environment = var.environment
    Repository  = var.repository
    ManagedBy   = "Terraform"
    Creator     = var.creator
  }
}
