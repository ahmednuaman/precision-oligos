# Single image used by both the Fargate API service and the Lambda pipeline
# steps. Based on the AWS Lambda Python base image so the Lambda runtime
# interface client is present; ECS overrides the entrypoint to run uvicorn.
FROM public.ecr.aws/lambda/python:3.12

# Dependencies first for better layer caching.
COPY pyproject.toml README.md ${LAMBDA_TASK_ROOT}/
COPY src ${LAMBDA_TASK_ROOT}/src

RUN python -m pip install --no-cache-dir --upgrade pip \
    && python -m pip install --no-cache-dir "${LAMBDA_TASK_ROOT}"

# Default (Lambda) handler; overridden per-function by image_config.command and
# overridden entirely by the ECS task definition entrypoint for the API.
CMD ["oligos_agents.steps.handlers.route_handler"]
