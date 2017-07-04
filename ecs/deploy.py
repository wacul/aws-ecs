# coding: utf-8
import os
import sys
import time
import traceback
import json
from multiprocessing import Queue
from queue import Queue, Empty
from random import randint
from threading import Thread

import botocore.exceptions
import yaml

import render
from aws import AwsUtils, ServiceNotFoundException
from ecs.classes import ProcessMode, ProcessStatus, VariableNotFoundException
from ecs.service import Service, DescribeService, get_service_list_json, get_service_list_yaml,\
    fetch_aws_service, get_deploy_service_list
from ecs.scheduled_tasks import ScheduledTask
from ecs.utils import h1, success, error, info


class DeployProcess(Thread):
    def __init__(self, task_queue, key, secret, region, is_service_zero_keep):
        super().__init__()
        self.task_queue = task_queue
        self.awsutils = AwsUtils(access_key=key, secret_key=secret, region=region)
        self.is_service_zero_keep = is_service_zero_keep

    def run(self):
        while True:
            try:
                deploy, mode = self.task_queue.get_nowait()
            except Empty:
                time.sleep(1)
                continue
            try:
                self.process(deploy, mode)
            except:
                deploy.status = ProcessStatus.error
                error("Unexpected error in `{deploy.name}`.\n{traceback}"
                      .format(deploy=deploy, traceback=traceback.format_exc()))
            finally:
                self.task_queue.task_done()

    def process(self, deploy, mode):
        if deploy.status == ProcessStatus.error:
            error("`{deploy.name}` previous process error. skipping.".format(deploy=deploy))
            return

        if mode == ProcessMode.checkServiceAndTask:
            self.check_service_task(deploy)

        elif mode == ProcessMode.deployService:
            self.process_service(deploy)

        elif mode == ProcessMode.checkDeployService:
            self.check_deploy_service(deploy)

        elif mode == ProcessMode.waitForStable:
            wait_for_stable(self.awsutils, deploy)

        elif mode == ProcessMode.deployScheduledTask:
            self.deploy_scheduled_task(deploy)

    def deploy_scheduled_task(self, scheduled_task: ScheduledTask):
        self.awsutils.create_scheduled_task(
            task_name=scheduled_task.family,
            schedule_expression=scheduled_task.schedule_expression,
            target_arn=scheduled_task.target_arn,
            description=scheduled_task.task_environment.environment
        )

    def process_service(self, service: Service):
        self.__register_task_definition(service)
        if service.origin_service_exists:
            self.__update_service(service)
        else:
            self.__create_service(service)
        success("Deploy Service '{service.service_name}' succeeded.\n"
                "    - Registering task definition arn: '{service.task_definition_arn}'\n"
                "    - {service.desired_count:d} task desired"
                .format(service=service))

    def __register_task_definition(self, service: Service):
        # for register task rate limit
        retry_count = 0
        while True:
            try:
                task_definition = self.awsutils.register_task_definition(task_definition=service.task_definition)
            except botocore.exceptions.ClientError as e:
                error_code = e.response['Error']['Code']
                if error_code == 'ThrottlingException':
                    if retry_count > 6:
                        raise
                    retry_count = retry_count + 1
                    time.sleep(randint(3, 10))
                    continue
                else:
                    raise
            break
        service.set_task_definition_arn(task_definition)

    def check_service_task(self, describe_service: DescribeService):
        # for describe task rate limit
        retry_count = 0
        while True:
            try:
                task_definition = self.awsutils.describe_task_definition(describe_service.task_definition_arn)
            except botocore.exceptions.ClientError as e:
                error_code = e.response['Error']['Code']
                if error_code == 'ThrottlingException':
                    if retry_count > 6:
                        raise
                    retry_count = retry_count + 1
                    time.sleep(randint(3, 10))
                    continue
                else:
                    raise
            break
        describe_service.set_from_task_definition(task_definition)

    def check_deploy_service(self, service: Service):
        if service.origin_task_definition_arn is None:
            try:
                res_service = self.awsutils.describe_service(
                    service.task_environment.cluster_name, service.service_name)
                describe_service = DescribeService(service_description=res_service)
                task_definition = self.awsutils.describe_task_definition(describe_service.task_definition_arn)
                describe_service.set_from_task_definition(task_definition)
                service.set_from_describe_service(describe_service=describe_service)
            except ServiceNotFoundException:
                error("Service '{service.service_name}' not Found. will be created.".format(service=service))
                return
        if not service.origin_service_exists:
            error("Service '{service.service_name}' status not Acrive. will be recreated.".format(service=service))
            return

        checks = service.compare_container_definition()

        success("Checking service '{service.service_name}' succeeded "
                "({service.running_count:d} / {service.desired_count:d})\n\033[39m{checks}"
                .format(service=service, checks=checks))

    def __create_service(self, service: Service):
        res_service = self.awsutils.create_service(
            cluster=service.task_environment.cluster_name,
            service=service.service_name,
            task_definition=service.task_definition_arn,
            desired_count=service.task_environment.desired_count,
            maximum_percent=service.task_environment.maximum_percent,
            minimum_healthy_percent=service.task_environment.minimum_healthy_percent,
            distinct_instance=service.task_environment.distinct_instance
        )
        service.update(res_service)

    def __update_service(self, service: Service):
        desired_count = service.task_environment.desired_count
        # サービスのタスク数が0だったらそれを維持する
        if self.is_service_zero_keep and service.desired_count == 0:
            desired_count = 0
        res_service = self.awsutils.update_service(
            cluster=service.task_environment.cluster_name,
            service=service.service_name,
            task_definition=service.task_definition_arn,
            maximum_percent=service.task_environment.maximum_percent,
            minimum_healthy_percent=service.task_environment.minimum_healthy_percent,
            desired_count=desired_count
        )
        service.update(res_service)


class DeployManager(object):
    def __init__(self, args):
        self.awsutils = AwsUtils(access_key=args.key, secret_key=args.secret, region=args.region)
        self.task_queue = Queue()

        self.service_list, self.deploy_service_list, self.environment =\
            get_deploy_list(
                services_yaml=args.services_yaml,
                environment_yaml=args.environment_yaml,
                task_definition_template_dir=args.task_definition_template_dir,
                task_definition_config_json=args.task_definition_config_json,
                task_definition_config_env=args.task_definition_config_env,
                deploy_service_group=args.deploy_service_group,
                template_group=args.template_group
            )

        self.threads_count = args.threads_count
        # thread数がタスクの数を超えているなら減らす
        if len(self.deploy_service_list) < self.threads_count:
            self.threads_count = len(self.deploy_service_list)

        self.key = args.key
        self.secret = args.secret
        self.region = args.region
        self.is_service_zero_keep = args.service_zero_keep
        self.template_group = args.template_group
        self.is_delete_unused_service = args.delete_unused_service

        self.cluster_list = []
        for service in self.service_list:
            if service.task_environment.cluster_name not in self.cluster_list:
                self.cluster_list.append(service.task_environment.cluster_name)

        self.error = False

        self.delete_service_list = []

    def start_threads(self):
        # threadの開始
        for i in range(self.threads_count):
            thread = DeployProcess(self.task_queue, self.key, self.secret, self.region, self.is_service_zero_keep)
            thread.setDaemon(True)
            thread.start()

    def run(self):
        # Step: Check ECS cluster
        self.check_ecs_cluster()

        self.start_threads()
        self.check_service_and_task()

        # Step: Delete Unused Service
        self.delete_unused_services()
        self.check_service()

        self.deploy_service()
        self.wait_for_stable()

        self.result_check()

    def dry_run(self):
        # Step: Check ECS cluster
        self.check_ecs_cluster()

        self.start_threads()
        self.check_service_and_task()

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
        if len(self.delete_service_list) == 0:
            info("There was no service to delete.")
        for delete_service in self.delete_service_list:
            success("Delete service '{delete_service.service_name}'".format(delete_service=delete_service))
            if not dry_run:
                self.awsutils.delete_service(delete_service.cluster_name, delete_service.service_name)

    def check_ecs_cluster(self):
        h1("Step: Check ECS cluster")
        for cluster_name in self.cluster_list:
            self.awsutils.describe_cluster(cluster=cluster_name)
            success("Checking cluster '{cluster_name}' succeeded".format(cluster_name=cluster_name))

    def check_service_and_task(self):
        h1("Step: Check ECS service and task definition")
        describe_service_list = fetch_aws_service(cluster_list=self.cluster_list, awsutils=self.awsutils)
        for s in describe_service_list:
            self.task_queue.put([s, ProcessMode.checkServiceAndTask])
        while self.task_queue.qsize() > 0:
            print('.', end='', flush=True)
            time.sleep(3)
        self.task_queue.join()
        info("")

        for describe_service in describe_service_list:
            if self.environment != describe_service.task_environment.environment:
                continue
            if self.template_group is not None:
                if describe_service.task_environment.template_group != self.template_group:
                    continue
            is_delete = True
            for service in self.service_list:
                if service.service_name == describe_service.service_name:
                    if service.task_environment.cluster_name == describe_service.cluster_name:
                        service.set_from_describe_service(describe_service=describe_service)
                        is_delete = False
                        break
            if is_delete:
                self.delete_service_list.append(describe_service)
        success("Check succeeded")

    def deploy_service(self):
        h1("Step: Deploy Service")
        for service in self.deploy_service_list:
            self.task_queue.put([service, ProcessMode.deployService])
        self.task_queue.join()

    def check_service(self):
        h1("Step: Check Deploy ECS Service")
        for service in self.deploy_service_list:
            self.task_queue.put([service, ProcessMode.checkDeployService])
        self.task_queue.join()

    def wait_for_stable(self):
        h1("Step: Wait for Service Status 'Stable'")
        for service in self.deploy_service_list:
            self.task_queue.put([service, ProcessMode.waitForStable])
        self.task_queue.join()

    def result_check(self):
        error_service_list = list(filter(
            lambda service: service.status == ProcessStatus.error, self.deploy_service_list
        ))
        # サービスでエラーが一個でもあれば失敗としておく
        if len(error_service_list) > 0:
            sys.exit(1)
        if self.error:
            sys.exit(1)


def deregister_task_definition(awsutils, service: Service):
    retry_count = 0
    if service.origin_task_definition_arn is None:
        return
    if service.is_same_task_definition:
        return
    while True:
        try:
            awsutils.deregister_task_definition(service.origin_task_definition_arn)
        except botocore.exceptions.ClientError as e:
            error_code = e.response['Error']['Code']
            if error_code == 'ThrottlingException':
                if retry_count > 3:
                    raise
                retry_count = retry_count + 1
                time.sleep(3)
                continue
            else:
                raise
        break


def wait_for_stable(awsutils, service: Service):
    retry_count = 0
    while True:
        try:
            res_service = awsutils.wait_for_stable(cluster_name=service.task_environment.cluster_name,
                                                   service_name=service.service_name)
        except botocore.exceptions.WaiterError:
            if retry_count > 2:
                raise
            retry_count = retry_count + 1
            continue
        break
    service.update(res_service)
    deregister_task_definition(awsutils, service)
    success("service '{service.service_name}' ({service.running_count:d} / {service.desired_count}) update completed."
            .format(service=service))


def test_templates(args):
    h1("Step: Check ECS Template")
    environment = None
    files = os.listdir(args.environment_yaml_dir)
    if files is None or len(files) == 0:
        raise Exception("environment yaml file not found.")
    services_config = yaml.load(args.services_yaml)
    for f in files:
        file_path = os.path.join(args.environment_yaml_dir, f)
        if os.path.isfile(file_path):
            with open(file_path, 'r') as environment_yaml:
                environment_config = yaml.load(environment_yaml)

                environment = environment_config.get("environment")
                if environment is None:
                    raise VariableNotFoundException("environment-yaml requires paramter `environment`.")
                environment = render.render_template(
                    str(environment),
                    environment_config,
                    args.task_definition_config_env
                )

                get_service_list_yaml(
                    services_config=services_config,
                    environment_config=environment_config,
                    task_definition_config_env=args.task_definition_config_env,
                    environment=environment
                )
        success("Template check environment `{environment}` done.".format(environment=environment))


def get_deploy_list(
        services_yaml,
        environment_yaml,
        task_definition_template_dir,
        task_definition_config_json,
        task_definition_config_env,
        deploy_service_group,
        template_group
):
    h1("Step: Check ECS Template")
    if services_yaml:
        services_config = yaml.load(services_yaml)
        environment_config = yaml.load(environment_yaml)

        environment = environment_config.get("environment")
        if environment is None:
            raise VariableNotFoundException("environment-yaml requires paramter `environment`.")
        environment = render.render_template(str(environment), environment_config, task_definition_config_env)

        service_list =\
            get_service_list_yaml(
                services_config=services_config,
                environment_config=environment_config,
                task_definition_config_env=task_definition_config_env,
                environment=environment
            )
    else:
        task_definition_config = json.load(task_definition_config_json)
        environment = task_definition_config['environment']
        service_list =\
            get_service_list_json(
                task_definition_template_dir=task_definition_template_dir,
                task_definition_config=task_definition_config,
                task_definition_config_env=task_definition_config_env
            )
    deploy_service_list = get_deploy_service_list(service_list, deploy_service_group, template_group)
    success("Template check environment `{environment}` done.".format(environment=environment))
    return service_list, deploy_service_list, environment
