#!/bin/sh
set +e

#
# Headers and Logging
#

error() { printf "✖ %s\n" "$@"
}
warn() { printf "➜ %s\n" "$@"
}

# Check variables
if [ ! -z "$AWS_ECS_SERVICES_YAML" ]; then
  if [ "$AWS_ECS_TEST_TEMPLATES" == 'true' ]; then
    if [ -z "$AWS_ECS_ENVIRONMENT_YAML_DIR" ]; then
      error "Please set the '--environment-yaml-dir' variable"
      exit 1
    fi
    TASK_DEFINITION="--services-yaml $AWS_ECS_SERVICES_YAML --environment-yaml-dir $AWS_ECS_ENVIRONMENT_YAML_DIR"
  else 
    if [ -z "$AWS_ECS_ENVIRONMENT_YAML" ]; then
      error "Please set the '--environment-yaml' variable"
      exit 1
    fi
    TASK_DEFINITION="--services-yaml $AWS_ECS_SERVICES_YAML --environment-yaml $AWS_ECS_ENVIRONMENT_YAML"
  fi
else
  if [ -z "$AWS_ECS_TASK_DEFINITION_TEMPLATE_DIR" ]; then
    error "Please set the '--services-yaml or --task-definition-config-json' variable"
    exit 1
  fi
  if [ -z "$AWS_ECS_TASK_DEFINITION_CONFIG_JSON" ]; then
    error "Please set the '--task-definition-config-json' variable"
    exit 1
  fi
  TASK_DEFINITION="--task-definition-template-dir $AWS_ECS_TASK_DEFINITION_TEMPLATE_DIR --task-definition-config-json $AWS_ECS_TASK_DEFINITION_CONFIG_JSON"
fi

if [ ! -z "$AWS_ECS_TEMPLATE_GROUP" ]; then
  TEMPLATE_GROUP="--template-group $AWS_ECS_TEMPLATE_GROUP"
fi


if [ "$AWS_ECS_TASK_DEFINITION_CONFIG_ENV" == 'false' ]; then
  TASK_DEFINITION_CONFIG_ENV='--no-task-definition-config-env'
fi
if [ "$AWS_ECS_SERVICE_ZERO_KEEP" == 'false' ]; then
  SERVICE_ZERO_KEEP='--no-service-zero-keep'
fi
if [ ! -z "$AWS_ECS_DEPLOY_SERVICE_GROUP" ]; then
  DEPLOY_SERVICE_GROUP="--deploy-service-group $AWS_ECS_DEPLOY_SERVICE_GROUP"
fi
if [ "$AWS_ECS_DELETE_UNUSED_SERVICE" == 'false' ]; then
  NO_DELETE_UNUSED_SERVICE='--no-delete-unused-service'
fi
if [ "$AWS_ECS_STOP_BEFORE_DEPLOY" == 'false' ]; then
  NO_STOP_BEFORE_DEPLOY='--no-stop-before-deploy'
fi
if [ ! -z "$AWS_ECS_THREADS_COUNT" ]; then
  THREADS_COUNT="--threads-count $AWS_ECS_THREADS_COUNT"
fi
if [ ! -z "$AWS_ECS_SERVICE_WAIT_MAX_ATTEMPTS" ]; then
  SERVICE_WAIT_MAX_ATTEMPTS="--service-wait-max-attempts $AWS_ECS_SERVICE_WAIT_MAX_ATTEMPTS"
fi
if [ ! -z "$AWS_ECS_SERVICE_WAIT_DELAY" ]; then
  SERVICE_WAIT_DELAY="--service-wait-delay $AWS_ECS_SERVICE_WAIT_DELAY"
fi
if [ "$AWS_ECS_SERVICE_UPDATE_ONLY" == 'true' ]; then
  SERVICE_UPDATE_ONLY="--service-update-only"
fi
if [ "$AWS_ECS_TASK_DEFINITION_UPDATE_ONLY" == 'true' ]; then
  TASK_DEFINITION_UPDATE_ONLY="--task-definition-update-only"
fi

if [ "$AWS_ECS_TEST_TEMPLATES" == 'true' ]; then
    python3 /app/main.py test-templates \
        $TASK_DEFINITION
else
    python3 /app/main.py service \
        --key "$AWS_ECS_KEY" \
        --secret "$AWS_ECS_SECRET" \
        --region "${AWS_ECS_REGION:-us-east-1}" \
        $TEMPLATE_GROUP \
        $NO_TASK_DEFINITION_CONFIG_ENV \
        $NO_DELETE_UNUSED_SERVICE \
        $SERVICE_ZERO_KEEP \
        $DEPLOY_SERVICE_GROUP \
        $THREADS_COUNT \
        $NO_STOP_BEFORE_DEPLOY \
        $TASK_DEFINITION \
        $SERVICE_WAIT_MAX_ATTEMPTS \
        $SERVICE_WAIT_DELAY \
        $SERVICE_UPDATE_ONLY \
        $TASK_DEFINITION_UPDATE_ONLY
fi
