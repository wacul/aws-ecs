# coding: utf-8
from boto3 import Session
from botocore.exceptions import WaiterError, ClientError

class ServiceNotFoundException(Exception):
    pass

class AwsUtils(object):
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

    def describe_task_definition(self, name):
        try:
            response = self.client.describe_task_definition(taskDefinition=name)
        except ClientError as e:
            return None
        return response.get('taskDefinition')

    def delete_service(self, cluster, service_name):
        self.client.update_service(cluster=cluster, service=service_name, desiredCount=0)
        waiter = self.client.get_waiter('services_stable')
        waiter.wait(cluster=cluster, services=[service_name])

        self.client.delete_service(cluster=cluster, service=service_name)

    def list_services(self, cluster):
        response = self.client.list_services(cluster=cluster, maxResults=10)
        service_arn_list = response['serviceArns']
        while 'nextToken' in response:
            response = self.client.list_services(cluster=cluster, maxResults=10, nextToken=response['nextToken'])
            service_arn_list.extend(response['serviceArns'])
        return service_arn_list

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
        res_services = response['services']
        # 複数同名のサービスが見つかったら、ACTIVEを返しておく
        if len(res_services) > 1:
            for res_s in res_services:
                if res_s.get['status'] == 'ACTIVE':
                    return res_s
        return res_services[0]

    def describe_services(self, cluster, service_list):
        """
        Describe the specified service or raise an Exception if service does not exists in cluster
        :param cluster: the cluster name
        :param service: the service names
        :return: the response or raise an Exception
        """
        result = { "services": [], "failures": [] }
        while len(service_list) > 0:
            response = self.client.describe_services(cluster=cluster, services=service_list[:10])
            if len(response['services']) > 0:
                result['services'].extend(response['services'])
            if len(response['failures']) > 0:
                result['failures'].extend(response['failures'])
            
            service_list = service_list[10:]

            failures = response.get('failures')

        # リストからサービス詳細が取れなければエラーにしてしまう
        if len(failures) > 0:
            message = "describe_service failure."
            for failure in failures:
                message = message + "\nservice: %s, reson: %s" % (failure.get('arn'), failure.get('reason'))
            raise ServiceNotFoundException("message")
        services = result.get('services')

        # 重複チェック
        t = set()
        dup_service_names = [x for x in services if x["serviceName"] in t or t.add(x["serviceName"])]
        dup_services = []
        for d in dup_service_names:
            dup_services.extend([x for x in services if x["serviceName"] == d])
        if len(dup_services) > 0:
            # 重複があれば一旦リストから外す
            services = list(filter(lambda x: x["serviceName"] == d, services))

            # 重複したものがあればACTIVEのみ取り出す。どちらも違うなら取得順
            active_dup_services = [x for x in dup_services if x["status"] == 'ACTIVE']
            inactive_dup_services = [x for x in dup_services if x["status"] != 'ACTIVE']
            if len(active_services) > 1:
                services.append(active_service[0])
            else:
                services.append(inactive_service[0])
        return services

    def create_service(self, cluster, service, taskDefinition, desiredCount, maximumPercent, minimumHealthyPercent, distinctInstance):
        """
        Create service
        :param cluster: the cluster name
        :param service: the service name
        :param taskDefinition: taskDefinition
        :param desiredCount: desiredCount
        :param maximumPercent: maximumPercent
        :param minimumHealthyPercent: minimumHealthyPercent
        :param distinctInstance: placementConstraints distictInstance
        :return: the response or raise an Exception
        """
        if distinctInstance:
            response = self.client.create_service(
                cluster=cluster,
                serviceName=service,
                taskDefinition=taskDefinition,
                desiredCount=desiredCount,
                deploymentConfiguration={
                    'maximumPercent': maximumPercent,
                    'minimumHealthyPercent': minimumHealthyPercent
                },
                placementConstraints=[
                    {
                        'type': 'distinctInstance'
                    }
                ]
            )
        else:
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

        return self.describe_service(cluster=cluster, service=service)

    def register_task_definition(self, task_definition):
        """
        Register the task definition contained in the file
        :param task_definition: the task definition
        :return: the response or raise an Exception
        """
        family=task_definition.get('family')
        containerDefinitions=task_definition.get('containerDefinitions')
        volumes=task_definition.get('volumes', [])
        networkMode=task_definition.get('networkMode', None)
        taskRoleArn=task_definition.get('taskRoleArn', None)
        if networkMode is not None and taskRoleArn is not None:
            response = self.client.register_task_definition(family=family, containerDefinitions=containerDefinitions, volumes=volumes, networkMode=networkMode, taskRoleArn=taskRoleArn)
        elif networkMode is not None:
            response = self.client.register_task_definition(family=family, containerDefinitions=containerDefinitions, volumes=volumes, networkMode=networkMode)
        elif taskRoleArn is not None:
            response = self.client.register_task_definition(family=family, containerDefinitions=containerDefinitions, volumes=volumes, taskRoleArn=taskRoleArn)
        else:
            response = self.client.register_task_definition(family=family, containerDefinitions=containerDefinitions, volumes=volumes)
        task_definition = response.get('taskDefinition')
        if task_definition.get('status') is 'INACTIVE':
            arn = task_definition.get('taskDefinitionArn')
            raise Exception('Task definition (%s) is inactive' % arn)
        return response

    def deregister_task_definition(self, taskDefinition):
        return self.client.deregister_task_definition(taskDefinition=taskDefinition)

    def downscale_service(self, cluster, service, maximumPercent, minimumHealthyPercent, delta=1):
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
        return self.update_service(cluster=cluster, service=service, taskDefinition=task_definition, desiredCount=desired_count, maximumPercent=maximumPercent, minimumHealthyPercent=minimumHealthyPercent)

    def upscale_service(self, cluster, service, maximumPercent, minimumHealthyPercent, delta=1):
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
        return self.update_service(cluster=cluster, service=service, taskDefinition=task_definition, desiredCount=desired_count, maximumPercent=maximumPercent, minimumHealthyPercent=minimumHealthyPercent)

    def update_service(self, cluster, service, taskDefinition, maximumPercent, minimumHealthyPercent, desiredCount=None):
        """
        Update the service with the task definition
        :param cluster: the cluster name
        :param service: the service name
        :param taskDefinition: the task definition
        :param delta: Number of tasks to start/shutdown relatively to the running tasks
        :return: the response or raise an Exception
        """
        if desiredCount is None:
            self.client.update_service(cluster=cluster, service=service, taskDefinition=taskDefinition,
                deploymentConfiguration={
                    'maximumPercent': maximumPercent,
                    'minimumHealthyPercent': minimumHealthyPercent
                })
        else:
            self.client.update_service(cluster=cluster, service=service, taskDefinition=taskDefinition,
                deploymentConfiguration={
                    'maximumPercent': maximumPercent,
                    'minimumHealthyPercent': minimumHealthyPercent
                },
                desiredCount=desiredCount)

        return self.describe_service(cluster=cluster, service=service)

    def wait_for_stable(self, cluster, service):
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
        return taskArn

    def describe_task(self, cluster, taskArn):
        response = self.client.describe_tasks(cluster=cluster, tasks=[taskArn])

        failures = response.get('failures')
        if failures:
            raise Exception('Can\'t retreive task %s description: %s' % (failures[0].get('arn'), failures[0].get('reason')))

        return response.get('tasks')[0]
