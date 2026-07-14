# Remote state uses a partial S3 backend so that a separate state file is kept
# per environment. Initialise with a per-environment backend config, e.g.:
#
#   terraform init -backend-config=backend-config/development.s3.tfbackend
#
# The state bucket and lock table are created once by the bootstrap stack
# (terraform/bootstrap).
terraform {
  backend "s3" {
    encrypt      = true
    use_lockfile = true
  }
}
