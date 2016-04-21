# coding: utf-8
from __future__ import unicode_literals
import json
import os

import jinja2
import jinja2.loaders

from boto3 import Session

class ServiceNotFoundException(Exception):
    def __init__(self, value):
        self.value = value
    def __str__(self):
        return repr(self.value)

class FilePathLoader(jinja2.BaseLoader):
    """ Custom Jinja2 template loader which just loads a single template file """

    def __init__(self, cwd, encoding='utf-8'):
        self.cwd = cwd
        self.encoding = encoding

    def get_source(self, environment, template):
        # Path
        filename = os.path.join(self.cwd, template)

        # Read
        try:
            with open(template, 'r') as f:
                contents = f.read().decode(self.encoding)
        except IOError:
            raise jinja2.TemplateNotFound(template)

        # Finish
        uptodate = lambda: False
        return contents, filename, uptodate

def parse_env(data_string):
    # Parse
    if isinstance(data_string, basestring):
        data = filter(
            lambda l: len(l) == 2 ,
            (
                map(
                    str.strip,
                    line.split('=')
                )
                for line in data_string.split("\n"))
        )
    else:
        data = data_string

    # Finish
    return data

def render_template(cwd, template_path, context):
    """ Render a template
    :param template_path: Path to the template file
    :type template_path: basestring
    :param context: Template data
    :type context: dict
    :return: Rendered template
    :rtype: basestring
    """
    env = jinja2.Environment(
        loader=FilePathLoader(cwd),
        undefined=jinja2.StrictUndefined # raises errors for undefined variables
    )

    return env \
        .get_template(template_path) \
        .render(context) \
        .encode('utf-8')


class ECSService(object):
    def __init__(self, access_key, secret_key, region='us-east-1'):
        session = Session(aws_access_key_id=access_key, aws_secret_access_key=secret_key, region_name=region)
        self.client = session.client('ecs')

    def describe_cluster(self, cluster):
        """
        Describe the cluster or raise an Exception if cluster does not exists
        :param cluster: the cluster name
        :return: the response or raise an Exception
        """
        response = self.client.describe_clusters(clusters=[cluster])
        failures = response.get('failures')
        if failures:
            raise Exception("Cluster '%s' is %s" % (cluster, failures[0].get('reason')))
        return response

    def describe_service(self, cluster, service):
        """
        Describe the specified service or raise an Exception if service does not exists in cluster
        :param cluster: the cluster name
        :param service: the service name
        :return: the response or raise an Exception
        """
        response = self.client.describe_services(cluster=cluster, services=[service])
        failures = response.get('failures')
        if failures:
            raise ServiceNotFoundException("Service '%s' is %s in cluster '%s'" % (service, failures[0].get('reason'), cluster))
        return response

    def create_service(self, cluster, service, taskDefinition, desiredCount, maximumPercent, minimumHealthyPercent):
        """
        Create service
        :param cluster: the cluster name
        :param service: the service name
        :param taskDefinition: taskDefinition
        :param desiredCount: desiredCount
        :param maximumPercent: maximumPercent
        :param minimumHealthyPercent: minimumHealthyPercent
        :return: the response or raise an Exception
        """
        response = self.client.create_service(
            cluster=cluster,
            serviceName=service,
            taskDefinition=taskDefinition,
            desiredCount=desiredCount,
            deploymentConfiguration={
                'maximumPercent': maximumPercent,
                'minimumHealthyPercent': minimumHealthyPercent
            }
        )
        failures = response.get('failures')
        if failures:
            raise Exception("Service '%s' is %s in cluster '%s'" % (service, failures[0].get('reason'), cluster))

        # Waiting for the service update is done
        waiter = self.client.get_waiter('services_stable')
        waiter.wait(cluster=cluster, services=[service])
        return self.describe_service(cluster=cluster, service=service)

    def register_task_definition(self, family, file, template, template_json, template_env):
        """
        Register the task definition contained in the file
        :param family: the task definition name
        :param file: the task definition content file
        :param template: the task definition template
        :param template_json: the task definition template json
        :param template_env: the task definition template env
        :return: the response or raise an Exception
        """
        if file:
            if os.path.isfile(file) is False:
                raise IOError('The task definition file does not exist')

            with open(file, 'r') as content_file:
                container_definitions = json.loads(content_file.read())
        elif template:
            context = {}
            if os.path.isfile(template) is False:
                raise IOError('The task definition template does not exist')
            elif template_json:
                if os.path.isfile(template_json) is False:
                    raise IOError('The task definition json does not exist')
                else:
                    with open(template_json, 'r') as template_json_data:
                        context.update(json.load(template_json_data))
            if template_env:
                context.update(parse_env(os.environ))
            print(context)

            # Render
            render_definition = render_template(os.getcwd(), template, context)

            container_definitions = json.loads(render_definition)
        else:
            raise Exception('The task definition does not exist')

        response = self.client.register_task_definition(family=family, containerDefinitions=container_definitions)
        task_definition = response.get('taskDefinition')
        if task_definition.get('status') is 'INACTIVE':
            arn = task_definition.get('taskDefinitionArn')
            raise Exception('Task definition (%s) is inactive' % arn)
        return response

    def downscale_service(self, cluster, service, delta=1):
        """
        Downscale a service
        :param cluster: the cluster name
        :param service: the service name
        :param delta: Number of tasks to shutdown relatively to the running tasks (1 by default)
        :return: the response or raise an Exception
        """
        response = self.describe_service(cluster=cluster, service=service)
        running_count = (response.get('services')[0]).get('runningCount')
        task_definition = (response.get('services')[0]).get('taskDefinition')
        desired_count = running_count - delta
        return self.update_service(cluster=cluster, service=service, taskDefinition=task_definition,
                                   desiredCount=desired_count)

    def upscale_service(self, cluster, service, delta=1):
        """
        Upscale a service
        :param cluster: the cluster name
        :param service: the service name
        :param delta: Number of tasks to start relatively to the running tasks (1 by default)
        :return: the response or raise an Exception
        """
        response = self.describe_service(cluster=cluster, service=service)
        running_count = (response.get('services')[0]).get('runningCount')
        task_definition = (response.get('services')[0]).get('taskDefinition')
        desired_count = running_count + delta
        return self.update_service(cluster=cluster, service=service, taskDefinition=task_definition,
                                   desiredCount=desired_count)

    def update_service(self, cluster, service, taskDefinition, desiredCount=None):
        """
        Update the service with the task definition
        :param cluster: the cluster name
        :param service: the service name
        :param taskDefinition: the task definition
        :param delta: Number of tasks to start/shutdown relatively to the running tasks
        :return: the response or raise an Exception
        """
        if desiredCount is None:
            self.client.update_service(cluster=cluster, service=service, taskDefinition=taskDefinition)
        else:
            self.client.update_service(cluster=cluster, service=service, taskDefinition=taskDefinition,
                                   desiredCount=desiredCount)

        # Waiting for the service update is done
        waiter = self.client.get_waiter('services_stable')
        waiter.wait(cluster=cluster, services=[service])
        return self.describe_service(cluster=cluster, service=service)

    def run_task(self, cluster, family):
        """
        run the task
        :param cluster: the cluster name
        :param family: the task definition name
        :return: the response or raise an Exception
        """
        response = self.client.run_task(cluster=cluster, taskDefinition=family)

        failures = response.get('failures')
        if failures:
            raise Exception('Task %s failed: %s' % (failures[0].get('arn'), failures[0].get('reason')))

        taskArn = (response.get('tasks')[0]).get('taskArn')
        waiter = self.client.get_waiter('tasks_stopped')
        waiter.wait(cluster=cluster, tasks=[taskArn])

        response = self.client.describe_tasks(cluster=cluster, tasks=[taskArn])

        failures = response.get('failures')
        if failures:
            raise Exception('Can\'t retreive task %s description: %s' % (failures[0].get('arn'), failures[0].get('reason')))

        task = response.get('tasks')[0]
        container = task.get('containers')[0]
        exitCode = container.get('exitCode')
        if exitCode != 0:
            raise Exception('Task %s return exit code %s: %s' % (task.get('arn'), exitCode, container.get('reason')))

        return response
