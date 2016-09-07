# coding: utf-8
import logging
import sys
import os
import argparse
import time
import traceback
import render
from multiprocessing import Process, Pool, Queue
from ecs import ECSService
from ecs import ServiceNotFoundException
from queue import Queue, Empty
from threading import Thread
from enum import Enum
import distutils.util
from botocore.exceptions import WaiterError


logging.basicConfig(stream=sys.stdout, level=logging.INFO, format='%(message)s')
logging.getLogger("botocore").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)
h1 = lambda x: logger.info("\033[1m\033[4m\033[94m%s\033[0m\n" % x)
success = lambda x: logger.info("\033[92m✔ %s\033[0m\n" % x)
error = lambda x: logger.info("\033[91m✖ %s\033[0m\n" % x)
info = lambda x: logger.info("  %s\n" % x)


class ProcessMode(Enum):
    registerTask = 0
    checkService = 1
    createService = 2
    updateService = 4
    runTask = 6
    waitForStable = 7

class ProcessStatus(Enum):
    normal = 0
    error = 1

class EnvironmentValueNotFoundException(Exception):
    def __str__(self):
        return repr(self.value)

class AwsProcess(Thread):
    def __init__(self, key, secret, region):
        super().__init__()
        self.ecs_service = ECSService(access_key=key, secret_key=secret, region=region)

    def run(self):
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
            response = self.ecs_service.register_task_definition(task_definition=service.task_definition)
            service.task_definition_arn = response.get('taskDefinition').get('taskDefinitionArn')
            success("Registering task definition '%s' succeeded (arn: '%s')" % (service.task_name, service.task_definition_arn))
            # for register task rate limit
            time.sleep(3)

        elif mode == ProcessMode.checkService:
            try:
                response = self.ecs_service.describe_service(service.task_environment.cluster_name, service.service_name)
            except ServiceNotFoundException:
                error("Service '%s' not Found." % (service.service_name))
                return
            if response['services'][0]['status'] == 'INACTIVE':
                error("Service '%s' status is INACTIVE." % (service.service_name))
                return
            service.original_task_definition = (response.get('services')[0]).get('taskDefinition')
            service.original_running_count = (response.get('services')[0]).get('runningCount')
            service.original_desired_count = (response.get('services')[0]).get('desiredCount')
            service.desired_count = service.original_desired_count
            service.service_exists = True
            success("Checking service '%s' succeeded (%d tasks running)" % (service.service_name, service.original_running_count))

        elif mode == ProcessMode.createService:
            response = self.ecs_service.create_service(cluster=service.task_environment.cluster_name, service=service.service_name, taskDefinition=service.task_definition_arn, desiredCount=service.task_environment.desired_count, maximumPercent=service.task_environment.maximum_percent, minimumHealthyPercent=service.task_environment.minimum_healthy_percent)
            service.original_running_count = (response.get('services')[0]).get('runningCount')
            service.original_desired_count = (response.get('services')[0]).get('desiredCount')
            service.desired_count = service.original_desired_count
            success("Create service '%s' succeeded (%d tasks running)" % (service.service_name, service.original_running_count))

        elif mode == ProcessMode.updateService:
            response = self.ecs_service.update_service(cluster=service.task_environment.cluster_name, service=service.service_name, taskDefinition=service.task_definition_arn, maximumPercent=service.task_environment.maximum_percent, minimumHealthyPercent=service.task_environment.minimum_healthy_percent, desiredCount=service.task_environment.desired_count)
            service.running_count = response.get('services')[0].get('runningCount')
            service.desired_count = response.get('services')[0].get('desiredCount')
            success("Update service '%s' with task definition '%s' succeeded" % (service.service_name, service.task_definition_arn))

        elif mode == ProcessMode.waitForStable:
            retryCount = 0
            while True:
                try:
                    response = self.ecs_service.wait_for_stable(cluster=service.task_environment.cluster_name, service=service.service_name)
                except WaiterError:
                    if retryCount > 2:
                        break
                    retryCount = retryCount + 1
                    continue
                break
            service.running_count = response.get('services')[0].get('runningCount')
            service.desired_count = response.get('services')[0].get('desiredCount')
            self.ecs_service.deregister_task_definition(service.original_task_definition)
            success("service '%s' (%d tasks) update completed"
                        % (service.service_name, service.running_count))


class TaskEnvironment(object):
    def __init__(self, task_environment_list):
        self.environment = None
        self.cluster_name = None
        self.service_group = None
        self.template_group = None
        self.desired_count = None
        self.is_downscale_task = None
        self.minimum_healthy_percent = 50
        self.maximum_percent = 200
        for task_environment in task_environment_list:
            if task_environment['name'] == 'ENVIRONMENT':
                self.environment = task_environment['value']
            if task_environment['name'] == 'CLUSTER_NAME':
                self.cluster_name = task_environment['value']
            elif task_environment['name'] == 'SERVICE_GROUP':
                self.service_group = task_environment['value']
            elif task_environment['name'] == 'TEMPLATE_GROUP':
                self.template_group = task_environment['value']
            elif task_environment['name'] == 'DESIRED_COUNT':
                self.desired_count = int(task_environment['value'])
            elif task_environment['name'] == 'MINIMUM_HEALTHY_PERCENT':
                self.minimum_healthy_percent = int(task_environment['value'])
            elif task_environment['name'] == 'MAXIMUM_PERCENT':
                self.maximum_percent = int(task_environment['value'])
        if self.environment is None or self.cluster_name is None or self.service_group is None or self.desired_count is None:
            raise EnvironmentValueNotFoundException("task_definition required environment not defined. data: %s" % (task_environment_list))

class Service(object):
    def __init__(self, task_definition):
        self.task_definition = task_definition
        try:
            self.task_environment = TaskEnvironment(task_definition['containerDefinitions'][0]['environment'])
            self.task_name = task_definition['family']
            self.service_name = self.task_name + '-service'
        except EnvironmentValueNotFoundException:
            error("service '%s' is lack of environment" % (service_name))
            sys.exit(1)
        except:
            raise

        self.status = ProcessStatus.normal

        self.original_task_definition = None
        self.task_definition_arn = None
        self.service_exists = False
        self.original_running_count = 0
        self.running_count = 0
        self.original_desired_count = 0
        self.desired_count = 0



# Arguments parsing
def init():
    parser = argparse.ArgumentParser(description='Deploy Service on ECS')
    parser.add_argument('--key', dest='key', required=True)
    parser.add_argument('--secret', dest='secret', required=True)
    parser.add_argument('--region', dest='region', default='us-east-1')
    parser.add_argument('--task-definition-template-dir', dest='task_definition_template_dir', required=True)
    parser.add_argument('--task-definition-config-json', dest='task_definition_config_json', required=True)
    parser.add_argument('--task-definition-config-env', dest='task_definition_config_env', default=True, action='store_true', required=False)
    parser.add_argument('--no-task-definition-config-env', dest='task_definition_config_env', default=True, action='store_false', required=False)
    parser.add_argument('--threads-count', type=int, default=10, required=False)
    parser.add_argument('--service-zero-keep', dest='service_zero_keep', default=True, action='store_true', required=False)
    parser.add_argument('--no-service-zero-keep', dest='service_zero_keep', default=True, action='store_false', required=False)
    parser.add_argument('--template-group', dest='template_group', required=False)
    parser.add_argument('--deploy-service-group', dest='deploy_service_group', required=False)
    parser.add_argument('--delete-unused-service', dest='delete_unused_service', default=True, action='store_true', required=False)
    parser.add_argument('--no-delete-unused-service', dest='delete_unused_service', default=True, action='store_false', required=False)
    return parser.parse_args()

class ServiceManager(object):
    def __init__(self, args):
        self.service_list = []

        task_definition_config_json = render.load_json(args.task_definition_config_json)
        files = os.listdir(args.task_definition_template_dir)
        for file in files:
            try:
                task_definitions = render.render_definition(args.task_definition_template_dir, file, task_definition_config_json, args.task_definition_config_env)
                self.service_list.extend(self.import_service_from_task_definitions(task_definitions))
            except:
                error("Template error. file: %s.\n%s" % (file, traceback.format_exc()))
                sys.exit(1)
        if args.deploy_service_group:
            self.deploy_service_list = list(filter(lambda service:service.task_environment.service_group == args.deploy_service_group, self.service_list))
        else:
            self.deploy_service_list = self.service_list
        if len(self.deploy_service_list) == 0:
            error("Deployment target service is None.")
            sys.exit(1)
        self.ecs_service = ECSService(access_key=args.key, secret_key=args.secret, region=args.region)
        self.is_service_zero_keep = args.service_zero_keep
        self.environment = task_definition_config_json['environment']
        self.template_group = args.template_group

        self.cluster_list = []
        for service in self.service_list:
            if service.task_environment.cluster_name not in self.cluster_list:
                self.cluster_list.append(service.task_environment.cluster_name)

        self.error = False

    def delete_unused_services(self, is_delete_unused_service):
        h1("Step: Delete Unused Service")
        if not is_delete_unused_service:
            info("Do not delete unused service")
            return

        cluster_services = {}
        for cluster_name in self.cluster_list:
            running_service_arn_list = self.ecs_service.list_services(cluster_name)
            response = self.ecs_service.describe_services(cluster_name, running_service_arn_list)
            failures = response.get('failures')

            # リストからサービス詳細が取れなければエラーにしてしまう
            if len(failures) > 0:
                for failure in failures:
                    error("list service failer. service: '%s', reason: '%s'" % (failure.get('arn'), failure.get('reason')))
                sys.exit(1)
            cluster_services[cluster_name] = response['services']

        task_definition_names = []
        task_dict = {}
        for cluster_name, d in cluster_services.items():
            for service_description in d:
                service_name = service_description['serviceName']

                task_definition_name = service_description['taskDefinition']
                response = self.ecs_service.describe_task_definition(task_definition_name)
                response_task_environment = response['taskDefinition']['containerDefinitions'][0]['environment']

                # 環境変数なし
                if len(response_task_environment) <= 0:
                    error("Service '%s' is environment value not found" % (service_name))
                    self.error = True
                    continue
                try:
                    task_environment = TaskEnvironment(response_task_environment)
                # 環境変数の値が足りない 
                except EnvironmentValueNotFoundException:
                    error("Service '%s' is lack of environment value" % (service_name))
                    self.error = True
                    continue

                # 同一環境のものだけ
                if task_environment.environment != self.environment:
                    continue
                # 同一テンプレートグループだけ
                if self.template_group:
                    if not task_environment.template_group:
                        error("Service '%s' is not set TEMPLATE_GROUP" % (service_name))
                        self.error = True
                        continue
                    if task_environment.template_group != self.template_group:
                        continue

                ident_service_list = [ service for service in self.service_list if service.service_name == service_name and service.task_environment.cluster_name == cluster_name ]

                if len(ident_service_list) <= 0:
                    success("Delete service '%s' for service template deleted" % (service_name))
                    self.ecs_service.delete_service(cluster_name, service_name)

    def import_service_from_task_definitions(self, task_definitions):
        service_list = []
        for task_definition in task_definitions:
            service = Service(task_definition)
            service_list.append(service)
        return service_list

    def check_ecs_cluster(self):
        h1("Step: Check ECS cluster")
        for cluster_name in self.cluster_list:
            self.ecs_service.describe_cluster(cluster=cluster_name)
            success("Checking cluster '%s' succeeded" % cluster_name)

    def register_new_task_definition(self):
        h1("Step: Register New Task Definition")
        for service in self.deploy_service_list:
            task_queue.put([service, ProcessMode.registerTask])
        task_queue.join()

    def check_service(self):
        h1("Step: Check ECS Service")
        for service in self.deploy_service_list:
            task_queue.put([service, ProcessMode.checkService])
        task_queue.join()

    def create_service(self):
        # Step: Create ECS Service if necessary
        not_exists_service_list = list(filter(lambda service:service.service_exists == False, self.deploy_service_list))
        if len(not_exists_service_list) > 0:
            h1("Step: Create ECS Service")
        for service in not_exists_service_list:
            task_queue.put([service, ProcessMode.createService])
        task_queue.join()

    def update_service(self):
        h1("Step: Update ECS Service")
        for service in self.deploy_service_list:
            if not service.service_exists:
                continue
            if self.is_service_zero_keep and service.original_desired_count == 0:
                # サービスのタスク数が0だったらそれを維持する
                info("Service '%s' is zero task service. skipping." % service.service_name)
            else:
                task_queue.put([service, ProcessMode.updateService])
        task_queue.join()

    def wait_for_stable(self):
        h1("Step: Wait for Service Status 'Stable'")
        for service in self.deploy_service_list:
            if not service.service_exists:
                continue
            else:
                task_queue.put([service, ProcessMode.waitForStable])
        task_queue.join()

    def result_check(self):
        error_service_list = list(filter(lambda service:service.status == ProcessStatus.error, self.deploy_service_list))
        # サービスでエラーが一個でもあれば失敗としておく
        if len(error_service_list) > 0:
            sys.exit(1)
        if self.error:
            sys.exit(1)

if __name__ == '__main__':
    args = init()
    service_manager = ServiceManager(args)

    # thread数がタスクの数を超えているなら減らす
    task_queue = Queue()
    threads_count = args.threads_count
    if len(service_manager.deploy_service_list) < threads_count:
        threads_count = len(service_manager.deploy_service_list)
    # threadの開始
    for i in range(threads_count):
        thread = AwsProcess(args.key, args.secret, args.region)
        thread.setDaemon(True)
        thread.start()

    # Step: Check ECS cluster
    service_manager.check_ecs_cluster()

    # Step: Delete Unused Service
    service_manager.delete_unused_services(args.delete_unused_service)

    # Step: Register New Task Definition
    service_manager.register_new_task_definition()

    # Step: service
    service_manager.check_service()
    service_manager.create_service()
    service_manager.update_service()
    service_manager.wait_for_stable()


    service_manager.result_check()
