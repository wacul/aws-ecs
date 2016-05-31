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
if ! type_exists 'python2.7'; then
  error "Please install python 2.7"
  exit 1
fi

# Check pip is installed
if ! type_exists 'pip'; then
  if type_exists 'curl'; then
    curl --silent --show-error --retry 5 https://bootstrap.pypa.io/get-pip.py | sudo python2.7
  elif type_exists 'wget' && type_exists 'openssl'; then
    wget -q -O - https://bootstrap.pypa.io/get-pip.py | sudo python2.7
  else
    error "Please install pip, curl, or wget with openssl"
    exit 1
  fi
fi

# Install python dependencies
INSTALL_DEPENDENCIES=$(pip install -r $WERCKER_STEP_ROOT/requirements.txt 2>&1)
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

if [ -z "$WERCKER_AWS_ECS_CLUSTER_NAME" ]; then
  error "Please set the 'cluster-name' variable"
  exit 1
fi

if [ -z "$WERCKER_AWS_ECS_TASK_DEFINITION_NAMES" ]; then
  error "Please set the 'task-definition-names' variable"
  exit 1
fi

if [ -z "$WERCKER_AWS_ECS_TASK_DEFINITION_FILES" -a -z "$WERCKER_AWS_ECS_TASK_DEFINITION_TEMPLATES" ]; then
  error "Please set the 'task-definition-files' or 'task-definition-templates' variable"
  exit 1
fi



if [ -z "$WERCKER_AWS_ECS_SERVICE_NAMES" ]; then
  if [ "$WERCKER_AWS_ECS_TASK_DEFINITION_TEMPLATE_ENV" == 'false' ]; then
    NO_TASK_DEFINITION_TEMPLATE_ENV='--no-task-definition-template-env'
  fi
  python "$WERCKER_STEP_ROOT/main.py" \
    --key "$WERCKER_AWS_ECS_KEY" \
    --secret "$WERCKER_AWS_ECS_SECRET" \
    --region "${WERCKER_AWS_ECS_REGION:-us-east-1}" \
    --cluster-name "$WERCKER_AWS_ECS_CLUSTER_NAME" \
    --task-definition-names "$WERCKER_AWS_ECS_TASK_DEFINITION_NAMES" \
    --task-definition-files "$WERCKER_AWS_ECS_TASK_DEFINITION_FILES" \
    --task-definition-templates "$WERCKER_AWS_ECS_TASK_DEFINITION_TEMPLATES" \
    $NO_TASK_DEFINITION_TEMPLATE_ENV \
    --task-definition-template-json "$WERCKER_AWS_ECS_TASK_DEFINITION_TEMPLATE_JSON"
else
  if [ "$WERCKER_AWS_ECS_TASK_DEFINITION_TEMPLATE_ENV" == 'false' ]; then
    TASK_DEFINITION_TEMPLATE_ENV='--no-task-definition-template-env'
  fi
  if [ "$WERCKER_AWS_ECS_DOWNSCALE_TASKS" == 'true' ]; then
    DOWNSCALE_TASKS='--downscale-tasks'
  fi
  python "$WERCKER_STEP_ROOT/main.py" \
    --key "$WERCKER_AWS_ECS_KEY" \
    --secret "$WERCKER_AWS_ECS_SECRET" \
    --region "${WERCKER_AWS_ECS_REGION:-us-east-1}" \
    --cluster-name "$WERCKER_AWS_ECS_CLUSTER_NAME" \
    --task-definition-names "$WERCKER_AWS_ECS_TASK_DEFINITION_NAMES" \
    --task-definition-files "$WERCKER_AWS_ECS_TASK_DEFINITION_FILES" \
    --task-definition-templates "$WERCKER_AWS_ECS_TASK_DEFINITION_TEMPLATES" \
    $NO_TASK_DEFINITION_TEMPLATE_ENV \
    --task-definition-template-json "$WERCKER_AWS_ECS_TASK_DEFINITION_TEMPLATE_JSON" \
    --service-names "$WERCKER_AWS_ECS_SERVICE_NAMES" \
    --service-desired-count "$WERCKER_AWS_ECS_SERVICE_DESIRED_COUNT" \
    $DOWNSCALE_TASKS \
    --minimum-running-tasks "${WERCKER_AWS_ECS_MINIMUM_RUNNING_TASKS:-1}" \
    --service-maximum-percent "${WERCKER_AWS_ECS_SERVICE_MAXIMUM_PERCENT:-200}" \
    --service-minimum-healthy-percent "${WERCKER_AWS_ECS_SERVICE_MINIMUM_HEALTHY_PERCENT:-50}"
fi



