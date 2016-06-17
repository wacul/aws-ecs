# coding: utf-8
from __future__ import unicode_literals
import logging
import sys
import argparse
from multiprocessing import Process, Manager, Pool

from ecs import ECSService
from ecs import ServiceNotFoundException

POOL_PROCESSES=10

class ECSServiceState(object):
    def __init__(self, service_name, task_name, task_definition_arn):
        self.service_name = service_name
        self.task_name = task_name
        self.task_definition_arn = task_definition_arn
        self.service_exist = False
        self.original_running_count = 0
        self.downscale_running_count = 0
        self.running_count = 0
        self.delta = 0
        self.downscale_apply_result = None
        self.update_apply_result = None
        self.upscale_apply_result = None


def downscale_ecs_service(cluster_name, service_name):
    ecs_service = ECSService(access_key=args.key, secret_key=args.secret, region=args.region)
    return ecs_service.downscale_service(cluster=cluster_name, service=service_name)

def update_ecs_service(cluster_name, service_name, task_definition_arn):
    ecs_service = ECSService(access_key=args.key, secret_key=args.secret, region=args.region)
    return ecs_service.update_service(cluster=cluster_name, service=service_name, taskDefinition=task_definition_arn)

def upscale_ecs_service(cluster_name, service_name, delta):
    ecs_service = ECSService(access_key=args.key, secret_key=args.secret, region=args.region)
    return ecs_service.upscale_service(cluster=cluster_name, service=service_name, delta=delta)

def get_separated_args(value):
    if value:
        value = value.rstrip('\\n').replace('\\n', ',')
        value = value.replace(' ', ',')
        print value
        return value.split(',')
    return None

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
parser.add_argument('--task-definition-names', dest='task_definition_names', required=False)
parser.add_argument('--task-definition-files', dest='task_definition_files', required=False)
parser.add_argument('--task-definition-templates', dest='task_definition_templates', required=False)
parser.add_argument('--task-definition-template-json', dest='task_definition_template_json', required=False)
parser.add_argument('--task-definition-template-env', dest='task_definition_template_env', default=True, action='store_true', required=False)
parser.add_argument('--no-task-definition-template-env', dest='task_definition_template_env', default=True, action='store_false', required=False)
parser.add_argument('--service-names', dest='service_names', required=False)
parser.add_argument('--service-desired-count', type=int, dest='service_desired_count', required=False)
parser.add_argument('--service-maximum-percent', type=int, dest='service_maximum_percent', default=200, required=False)
parser.add_argument('--service-minimum-healthy-percent', type=int, dest='service_minimum_healthy_percent', default=50, required=False)
parser.add_argument('--downscale-tasks', dest='downscale_tasks', default=False, action='store_true', required=False)
parser.add_argument('--no-downscale-tasks', dest='downscale_tasks', default=False, action='store_false', required=False)
parser.add_argument('--minimum-running-tasks', type=int, dest='minimum_running_tasks', default=1, required=False)
args = parser.parse_args()
task_definition_names = get_separated_args(args.task_definition_names)
task_definition_files = get_separated_args(args.task_definition_files)
task_definition_templates = get_separated_args(args.task_definition_templates)
service_names = get_separated_args(args.service_names)


try:

    h1("Step: Configuring AWS")
    ecs = ECSService(access_key=args.key, secret_key=args.secret, region=args.region)
    success("Configuring AWS succeeded")
    if task_definition_files:
        if len(task_definition_files) != len(task_definition_names):
            raise Exception("task-definition-names and task-definition-files need same argment number")
    elif task_definition_templates:
        if len(task_definition_templates) != len(task_definition_names):
            raise Exception("task-definition-names and task-definition-templates need same argment number")
    if service_names:
        if len(service_names) != len(task_definition_names):
            raise Exception("task-definition-names and service_names need same argment number")

    serviceMode = service_names is not None

    # Step: Configuring AWS

    # Step: Check ECS cluster
    h1("Step: Check ECS cluster")
    ecs.describe_cluster(cluster=args.cluster_name)
    success("Checking cluster '%s' succeeded" % args.cluster_name)

    # Step: Register New Task Definition
    h1("Step: Register New Task Definition")
    count = 0
    service_states = []
    for task_name in task_definition_names:
        try:
            service_name = service_names[count]
        except TypeError:
            service_name = None
        file = None
        template = None
        if task_definition_files:
            file = task_definition_files[count]
        if task_definition_templates:
            template = task_definition_templates[count]
        response = ecs.register_task_definition(family=task_name, file=file, template=template, template_json=args.task_definition_template_json, template_env=args.task_definition_template_env)
        task_definition_arn = response.get('taskDefinition').get('taskDefinitionArn')
        st = ECSServiceState(service_name, task_name, task_definition_arn)
        service_states.append(st)
        success("Registering task definition '%s' succeeded (arn: '%s')" % (task_name, task_definition_arn))
        count = count + 1

    if serviceMode:
        h1("Step: Check ECS Service")
        for st in service_states:
            try:
                response = ecs.describe_service(args.cluster_name, st.service_name)
                if response['services'][0]['status'] == 'INACTIVE':
                    error("Service '%s' status is INACTIVE." % (st.service_name))
                    continue
                st.original_running_count = (response.get('services')[0]).get('runningCount')
                st.service_exist = True
                success("Checking service '%s' succeeded (%d tasks running)" % (st.service_name, st.original_running_count))
            except ServiceNotFoundException:
                error("Service '%s' not Found." % (st.service_name))
            except:
                raise

        # Step: Create ECS Service if necessary
        is_create_service = False
        for st in service_states:
            if not st.service_exist:
                if not is_create_service:
                    h1("Step: Create ECS Service")
                    is_create_service = True
                response = ecs.create_service(cluster=args.cluster_name, service=st.service_name, taskDefinition=st.task_definition_arn, desiredCount=args.service_desired_count, maximumPercent=args.service_maximum_percent, minimumHealthyPercent=args.service_minimum_healthy_percent)
                st.original_running_count = (response.get('services')[0]).get('runningCount')
                success("Create service '%s' succeeded (%d tasks running)" % (st.service_name, st.original_running_count))


        # Step: Downscale ECS Service if necessary
        if args.downscale_tasks:
            is_downscale_service = False
            pool = Pool(processes=POOL_PROCESSES)
            for st in service_states:
                if not st.service_exist:
                    continue
                if not is_downscale_service:
                    h1("Step: Downscale ECS Service")
                    is_downscale_service = True
                if st.original_running_count >= args.minimum_running_tasks:
                    st.downscale_apply_result = pool.apply_async(downscale_ecs_service, [args.cluster_name, st.service_name])
                    st.delta = 1
                else:
                    success("Downscaling service '%s' is not necessary" % st.service_name)
                    st.delta = args.minimum_running_tasks - st.original_running_count
            pool.close()
            pool.join()
            for st in service_states:
                if st.downscale_apply_result:
                    st.downscale_running_count = (st.downscale_apply_result.get().get('services')[0]).get('runningCount')
                    success("Downscaling service '%s' (from %d to %d tasks) succeeded"
                             % (st.service_name, st.original_running_count, st.downscale_running_count))

        # Step: Update ECS Service
        is_update_service = False
        pool = Pool(processes=POOL_PROCESSES)
        for st in service_states:
            if not st.service_exist:
                continue
            if not is_update_service:
                h1("Step: Update ECS Service")
                is_update_service = True
            st.update_apply_result = pool.apply_async(update_ecs_service, [args.cluster_name, st.service_name, st.task_definition_arn])
        pool.close()
        pool.join()
        for st in service_states:
            if not st.service_exist:
                continue
            response = st.update_apply_result.get()
            st.running_count = response.get('services')[0].get('runningCount')
            success("Updating service '%s' with task definition '%s' succeeded" % (st.service_name, st.task_definition_arn))

        # Step: Upscale ECS Service
        if args.downscale_tasks:
            is_upscale_service = False
            pool = Pool(processes=POOL_PROCESSES)
            for st in service_states:
                if not st.service_exist:
                    continue
                if not is_upscale_service:
                    h1("Step: Upscale ECS Service")
                    is_upscale_service = True
                st.upscale_apply_result = pool.apply_async(upscale_ecs_service, [args.cluster_name, st.service_name, st.delta])
            pool.close()
            pool.join()
            for st in service_states:
                if not st.service_exist:
                    continue
                upscale_running_count = (st.upscale_apply_result.get().get('services')[0]).get('runningCount')
                success("Upscaling service '%s' (from %d to %d tasks) succeeded"
                        % (st.service_name, st.running_count, upscale_running_count))
    else:
        # Step: run task
        h1("Step: Run task")
        for task_name in task_definition_names:
            response = ecs.run_task(cluster=args.cluster_name, family=task_name)
            success("Task %s succeeded" % (response.get('tasks')[0].get('taskArn')))

except Exception as e:
    raise
    error(e)
    sys.exit(1)

