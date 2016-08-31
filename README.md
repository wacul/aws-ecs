Wercker step for AWS ECS
=======================

The step is written in Python 3.5 and use Pip and Boto3 module.

## Example

##### `wercker.yml`

```yml
deploy:
  steps:
    - wacul/aws-ecs:
        key: $AWS_ACCESS_KEY_ID
        secret: $AWS_SECRET_ACCESS_KEY
        deploy-service-group: web
        task-definition-template-dir: templates/
        task-definition-json: conf/dev.json
        template-group: app
```

##### `conf/dev.conf`

```json
{
  "environment": "development",
  "cpu": 16,
  "memory": 64
}
```

##### `templates/example.template.j2`

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
