Wercker step for AWS ECS
=======================

The step is written in Python 3.5 and use Pip and Boto3 module.

## Example

#### `wercker.yml`


* `key` (required): AWS Access Key ID
* `secret` (required): AWS Secret Access Key
* `region` (optional): Region name (default: us-east-1)
* `task-definition-template-dir` (required): ecs task-definition jinja2 template files directory. all files below directory is loaded.
* `task-definition-json` (required): jinja2 template input json data file. `environment:` parameter is required. only same task-definition's environment `ENVIRONMENT` service is deployed.
* `deploy-service-group` (optional): deployment service group. if not set, all service is deployed. deploy-service-group is setting by task-definitions environment `SERVICE_GROUP` value.
* `delete-unused-service` (optional): If template file is deleted, then related service is delete.  (default: true)
* `template-group` (optional): for multiple repositories deployment. on delete-unused-service, can not found template file's service is delete. But, when multiple repositories deploy, template file is divided. Then, setting `template-group`,  only task-definition's environment `TEMPLATE_GROUP` is deployed target.  only affect to delete-unused-service.
* `threads-count` (optional): deployment thread size. default: 10

```yml
deploy:
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

#### `infra/conf/dev.conf`

`environment` parameter is required. only same task-definition's environment `ENVIRONMENT` service is deployed.

```json
{
  "environment": "development",
  "cpu": 16,
  "memory": 64
}
```

#### `infra/template/example.template.j2`

http://docs.aws.amazon.com/AmazonECS/latest/developerguide/task_definition_parameters.html

* `CLUSTER_NAME` (required): deployment ecs cluster name.
* `ENVIRONMENT` (required): deployment environment. only same environment is deployed. related to `task-definition-json`'s environment value
* `TEMPLATE_GROUP` (optional): related to wercker.yml's `template-group`.
* `SERVICE_GROUP` (optional): related to wercker.yml's `deploy-service-group`.
* `DESIRED_COUNT` (required): ecs service's desired count.
* `MINIMUM_HEALTHY_PERCENT` (optional): ecs service's minimum_healthy_percent. (default: 50)
* `MAXIMUM_PERCENT` (optional): ecs service's maximum_percent. (default: 200)


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
            "value": "app"
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
        "image": "helloworld",
        "cpu": {{cpu}},
        "portMappings": [
          {
            "hostPort": 0,
            "containerPort": 8080,
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
