# coding: utf-8
import sys, os, time, logging, yaml, json, jinja2, botocore
import render
from enum import Enum
from distutils.util import strtobool
from datadiff import diff

logger = logging.getLogger(__name__)
h1 = lambda x: print("\033[1m\033[4m\033[94m%s\033[0m\n" % x)
success = lambda x: print("\033[92m* %s\033[0m\n" % x)
error = lambda x: print("\033[91mx %s\033[0m\n" % x)
info = lambda x: print("  %s\n" % x)

class ParameterNotFoundException(Exception):
    pass
class ParameterInvalidException(Exception):
    pass
class VariableNotFoundException(Exception):
    pass
class EnvironmentValueNotFoundException(Exception):
    pass


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


class TaskEnvironment(object):
    def __init__(self, task_definition):
        try:
            task_environment_list = task_definition['containerDefinitions'][0]['environment']
        except:
            raise EnvironmentValueNotFoundException("task definition is lack of environment.\ntask definition:\n%s" % (task_definition))

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
            raise EnvironmentValueNotFoundException("task definition is lack of environment `ENVIRONMENT`.\ntask definition:\n%s" % (task_definition))
        elif self.cluster_name is None:
            raise EnvironmentValueNotFoundException("task definition is lack of environment `CLUSTER_NAME`.\ntask definition:\n%s" % (task_definition))
        elif self.desired_count is None:
            raise EnvironmentValueNotFoundException("task definition is lack of environment `DESIRED_COUNT`.\ntask definition:\n%s" % (task_definition))

class Service(object):
    def __init__(self, task_definition):
        self.task_definition = task_definition
        self.task_environment = TaskEnvironment(task_definition)
        self.task_name = task_definition['family']
        self.service_name = self.task_name + '-service'

        self.status = ProcessStatus.normal

        self.original_task_definition_arn = None
        self.task_definition_arn = None
        self.service_exists = False
        self.original_running_count = 0
        self.running_count = 0
        self.original_desired_count = 0
        self.desired_count = 0


    @staticmethod
    def _import_service_from_task_definitions(task_definitions):
        service_list = []
        for task_definition in task_definitions:
            service = Service(task_definition)
            service_list.append(service)
        return service_list

    @staticmethod
    def _get_service_variables(service_name, base_service_config, environment_config):
        variables = {"item": service_name}
        service_config = {}
        # サービスの値
        variables.update(base_service_config)
        service_config.update(base_service_config)
        # サービスのvars
        vars = base_service_config.get("vars")
        if vars:
            variables.update(vars)
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


    @staticmethod
    def get_service_list(services_yaml, environment_yaml, task_definition_template_dir, task_definition_config_json, task_definition_config_env, deploy_service_group, template_group, environment_yaml_dir=None):
        h1("Step: Check ECS Template")

        if services_yaml:
            services_config = yaml.load(services_yaml)
            if environment_yaml_dir:
                files = os.listdir(environment_yaml_dir)
                if files is None or len(files) == 0:
                    raise Exception("environment yaml file not found.")
                for f in files:
                    file_path = os.path.join(environment_yaml_dir, f)
                    if os.path.isfile(file_path):
                        with open(file_path, 'r') as environment_yaml:
                            environment_config = yaml.load(environment_yaml)
                            service_list, deploy_service_list, environment =  Service._get_service_list_yaml(services_config, environment_config, task_definition_config_env, deploy_service_group, template_group)
                    success("Template check environment `%s` done." % environment)
            else:
                environment_config = yaml.load(environment_yaml)
                service_list, deploy_service_list, environment =  Service._get_service_list_yaml(services_config, environment_config, task_definition_config_env, deploy_service_group, template_group)
                success("Template check environment `%s` done." % environment)
        else:
            service_list, deploy_service_list, environment =  Service._get_service_list_json(task_definition_template_dir, task_definition_config_json, task_definition_config_env, deploy_service_group, template_group)
            success("Template check environment `%s` done." % environment)
        return service_list, deploy_service_list, environment

    @staticmethod
    def _get_service_list_yaml(services_config, environment_config, task_definition_config_env, deploy_service_group, template_group):

        services = services_config["services"]
        task_definition_template_dict = services_config["taskDefinitionTemplates"]

        task_definition_list = []
        for service_name in services:
            # 設定値と変数を取得
            service_config, variables = Service._get_service_variables(service_name=service_name, base_service_config=services.get(service_name), environment_config=environment_config)

            # parameter check & build docker environment
            env = []

            environment = environment_config.get("environment")
            if environment is None:
                raise VariableNotFoundException("environment-yaml requires paramter `environment`.")
            environment = render.render_template(str(environment), variables, task_definition_config_env)
            env.append({"name": "ENVIRONMENT", "value": environment})

            registrator = service_config.get("registrator")
            if registrator is not None:
                registrator = render.render_template(str(registrator), variables, task_definition_config_env)
                try:
                    registrator = strtobool(registrator)
                except ValueError:
                    raise ParameterInvalidException("Service `%s` parameter `registrator` must be bool" % (service_name))
                if registrator:
                    env.append({"name": "SERVICE_NAME", "value": environment})
                    env.append({"name": "SERVICE_TAGS", "value": service_name})

            cluster = service_config.get("cluster")
            if cluster is None:
                raise ParameterNotFoundException("Service `%s` requires parameter `cluster`" % (service_name))
            cluster = render.render_template(str(cluster), variables, task_definition_config_env)
            env.append({"name": "CLUSTER_NAME", "value": cluster})
            
            serviceGroup = service_config.get("serviceGroup")
            if serviceGroup is not None:
                serviceGroup = render.render_template(str(serviceGroup), variables, task_definition_config_env)
                env.append({"name": "SERVICE_GROUP", "value": serviceGroup})

            templateGroup = service_config.get("templateGroup")
            if templateGroup is not None:
                templateGroup = render.render_template(str(templateGroup), variables, task_definition_config_env)
                env.append({"name": "TEMPLATE_GROUP", "value": templateGroup})

           
            desiredCount = service_config.get("desiredCount")
            if desiredCount is None:
                raise ParameterNotFoundException("Service `%s` requires parameter `desiredCount`" % (service_name))
            desiredCount = render.render_template(str(desiredCount), variables, task_definition_config_env)
            try:
                int(desiredCount)
            except ValueError:
                raise ParameterInvalidException("Service `%s` parameter `desiredCount` is int" % (service_name))
            env.append({"name": "DESIRED_COUNT", "value": desiredCount})

            minimumHealthyPercent = service_config.get("minimumHealthyPercent")
            if minimumHealthyPercent is not None:
                minimumHealthyPercent = render.render_template(str(minimumHealthyPercent), variables, task_definition_config_env)
                try:
                    int(minimumHealthyPercent)
                except ValueError:
                    raise ParameterInvalidException("Service `%s` parameter `minimumHealthyPercent` is int" % (service_name))
                env.append({"name": "MINIMUM_HEALTHY_PERCENT", "value": minimumHealthyPercent})

            maximumPercent = service_config.get("maximumPercent")
            if maximumPercent is not None:
                maximumPercent = render.render_template(str(maximumPercent), variables, task_definition_config_env)
                try:
                    int(maximumPercent)
                except ValueError:
                    raise ParameterInvalidException("Service `%s` parameter `maximumPercent` is int" % (service_name))
                env.append({"name": "MAXIMUM_PERCENT", "value": str(maximumPercent)})

            distinctInstance = service_config.get("distinctInstance")
            if distinctInstance is not None:
                distinctInstance = render.render_template(str(distinctInstance), variables, task_definition_config_env)
                try:
                    distinctInstance = strtobool(distinctInstance)
                except ValueError:
                    raise ParameterInvalidException("Service `%s` parameter `distinctInstance` must be bool" % (service_name))
                if distinctInstance:
                    env.append({"name": "DISTINCT_INSTANCE", "value": "true"})

            taskDefinitionTemplate = service_config.get("taskDefinitionTemplate")
            if taskDefinitionTemplate is None:
                raise ParameterNotFoundException("Service `%s` requires parameter `taskDefinitionTemplate`" % (service_name))
            service_task_definition_template = task_definition_template_dict.get(taskDefinitionTemplate)
            if service_task_definition_template is None or len(service_task_definition_template) == 0:
                raise Exception("'%s' taskDefinitionTemplate not found. " % service_name)
            if not isinstance(service_task_definition_template, str):
                raise Exception("'%s' taskDefinitionTemplate specified template value must be str. " % service_name)

            try:
                task_definition_data = render.render_template(service_task_definition_template, variables, task_definition_config_env)
            except jinja2.exceptions.UndefinedError as e:
                logger.error("Service `%s` jinja2 varibles Undefined Error." % service_name)
                raise
            try:
                task_definition = json.loads(task_definition_data)
            except json.decoder.JSONDecodeError as e:
                raise Exception("Service `{service}`: {e.__class__.__name__} {e}\njson:\n{json}".format(service=service_name, e=e, json=task_definition_data))

            # set parameters to docker environment
            for container_definitions in task_definition.get("containerDefinitions"):
                task_environment = container_definitions.get("environment")
                if task_environment is not None:
                    if not isinstance(task_environment, list):
                        raise Exception("'%s' taskDefinitionTemplate environment value must be list. " % service_name)
                    env.extend(task_environment)
                container_definitions["environment"] = env
            task_definition_list.append(task_definition)
        service_list = Service._import_service_from_task_definitions(task_definition_list)

        deploy_service_list = Service._deploy_service_list(service_list, deploy_service_group, template_group)
        return service_list, deploy_service_list, environment

    @staticmethod
    def _get_service_list_json(task_definition_template_dir, task_definition_config_json, task_definition_config_env, deploy_service_group, template_group):
        service_list = []

        task_definition_config = json.load(task_definition_config_json)
        environment = task_definition_config['environment']
        files = os.listdir(task_definition_template_dir)
        for file in files:
            file_path = os.path.join(task_definition_template_dir, file)
            try:
                with open(file_path, 'r') as template:
                    task_definitions_data = render.render_template(template.read(), task_definition_config, task_definition_config_env)
            except Exception as e:
                raise Exception("Template error. file: %s\n%s" % (file, e))
            try:
                task_definitions = json.loads(task_definitions_data)
            except json.decoder.JSONDecodeError as e:
                raise Exception("Service `{service}`: {e.__class__.__name__} {e}\njson:\n{json}".format(service=service_name, e=e, json=task_definitions_data))
            service_list.extend(Service._import_service_from_task_definitions(task_definitions))

        deploy_service_list = Service._deploy_service_list(service_list, deploy_service_group, template_group)
        return service_list, deploy_service_list, environment

    @staticmethod
    def _deploy_service_list(service_list, deploy_service_group, template_group):
        if deploy_service_group:
            deploy_service_list = list(filter(lambda service:service.task_environment.service_group == deploy_service_group, service_list))
        else:
            deploy_service_list = service_list

        if template_group:
            deploy_service_list = list(filter(lambda service:service.task_environment.template_group == template_group, deploy_service_list))
        if len(deploy_service_list) == 0:
            raise Exception("Deployment target service not found.")

        return deploy_service_list

class EcsUtils(object):
    @staticmethod
    def register_task_definition(awsutils, task_definition):
        retryCount = 0
        while True:
            try:
                response = awsutils.register_task_definition(task_definition=task_definition)
            except botocore.exceptions.ClientError as e:
                error_code = e.response['Error']['Code']
                if error_code == 'ThrottlingException':
                    if retryCount > 6:
                        raise
                    retryCount = retryCount + 1
                    time.sleep(10)
                    continue
                else:
                    raise
            break
        return response.get('taskDefinition').get('taskDefinitionArn')

    @staticmethod
    def wait_for_stable(awsutils, service):
        retryCount = 0
        while True:
            try:
                res_service = awsutils.wait_for_stable(cluster=service.task_environment.cluster_name, service=service.service_name)
            except botocore.exceptions.WaiterError:
                if retryCount > 2:
                    raise
                retryCount = retryCount + 1
                continue
            break
        service.running_count = res_service.get('runningCount')
        service.desired_count = res_service.get('desiredCount')

    @staticmethod
    def deregister_task_definition(awsutils, service):
        retryCount = 0
        while True:
            try:
                awsutils.deregister_task_definition(service.original_task_definition_arn)
            except botocore.exceptions.ClientError as e:
                error_code = e.response['Error']['Code']
                if error_code == 'ThrottlingException':
                    if retryCount > 3:
                        raise
                    retryCount = retryCount + 1
                    time.sleep(3)
                    continue
                else:
                   raise
            break

    @staticmethod
    def check_container_definition(a, b):
        ad = adjust_container_definition(a)
        bd = adjust_container_definition(b)
        if is_same_container_definition(ad, bd):
            return "    - Container Definition is not changed."
        else:
            t = diff(ad, bd)
            return "    - Container is changed. Diff:\n%s" % (t)

def is_same_container_definition(a, b):
    if not len(a) == len(b):
        return False
    for i in range(len(a)):
        if not compare_container_definitions(a[i], b[i]):
            return False
    return True

def adjust_container_definition(definition):
    for d in definition:
        remove_keys = []
        for k, v in d.items():
            if isinstance(v, list):
                if len(v) == 0:
                    remove_keys.append(k)
                if k == 'environment':
                    d[k] = sorted(v, key=lambda k: k['name'])

        for k in remove_keys:
            d.pop(k)
    return definition

def compare_container_definitions(a, b):
    seta = set(a.keys())
    setb = set(b.keys())
    if len(seta.difference(setb)) > 0:
       return False
    elif len(setb.difference(seta)) > 0:
       return False
    for k, v in a.items():
        if isinstance(v, dict):
            if not compare_container_definitions(v, b.get(k)):
                return False
        elif isinstance(v, list):
            if not v == b.get(k):
               return False
        elif not v == b.get(k):
            return False
    return True
