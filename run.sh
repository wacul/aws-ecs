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
INSTALL_DEPENDENCIES=$(pip install --upgrade -r $WERCKER_STEP_ROOT/requirements.txt 2>&1)
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

if [ -z "$WERCKER_AWS_ECS_TASK_DEFINITION_NAME" ]; then
  error "Please set the 'task-definition-name' variable"
  exit 1
fi

if [ -z "$WERCKER_AWS_ECS_TASK_DEFINITION_FILE" -a -z "$WERCKER_AWS_ECS_TASK_DEFINITION_TEMPLATE" ]; then
  error "Please set the task-definition variable"
  exit 1
elif [ ! -z "$WERCKER_AWS_ECS_TASK_DEFINITION_TEMPLATE" -a -z "$WERCKER_AWS_ECS_TASK_DEFINITION_TEMPLATE_YAML" ];then
  error "'task-definition-template' requires 'task-definition-template-yaml'"
  exit 1
fi



if [ -z "$WERCKER_AWS_ECS_SERVICE_NAME" ]; then
  python "$WERCKER_STEP_ROOT/main.py" \
    --key "$WERCKER_AWS_ECS_KEY" \
    --secret "$WERCKER_AWS_ECS_SECRET" \
    --region "${WERCKER_AWS_ECS_REGION:-us-east-1}" \
    --cluster-name "$WERCKER_AWS_ECS_CLUSTER_NAME" \
    --task-definition-name "$WERCKER_AWS_ECS_TASK_DEFINITION_NAME" \
    --task-definition-file "$WERCKER_AWS_ECS_TASK_DEFINITION_FILE" \
    --task-definition-template "$WERCKER_AWS_ECS_TASK_DEFINITION_TEMPLATE" \
    --task-definition-template-yaml "$WERCKER_AWS_ECS_TASK_DEFINITION_TEMPLATE_YAML"
else
  if [ "$WERCKER_DOWNSCALE_TASKS" == 'true' ]; then
    DOWNSCALE_TASKS='--downscale-tasks'
  fi
  python "$WERCKER_STEP_ROOT/main.py" \
    --key "$WERCKER_AWS_ECS_KEY" \
    --secret "$WERCKER_AWS_ECS_SECRET" \
    --region "${WERCKER_AWS_ECS_REGION:-us-east-1}" \
    --cluster-name "$WERCKER_AWS_ECS_CLUSTER_NAME" \
    --task-definition-name "$WERCKER_AWS_ECS_TASK_DEFINITION_NAME" \
    --task-definition-file "$WERCKER_AWS_ECS_TASK_DEFINITION_FILE" \
    --task-definition-template "$WERCKER_AWS_ECS_TASK_DEFINITION_TEMPLATE" \
    --task-definition-template-yaml "$WERCKER_AWS_ECS_TASK_DEFINITION_TEMPLATE_YAML" \
    --service-name "$WERCKER_AWS_ECS_SERVICE_NAME" \
    --service-desired-count "$WERCKER_AWS_ECS_SERVICE_DESIRED_COUNT" \
    $DOWNSCALE_TASKS \
    --minimum-running-tasks "${WERCKER_AWS_ECS_MINIMUM_RUNNING_TASKS:-1}"
fi



