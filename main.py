# coding: utf-8
import logging
import sys
import argparse
import traceback
from multiprocessing import Process, Pool, Queue
from queue import Queue, Empty
from threading import Thread
from ecs.service import ServiceProcess, ServiceManager


logging.basicConfig(stream=sys.stdout, level=logging.INFO, format='%(message)s')
logging.getLogger("botocore").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)


# Arguments parsing
def init():
    parser = argparse.ArgumentParser(description='Deploy Service on ECS')
    parser.add_argument('--key', dest='key', default="")
    parser.add_argument('--secret', dest='secret', default="")
    parser.add_argument('--region', dest='region', default='us-east-1')
    parser.add_argument('--task-definition-template-dir', dest='task_definition_template_dir', required=True)
    parser.add_argument('--task-definition-config-json', dest='task_definition_config_json', required=True)
    parser.add_argument('--task-definition-config-env', dest='task_definition_config_env', default=True, action='store_true', required=False)
    parser.add_argument('--no-task-definition-config-env', dest='task_definition_config_env', default=True, action='store_false', required=False)
    parser.add_argument('--threads-count', type=int, default=10, required=False)
    parser.add_argument('--service-zero-keep', dest='service_zero_keep', default=True, action='store_true', required=False)
    parser.add_argument('--no-service-zero-keep', dest='service_zero_keep', default=True, action='store_false', required=False)
    parser.add_argument('--template-group', dest='template_group', required=False)
    parser.add_argument('--deploy-service-group', dest='deploy_service_group', required=False)
    parser.add_argument('--delete-unused-service', dest='delete_unused_service', default=True, action='store_true', required=False)
    parser.add_argument('--no-delete-unused-service', dest='delete_unused_service', default=True, action='store_false', required=False)
    subparser = parser.add_subparsers(dest='command')
    run_task_parser = subparser.add_parser("run-task")
    run_task_parser.add_argument('--task-definition-template-file', dest='task_definition_template_file', required=True)
    run_task_parser.add_argument('--key', dest='key', default="")
    run_task_parser.add_argument('--secret', dest='secret', default="")
    run_task_parser.add_argument('--region', dest='region', default='us-east-1')
    run_task_parser.add_argument('--task-definition-config-json', dest='task_definition_config_json', required=True)
    run_task_parser.add_argument('--task-definition-config-env', dest='task_definition_config_env', default=True, action='store_true', required=False)
    run_task_parser.add_argument('--no-task-definition-config-env', dest='task_definition_config_env', default=True, action='store_false', required=False)
    return parser.parse_args()

if __name__ == '__main__':
    args = init()
    if args.command == 'run_task':
        print("run_task")
    else:
        service_manager = ServiceManager(args)
        service_manager.run()
