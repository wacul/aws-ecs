Wercker step for AWS ECS
=======================

The step is written in Python 3.5 and use Pip and Boto3 module.

#### Step [Configuring AWS](http://docs.aws.amazon.com/cli/latest/reference/configure/index.html)

This initial step consists on configuring AWS.

The following configuration allows to setup this step :

* `key` (required): AWS Access Key ID
* `secret` (required): AWS Secret Access Key
* `region` (optional): Default region name

## Example

```wercker.yml
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

```json:conf/dev.conf
{
  "environment": "development",
  "cpu": 16,
  "memory": 64
}
```

```templates/example.template
[
  {
    "family": "{{environment}}-web",
    "containerDefinitions":  [
      {
        "environment": [
          {
            "name": "CLUSTER_NAME",
            "value": "cluster"
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
            "name": "MINIMUM_RUNNING_TASKS",
            "value": "1"
          },
          {
            "name": "DOWNSCALE_TASK",
            "value": false
          }
        ],
        "name": "{{environment}}-web",
        "image": "helloworld"
        "cpu": {{cpu}},
        "portMappings": [
          {
            "hostPort": 0,
            "containerPort": 8080,
            "protocol": "tcp"
          }
        ],
        "memory": {{memory}},
        "essential": true
      }
    ]
  }
]
```
