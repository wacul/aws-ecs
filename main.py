# coding: utf-8
from __future__ import unicode_literals
import logging
import sys
import argparse
from multiprocessing import Process, Manager, Pool

from ecs import ECSService
from ecs import ServiceNotFoundException

POOL_PROCESSES=3

class ECSServiceState(object):
    def __init__(self, service_name, task_name):
        self.service_name = service_name
        self.task_name = task_name
        self.task_definition_arn = ""
        self.service_exist = False
        self.original_running_count = 0
        self.downscale_running_count = 0
        self.running_count = 0
        self.delta = 0
        self.service_apply_result = None
        self.task_apply_result = None
        self.downscale_apply_result = None
        self.update_apply_result = None
        self.upscale_apply_result = None

def register_task_definition(task, file, template, task_definition_template_json, task_definition_template_env):
    return ecs.register_task_definition(task, file, template, task_definition_template_json, task_definition_template_env)

def check_ecs_service(cluster_name, service_name):
    return ecs.describe_service(cluster=cluster_name, service=service_name)

def downscale_ecs_service(cluster_name, service_name):
    return ecs.downscale_service(cluster=cluster_name, service=service_name)

def update_ecs_service(cluster_name, service_name, task_definition_arn):
    return ecs.update_service(cluster=cluster_name, service=service_name, taskDefinition=task_definition_arn)

def upscale_ecs_service(cluster_name, service_name, delta):
    return ecs.upscale_service(cluster=cluster_name, service=service_name, delta=delta)

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
parser.add_argument('--task-definition-names', dest='task_definition_names', required=True, action='store', nargs='+')
parser.add_argument('--task-definition-files', dest='task_definition_files', required=True, action='store', nargs='*')
parser.add_argument('--task-definition-templates', dest='task_definition_templates', required=True, action='store', nargs='*')
parser.add_argument('--task-definition-template-json', dest='task_definition_template_json', required=True)
parser.add_argument('--task-definition-template-env', dest='task_definition_template_env', default=True, action='store_true', required=False)
parser.add_argument('--no-task-definition-template-env', dest='task_definition_template_env', default=True, action='store_false', required=False)
parser.add_argument('--service-names', dest='service_names', required=False, action='store', nargs='+')
parser.add_argument('--service-desired-count', type=int, dest='service_desired_count', required=False)
parser.add_argument('--service-maximum-percent', type=int, dest='service_maximum_percent', default=200, required=False)
parser.add_argument('--service-minimum-healthy-percent', type=int, dest='service_minimum_healthy_percent', default=50, required=False)
parser.add_argument('--downscale-tasks', dest='downscale_tasks', default=False, action='store_true', required=False)
parser.add_argument('--no-downscale-tasks', dest='downscale_tasks', default=False, action='store_false', required=False)
parser.add_argument('--minimum-running-tasks', type=int, dest='minimum_running_tasks', default=1, required=False)
args = parser.parse_args()


try:

    h1("Step: Configuring AWS")
    ecs = ECSService(access_key=args.key, secret_key=args.secret, region=args.region)
    success("Configuring AWS succeeded")
    if args.task_definition_files:
        if len(args.task_definition_files) != len(args.task_definition_names):
            raise Exception("task-definition-names and task-definition-files need same argment number")
    elif args.task_definition_templates:
        if len(args.task_definition_templates) != len(args.task_definition_names):
            raise Exception("task-definition-names and task-definition-templates need same argment number")
    if args.service_names:
        if len(args.service_names) != len(args.task_definition_names):
            raise Exception("task-definition-names and service_names need same argment number")

    serviceMode = args.service_names is not None

    # Step: Configuring AWS

    # Step: Check ECS cluster
    h1("Step: Check ECS cluster")
    ecs.describe_cluster(cluster=args.cluster_name)
    success("Checking cluster '%s' succeeded" % args.cluster_name)

    # Step: Register New Task Definition
    h1("Step: Register New Task Definition")
    count = 0
    pool = Pool(processes=POOL_PROCESSES)
    service_states = []
    for task_name in args.task_definition_names:
        try:
            service_name = args.service_names[count]
        except TypeError:
            service_name = None
        st = ECSServiceState(service_name, task_name)
        file = None
        template = None
        if args.task_definition_files:
            file = args.task_definition_files[count]
        if args.task_definition_templates:
            template = args.task_definition_templates[count]
        st.task_apply_result = pool.apply_async(register_task_definition, [st.task_name, file, template, args.task_definition_template_json, args.task_definition_template_env])
        service_states.append(st)
        count = count + 1
    pool.close()
    pool.join()
    for st in service_states:
        st.task_definition_arn = st.task_apply_result.get().get('taskDefinition').get('taskDefinitionArn')
        success("Registering task definition '%s' succeeded" % st.task_name)

    if serviceMode:
        h1("Step: Check ECS Service")
        pool = Pool(processes=POOL_PROCESSES)
        for st in service_states:
            st.service_apply_result = pool.apply_async(check_ecs_service, [args.cluster_name, st.service_name])
        pool.close()
        pool.join()
        for st in service_states:
            try:
                response = st.service_apply_result.get()
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
            st.running_count = (st.update_apply_result.get().get('services')[0]).get('runningCount')
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
        for task_name in args.task_definition_names:
            response = ecs.run_task(cluster=args.cluster_name, family=task_name)
            success("Task %s succeeded" % (response.get('tasks')[0].get('taskArn')))

except Exception as e:
    raise
    error(e)
    sys.exit(1)

