# coding: utf-8
import json
import os
import sys
import time
import traceback
from multiprocessing import Queue
from queue import Queue, Empty
from random import randint
from threading import Thread

import botocore.exceptions
import yaml

import render
from aws import AwsUtils, ServiceNotFoundException, CloudwatchEventRuleNotFoundException
from ecs.classes import ProcessMode, ProcessStatus, VariableNotFoundException
from ecs.scheduled_tasks import ScheduledTask, get_scheduled_task_list, get_deploy_scheduled_task_list, \
    CloudwatchEventRule, CloudWatchEventState, scheduled_task_managed_description
from ecs.service import Service, DescribeService, get_service_list_json, get_service_list_yaml, \
    fetch_aws_service, get_deploy_service_list
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

        if mode == ProcessMode.fetchServices:
            self.fetch_service(deploy)

        elif mode == ProcessMode.deployService:
            self.process_service(deploy)

        elif mode == ProcessMode.checkDeployService:
            self.check_deploy_service(deploy)

        elif mode == ProcessMode.waitForStable:
            wait_for_stable(self.awsutils, deploy)

        elif mode == ProcessMode.deployScheduledTask:
            self.deploy_scheduled_task(deploy)

        elif mode == ProcessMode.fetchCloudwatchEvents:
            self.fetch_cloudwatch_event(deploy)

        elif mode == ProcessMode.checkDeployScheduledTask:
            self.check_deploy_scheduled_task(deploy)

        elif mode == ProcessMode.stopScheduledTask:
            self.stop_scheduled_task(deploy)

    def stop_scheduled_task(self, scheduled_task: ScheduledTask):
        if not scheduled_task.task_exists:
            return
        if scheduled_task.state == CloudWatchEventState.enabled:
            self.awsutils.disable_rule(name=scheduled_task.family)
        running_task_arns = self.awsutils.list_running_tasks(
            cluster=scheduled_task.origin_task_environment.cluster_name,
            family=scheduled_task.family
        )
        if len(running_task_arns) > 0:
            info("Stopping Task `{family}`.".format(family=scheduled_task.family))
            for task_arn in running_task_arns:
                self.awsutils.stop_task(
                    cluster=scheduled_task.origin_task_environment.cluster_name,
                    task_arn=task_arn
                )
            self.awsutils.wait_for_task_stopped(
                cluster=scheduled_task.origin_task_environment.cluster_name,
                tasks=running_task_arns
            )

    def fetch_cloudwatch_event(self, cloud_watch_event_rule: CloudwatchEventRule):
        task_definition = self.__describe_task_definition(name=cloud_watch_event_rule.name)
        cloud_watch_event_rule.set_from_task_definition(task_definition)

    def deploy_scheduled_task(self, scheduled_task: ScheduledTask):
        if not scheduled_task.is_same_task_definition:
            res_reg = self.awsutils.register_task_definition(task_definition=scheduled_task.task_definition)
            scheduled_task.task_definition_arn = res_reg['taskDefinitionArn']
        self.awsutils.create_scheduled_task(
            scheduled_task=scheduled_task, description=scheduled_task_managed_description)
        success("Deploy Scheduled Task '{scheduled_task.name}' succeeded.\n\033[39m"
                "    - Cloudwatch Event State: {state.value}\n"
                "    - Registering task definition arn: '{task_definition_arn}'.\n"
                "    - schedule '{scheduled_task.schedule_expression}'.\n"
                "    - {scheduled_task.task_environment.task_count} task count."
                .format(state=scheduled_task.state,
                        scheduled_task=scheduled_task,
                        task_definition_arn=scheduled_task.task_definition_arn))

    def process_service(self, service: Service):
        self.__register_task_definition(service)
        if service.origin_service_exists:
            self.__update_service(service)
        else:
            self.__create_service(service)
        success("Deploy Service '{service.service_name}' succeeded.\n\033[39m"
                "    - Registering task definition arn: '{service.task_definition_arn}'\n"
                "    - {service.desired_count:d} task desired"
                .format(service=service))

    def fetch_service(self, describe_service: DescribeService):
        task_definition = self.__describe_task_definition(name=describe_service.task_definition_arn)
        describe_service.set_from_task_definition(task_definition)

    def check_deploy_service(self, service: Service):
        if service.origin_task_definition_arn is None:
            try:
                res_service = self.awsutils.describe_service(
                    service.task_environment.cluster_name, service.service_name
                )
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

    def check_deploy_scheduled_task(self, scheduled_task: ScheduledTask):
        if scheduled_task.origin_task_definition_arn is None:
            try:
                describe_rule = self.awsutils.describe_rule(scheduled_task.name)
                task_definition = self.awsutils.describe_task_definition(scheduled_task.name)
                c = CloudwatchEventRule(describe_rule)
                c.set_from_task_definition(task_definition)
                scheduled_task.set_from_cloudwatch_event_rule(c)
            except CloudwatchEventRuleNotFoundException:
                error("Scheduled Task '{scheduled_task.name}' not Found. will be created."
                      .format(scheduled_task=scheduled_task))
                return

        checks = scheduled_task.compare_container_definition()

        success("Checking scheduled task '{scheduled_task.name}' succeeded. \n\033[39m{checks}"
                .format(scheduled_task=scheduled_task, checks=checks))

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

    def __describe_task_definition(self, name: str) -> dict:
        # for describe task rate limit
        retry_count = 0
        while True:
            try:
                task_definition = self.awsutils.describe_task_definition(name=name)
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
        return task_definition

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


class DeployManager(object):
    def __init__(self, args):
        self.awsutils = AwsUtils(access_key=args.key, secret_key=args.secret, region=args.region)
        self.task_queue = Queue()

        self.service_list,\
            self.deploy_service_list,\
            self.scheduled_task_list,\
            self.deploy_scheduled_task_list,\
            self.environment = get_deploy_list(
                    services_yaml=args.services_yaml,
                    environment_yaml=args.environment_yaml,
                    task_definition_template_dir=args.task_definition_template_dir,
                    task_definition_config_json=args.task_definition_config_json,
                    task_definition_config_env=args.task_definition_config_env,
                    deploy_service_group=args.deploy_service_group,
                    template_group=args.template_group
                )
        self.cluster_list = self.awsutils.list_clusters()
        self.threads_count = args.threads_count
        # thread数がタスクの数を超えているなら減らす
        deploy_size = len(self.deploy_scheduled_task_list) + len(self.deploy_service_list)
        if deploy_size < self.threads_count:
            self.threads_count = deploy_size

        self.key = args.key
        self.secret = args.secret
        self.region = args.region
        self.is_service_zero_keep = args.service_zero_keep
        self.template_group = args.template_group
        self.is_delete_unused_service = args.delete_unused_service

        self.error = False

        self.delete_service_list = []
        self.delete_scheduled_task_list = []

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
        self.fetch_ecs_information()

        # Step: Delete Unused Service
        self.delete_unused()
        self.check_deploy()

        self.stop_scheduled_task()
        self.deploy_service()
        self.wait_for_stable()
        self.deploy_scheduled_task()

        self.result_check()

    def dry_run(self):
        # Step: Check ECS cluster
        self.check_ecs_cluster()

        self.start_threads()
        self.fetch_ecs_information()

        # Step: Check Delete Service
        self.delete_unused(dry_run=True)
        # Step: Check Service
        self.check_deploy()

    def stop_scheduled_task(self):
        if len(self.deploy_scheduled_task_list) > 0:
            h1("Step: Stop ECS Scheduled Task")
            for task in self.deploy_scheduled_task_list:
                self.task_queue.put([task, ProcessMode.stopScheduledTask])
            self.task_queue.join()

    def deploy_scheduled_task(self):
        if len(self.deploy_scheduled_task_list) > 0:
            h1("Step: Deploy ECS Scheduled Task")
            for task in self.deploy_scheduled_task_list:
                self.task_queue.put([task, ProcessMode.deployScheduledTask])
            self.task_queue.join()

    def delete_unused(self, dry_run=False):
        if dry_run:
            h1("Step: Check Delete Unused")
        else:
            h1("Step: Delete Unused")
        if not self.is_delete_unused_service:
            info("Do not delete unused")
            return
        if len(self.delete_service_list) == 0 and len(self.delete_scheduled_task_list) == 0:
            info("There was no service or task to delete.")
        for delete_service in self.delete_service_list:
            success("Delete service '{delete_service.service_name}'".format(delete_service=delete_service))
            if not dry_run:
                self.awsutils.delete_service(delete_service.cluster_name, delete_service.service_name)
        for delete_scheduled_task in self.delete_scheduled_task_list:
            success("Delete scheduled task '{delete_scheduled_task.name}'"
                    .format(delete_scheduled_task=delete_scheduled_task))
            if not dry_run:
                self.awsutils.delete_scheduled_task(
                    name=delete_scheduled_task.name,
                    target_arn=delete_scheduled_task.task_environment.target_lambda_arn
                )

    def check_ecs_cluster(self):
        h1("Step: Check ECS cluster")
        for cluster_name in self.cluster_list:
            self.awsutils.describe_cluster(cluster=cluster_name)
            success("Checking cluster '{cluster_name}' succeeded".format(cluster_name=cluster_name))

    def fetch_ecs_information(self):
        h1("Step: Fetch ECS Information")
        describe_service_list = []
        if len(self.service_list) > 0:
            describe_service_list = fetch_aws_service(cluster_list=self.cluster_list, awsutils=self.awsutils)
            for s in describe_service_list:
                self.task_queue.put([s, ProcessMode.fetchServices])
        cloud_watch_rule_list = []
        if len(self.scheduled_task_list) > 0:
            rules = self.awsutils.list_cloudwatch_event_rules()
            for r in rules:
                if r.get('Description') == scheduled_task_managed_description:
                    c = CloudwatchEventRule(r)
                    cloud_watch_rule_list.append(c)
                    self.task_queue.put([c, ProcessMode.fetchCloudwatchEvents])
        while self.task_queue.qsize() > 0:
            print('.', end='', flush=True)
            time.sleep(3)
        self.task_queue.join()
        info("")

        # set service description and get delete servicelist
        for describe_service in describe_service_list:
            if self.environment != describe_service.task_environment.environment:
                continue
            if self.template_group is not None:
                if self.template_group != describe_service.task_environment.template_group:
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
        for cloud_watch_rule in cloud_watch_rule_list:
            if self.environment != cloud_watch_rule.task_environment.environment:
                continue
            if self.template_group is not None:
                if self.template_group != cloud_watch_rule.task_environment.template_group:
                    continue
            is_delete = True
            for scheduled_task in self.scheduled_task_list:
                if scheduled_task.family == cloud_watch_rule.family:
                    scheduled_task.set_from_cloudwatch_event_rule(cloud_watch_rule)
                    is_delete = False
                    break
            if is_delete:
                self.delete_scheduled_task_list.append(cloud_watch_rule)
        success("Check succeeded")

    def deploy_service(self):
        if len(self.deploy_service_list) > 0:
            h1("Step: Deploy ECS Service")
            for service in self.deploy_service_list:
                self.task_queue.put([service, ProcessMode.deployService])
            self.task_queue.join()

    def check_deploy(self):
        h1("Step: Check Deploy ECS Service and Scheduled tasks")
        for service in self.deploy_service_list:
            self.task_queue.put([service, ProcessMode.checkDeployService])
        for scheduled_task in self.deploy_scheduled_task_list:
            self.task_queue.put([scheduled_task, ProcessMode.checkDeployScheduledTask])
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
    scheduled_task_list = []
    deploy_scheduled_task_list = []
    if services_yaml:
        services_config = yaml.load(services_yaml)
        environment_config = yaml.load(environment_yaml)

        environment = environment_config.get("environment")
        if environment is None:
            raise VariableNotFoundException("environment-yaml requires parameter `environment`.")
        environment = render.render_template(str(environment), environment_config, task_definition_config_env)

        service_list = get_service_list_yaml(
            services_config=services_config,
            environment_config=environment_config,
            task_definition_config_env=task_definition_config_env,
            environment=environment
        )

        scheduled_task_list = get_scheduled_task_list(
            services_config=services_config,
            environment_config=environment_config,
            task_definition_config_env=task_definition_config_env,
            environment=environment
        )
        deploy_scheduled_task_list = get_deploy_scheduled_task_list(
            scheduled_task_list, deploy_service_group, template_group)

    else:
        task_definition_config = json.load(task_definition_config_json)
        environment = task_definition_config['environment']
        service_list = get_service_list_json(
            task_definition_template_dir=task_definition_template_dir,
            task_definition_config=task_definition_config,
            task_definition_config_env=task_definition_config_env
        )
    deploy_service_list = get_deploy_service_list(service_list, deploy_service_group, template_group)

    # duplicate name check
    for deploy_service in deploy_service_list:
        for deploy_scheduled_task in deploy_scheduled_task_list:
            if deploy_service.family == deploy_scheduled_task.family:
                raise Exception('Duplicate family name `{family}` found.'.format(family=deploy_service.family))

    if len(deploy_service_list) == 0 and len(deploy_scheduled_task_list) == 0:
        error("Deployment target not found.")

    success("Template check environment `{environment}` done.".format(environment=environment))
    return service_list, deploy_service_list, scheduled_task_list, deploy_scheduled_task_list, environment
