Wercker step for AWS ECS
=======================

The step is written in Python 3.5 and use Pip and Boto3 module.

## Example

#### `wercker.yml`


* `key` (optional): AWS Access Key ID
* `secret` (optional): AWS Secret Access Key
* `region` (optional): Region name (default: us-east-1)
* `delete-unused-service` (optional): When services or scheduledTask on `services-yml` or `task-definition-template-dir` was deleted or disabled, then ecs service is deleted.  (default: true)
* `template-group` (optional): For multiple repositories ecs cluster deployment. When delete unused service with multiple repositories deployment, service and scheduled task settings exists for each repository. Then, only matches between `template-group` and ecs task-definition's environment `TEMPLATE_GROUP` value are targeted.
* `deploy-service-group` (optional): Only matches between `deploy-service-group` and ecs task-defintion `service-group` value on `service-yml` are deployed. If do not set `deploy-service-group` value, all service and scheduled task is deployed.
* `threads-count` (optional): python thread size. (default: 10)
* `service-wait-max-attempts` (optional): ecs wait for stable max attempts. (default: 18)
* `service-wait-delay` (optional): ecs wait for stable delay. (default: 10)
* `service-zero-keep` (optional): when deployment, if ecs service with desired count 0, keep service desired count 0. (default: true)
* `stop-before-deploy` (optional): If this value is false, `stopBeforeDeploy` option in `services-yml` is ignored.  (default: true)

test templates

* `test-templates` (optional): test templates. do not deploy. (default: false)

service and task-definition settings. Details are described later.

* `services-yaml` (required): ecs service and task-definition settings file.
* `environment-yaml` (required): jinja2 template input json data file. `environment:` parameter is required. only same task-definition's environment `ENVIRONMENT` service is deployed.
* `environment-yaml-dir` : for test-templates. all files below directory is loaded.

or

* `task-definition-template-dir` (required): ecs task-definition jinja2 template files directory. all files below directory is loaded.
* `task-definition-json` (required): jinja2 template input json data file. 

```:yaml
  steps:
    - wacul/aws-ecs:
      key: $AWS_ACCESS_KEY_ID
      secret: $AWS_SECRET_ACCESS_KEY
      region: $AWS_DEFAULT_REGION
      services-yaml: infra/services.yml
      environment-yaml: infra/conf/dev.yml
      deploy-service-group: group
      template-group: repo
# or
  steps:
    - wacul/aws-ecs:
      key: $AWS_ACCESS_KEY_ID
      secret: $AWS_SECRET_ACCESS_KEY
      region: $AWS_DEFAULT_REGION
      task-definition-template-dir: infra/template/
      task-definition-config-json: infra/conf/dev.json
      deploy-service-group: group
      template-group: repo
```

### Yaml Template examples

#### environment-yaml

`environment` parameter is required. then set docker environment `ENVIRONMENT` value.

```yaml

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

#### services-yaml

##### service parameters

* `cluster` (required): The ecs cluster name to deploy. then set ecs task-definition environment `CLUSTER_NAME` value.
* `templateGroup` (optional): refer to wercker.yml's `template-group`. Set ecs task-definition's environment `TEMPLATE_GROUP` value.
* `serviceGroup` (optional): refer to wercker.yml's `deploy-service-group`. Set ecs task-definition's environment `SERVICE_GROUP` value.
* `desiredCount` (required): Set ecs service desired count. then set ecs task-definition's environment `DESIRED_COUNT` value.
* `minimumHealthyPercent` (optional): Set ecs service minimum_healthy_percent. then set ecs task-definition's environment `MINIMUM_HEALTHY_PERCENT` value. (default: 50)
* `maximumPercent` (optional): Set ecs service maximum_percent. then set ecs task-definition's environment `MAXIMUM_PERCENT` value. (default: 200)
* `distinctInstance` (optional): Set ecs service placementConstraints type to distinctInstance. then set ecs task-definition's environment `DISTINCT_INSTANCE` value. (default: False)
* `registrator` (optional): Set ecs service environment `SERVICE_NAME` to environment parameter value and Set ecs task-definition environment `SERVICE_TAGS` value to service name. (default: False)
* `taskDefinitionTemplate` (required): Specify ecs task-definition template name from `taskDefinitionTemplates`. service name is set to `{{item}}`.
* `disabled` (optional): if parameter is true, scheduled task is disabled. (default: False)
* `stopBeforeDeploy` (optional): if this parameter is true, stop service before ecs service update. (default: False)
* `placementStrategy` (optional): ecs service run strategy. then set ecs service environment `PLACEMENT_STRATEGY` value.
* `primaryPlacement` (optional): if this parameter is true, ecs service start up first.
* `loadBlancers` (optional): elb settings. list.
  * `loadBalancerName`: elb name.
  * `targetGroupArn`: elb target group arn.
  * `containerName`: container name to associate with the elb.
  * `containerPort`: port number to associaate with elb.
* `vars` (optional): jinja2 template variable settings.


##### scheduled task parameters

* `cluster` (required): The ecs cluster name to run. then set ecs task-definition environment `CLUSTER_NAME` value.
* `templateGroup` (optional): refer to wercker.yml's `template-group`. Set ecs task-definition's environment `TEMPLATE_GROUP` value.
* `serviceGroup` (optional): refer to wercker.yml's `deploy-service-group`. Set ecs task-definition's environment `SERVICE_GROUP` value.
* `cloudwatchEvent`
  * `scheduleExpression` (required): cloudwatch event schedule expression.
  * `targetLambdaArn` (required): cloudwatch event target lambda arn. 
* `placementStrategy` (optional): ecs task run strategy. then set ecs service environment `PLACEMENT_STRATEGY` value.
* `taskDefinitionTemplate` (required): Specify ecs task-definition template name from `taskDefinitionTemplates`. scheduled task name is set to `{{item}}`.
* `taskCount` (required): ecs task run count. then set ecs service's environment `TASK_COUNT`.
* `disabled` (optional): if parameter is true, service is disabled. (default: False)
* `vars` (optional): jinja2 template variable settings.


##### taskDefinitionTemplates

Template can use jinja2 template engine. service or scheduled task name is set to `{{item}}`. 

```yaml

---

aliases:
  - &cluster_applications app
  - &cluster_batch batch

services:
  web:
    cluster: *cluster_applications
    serviceGroup: web
    templateGroup: repo
    desiredCount: 2
    minimumHealthyPercent: 50
    maximumPercent: 100
    registrator: true
    distinctInstance: true
    taskDefinitionTemplate: default
    vars:
      startupScript: ./script/startup_web.sh
      portMappings:
        - hostPort: 0
          containerPort: 3000
          protocol: tcp
scheduledTasks:
  batch:
    cluster: *cluster_batch
    serviceGroup: batch
    templateGroup: repo
    taskCount: 1
    placementStrategy:
      - field: memory
        type": binpack
    cloudwatchEvent:
      scheduleExpression: rate(5 minutes)
      targetLambdaArn: arn:aws:lambda:us-east-1:111111111111:function:lambda_name
    taskDefinitionTemplate: default
    vars:
      cpu: 64
      memory: 64
      startupScript: ./script/run.sh

taskDefinitionTemplates:
  default: |
    {
      "family": "{{environment}}-{{item}}",
      "containerDefinitions": [
        {
          "name": "{{environment}}-{{item}}",
          "cpu": {{cpu}},
          "memoryReservation": {{memoryReservation}},
          "image": "mydomain/myimage:{{environment}}{% if environment == 'production' %}-{{serviceGroup}}{% endif %}",
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

* `CLUSTER_NAME` (required): The ecs cluster name to deploy.
* `ENVIRONMENT` (required): deployment environment.
* `TEMPLATE_GROUP` (optional): refer to wercker.yml's `template-group`.
* `SERVICE_GROUP` (optional): refer to wercker.yml's `deploy-service-group`.
* `DESIRED_COUNT` (required): ecs service desired count.
* `MINIMUM_HEALTHY_PERCENT` (optional): ecs service minimum_healthy_percent. (default: 50)
* `MAXIMUM_PERCENT` (optional): ecs service maximum_percent. (default: 200)
* `DISTINCT_INSTANCE` (optional): set ecs service placementConstraints type to distinctInstance (default: False)

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

* delete

```
docker run -it --rm -e "AWS_PROFILE=profile" -v $HOME/.aws/:/root/.aws/ -v $(pwd)/infra/:/infra quay.io/wacul/aws-ecs delete --environment dev
```
