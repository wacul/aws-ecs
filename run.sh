#!/bin/sh
set +e
set -o noglob

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
if [ -z "$WERCKER_AWS_ECS_KEY" ]; then
  error "Please set the 'key' variable"
  exit 1
fi

if [ -z "$WERCKER_AWS_ECS_SECRET" ]; then
  error "Please set the 'secret' variable"
  exit 1
fi

if [ -z "$WERCKER_AWS_ECS_TASK_DEFINITION_TEMPLATE_DIR" ]; then
  error "Please set the 'task-definition-template-dir' variable"
  exit 1
fi

if [ -z "$WERCKER_AWS_ECS_TEMPLATE_GROUP" ]; then
  error "Please set the 'template-group' variable"
  exit 1
fi

if [ -z "$WERCKER_AWS_ECS_TASK_DEFINITION_CONFIG_JSON" ]; then
  error "Please set the 'task-definition-config-json' variable"
  exit 1
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
if [ ! -z "$WERCKER_AWS_ECS_THREADS_COUNT" ]; then
  THREADS_COUNT="--threads-count $WERCKER_AWS_ECS_THREADS_COUNT"
fi


python3 "$WERCKER_STEP_ROOT/main.py" \
    --key "$WERCKER_AWS_ECS_KEY" \
    --secret "$WERCKER_AWS_ECS_SECRET" \
    --region "${WERCKER_AWS_ECS_REGION:-us-east-1}" \
    --task-definition-template-dir "$WERCKER_AWS_ECS_TASK_DEFINITION_TEMPLATE_DIR" \
    --template-group "$WERCKER_AWS_ECS_TEMPLATE_GROUP" \
    $NO_TASK_DEFINITION_CONFIG_ENV \
    $NO_DELETE_UNUSED_SERVICE \
    $SERVICE_ZERO_KEEP \
    $DEPLOY_SERVICE_GROUP \
    $THREADS_COUNT \
    --task-definition-config-json "$WERCKER_AWS_ECS_TASK_DEFINITION_CONFIG_JSON"
