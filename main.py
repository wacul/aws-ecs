# coding: utf-8
from __future__ import unicode_literals
import logging
import sys
import argparse

from ecs import ECSService
from ecs import ServiceNotFoundException

logging.basicConfig(stream=sys.stdout, level=logging.INFO, format='%(message)s')
logging.getLogger("botocore").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)
h1 = lambda x: logger.info("\033[1m\033[4m\033[94m%s\033[0m\n" % x)
success = lambda x: logger.info("\033[92m✔ %s\033[0m\n" % x)
error = lambda x: logger.info("\033[91m✖ %s\033[0m\n" % x)

# Arguments parsing
parser = argparse.ArgumentParser(description='Deploy Service on ECS')
parser.add_argument('--key', dest='key', required=True)
parser.add_argument('--secret', dest='secret', required=True)
parser.add_argument('--region', dest='region', default='us-east-1')
parser.add_argument('--cluster-name', dest='cluster_name', required=True)
parser.add_argument('--task-definition-name', dest='task_definition_name', required=True)
parser.add_argument('--task-definition-file', dest='task_definition_file', required=True)
parser.add_argument('--task-definition-template', dest='task_definition_template', required=True)
parser.add_argument('--task-definition-template-yaml', dest='task_definition_template_yaml', required=True)
parser.add_argument('--task-definition-template-json', dest='task_definition_template_json', required=True)
parser.add_argument('--service-name', dest='service_name', required=False)
parser.add_argument('--service-desired-count', type=int, dest='service_desired_count', required=False)
parser.add_argument('--service-maximum-percent', type=int, dest='service_maximum_percent', default=200, required=False)
parser.add_argument('--service-minimum-healthy-percent', type=int, dest='service_minimum_healthy_percent', default=50, required=False)
parser.add_argument('--downscale-tasks', dest='downscale_tasks', default=False, action='store_true', required=False)
parser.add_argument('--no-downscale-tasks', dest='downscale_tasks', default=False, action='store_false', required=False)
parser.add_argument('--minimum-running-tasks', type=int, dest='minimum_running_tasks', default=1, required=False)
args = parser.parse_args()

try:

    serviceMode = args.service_name is not None

    # Step: Configuring AWS
    h1("Step: Configuring AWS")
    ecs = ECSService(access_key=args.key, secret_key=args.secret, region=args.region)
    success("Configuring AWS succeeded")

    # Step: Check ECS cluster
    h1("Step: Check ECS cluster")
    ecs.describe_cluster(cluster=args.cluster_name)
    success("Checking cluster '%s' succeeded" % args.cluster_name)

    # Step: Register New Task Definition
    h1("Step: Register New Task Definition")
    response = ecs.register_task_definition(family=args.task_definition_name, file=args.task_definition_file, template=args.task_definition_template, template_yaml=args.task_definition_template_yaml, template_json=args.task_definition_template_json)
    task_definition_arn = response.get('taskDefinition').get('taskDefinitionArn')
    success("Registering task definition '%s' succeeded" % task_definition_arn)

    if serviceMode:
        h1("Step: Check ECS Service")
        create_service = False
        try:
            response = ecs.describe_service(cluster=args.cluster_name, service=args.service_name)
            original_running_count = (response.get('services')[0]).get('runningCount')
            success("Checking service '%s' succeeded (%d tasks running)" % (args.service_name, original_running_count))
        except ServiceNotFoundException:
            error("Service not Found.")
            create_service = True
        except:
            raise
        if response['services'][0]['status'] == 'INACTIVE':
            error("Service status is INACTIVE.")
            create_service = True

        if create_service:
            h1("Step: Create ECS Service")
            response = ecs.create_service(cluster=args.cluster_name, service=args.service_name, taskDefinition=task_definition_arn, desiredCount=args.service_desired_count, maximumPercent=args.service_maximum_percent, minimumHealthyPercent=args.service_minimum_healthy_percent)
            original_running_count = (response.get('services')[0]).get('runningCount')
            success("Create service '%s' succeeded (%d tasks running)" % (args.service_name, original_running_count))
            sys.exit(0)

        # Step: Downscale ECS Service if necessary
        if args.downscale_tasks and original_running_count >= args.minimum_running_tasks:
            h1("Step: Downscale ECS Service")
            response = ecs.downscale_service(cluster=args.cluster_name, service=args.service_name)
            downscale_running_count = (response.get('services')[0]).get('runningCount')
            success("Downscaling service '%s' (from %d to %d tasks) succeeded"
                    % (args.service_name, original_running_count, downscale_running_count))
            delta = 1
        else:
            h1("Step: Downscale ECS Service")
            success("Downscaling service is not necessary")
            delta = args.minimum_running_tasks - original_running_count

        # Step: Update ECS Service
        h1("Step: Update ECS Service")
        response = ecs.update_service(cluster=args.cluster_name, service=args.service_name, taskDefinition=task_definition_arn)
        running_count = (response.get('services')[0]).get('runningCount')
        success("Updating service '%s' with task definition '%s' succeeded" % (args.service_name, task_definition_arn))

        # Step: Upscale ECS Service
        h1("Step: Upscale ECS Service")
        response = ecs.upscale_service(cluster=args.cluster_name, service=args.service_name, delta=delta)
        upscale_running_count = (response.get('services')[0]).get('runningCount')
        success("Upscaling service '%s' (from %d to %d tasks) succeeded"
                % (args.service_name, running_count, upscale_running_count))
    else:
        # Step: run task
        h1("Step: Run task")
        response = ecs.run_task(cluster=args.cluster_name, family=args.task_definition_name)
        success("Task %s succeeded" % (response.get('tasks')[0].get('taskArn')))

except Exception as e:
    raise
    error(e)
    sys.exit(1)
