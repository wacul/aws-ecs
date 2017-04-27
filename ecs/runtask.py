# coding: utf-8
import time, logging, sys, traceback
import render
from aws import AwsUtils
from ecs.classes import EcsUtils

logging.basicConfig(stream=sys.stdout, level=logging.INFO, format='%(message)s')
logging.getLogger("botocore").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)

class RunTask(object):
    def __init__(self, args):
        try:
            task_definition_config_json = render.load_json(args.task_definition_config_json)
            self.task_definition = render.render_definition("", args.task_definition_template_file, task_definition_config_json, args.task_definition_config_env)
        except:
            logger.error("Template error. file: %s.\n%s" % (args.task_definition_template_file, traceback.format_exc()))
            sys.exit(1)

        self.family = self.task_definition.get("family")
        self.awsutils = AwsUtils(access_key=args.key, secret_key=args.secret, region=args.region)
        self.cluster = args.cluster
        self.timeout = args.timeout
   

    def run(self):
        task_definition_arn = self.register_task_definition()
        # run
        task_arn = self.awsutils.run_task(self.cluster, task_definition_arn)
        # wait & check exit code
        self.wait_for_task(task_arn)

    def register_task_definition(self):
        latest_task_definition = EcsUtils.check_task_definition(self.awsutils, self.family)
        if not latest_task_definition:
            logger.info("Task Definition not found. Register new one.")
            task_definition_arn = EcsUtils.register_task_definition(self.awsutils, self.task_definition)
        else:
            if EcsUtils.is_same_task_definition(self.task_definition, latest_task_definition):
                logger.info("Task Definition is not changed.")
                task_definition_arn = latest_task_definition.get('taskDefinitionArn')
            else:
                logger.info("Task Definition is changed. Register new revision.")
                task_definition_arn = EcsUtils.register_task_definition(self.awsutils, self.task_definition)
        return task_definition_arn

    def wait_for_task(self, taskArn):
        check_interval = 15
        retry_count = self.timeout / check_interval
        while retry_count >= 0:
            task = self.awsutils.describe_task(self.cluster, taskArn)
            if task.get('lastStatus') == 'STOPPED':
                break
            retry_count = retry_count - 1
            if retry_count == 0:
                raise Exception('Task %s timed out' % (task.get('arn')))
            time.sleep(check_interval)
        container = task.get('containers')[0]
        exitCode = container.get('exitCode')
        if exitCode != 0:
            raise Exception('Task %s return exit code %s: %s' % (task.get('arn'), exitCode, container.get('reason')))
