Wercker step for AWS ECS
=======================

The step is written in Python 3.5 and use Pip and Boto3 module.

## Example

#### `wercker.yml`


* `key` (optional): AWS Access Key ID
* `secret` (optional): AWS Secret Access Key
* `region` (optional): Region name (default: us-east-1)
* `deploy-service-group` (optional): deployment service group. if not set, all service is deployed. deploy-service-group is setting by task-definitions environment `SERVICE_GROUP` value.
* `delete-unused-service` (optional): If template file is deleted, then related service is deleted.  (default: true)
* `template-group` (optional): for multiple repositories deployment. When with multiple repositories, template file is divided. Then, match between `template-group` and task-definition's environment `TEMPLATE_GROUP` is deploy and delete target.
* `threads-count` (optional): deployment thread size. (default: 10)
* `service-zero-keep` (optional): desired count zero's service keep service desired count. (defalut: true)
* `test-templates` (optional): only test templates. do not deploy. (default: false)

service and task-definition settings

* `services-yaml` (required): ecs service and task-definition.
* `environment-yaml` (required): jinja2 template input json data file. `environment:` parameter is required. only same task-definition's environment `ENVIRONMENT` service is deployed.
* `environment-yaml-dir` : for test-templates. all files below directory is loaded.

or

* `task-definition-template-dir` (required): ecs task-definition jinja2 template files directory. all files below directory is loaded.
* `task-definition-json` (required): jinja2 template input json data file. 

```yml
deploy-yaml:
  steps:
    - wacul/aws-ecs:
      key: $AWS_ACCESS_KEY_ID
      secret: $AWS_SECRET_ACCESS_KEY
      region: $AWS_DEFAULT_REGION
      services-yaml: infra/services.yml
      environment-yaml: infra/conf/dev.yml
      deploy-service-group: $DEPLOY_SERVICE_GROUP
      template-group: back

deploy-json:
  steps:
    - wacul/aws-ecs:
      key: $AWS_ACCESS_KEY_ID
      secret: $AWS_SECRET_ACCESS_KEY
      region: $AWS_DEFAULT_REGION
      task-definition-template-dir: infra/template/
      task-definition-config-json: infra/conf/dev.json
      deploy-service-group: $DEPLOY_SERVICE_GROUP
      template-group: back

```
### Yaml Template examples

#### environment-yaml `infra/conf/dev.yml`
`environment` parameter is required. then set docker environment `ENVIRONMENT`.
and  override services paramters.
```
---
environment: dev
cpu: 64
memoryReservation: 64
conf: dev.yaml

services:
  web:
    desiredCount: 4
    vars:
      cpu: 96
      memoryReservation: 96
```
#### service-yaml `infra/services.yml`


* `cluster` (required): deployment ecs cluster name. then set docker environment `CLUSTER_NAME`.
* `templateGroup` (optional): refer to wercker.yml's `template-group`. only same `template-group` is . then set ecs service's environment `TEMPLATE_GROUP`.
* `serviceGroup` (optional): refer to wercker.yml's `deploy-service-group`. only same `service-group` is deployed. then set ecs service's environment `SERVICE_GROUP`.
* `desiredCount` (required): ecs service's desired count. then set ecs service's environment `DESIRED_COUNT`.
* `minimumHealthyPercent` (optional): ecs service's minimum_healthy_percent. then set ecs service's environment `MINIMUM_HEALTHY_PERCENT`. (default: 50)
* `maximumPercent` (optional): ecs service's maximum_percent. then set ecs service's environment `MAXIMUM_PERCENT`. (default: 200)
* `distinctInstance` (optional): ecs service placementConstraints type is distinctInstance. then set ecs service's environment `DISTINCT_INSTANCE`. (default: False)
* `registrator` (optional): set `environment` for ecs service's environment `SERVICE_NAME` and set service name for ecs service's environment `SERVICE_TAGS` (default: False)
* `taskDefinitionTemplate` (required): ecs task definition. can use jinja2 template. service name is set to `{{item}}`.
* `vars` (optional): jinja2 template variables.

```
---

aliases:
  - &cluster_app app

services:
  web:
    cluster: *cluster_app
    serviceGroup: web
    templateGroup: web-repository
    desiredCount: 2
    minimumHealthyPercent: 50
    maximumPercent: 100
    registrator: true
    distinctInstance: true
    taskDefinitionTemplate: default
    vars:
      startupScript: ./infra/script/startup_web.sh
      portMappings:
        - hostPort: 0
          containerPort: 3000
          protocol: tcp

taskDefinitionTemplates:
  default: |
    {
      "family": "{{environment}}-{{item}}",
      "containerDefinitions": [
        {
          "name": "{{environment}}-{{item}}",
          "cpu": {{cpu}},
          "memoryReservation": {{memoryReservation}},
          "image": "quay.io/wacul/ai-analyst-ocha:{{environment}}{% if environment == 'production' %}-{{serviceGroup}}{% endif %}",
          "command": [
            "{{startupScript}}",
            "{{conf}}"
          ],
          "portMappings": {{portMappings|default([])|tojson}},
          "logConfiguration": {
            "logDriver": "syslog",
            "options": {
              "tag": "docker/{{environment}}/{{item}}/{% raw %}{{.ID}}{% endraw %}"
            }
          },
          "volumesFrom": [],
          "mountPoints": [],
          "essential": true
        }
      ]
    }
```

### Json Template examples
#### `infra/conf/dev.json`

`environment` parameter is required. only same task-definition's environment `ENVIRONMENT` service is deployed.

```json
{
  "environment": "development",
  "cpu": 16,
  "memory": 64
}
```

#### `infra/template/example.j2`

task-definition parameters

http://docs.aws.amazon.com/AmazonECS/latest/developerguide/task_definition_parameters.html

can use jinja2 template.
this script use environment variables below:

* `CLUSTER_NAME` (required): deployment ecs cluster name.
* `ENVIRONMENT` (required): deployment environment. only same environment is deployed. related to `task-definition-json`'s environment value
* `TEMPLATE_GROUP` (optional): refer to wercker.yml's `template-group`.
* `SERVICE_GROUP` (optional): refer to wercker.yml's `deploy-service-group`.
* `DESIRED_COUNT` (required): ecs service's desired count.
* `MINIMUM_HEALTHY_PERCENT` (optional): ecs service's minimum_healthy_percent. (default: 50)
* `MAXIMUM_PERCENT` (optional): ecs service's maximum_percent. (default: 200)
* `DISTINCT_INSTANCE` (optional): ecs service placementConstraints type is distinctInstance (default: False)


```
[
  {
    "family": "{{environment}}-web",
    "containerDefinitions":  [
      {
        "environment": [
          {
            "name": "CLUSTER_NAME",
            "value": "cluster"
          },
          {
            "name": "TEMPLATE_GROUP",
            "value": "web-repo"
          },
          {
            "name": "ENVIRONMENT",
            "value": "{{environment}}"
          },
          {
            "name": "SERVICE_GROUP",
            "value": "web"
          },
          {
            "name": "DESIRED_COUNT",
            "value": "2"
          },
          {
            "name": "MINIMUM_HEALTHY_PERCENT",
            "value": "50"
          },
          {
            "name": "MAXIMUM_PERCENT",
            "value": "100"
          }
        ],
        "name": "{{environment}}-web",
        "image": "nginx",
        "cpu": {{cpu}},
        "portMappings": [
          {
            "hostPort": 0,
            "containerPort": 80,
            "protocol": "tcp"
          }
        ],
        "memoryReservation": {{memory}},
        "essential": true
      }
    ]
  }
]
```

## Docker
* template test
```
docker run -it --rm -e "AWS_PROFILE=profile" -v $HOME/.aws/:/root/.aws/ -v $(pwd)/infra/:/infra quay.io/wacul/aws-ecs test-templates --environment-yaml-dir /infra/conf/ --services-yaml infra/services.yml
```

* dry-run
```
docker run -it --rm -e "AWS_PROFILE=profile" -v $HOME/.aws/:/root/.aws/ -v $(pwd)/infra/:/infra quay.io/wacul/aws-ecs service --environment-yaml /infra/conf/dev.yml --service-yaml /infra/services.yml --template-group web-repo --dry-run
```

* run task
```
docker run -it --rm -v $(pwd)/infra/:/infra quay.io/wacul/aws-ecs taskrun --task-definition-template-file /infra/task.json --task-definition-config-json /infra/conf/environment.json --cluster cluster --tumeout 600
```
