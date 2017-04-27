# coding: utf-8
import sys, os, time, traceback, logging
import render
from enum import Enum
from distutils.util import strtobool
from botocore.exceptions import WaiterError, ClientError


logging.basicConfig(stream=sys.stdout, level=logging.INFO, format='%(message)s')
logging.getLogger("botocore").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)
h1 = lambda x: logger.info("\033[1m\033[4m\033[94m%s\033[0m\n" % x)
success = lambda x: logger.info("\033[92m* %s\033[0m\n" % x)
error = lambda x: logger.info("\033[91mx %s\033[0m\n" % x)
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


    @staticmethod
    def import_service_from_task_definitions(task_definitions):
        service_list = []
        for task_definition in task_definitions:
            service = Service(task_definition)
            service_list.append(service)
        return service_list

    @staticmethod
    def get_service_list(task_definition_template_dir, task_definition_config_json, task_definition_config_env, deploy_service_group, template_group):
        service_list = []

        files = os.listdir(task_definition_template_dir)
        for file in files:
            try:
                task_definitions = render.render_definition(task_definition_template_dir, file, task_definition_config_json, task_definition_config_env)
                service_list.extend(Service.import_service_from_task_definitions(task_definitions))
            except:
                error("Template error. file: %s.\n%s" % (file, traceback.format_exc()))
                sys.exit(1)

        if deploy_service_group:
            deploy_service_list = list(filter(lambda service:service.task_environment.service_group == deploy_service_group, service_list))
        else:
            deploy_service_list = service_list

        if template_group:
            deploy_service_list = list(filter(lambda service:service.task_environment.template_group == template_group, deploy_service_list))
        if len(deploy_service_list) == 0:
            error("Deployment target service is None.")
            sys.exit(1)

        return service_list, deploy_service_list

class EcsUtils(object):
    @staticmethod
    def register_task_definition(awsutils, task_definition):
        retryCount = 0
        while True:
            try:
                response = awsutils.register_task_definition(task_definition=task_definition)
            except ClientError as e:
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
                response = awsutils.wait_for_stable(cluster=service.task_environment.cluster_name, service=service.service_name)
            except WaiterError:
                if retryCount > 2:
                    raise
                retryCount = retryCount + 1
                continue
            break
        service.running_count = response.get('services')[0].get('runningCount')
        service.desired_count = response.get('services')[0].get('desiredCount')

    @staticmethod
    def deregister_task_definition(awsutils, service):
        retryCount = 0
        while True:
            try:
                awsutils.deregister_task_definition(service.original_task_definition)
            except ClientError as e:
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
    def check_task_definition(awsutils, task_definition_name):
        try:
            response = awsutils.describe_task_definition(task_definition_name)
        except ClientError as e:
            return None
        return response.get('taskDefinition')

    @staticmethod
    def is_same_task_definition(task_definition, latest_task_definition):
        if not len(task_definition.get('containerDefinitions')) == len(latest_task_definition.get('containerDefinitions')):
            return False
        for i in range(len(task_definition.get('containerDefinitions'))):
            if not compare(task_definition.get('containerDefinitions')[i], latest_task_definition.get('containerDefinitions')[i]):
                return False
        return True

def compare(a, b):
    for k, v in a.items():
        if isinstance(v, dict):
            if not compare(v, b.get(k)):
                return False
        if isinstance(v, list):
            if not v == b.get(k):
                return False
        if not v == b.get(k):
            return False
    return True
