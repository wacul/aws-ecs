# coding: utf-8
import ecs.classes
import ecs.deploy
import jinja2
import json
import logging
import render

logger = logging.getLogger(__name__)


class ParameterNotFoundException(Exception):
    pass


class ParameterInvalidException(Exception):
    pass


class VariableNotFoundException(Exception):
    pass


class EnvironmentValueNotFoundException(Exception):
    pass


class TaskEnvironment(object):
    def __init__(self, task_definition: dict) -> None:
        try:
            task_environment_list = task_definition['containerDefinitions'][0]['environment']
        except:
            raise EnvironmentValueNotFoundException(
                "task definition is lack of environment.\ntask definition:\n{task_definition}"
                    .format(task_definition=task_definition))

        self.__environment = None
        self.__cluster_name = None
        self.__service_group = None
        self.__template_group = None
        self.__task_count = None
        self.__spot_fleet_id = None
        self.__placement_strategy = None
        for task_environment in task_environment_list:
            if task_environment['name'] == 'ENVIRONMENT':
                self.__environment = task_environment['value']
            if task_environment['name'] == 'CLUSTER_NAME':
                self.__cluster_name = task_environment['value']
            elif task_environment['name'] == 'SERVICE_GROUP':
                self.__service_group = task_environment['value']
            elif task_environment['name'] == 'TEMPLATE_GROUP':
                self.__template_group = task_environment['value']
            elif task_environment['name'] == 'TASK_COUNT':
                self.__task_count = int(task_environment['value'])
        if self.__environment is None:
            raise EnvironmentValueNotFoundException(
                "task definition is lack of environment `ENVIRONMENT`.\ntask definition:\n{task_definition}"
               .format(task_definition=task_definition))
        elif self.__cluster_name is None:
            raise EnvironmentValueNotFoundException(
                "task definition is lack of environment `CLUSTER_NAME`.\ntask definition:\n{task_definition}"
                .format(task_definition=task_definition))
        elif self.__task_count is None:
            raise EnvironmentValueNotFoundException(
                "task definition is lack of environment `TASK_COUNT`.\ntask definition:\n{task_definition}"
                .format(task_definition=task_definition))


class ScheduledTask(object):
    def __init__(self, task_definition, target_arn, schedule_expression, placement_strategy):
        self.task_definition = task_definition
        self.family = task_definition.get('family')
        if self.family is None:
            raise EnvironmentValueNotFoundException(
                "task definition parameter `family` no found.\ntask definition:\n{task_definition}"
                    .format(task_definition=task_definition))

        self.task_environment = TaskEnvironment(task_definition)
        self.target_arn = target_arn
        self.schedule_expression = schedule_expression
        self.placement_strategy = placement_strategy

        self.status = ecs.classes.ProcessStatus.normal


def __deploy_task_list(task_list, deploy_service_group, template_group):
    if deploy_service_group:
        deploy_service_list = list(filter(
            lambda service: service.task_environment.service_group == deploy_service_group, task_list))
    else:
        deploy_service_list = task_list

    if template_group:
        deploy_service_list = list(filter(
            lambda service: service.task_environment.template_group == template_group, deploy_service_list))
    if len(deploy_service_list) == 0:
        raise Exception("Deployment target service not found.")

    return deploy_service_list


def __get_variables(task_name, base_service_config, environment_config):
    variables = {"item": task_name}
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
    environment_config_services = environment_config.get("scheduledTasks")
    if environment_config_services:
        environment_service = environment_config_services.get(task_name)
        if environment_service:
            variables.update(environment_service)
            service_config.update(environment_service)
            environment_vars = environment_service.get("vars")
            if environment_vars:
                variables.update(environment_vars)
    return service_config, variables


def get_scheduled_task_list(services_config,
                            environment_config,
                            task_definition_config_env,
                            deploy_service_group,
                            template_group,
                            environment):

    scheduled_tasks = services_config["scheduledTasks"]
    task_definition_template_dict = services_config["taskDefinitionTemplates"]

    scheduled_task_list = []
    for task_name in scheduled_tasks:
        # 設定値と変数を取得
        service_config, variables = __get_variables(task_name=task_name,
                                                    base_service_config=scheduled_tasks.get(task_name),
                                                    environment_config=environment_config)

        # parameter check & build docker environment
        env = [{"name": "ENVIRONMENT", "value": environment}]

        cluster = service_config.get("cluster")
        if cluster is None:
            raise ParameterNotFoundException("Service `{task_name}` requires parameter `cluster`"
                                             .format(task_name=task_name))
        cluster = render.render_template(str(cluster), variables, task_definition_config_env)
        env.append({"name": "CLUSTER_NAME", "value": cluster})

        service_group = service_config.get("serviceGroup")
        if service_group is not None:
            service_group = render.render_template(str(service_group), variables, task_definition_config_env)
            env.append({"name": "SERVICE_GROUP", "value": service_group})

        template_group = service_config.get("templateGroup")
        if template_group is not None:
            template_group = render.render_template(str(template_group), variables, task_definition_config_env)
            env.append({"name": "TEMPLATE_GROUP", "value": template_group})

        task_count = service_config.get("taskCount")
        if task_count is None:
            raise ParameterNotFoundException("Scheduled Task `{task_name}` requires parameter `desiredCount`"
                                             .format(task_name=task_name))
        task_count = render.render_template(str(task_count), variables, task_definition_config_env)
        try:
            int(task_count)
        except ValueError:
            raise ParameterInvalidException("Scheduled Task `{task_name}` parameter `taskCount` is int"
                                            .format(task_name=task_name))
        env.append({"name": "TASK_COUNT", "value": task_count})

        placement_strategy = service_config.get("placementStrategy")
        if placement_strategy is not None:
            placement_strategy = render.render_template(str(placement_strategy), variables, task_definition_config_env)

        schedule_expression = service_config.get("scheduleExpression")
        if schedule_expression is not None:
            schedule_expression = render.render_template(
                str(schedule_expression),
                variables,
                task_definition_config_env
            )

        target_arn = service_config.get("targetArn")
        if target_arn is not None:
            target_arn = render.render_template(str(target_arn), variables, task_definition_config_env)

        task_definition_template = service_config.get("taskDefinitionTemplate")
        if task_definition_template is None:
            raise ParameterNotFoundException(
                "Scheduled Task `{task_name}` requires parameter `taskDefinitionTemplate`".format(task_name=task_name))
        scheduled_task_definition_template = task_definition_template_dict.get(task_definition_template)
        if scheduled_task_definition_template is None or len(scheduled_task_definition_template) == 0:
            raise Exception("Scheduled Task '%s' taskDefinitionTemplate not found. " % task_name)
        if not isinstance(scheduled_task_definition_template, str):
            raise Exception(
                "Scheduled Task '{task_name}' taskDefinitionTemplate specified template value must be str. "
                    .format(task_name=task_name))

        try:
            task_definition_data = render.render_template(scheduled_task_definition_template, variables,
                                                          task_definition_config_env)
        except jinja2.exceptions.UndefinedError:
            logger.error("Scheduled Task `%s` jinja2 varibles Undefined Error." % task_name)
            raise
        try:
            task_definition = json.loads(task_definition_data)
        except json.decoder.JSONDecodeError as e:
            raise Exception(
                "Scheduled Task `{task_name}`: {e.__class__.__name__} {e}\njson:\n{task_definition_data}"
                    .format(task_name=task_name, e=e, task_definition_data=task_definition_data))

        # set parameters to docker environment
        for container_definitions in task_definition.get("containerDefinitions"):
            task_environment = container_definitions.get("environment")
            if task_environment is not None:
                if not isinstance(task_environment, list):
                    raise Exception(
                        "Scheduled Task '{task_name}' taskDefinitionTemplate environment value must be list. "
                            .format(task_name=task_name))
                env.extend(task_environment)
            container_definitions["environment"] = env

        scheduled_task = ScheduledTask(
            task_definition=task_definition,
            target_arn=target_arn,
            schedule_expression=schedule_expression,
            placement_strategy=placement_strategy
        )
        scheduled_task_list.append(scheduled_task)

    deploy_task_list = __deploy_task_list(scheduled_task_list, deploy_service_group, template_group)
    return scheduled_task_list, deploy_task_list, environment
