locals {
  # Pipeline step Lambda base-name -> handler function.
  steps = {
    "RouteStepLambdaFunction"         = "route_handler"
    "RetrieveStepLambdaFunction"      = "retrieve_handler"
    "DetectStepLambdaFunction"        = "detect_handler"
    "DraftStepLambdaFunction"         = "draft_handler"
    "StoreTokenStepLambdaFunction"    = "store_token_handler"
    "ExecuteWritesStepLambdaFunction" = "execute_writes_handler"
    "SpecialistStepLambdaFunction"    = "specialist_handler"
  }
  step_names = keys(local.steps)

  # Common application environment for both the API and the step Lambdas.
  app_env = {
    ENVID                      = var.suffix_global
    AWS_REGION                 = var.aws_region
    ROUTER_MODEL               = var.router_model
    EXTRACTION_MODEL           = var.extraction_model
    DRAFTING_MODEL             = var.drafting_model
    KNOWLEDGE_BASE_ID          = var.knowledge_base_id
    KNOWLEDGE_BASE_REGION      = var.knowledge_base_region
    KB_ASSUME_ROLE_ARN         = var.kb_assume_role_arn
    RUNS_TABLE                 = aws_dynamodb_table.runs.name
    AUDIT_TABLE                = aws_dynamodb_table.audit.name
    SESSIONS_TABLE             = aws_dynamodb_table.sessions.name
    AUDIT_WORM_BUCKET          = aws_s3_bucket.audit.bucket
    NOTIFICATIONS_TOPIC_ARN    = aws_sns_topic.notifications.arn
    LIMS_BASE_URL              = var.lims_base_url
    LIMS_API_KEY_SECRET_ARN    = aws_secretsmanager_secret.lims_api_key.arn
    COGNITO_USER_POOL_ID       = var.cognito_user_pool_id
    COGNITO_CLIENT_ID          = var.cognito_client_id
    COGNITO_CLIENT_SECRET_ARN  = var.cognito_client_secret_arn
    COGNITO_DOMAIN             = var.cognito_domain_url
    COGNITO_REGION             = var.cognito_region
    COGNITO_SAML_PROVIDER_NAME = var.saml_provider_name
    PUBLIC_BASE_URL            = var.public_base_url
    POWERTOOLS_SERVICE_NAME    = "oligos-agents"
    SERVICE_VERSION            = var.service_version
    OTEL_FIREHOSE_STREAM       = aws_kinesis_firehose_delivery_stream.traces.name
    OTEL_CAPTURE_CONTENT       = var.otel_capture_content ? "true" : "false"
    LOGFIRE_TOKEN_SECRET_ARN   = try(aws_secretsmanager_secret.logfire_token[0].arn, "")
  }

  # The API additionally needs the state-machine ARN to start executions, and
  # hosts the remote MCP server + its OAuth authorization server.
  api_env = merge(local.app_env, {
    STATE_MACHINE_ARN     = aws_sfn_state_machine.pipeline.arn
    SESSION_COOKIE_SECURE = "true"
    MCP_ENABLED           = var.mcp_enabled ? "true" : "false"
    MCP_OAUTH_TABLE       = aws_dynamodb_table.mcp_oauth.name
    MCP_SCOPES            = var.mcp_scopes
  })
}
