# coding: utf-8
from __future__ import unicode_literals
import logging
import sys
import argparse
import time
import traceback
from multiprocessing import Process, Pool, Queue
from ecs import ECSService
from ecs import ServiceNotFoundException
from queue import Queue, Empty
from threading import Thread
from enum import Enum

class ProcessMode(Enum):
    registerTask = 0
    checkService = 1
    createService = 2
    downscaleService = 3
    updateService = 4
    upscaleService = 5
    runTask = 6

class ProcessStatus(Enum):
    normal = 0
    error = 1

class AwsProcess(Thread):
    def run(self):
        self.ecs_service = ECSService(access_key=args.key, secret_key=args.secret, region=args.region)
        while True:
            try:
                service, mode = task_queue.get_nowait()
            except Empty:
                time.sleep(1)
                continue
            try:
                self.process(service, mode)
            except:
                service.status = ProcessStatus.error
                error("Unexpected error. service: %s.\n%s" % (service.service_name, traceback.format_exc()))
            finally:
                task_queue.task_done()

    def process(self, service, mode):
        if service.status == ProcessStatus.error:
            error("service '%s' previous process error. skipping." % service.service_name)
            return

        if mode == ProcessMode.registerTask:
            response = self.ecs_service.register_task_definition(family=service.task_name, file=service.file, template=service.template, template_json=args.task_definition_template_json, template_env=args.task_definition_template_env)
            service.task_definition_arn = response.get('taskDefinition').get('taskDefinitionArn')
            success("Registering task definition '%s' succeeded (arn: '%s')" % (service.task_name, service.task_definition_arn))

        elif mode == ProcessMode.checkService:
            try:
                response = self.ecs_service.describe_service(service.cluster_name, service.service_name)
            except ServiceNotFoundException:
                error("Service '%s' not Found." % (service.service_name))
                return
            if response['services'][0]['status'] == 'INACTIVE':
                error("Service '%s' status is INACTIVE." % (service.service_name))
                return
            service.original_running_count = (response.get('services')[0]).get('runningCount')
            service.desired_count = (response.get('services')[0]).get('desiredCount')
            service.service_exists = True
            success("Checking service '%s' succeeded (%d tasks running)" % (service.service_name, service.original_running_count))

        elif mode == ProcessMode.createService:
            response = self.ecs_service.create_service(cluster=service.cluster_name, service=service.service_name, taskDefinition=service.task_definition_arn, desiredCount=args.service_desired_count, maximumPercent=args.service_maximum_percent, minimumHealthyPercent=args.service_minimum_healthy_percent)
            service.original_running_count = (response.get('services')[0]).get('runningCount')
            success("Create service '%s' succeeded (%d tasks running)" % (service.service_name, service.original_running_count))

        elif mode == ProcessMode.downscaleService:
            response = self.ecs_service.downscale_service(cluster=service.cluster_name, service=service.service_name)
            service.downscale_running_count = (response.get().get('services')[0]).get('runningCount')
            success("Downscaling service '%s' (from %d to %d tasks) succeeded"
                 % (service.service_name, service.original_running_count, service.downscale_running_count))

        elif mode == ProcessMode.updateService:
            response = self.ecs_service.update_service(cluster=service.cluster_name, service=service.service_name, taskDefinition=service.task_definition_arn)
            service.running_count = response.get('services')[0].get('runningCount')
            success("Updating service '%s' with task definition '%s' succeeded" % (service.service_name, service.task_definition_arn))

        elif mode == ProcessMode.upscaleService:
            response = self.ecs_service.upscale_service(cluster=service.cluster_name, service=service.service_name, delta=service.delta)
            upscale_running_count = (response.get().get('services')[0]).get('runningCount')
            success("Upscaling service '%s' (from %d to %d tasks) succeeded"
                        % (service.service_name, service.running_count, upscale_running_count))

        elif mode == ProcessMode.runTask:
            response = self.ecs_service.run_task(cluster=service.cluster_name, family=service.task_name)
            success("Task %s succeeded" % (response.get('tasks')[0].get('taskArn')))

class Service(object):
    def __init__(self, cluster_name, service_name, task_name, file, template):
        self.cluster_name = cluster_name
        self.service_name = service_name
        self.task_name = task_name
        self.file = file
        self.template = template
        self.status = ProcessStatus.normal

        self.task_definition_arn = None
        self.service_exists = False
        self.original_running_count = 0
        self.desired_count = 0
        self.downscale_running_count = 0
        self.running_count = 0
        self.delta = 0


def get_separated_args(value):
    if value:
        value = value.rstrip('\\n').replace('\\n', ',')
        value = value.replace(' ', ',')
        return value.split(',')
    return None

logging.basicConfig(stream=sys.stdout, level=logging.INFO, format='%(message)s')
logging.getLogger("botocore").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)
h1 = lambda x: logger.info("\033[1m\033[4m\033[94m%s\033[0m\n" % x)
success = lambda x: logger.info("\033[92m✔ %s\033[0m\n" % x)
error = lambda x: logger.info("\033[91m✖ %s\033[0m\n" % x)
info = lambda x: logger.info("  %s\n" % x)

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
parser.add_argument('--minimum-running-tasks', type=int, default=1, required=False)
parser.add_argument('--threads-count', type=int, default=10, required=False)
parser.add_argument('--service-zero-keep', dest='service_zero_keep', default=True, action='store_true', required=False)
parser.add_argument('--no-service-zero-keep', dest='service_zero_keep', default=True, action='store_false', required=False)
args = parser.parse_args()
task_definition_names = get_separated_args(args.task_definition_names)
task_definition_files = get_separated_args(args.task_definition_files)
task_definition_templates = get_separated_args(args.task_definition_templates)
service_names = get_separated_args(args.service_names)


class ServiceManager(object):
    def __init__(self, task_definition_files, task_definition_templates, service_names, cluster_name):
        if task_definition_files:
            if len(task_definition_files) != len(task_definition_names):
                raise Exception("task-definition-names and task-definition-files need same argment number")
        elif task_definition_templates:
            if len(task_definition_templates) != len(task_definition_names):
                raise Exception("task-definition-names and task-definition-templates need same argment number")
        if service_names:
            if len(service_names) != len(task_definition_names):
                raise Exception("task-definition-names and service_names need same argment number")
        count = 0
        self.service_list = []
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
            service = Service(args.cluster_name, service_name, task_name, file, template)
            self.service_list.append(service)
            count = count + 1
        self.cluster_name = cluster_name
        self.ecs_service = ECSService(access_key=args.key, secret_key=args.secret, region=args.region)

    def check_ecs_cluster(self):
        h1("Step: Check ECS cluster")
        self.ecs_service.describe_cluster(cluster=self.cluster_name)
        success("Checking cluster '%s' succeeded" % self.cluster_name)

    def register_new_task_definition(self):
        h1("Step: Register New Task Definition")
        for service in self.service_list:
            task_queue.put([service, ProcessMode.registerTask])
        task_queue.join()

    def check_service(self):
        h1("Step: Check ECS Service")
        for service in self.service_list:
            task_queue.put([service, ProcessMode.checkService])
        task_queue.join()

    def create_service(self):
        # Step: Create ECS Service if necessary
        not_exists_service_list = list(filter(lambda service:service.service_exists == False, self.service_list))
        if len(not_exists_service_list) > 0:
            h1("Step: Create ECS Service")
        for service in not_exists_service_list:
            task_queue.put([service, ProcessMode.createService])
        task_queue.join()

    def downscale_service(self):
        if args.downscale_tasks:
            is_downscale_service = False
            for service in self.service_lists:
                if not service.service_exists:
                    continue
                if not is_downscale_service:
                    h1("Step: Downscale ECS Service")
                    is_downscale_service = True
                if args.service_zero_keep and service.desired_count == 0:
                    # サービスのタスク数が0だったらそれを維持する
                    info("Service '%s' is zero task service. skipping." % service.service_name)
                    continue
                if service.original_running_count >= args.minimum_running_tasks:
                    task_queue.put([service, ProcessMode.downscaleService])
                    service.delta = 1
                else:
                    success("Downscaling service '%s' is not necessary" % service.service_name)
                    service.delta = args.minimum_running_tasks - service.original_running_count
        task_queue.join()

    def update_service(self):
        is_update_service = False
        for service in self.service_list:
            if not service.service_exists:
                continue
            if not is_update_service:
                h1("Step: Update ECS Service")
                is_update_service = True
            if args.service_zero_keep and service.desired_count == 0:
                # サービスのタスク数が0だったらそれを維持する
                info("Service '%s' is zero task service. skipping." % service.service_name)
                continue
            task_queue.put([service, ProcessMode.updateService])
        task_queue.join()

    def upscale_service(self):
        if args.downscale_tasks:
            is_upscale_service = False
            for service in service_list:
                if not service.service_exists:
                    continue
                if not is_upscale_service:
                    h1("Step: Upscale ECS Service")
                    is_upscale_service = True
                if args.service_zero_keep and service.desired_count == 0:
                    # サービスのタスク数が0だったらそれを維持する
                    info("Service '%s' is zero task service. skipping." % service.service_name)
                    continue
                task_queue.put([service, ProcessMode.upscaleService])
        task_queue.join()

    def run_task(self):
        h1("Step: Run task")
        for service in self.service_list:
            response = ecs.run_task(cluster=service.cluster_name, family=service.task_name)
            success("Task %s (%s) succeeded" % (service.task_name, response.get('tasks')[0].get('taskArn')))

    def result_check(self):
        error_service_list = list(filter(lambda service:service.status == ProcessStatus.error, self.service_list))
        if len(error_service_list) > 0:
            sys.exit(1)


if __name__ == '__main__':
    service_manager = ServiceManager(task_definition_files, task_definition_templates, service_names, args.cluster_name)

    # thread数がタスクの数を超えているなら減らす
    task_queue = Queue()
    threads_count = args.threads_count
    if len(service_manager.service_list) < threads_count:
        threads_count = len(service_manager.service_list)
    for i in range(threads_count):
        thread = AwsProcess()
        thread.setDaemon(True)
        thread.start()

    # Step: Check ECS cluster
    service_manager.check_ecs_cluster()
    # Step: Register New Task Definition
    service_manager.register_new_task_definition()

    # Step: check -> create & downscale & upscale
    if service_names is not None:
        service_manager.check_service()
        service_manager.create_service()
        service_manager.downscale_service()
        service_manager.update_service()
        service_manager.upscale_service()

    else:
        service_manager.run_task()


    service_manager.result_check()
