# coding: utf-8
import json
import logging
import os
import copy
from distutils.util import strtobool

import jinja2
from datadiff import diff

import render
from ecs.classes import DeployTargetType, Deploy, EnvironmentValueNotFoundException, ParameterInvalidException, \
    ParameterNotFoundException
from ecs.utils import is_same_container_definition, adjust_container_definition

logger = logging.getLogger(__name__)


class TaskEnvironment(object):
    def __init__(self, task_definition: dict):
        try:
            task_environment_list = task_definition['containerDefinitions'][0]['environment']
        except:
            raise EnvironmentValueNotFoundException(
                "task definition is lack of environment.\ntask definition:\n{task_definition}"
                .format(task_definition=task_definition))

        self.environment = None
        self.cluster_name = None
        self.service_group = None
        self.template_group = None
        self.desired_count = None
        self.is_downscale_task = None
        self.minimum_healthy_percent = 50
        self.maximum_percent = 200
        self.distinct_instance = False
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
            elif task_environment['name'] == 'DISTINCT_INSTANCE':
                self.distinct_instance = strtobool(task_environment['value'])
        if self.environment is None:
            raise EnvironmentValueNotFoundException(
                "task definition is lack of environment `ENVIRONMENT`.\ntask definition:\n{task_definition}"
                .format(task_definition=task_definition))
        elif self.cluster_name is None:
            raise EnvironmentValueNotFoundException(
                "task definition is lack of environment `CLUSTER_NAME`.\ntask definition:\n{task_definition}"
                .format(task_definition=task_definition))
        elif self.desired_count is None:
            raise EnvironmentValueNotFoundException(
                "task definition is lack of environment `DESIRED_COUNT`.\ntask definition:\n{task_definition}"
                .format(task_definition=task_definition))


class DescribeService(Deploy):
    def __init__(self, service_description: dict):
        self.service_name = service_description['serviceName']
        self.cluster_arn = service_description['clusterArn']
        self.cluster_name = arn_to_name(self.cluster_arn)
        self.task_definition_arn = service_description['taskDefinition']
        self.running_count = service_description['runningCount']
        self.desired_count = service_description['desiredCount']

        self.task_definition = None
        self.task_environment = None
        self.family = None

        self.service_exists = True
        if service_description['status'] != 'ACTIVE':
            self.service_exists = False

        super().__init__(name=self.service_name, target_type=DeployTargetType.service_describe)

    def set_from_task_definition(self, task_definition: dict):
        self.task_definition = task_definition
        self.task_environment = TaskEnvironment(task_definition)
        self.family = task_definition['family']


class Service(Deploy):
    def __init__(self, task_definition: dict):
        self.task_definition = task_definition
        self.task_environment = TaskEnvironment(task_definition)
        self.family = task_definition['family']
        self.service_name = self.family + '-service'
        self.desired_count = self.task_environment.desired_count

        self.origin_task_definition_arn = None
        self.origin_task_definition = None
        self.task_definition_arn = None
        self.origin_service_exists = False
        self.is_same_task_definition = False
        self.running_count = 0

        super().__init__(self.service_name, target_type=DeployTargetType.service)

    def set_from_describe_service(self, describe_service: DescribeService):
        self.origin_service_exists = describe_service.service_exists
        self.origin_task_definition = describe_service.task_definition
        self.origin_task_definition_arn = describe_service.task_definition_arn
        self.running_count = describe_service.running_count
        self.desired_count = describe_service.desired_count

    def set_task_definition_arn(self, task_definition: dict):
        self.task_definition_arn = task_definition.get('taskDefinitionArn')

    def update(self, describe_service: dict):
        self.running_count = describe_service.get('runningCount')
        self.desired_count = describe_service.get('desiredCount')

    def compare_container_definition(self):
        a = self.origin_task_definition['containerDefinitions']
        b = self.task_definition['containerDefinitions']
        ad = adjust_container_definition(a)
        bd = adjust_container_definition(b)
        self.is_same_task_definition = is_same_container_definition(ad, bd)
        if self.is_same_task_definition:
            self.task_definition_arn = self.origin_task_definition_arn
            return "    - Container Definition is not changed."
        else:
            t = diff(ad, bd)
            return "    - Container is changed. Diff:\n{t}".format(t=t)


def arn_to_name(arn):
    return arn.split('/')[-1]


def get_deploy_service_list(service_list, deploy_service_group, template_group):
    if deploy_service_group is not None:
        slist = []
        for service in service_list:
            if service.task_environment.service_group == deploy_service_group:
                slist.append(service)
        deploy_service_list = slist
    else:
        deploy_service_list = copy.copy(service_list)

    if template_group is not None:
        slist = []
        for service in deploy_service_list:
            if service.task_environment.template_group == template_group:
                slist.append(service)
        deploy_service_list = slist

    return deploy_service_list


def get_service_list_json(
        task_definition_template_dir,
        task_definition_config,
        task_definition_config_env
) -> list:
    service_list = []

    files = os.listdir(task_definition_template_dir)
    for file in files:
        file_path = os.path.join(task_definition_template_dir, file)
        try:
            with open(file_path, 'r') as template:
                task_definitions_data = render.render_template(template.read(),
                                                               task_definition_config,
                                                               task_definition_config_env)
        except Exception as e:
            raise Exception("Template error. file: %s\n%s" % (file, e))
        try:
            task_definitions = json.loads(task_definitions_data)
        except json.decoder.JSONDecodeError as e:
            raise Exception("{e.__class__.__name__} {e}\njson:\n{json}".format(e=e, json=task_definitions_data))
        for t in task_definitions:
            service_list.append(Service(t))

    return service_list


def get_service_list_yaml(
        services_config,
        environment_config,
        task_definition_config_env,
        environment
) -> list:
    try:
        services = services_config["services"]
    except KeyError:
        return []

    task_definition_template_dict = services_config["taskDefinitionTemplates"]

    service_list = []
    for service_name in services:
        # 設定値と変数を取得
        service_config, variables = __get_service_variables(
            service_name=service_name,
            base_service_config=services.get(service_name),
            environment_config=environment_config
        )

        # parameter check & build docker environment
        env = [{"name": "ENVIRONMENT", "value": environment}]

        registrator = service_config.get("registrator")
        if registrator is not None:
            registrator = render.render_template(str(registrator), variables, task_definition_config_env)
            try:
                registrator = strtobool(registrator)
            except ValueError:
                raise ParameterInvalidException(
                    "Service `{service_name}` parameter `registrator` must be bool".format(service_name=service_name)
                )
            if registrator:
                env.append({"name": "SERVICE_NAME", "value": environment})
                env.append({"name": "SERVICE_TAGS", "value": service_name})

        cluster = service_config.get("cluster")
        if cluster is None:
            raise ParameterNotFoundException("Service `{service_name}` requires parameter `cluster`"
                                             .format(service_name=service_name))
        cluster = render.render_template(str(cluster), variables, task_definition_config_env)
        env.append({"name": "CLUSTER_NAME", "value": cluster})

        service_group = service_config.get("serviceGroup")
        if service_group is not None:
            service_group = render.render_template(str(service_group), variables, task_definition_config_env)
            env.append({"name": "SERVICE_GROUP", "value": service_group})

        service_template_group = service_config.get("templateGroup")
        if service_template_group is not None:
            service_template_group = render.render_template(
                str(service_template_group), variables, task_definition_config_env)
            env.append({"name": "TEMPLATE_GROUP", "value": service_template_group})

        desired_count = service_config.get("desiredCount")
        if desired_count is None:
            raise ParameterNotFoundException("Service `{service_name}` requires parameter `desiredCount`"
                                             .format(service_name=service_name))
        desired_count = render.render_template(str(desired_count), variables, task_definition_config_env)
        try:
            int(desired_count)
        except ValueError:
            raise ParameterInvalidException("Service `{service_name}` parameter `desiredCount` is int"
                                            .format(service_name=service_name))
        env.append({"name": "DESIRED_COUNT", "value": desired_count})

        minimum_healthy_percent = service_config.get("minimumHealthyPercent")
        if minimum_healthy_percent is not None:
            minimum_healthy_percent = render.render_template(str(minimum_healthy_percent),
                                                             variables,
                                                             task_definition_config_env)
            try:
                int(minimum_healthy_percent)
            except ValueError:
                raise ParameterInvalidException("Service `{service_name}` parameter `minimumHealthyPercent` is int"
                                                .format(service_name=service_name))
            env.append({"name": "MINIMUM_HEALTHY_PERCENT", "value": minimum_healthy_percent})

        maximum_percent = service_config.get("maximumPercent")
        if maximum_percent is not None:
            maximum_percent = render.render_template(str(maximum_percent), variables, task_definition_config_env)
            try:
                int(maximum_percent)
            except ValueError:
                raise ParameterInvalidException(
                    "Service `{service_name}` parameter `maximumPercent` is int".format(service_name=service_name)
                )
            env.append({"name": "MAXIMUM_PERCENT", "value": str(maximum_percent)})

        distinct_instance = service_config.get("distinctInstance")
        if distinct_instance is not None:
            distinct_instance = render.render_template(str(distinct_instance), variables, task_definition_config_env)
            try:
                distinct_instance = strtobool(distinct_instance)
            except ValueError:
                raise ParameterInvalidException("Service `{service_name}` parameter `distinctInstance` must be bool"
                                                .format(service_name=service_name))
            if distinct_instance:
                env.append({"name": "DISTINCT_INSTANCE", "value": "true"})

        task_definition_template = service_config.get("taskDefinitionTemplate")
        if task_definition_template is None:
            raise ParameterNotFoundException("Service `{service_name}` requires parameter `taskDefinitionTemplate`"
                                             .format(service_name=service_name))
        service_task_definition_template = task_definition_template_dict.get(task_definition_template)
        if service_task_definition_template is None or len(service_task_definition_template) == 0:
            raise Exception("'%s' taskDefinitionTemplate not found. " % service_name)
        if not isinstance(service_task_definition_template, str):
            raise Exception("'%s' taskDefinitionTemplate specified template value must be str. " % service_name)

        try:
            task_definition_data = render.render_template(service_task_definition_template,
                                                          variables,
                                                          task_definition_config_env)
        except jinja2.exceptions.UndefinedError:
            logger.error("Service `%s` jinja2 varibles Undefined Error." % service_name)
            raise
        try:
            task_definition = json.loads(task_definition_data)
        except json.decoder.JSONDecodeError as e:
            raise Exception(
                "Service `{service}`: {e.__class__.__name__} {e}\njson:\n{json}".format(service=service_name, e=e,
                                                                                        json=task_definition_data))

        # set parameters to docker environment
        for container_definitions in task_definition.get("containerDefinitions"):
            task_environment = container_definitions.get("environment")
            if task_environment is not None:
                if not isinstance(task_environment, list):
                    raise Exception("'%s' taskDefinitionTemplate environment value must be list. " % service_name)
                env.extend(task_environment)
            container_definitions["environment"] = env

        service_list.append(Service(task_definition))

    return service_list


def __get_service_variables(service_name, base_service_config, environment_config):
    variables = {"item": service_name}
    service_config = {}
    # サービスの値
    variables.update(base_service_config)
    service_config.update(base_service_config)
    # サービスのvars
    v = base_service_config.get("vars")
    if v:
        variables.update(v)
    # 各環境の設定値
    variables.update(environment_config)
    # 各環境のサービス
    environment_config_services = environment_config.get("services")
    if environment_config_services:
        environment_service = environment_config_services.get(service_name)
        if environment_service:
            variables.update(environment_service)
            service_config.update(environment_service)
            environment_vars = environment_service.get("vars")
            if environment_vars:
                variables.update(environment_vars)
    return service_config, variables


def fetch_aws_service(cluster_list, awsutils) -> list:
    l = []
    for cluster_name in cluster_list:
        running_service_arn_list = awsutils.list_services(cluster_name)
        l.extend(awsutils.describe_services(cluster_name, running_service_arn_list))
    describe_service_list = []
    for service_description in l:
        describe = DescribeService(service_description=service_description)
        describe_service_list.append(describe)
    return describe_service_list
