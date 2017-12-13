#!/bin/sh
set +e

#
# Headers and Logging
#

error() { printf "✖ %s\n" "$@"
}
warn() { printf "➜ %s\n" "$@"
}

type_exists() {
  if [ $(type -P $1) ]; then
    return 0
  fi
  return 1
}

# Check python is installed
if ! type_exists 'python3'; then
  error "Please install python3"
  exit 
fi

# Check pip is installed
if ! type_exists 'pip3'; then
  if type_exists 'curl'; then
    curl --silent --show-error --retry 5 https://bootstrap.pypa.io/get-pip.py | sudo python3
  elif type_exists 'wget' && type_exists 'openssl'; then
    wget -q -O - https://bootstrap.pypa.io/get-pip.py | sudo python3
  else
    error "Please install pip, curl, or wget with openssl"
    exit 1
  fi
fi

# Install python dependencies
INSTALL_DEPENDENCIES=$(pip3 install -r $WERCKER_STEP_ROOT/requirements.txt 2>&1)
if [ $? -ne 0 ]; then
  error "Unable to install dependencies"
  warn "$INSTALL_DEPENDENCIES"
  exit 1
fi

# Check variables
if [ ! -z "$WERCKER_AWS_ECS_SERVICES_YAML" ]; then
  if [ "$WERCKER_AWS_ECS_TEST_TEMPLATES" == 'true' ]; then
    if [ -z "$WERCKER_AWS_ECS_ENVIRONMENT_YAML_DIR" ]; then
      error "Please set the '--environment-yaml-dir' variable"
      exit 1
    fi
    TASK_DEFINITION="--services-yaml $WERCKER_AWS_ECS_SERVICES_YAML --environment-yaml-dir $WERCKER_AWS_ECS_ENVIRONMENT_YAML_DIR"
  else 
    if [ -z "$WERCKER_AWS_ECS_ENVIRONMENT_YAML" ]; then
      error "Please set the '--environment-yaml' variable"
      exit 1
    fi
    TASK_DEFINITION="--services-yaml $WERCKER_AWS_ECS_SERVICES_YAML --environment-yaml $WERCKER_AWS_ECS_ENVIRONMENT_YAML"
  fi
else
  if [ -z "$WERCKER_AWS_ECS_TASK_DEFINITION_TEMPLATE_DIR" ]; then
    error "Please set the '--services-yaml or --task-definition-config-json' variable"
    exit 1
  fi
  if [ -z "$WERCKER_AWS_ECS_TASK_DEFINITION_CONFIG_JSON" ]; then
    error "Please set the '--task-definition-config-json' variable"
    exit 1
  fi
  TASK_DEFINITION="--task-definition-template-dir $WERCKER_AWS_ECS_TASK_DEFINITION_TEMPLATE_DIR --task-definition-config-json $WERCKER_AWS_ECS_TASK_DEFINITION_CONFIG_JSON"
fi

if [ ! -z "$WERCKER_AWS_ECS_TEMPLATE_GROUP" ]; then
  TEMPLATE_GROUP="--template-group $WERCKER_AWS_ECS_TEMPLATE_GROUP"
fi


if [ "$WERCKER_AWS_ECS_TASK_DEFINITION_CONFIG_ENV" == 'false' ]; then
  TASK_DEFINITION_CONFIG_ENV='--no-task-definition-config-env'
fi
if [ "$WERCKER_AWS_ECS_SERVICE_ZERO_KEEP" == 'false' ]; then
  SERVICE_ZERO_KEEP='--no-service-zero-keep'
fi
if [ ! -z "$WERCKER_AWS_ECS_DEPLOY_SERVICE_GROUP" ]; then
  DEPLOY_SERVICE_GROUP="--deploy-service-group $WERCKER_AWS_ECS_DEPLOY_SERVICE_GROUP"
fi
if [ "$WERCKER_AWS_ECS_DELETE_UNUSED_SERVICE" == 'false' ]; then
  NO_DELETE_UNUSED_SERVICE='--no-delete-unused-service'
fi
if [ "$WERCKER_AWS_ECS_STOP_BEFORE_DEPLOY" == 'false' ]; then
  NO_STOP_BEFORE_DEPLOY='--no-stop-before-deploy'
fi
if [ ! -z "$WERCKER_AWS_ECS_THREADS_COUNT" ]; then
  THREADS_COUNT="--threads-count $WERCKER_AWS_ECS_THREADS_COUNT"
fi
if [ ! -z "$WERCKER_AWS_ECS_SERVICE_WAIT_MAX_ATTEMPTS" ]; then
  SERVICE_WAIT_MAX_ATTEMPTS="--service-wait-max-attempts $WERCKER_AWS_ECS_SERVICE_WAIT_MAX_ATTEMPTS"
fi
if [ ! -z "$WERCKER_AWS_ECS_SERVICE_WAIT_DELAY" ]; then
  SERVICE_WAIT_DELAY="--service-wait-delay $WERCKER_AWS_ECS_SERVICE_WAIT_DELAY"
fi


if [ "$WERCKER_AWS_ECS_TEST_TEMPLATES" == 'true' ]; then
    python3 "$WERCKER_STEP_ROOT/main.py" test-templates \
        $TASK_DEFINITION
else
    python3 "$WERCKER_STEP_ROOT/main.py" service \
        --key "$WERCKER_AWS_ECS_KEY" \
        --secret "$WERCKER_AWS_ECS_SECRET" \
        --region "${WERCKER_AWS_ECS_REGION:-us-east-1}" \
        $TEMPLATE_GROUP \
        $NO_TASK_DEFINITION_CONFIG_ENV \
        $NO_DELETE_UNUSED_SERVICE \
        $SERVICE_ZERO_KEEP \
        $DEPLOY_SERVICE_GROUP \
        $THREADS_COUNT \
        $NO_STOP_BEFORE_DEPLOY \
        $TASK_DEFINITION \
        $SERVICE_WAIT_MAX_ATTEMPTS \
        $SERVICE_WAIT_DELAY
fi
