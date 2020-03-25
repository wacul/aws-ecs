# coding: utf-8
from boto3 import Session
from ecs.scheduled_tasks import ScheduledTask
from botocore.exceptions import ClientError
from time import sleep


class ServiceNotFoundException(Exception):
    pass


class CloudwatchEventRuleNotFoundException(Exception):
    pass


class TaskDefinitionNotFoundException(Exception):
    pass


class AwsUtils(object):
    def __init__(self, access_key, secret_key, region='us-east-1'):
        session = Session(aws_access_key_id=access_key, aws_secret_access_key=secret_key, region_name=region)
        self.client = session.client('ecs')
        self.cloudwatch_event = session.client('events')
        self.aws_lambda = session.client('lambda')

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
        response = self.client.describe_task_definition(taskDefinition=name)
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
            raise ServiceNotFoundException("Service '{service}' failure in cluster '{cluster}'.\nfailures:{failures}"
                                           .format(service=service, failures=failures, cluster=cluster))
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
        :param service_list: 
        :param cluster: the cluster name
        :return: the response or raise an Exception
        """
        result = {"services": [], "failures": []}
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
        if not isinstance(services, list):
            return []
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
            if len(active_dup_services) > 1:
                services.append(active_dup_services[0])
            else:
                services.append(inactive_dup_services[0])
        return services

    def create_service(self, cluster, service, task_definition, desired_count,
                       maximum_percent, minimum_healthy_percent, distinct_instance, placement_strategy, placement_constraints, load_balancers):
        """
        Create service
        :param cluster: the cluster name
        :param service: the service name
        :param task_definition: taskDefinition
        :param desired_count: desiredCount
        :param maximum_percent: maximumPercent
        :param minimum_healthy_percent: minimumHealthyPercent
        :param distinct_instance: placementConstraints distictInstance
        :param placement_strategy: placementStrategy
        :param placement_constraints: placementConstraints
        :param load_balancers: list LoadBalancers
        :return: the response or raise an Exception
        """
        parameters = {
            "cluster": cluster,
            "serviceName": service,
            "taskDefinition": task_definition,
            "desiredCount": desired_count,
            "deploymentConfiguration": {
                "maximumPercent": maximum_percent,
                "minimumHealthyPercent": minimum_healthy_percent
             }
        }
        if distinct_instance:
            parameters.update(
                {'placementConstraints': [{'type': 'distinctInstance'}]}
            )
        if placement_constraints:
            if parameters.get('placementConstraints') is not None:
                parameters['placementConstraints'].append(placement_constraints)
            else:
                parameters.update({'placementConstraints': placement_constraints})
        if placement_strategy:
            parameters.update({'placementStrategy': placement_strategy})
        if load_balancers:
            parameters.update({'loadBalancers': load_balancers})

        response = self.client.create_service(**parameters)
        failures = response.get('failures')
        if failures:
            raise Exception("Service '{service}' is {failures} in cluster '{cluster}'"
                            .format(service=service, failures=failures, cluster=cluster))

        return response['service']

    def register_task_definition(self, task_definition):
        """
        Register the task definition contained in the file
        :param task_definition: the task definition
        :return: the response or raise an Exception
        """
        family = task_definition.get('family')
        container_definitions = task_definition.get('containerDefinitions')
        volumes = task_definition.get('volumes', [])
        network_mode = task_definition.get('networkMode', None)
        task_role_arn = task_definition.get('taskRoleArn', None)
        if network_mode is not None and task_role_arn is not None:
            response = self.client.register_task_definition(
                family=family,
                containerDefinitions=container_definitions,
                volumes=volumes,
                networkMode=network_mode,
                taskRoleArn=task_role_arn
            )
        elif network_mode is not None:
            response = self.client.register_task_definition(
                family=family, containerDefinitions=container_definitions, volumes=volumes, networkMode=network_mode
            )
        elif task_role_arn is not None:
            response = self.client.register_task_definition(
                family=family, containerDefinitions=container_definitions, volumes=volumes, taskRoleArn=task_role_arn
            )
        else:
            response = self.client.register_task_definition(
                family=family, containerDefinitions=container_definitions, volumes=volumes
            )
        task_definition = response.get('taskDefinition')
        if task_definition.get('status') == 'INACTIVE':
            arn = task_definition.get('taskDefinitionArn')
            raise Exception('Task definition (%s) is inactive' % arn)
        return task_definition

    def deregister_task_definition(self, task_definition):
        return self.client.deregister_task_definition(taskDefinition=task_definition)

    def update_service(
            self, cluster, service, task_definition=None,
            maximum_percent=None, minimum_healthy_percent=None, desired_count=None, force_new_deployment=True
    ):
        parameters = {
            'cluster': cluster,
            'service': service
        }
        if force_new_deployment:
            parameters.update({'forceNewDeployment': True})
        if desired_count is not None:
            parameters.update({'desiredCount': desired_count})
        if task_definition is not None:
            parameters.update({'taskDefinition': task_definition})
        if maximum_percent is not None and minimum_healthy_percent is not None:
            parameters.update(
                {
                    'deploymentConfiguration': {
                        'maximumPercent': maximum_percent,
                        'minimumHealthyPercent': minimum_healthy_percent
                    }
                }
            )
        retry = 0
        while True:
            try:
                self.client.update_service(**parameters)
                break
            except ClientError as e:
                if e.response['Error']['Code'] == 'ThrottlingException':
                    if retry > 5:
                        raise e
                    sleep(3)
                    retry += 1
                    continue
                else:
                    raise e
        return self.describe_service(cluster=cluster, service=service)

    def wait_for_stable(self, cluster_name: str, service_name: str, delay: int, max_attempts: int):
        # Waiting for the service update is done
        waiter = self.client.get_waiter('services_stable')
        waiter.wait(
            cluster=cluster_name,
            services=[service_name],
            WaiterConfig={
                'Delay': delay,
                'MaxAttempts': max_attempts
            }
        )
        return self.describe_service(cluster=cluster_name, service=service_name)

    def create_scheduled_task(self, scheduled_task: ScheduledTask, description: str):
        res_p = self.cloudwatch_event.put_rule(
            Name=scheduled_task.family,
            ScheduleExpression=scheduled_task.schedule_expression,
            Description=description,
            State=scheduled_task.state.value
        )
        event_arn = res_p['RuleArn']
        targets = [{'Id': scheduled_task.name, 'Arn': scheduled_task.target_lambda_arn}]
        self.cloudwatch_event.put_targets(Rule=scheduled_task.name, Targets=targets)
        try:
            self.aws_lambda.add_permission(
                FunctionName=scheduled_task.target_lambda_arn,
                StatementId=scheduled_task.family,
                Action="lambda:*",
                Principal="events.amazonaws.com",
                SourceArn=event_arn
            )
        except ClientError as e:
            if e.response['Error']['Code'] == 'ResourceConflictException':
                pass
            else:
                raise

    def list_cloudwatch_event_rules(self) -> list:
        response = self.cloudwatch_event.list_rules()
        cloud_watch_event_rules = response['Rules']
        while 'nextToken' in response:
            response = self.cloudwatch_event.list_rules(nextToken=response['nextToken'])
            cloud_watch_event_rules.extend(response['Rules'])
        return cloud_watch_event_rules

    def delete_scheduled_task(self, name: str, target_arn: str):
        try:
            self.aws_lambda.remove_permission(
                FunctionName=target_arn,
                StatementId=name
            )
        except ClientError as e:
            if e.response['Error']['Code'] == 'ResourceNotFoundException':
                pass
            else:
                raise
        self.cloudwatch_event.remove_targets(Rule=name, Ids=[name])
        self.cloudwatch_event.delete_rule(Name=name)

    def describe_rule(self, name: str) -> dict:
        try:
            response = self.cloudwatch_event.describe_rule(Name=name)
        except ClientError as e:
            if e.response['Error']['Code'] == 'ResourceNotFoundException':
                raise CloudwatchEventRuleNotFoundException()
            else:
                raise
        return response

    def disable_rule(self, name: str):
        self.cloudwatch_event.disable_rule(Name=name)

    def list_running_tasks(self, cluster: str, family: str) -> list:
        response = self.client.list_tasks(cluster=cluster, family=family, desiredStatus='RUNNING')

        failures = response.get('failures')
        if failures:
            raise Exception('list_tasks failre. description: {failures}'.format(failures=failures))

        return response.get('taskArns')

    def stop_task(self, cluster: str, task_arn: str):
        self.client.stop_task(cluster=cluster, task=task_arn, reason='aws ecs deploy')

    def wait_for_task_stopped(self, cluster: str, tasks: list):
        # Waiting for the service update is done
        waiter = self.client.get_waiter('tasks_stopped')
        waiter.wait(cluster=cluster, tasks=tasks)

    def list_clusters(self) -> list:
        response = self.client.list_clusters()
        cluster_arns = response['clusterArns']
        while 'nextToken' in response:
            response = self.client.list_rules(nextToken=response['nextToken'])
            cluster_arns.extend(response['clusterArns'])
        return cluster_arns
