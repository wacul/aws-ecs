# coding: utf-8
import sys, time, traceback
import render
from random import randint
from multiprocessing import Process, Pool, Queue
from aws import AwsUtils, ServiceNotFoundException
from queue import Queue, Empty
from threading import Thread
from botocore.exceptions import WaiterError, ClientError
from ecs.classes import ProcessMode, ProcessStatus, EnvironmentValueNotFoundException, TaskEnvironment, Service, EcsUtils, h1, success, error, info

class ServiceProcess(Thread):
    def __init__(self, task_queue, key, secret, region, is_service_zero_keep):
        super().__init__()
        self.task_queue = task_queue
        self.awsutils = AwsUtils(access_key=key, secret_key=secret, region=region)
        self.is_service_zero_keep = is_service_zero_keep

    def run(self):
        while True:
            try:
                service, mode = self.task_queue.get_nowait()
            except Empty:
                time.sleep(1)
                continue
            try:
                self.process(service, mode)
            except:
                service.status = ProcessStatus.error
                error("Unexpected error. service: %s.\n%s" % (service.service_name, traceback.format_exc()))
            finally:
                self.task_queue.task_done()

    def process(self, service, mode):
        if service.status == ProcessStatus.error:
            error("service '%s' previous process error. skipping." % service.service_name)
            return

        if mode == ProcessMode.registerTask:
            # for register task rate limit
            time.sleep(randint(1,3))
            service.task_definition_arn = EcsUtils.register_task_definition(self.awsutils, service.task_definition)
            success("Registering task definition '%s' succeeded (arn: '%s')" % (service.task_name, service.task_definition_arn))

        elif mode == ProcessMode.checkService:
            self.check_service(service)

        elif mode == ProcessMode.createService:
            self.create_service(service)

        elif mode == ProcessMode.updateService:
            self.update_service(service)

        elif mode == ProcessMode.waitForStable:
            EcsUtils.wait_for_stable(self.awsutils, service)
            EcsUtils.deregister_task_definition(self.awsutils, service)
            success("service '%s' (%d tasks) update completed"
                        % (service.service_name, service.running_count))

    def check_service(self, service):
        try:
            res_service = self.awsutils.describe_service(service.task_environment.cluster_name, service.service_name)
        except ServiceNotFoundException:
            error("Service '%s' not Found. will be created." % (service.service_name))
            return
            
        if res_service['status'] == 'INACTIVE':
            error("Service '%s' status is INACTIVE. will be recreated." % (service.service_name))
            return
        if res_service['status'] == 'DRAINING':
            error("Service '%s' status is DRAINING. will be recreated." % (service.service_name))
            return
        service.original_task_definition_arn = res_service.get('taskDefinition')
        service.original_running_count = res_service.get('runningCount')
        service.original_desired_count = res_service.get('desiredCount')
        service.desired_count = service.original_desired_count
        service.service_exists = True

        original_task_definition = self.awsutils.describe_task_definition(service.original_task_definition_arn)
        checks = EcsUtils.check_container_definition(original_task_definition['containerDefinitions'], service.task_definition['containerDefinitions'])
        success("Checking service '%s' succeeded (%d tasks running)" % (service.service_name, service.original_running_count))
        info(checks)

    def create_service(self, service):
        res_service = self.awsutils.create_service(cluster=service.task_environment.cluster_name, service=service.service_name, taskDefinition=service.task_definition_arn, desiredCount=service.task_environment.desired_count, maximumPercent=service.task_environment.maximum_percent, minimumHealthyPercent=service.task_environment.minimum_healthy_percent, distinctInstance=service.task_environment.distinct_instance)
        service.original_running_count = res_service.get('runningCount')
        service.original_desired_count = res_service.get('desiredCount')
        service.desired_count = service.original_desired_count
        success("Create service '%s' succeeded (%d tasks running)" % (service.service_name, service.original_running_count))

    def update_service(self, service):
        desiredCount = service.task_environment.desired_count
        # サービスのタスク数が0だったらそれを維持する
        if self.is_service_zero_keep and service.original_desired_count == 0:
            desiredCount = 0
        res_service = self.awsutils.update_service(cluster=service.task_environment.cluster_name, service=service.service_name, taskDefinition=service.task_definition_arn, maximumPercent=service.task_environment.maximum_percent, minimumHealthyPercent=service.task_environment.minimum_healthy_percent, desiredCount=desiredCount)
        service.running_count = res_service.get('runningCount')
        service.desired_count = res_service.get('desiredCount')
        success("Update service '%s' with task definition '%s' succeeded" % (service.service_name, service.task_definition_arn))


class ServiceManager(object):
    def __init__(self, args):
        self.awsutils = AwsUtils(access_key=args.key, secret_key=args.secret, region=args.region)
        self.task_queue = Queue()

        self.service_list, self.deploy_service_list, self.environment = Service.get_service_list(services_yaml=args.services_yaml,
                                                                                                 environment_yaml=args.environment_yaml,
                                                                                                 task_definition_template_dir=args.task_definition_template_dir,
                                                                                                 task_definition_config_json=args.task_definition_config_json,
                                                                                                 task_definition_config_env=args.task_definition_config_env,
                                                                                                 deploy_service_group=args.deploy_service_group,
                                                                                                 template_group=args.template_group)

        threads_count = args.threads_count
        # thread数がタスクの数を超えているなら減らす
        if len(self.deploy_service_list) < threads_count:
           threads_count = len(self.deploy_service_list)
        # threadの開始
        for i in range(threads_count):
            thread = ServiceProcess(self.task_queue, args.key, args.secret, args.region, args.service_zero_keep)
            thread.setDaemon(True)
            thread.start()

        self.is_service_zero_keep = args.service_zero_keep
        self.template_group = args.template_group
        self.is_delete_unused_service = args.delete_unused_service

        self.cluster_list = []
        for service in self.service_list:
            if service.task_environment.cluster_name not in self.cluster_list:
                self.cluster_list.append(service.task_environment.cluster_name)

        self.error = False

    def run(self):
        # Step: Check ECS cluster
        self.check_ecs_cluster()

        # Step: Delete Unused Service
        self.delete_unused_services()

        # Step: Register New Task Definition
        self.register_new_task_definition()

        # Step: service
        self.check_service()
        self.create_service()
        self.update_service()
        self.wait_for_stable()

        self.result_check()

    def dry_run(self):
        # Step: Check ECS cluster
        self.check_ecs_cluster()

        # Step: Check Delete Service
        self.delete_unused_services(dry_run=True)

        # Step: Check Service
        self.check_service()

    def delete_unused_services(self, dry_run=False):
        if dry_run:
            h1("Step: Check Delete Unused Service")
        else:
            h1("Step: Delete Unused Service")
        if not self.is_delete_unused_service:
            info("Do not delete unused service")
            return

        cluster_services = {}
        for cluster_name in self.cluster_list:
            running_service_arn_list = self.awsutils.list_services(cluster_name)
            services = self.awsutils.describe_services(cluster_name, running_service_arn_list)
            cluster_services[cluster_name] = services

        task_definition_names = []
        task_dict = {}
        for cluster_name, d in cluster_services.items():
            for service_description in d:
                service_name = service_description['serviceName']

                task_definition_name = service_description['taskDefinition']
                response_task_definition = self.awsutils.describe_task_definition(task_definition_name)

                try:
                    task_environment = TaskEnvironment(response_task_definition)
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
                    success("Delete service '%s'" % (service_name))
                    if not dry_run:
                        self.awsutils.delete_service(cluster_name, service_name)

    def check_ecs_cluster(self):
        h1("Step: Check ECS cluster")
        for cluster_name in self.cluster_list:
            self.awsutils.describe_cluster(cluster=cluster_name)
            success("Checking cluster '%s' succeeded" % cluster_name)

    def register_new_task_definition(self):
        h1("Step: Register New Task Definition")
        for service in self.deploy_service_list:
            self.task_queue.put([service, ProcessMode.registerTask])
        self.task_queue.join()

    def check_service(self):
        h1("Step: Check Deploy ECS Service")
        for service in self.deploy_service_list:
            self.task_queue.put([service, ProcessMode.checkService])
        self.task_queue.join()

    def create_service(self):
        # Step: Create ECS Service if necessary
        not_exists_service_list = list(filter(lambda service:service.service_exists == False, self.deploy_service_list))
        if len(not_exists_service_list) > 0:
            h1("Step: Create ECS Service")
        for service in not_exists_service_list:
            self.task_queue.put([service, ProcessMode.createService])
        self.task_queue.join()

    def update_service(self):
        h1("Step: Update ECS Service")
        for service in self.deploy_service_list:
            if not service.service_exists:
                continue
            self.task_queue.put([service, ProcessMode.updateService])
        self.task_queue.join()

    def wait_for_stable(self):
        h1("Step: Wait for Service Status 'Stable'")
        for service in self.deploy_service_list:
            if not service.service_exists:
                continue
            else:
                self.task_queue.put([service, ProcessMode.waitForStable])
        self.task_queue.join()

    def result_check(self):
        error_service_list = list(filter(lambda service:service.status == ProcessStatus.error, self.deploy_service_list))
        # サービスでエラーが一個でもあれば失敗としておく
        if len(error_service_list) > 0:
            sys.exit(1)
        if self.error:
            sys.exit(1)

