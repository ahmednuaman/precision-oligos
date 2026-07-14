data "aws_caller_identity" "current" {}

locals {
  repo_sub = "repo:${var.github_org}/${var.github_repo}"
}

# --- Remote state bucket (shared, per-envid state keys) --------------------------------

resource "aws_s3_bucket" "state" {
  bucket = var.state_bucket_name
  tags   = { Name = var.state_bucket_name }
}

resource "aws_s3_bucket_versioning" "state" {
  bucket = aws_s3_bucket.state.id
  versioning_configuration { status = "Enabled" }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "state" {
  bucket = aws_s3_bucket.state.id
  rule {
    apply_server_side_encryption_by_default { sse_algorithm = "aws:kms" }
    bucket_key_enabled = true
  }
}

resource "aws_s3_bucket_public_access_block" "state" {
  bucket                  = aws_s3_bucket.state.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

# --- GitHub OIDC provider --------------------------------------------------------------

resource "aws_iam_openid_connect_provider" "github" {
  url             = "https://token.actions.githubusercontent.com"
  client_id_list  = ["sts.amazonaws.com"]
  thumbprint_list = ["6938fd4d98bab03faadb97b34396831e3780aea1"]
}

# --- Deploy permissions ----------------------------------------------------------------

data "aws_iam_policy_document" "deploy" {
  statement {
    sid    = "DeployServices"
    effect = "Allow"
    actions = [
      "ec2:*", "ecs:*", "ecr:*", "lambda:*", "states:*", "dynamodb:*",
      "s3:*", "sns:*", "sqs:*", "kms:*", "secretsmanager:*", "cognito-idp:*",
      "cloudfront:*", "wafv2:*", "logs:*", "application-autoscaling:*",
      "elasticloadbalancing:*", "cloudwatch:*", "acm:*", "events:*",
    ]
    resources = ["*"]
  }
  statement {
    sid    = "IamForServiceRoles"
    effect = "Allow"
    actions = [
      "iam:CreateRole", "iam:DeleteRole", "iam:GetRole", "iam:PassRole",
      "iam:TagRole", "iam:UntagRole", "iam:AttachRolePolicy",
      "iam:DetachRolePolicy", "iam:PutRolePolicy", "iam:DeleteRolePolicy",
      "iam:GetRolePolicy", "iam:ListRolePolicies", "iam:ListAttachedRolePolicies",
      "iam:CreatePolicy", "iam:DeletePolicy", "iam:GetPolicy",
      "iam:CreateServiceLinkedRole", "iam:GetPolicyVersion",
      "iam:CreateOpenIDConnectProvider", "iam:GetOpenIDConnectProvider",
    ]
    resources = ["*"]
  }
  statement {
    sid       = "StateAccess"
    effect    = "Allow"
    actions   = ["s3:GetObject", "s3:PutObject", "s3:ListBucket", "s3:DeleteObject"]
    resources = [aws_s3_bucket.state.arn, "${aws_s3_bucket.state.arn}/*"]
  }
}

resource "aws_iam_policy" "deploy" {
  name   = "${var.name_prefix}-deploy"
  policy = data.aws_iam_policy_document.deploy.json
}

# --- Per-environment deploy roles ------------------------------------------------------

locals {
  # Branch ref patterns per environment.
  env_subs = {
    development = ["${local.repo_sub}:ref:refs/heads/development"]
    staging     = ["${local.repo_sub}:ref:refs/heads/release/*"]
    production  = ["${local.repo_sub}:ref:refs/heads/production"]
  }
}

data "aws_iam_policy_document" "env_trust" {
  for_each = local.env_subs
  statement {
    actions = ["sts:AssumeRoleWithWebIdentity"]
    effect  = "Allow"
    principals {
      type        = "Federated"
      identifiers = [aws_iam_openid_connect_provider.github.arn]
    }
    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:aud"
      values   = ["sts.amazonaws.com"]
    }
    condition {
      test     = "StringLike"
      variable = "token.actions.githubusercontent.com:sub"
      values   = each.value
    }
  }
}

resource "aws_iam_role" "deploy" {
  for_each             = local.env_subs
  name                 = "${var.name_prefix}-deploy-${each.key}"
  assume_role_policy   = data.aws_iam_policy_document.env_trust[each.key].json
  max_session_duration = 3600
}

resource "aws_iam_role_policy_attachment" "deploy" {
  for_each   = local.env_subs
  role       = aws_iam_role.deploy[each.key].name
  policy_arn = aws_iam_policy.deploy.arn
}

# --- PR plan role (read-only, pull_request events) -------------------------------------

data "aws_iam_policy_document" "pr_trust" {
  statement {
    actions = ["sts:AssumeRoleWithWebIdentity"]
    effect  = "Allow"
    principals {
      type        = "Federated"
      identifiers = [aws_iam_openid_connect_provider.github.arn]
    }
    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:aud"
      values   = ["sts.amazonaws.com"]
    }
    condition {
      test     = "StringLike"
      variable = "token.actions.githubusercontent.com:sub"
      values   = ["${local.repo_sub}:pull_request"]
    }
  }
}

resource "aws_iam_role" "pr_plan" {
  name               = "${var.name_prefix}-pr-plan"
  assume_role_policy = data.aws_iam_policy_document.pr_trust.json
}

resource "aws_iam_role_policy_attachment" "pr_plan_readonly" {
  role       = aws_iam_role.pr_plan.name
  policy_arn = "arn:aws:iam::aws:policy/ReadOnlyAccess"
}

data "aws_iam_policy_document" "pr_state" {
  statement {
    actions   = ["s3:GetObject", "s3:PutObject", "s3:ListBucket"]
    resources = [aws_s3_bucket.state.arn, "${aws_s3_bucket.state.arn}/*"]
  }
}

resource "aws_iam_role_policy" "pr_state" {
  role   = aws_iam_role.pr_plan.id
  name   = "state-access"
  policy = data.aws_iam_policy_document.pr_state.json
}
