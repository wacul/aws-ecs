# coding: utf-8
import logging
import sys
import argparse
import traceback
from multiprocessing import Process, Pool, Queue
from queue import Queue, Empty
from threading import Thread
from ecs.service import ServiceProcess, ServiceManager
from ecs.runtask import RunTask


logging.basicConfig(stream=sys.stdout, level=logging.INFO, format='%(message)s')
logging.getLogger("botocore").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)


def set_default_subparser(self, name, args=None):
    """default subparser selection. Call after setup, just before parse_args()
    name: is the name of the subparser to call by default
    args: if set is the argument list handed to parse_args()

    , tested with 2.7, 3.2, 3.3, 3.4
    it works with 2.6 assuming argparse is installed
    """
    subparser_found = False
    existing_default = False # check if default parser previously defined
    for arg in sys.argv[1:]:
        if arg in ['-h', '--help']:  # global help if no subparser
            break
    else:
        for x in self._subparsers._actions:
            if not isinstance(x, argparse._SubParsersAction):
                continue
            for sp_name in x._name_parser_map.keys():
                if sp_name in sys.argv[1:]:
                    subparser_found = True
                if sp_name == name: # check existance of default parser
                    existing_default = True
        if not subparser_found:
            # If the default subparser is not among the existing ones,
            # create a new parser.
            # As this is called just before 'parse_args', the default
            # parser created here will not pollute the help output.

            if not existing_default:
                for x in self._subparsers._actions:
                    if not isinstance(x, argparse._SubParsersAction):
                        continue
                    x.add_parser(name)
                    break # this works OK, but should I check further?

            # insert default in first position, this implies no
            # global options without a sub_parsers specified
            if args is None:
                sys.argv.insert(1, name)
            else:
                args.insert(0, name)

# Arguments parsing
def init():
    parser = argparse.ArgumentParser(description='Deploy Service on ECS')
    subparser = parser.add_subparsers(dest='command')
    service_parser = subparser.add_parser("service")
    service_parser.add_argument('--key', dest='key', default="")
    service_parser.add_argument('--secret', dest='secret', default="")
    service_parser.add_argument('--region', dest='region', default='us-east-1')
    service_parser.add_argument('--task-definition-template-dir', dest='task_definition_template_dir', required=True)
    service_parser.add_argument('--task-definition-config-json', dest='task_definition_config_json', required=True)
    service_parser.add_argument('--task-definition-config-env', dest='task_definition_config_env', default=True, action='store_true', required=False)
    service_parser.add_argument('--no-task-definition-config-env', dest='task_definition_config_env', default=True, action='store_false', required=False)
    service_parser.add_argument('--threads-count', type=int, default=10, required=False)
    service_parser.add_argument('--service-zero-keep', dest='service_zero_keep', default=True, action='store_true', required=False)
    service_parser.add_argument('--no-service-zero-keep', dest='service_zero_keep', default=True, action='store_false', required=False)
    service_parser.add_argument('--template-group', dest='template_group', required=False)
    service_parser.add_argument('--deploy-service-group', dest='deploy_service_group', required=False)
    service_parser.add_argument('--delete-unused-service', dest='delete_unused_service', default=True, action='store_true', required=False)
    service_parser.add_argument('--no-delete-unused-service', dest='delete_unused_service', default=True, action='store_false', required=False)
    runtask_parser = subparser.add_parser("runtask")
    runtask_parser.add_argument('--task-definition-template-file', dest='task_definition_template_file', required=True)
    runtask_parser.add_argument('--key', dest='key', default="")
    runtask_parser.add_argument('--secret', dest='secret', default="")
    runtask_parser.add_argument('--region', dest='region', default='us-east-1')
    runtask_parser.add_argument('--timeout', type=int, default=300)
    runtask_parser.add_argument('--cluster', default='default')
    runtask_parser.add_argument('--task-definition-config-json', dest='task_definition_config_json', required=True)
    runtask_parser.add_argument('--task-definition-config-env', dest='task_definition_config_env', default=True, action='store_true', required=False)
    runtask_parser.add_argument('--no-task-definition-config-env', dest='task_definition_config_env', default=True, action='store_false', required=False)
    argparse.ArgumentParser.set_default_subparser = set_default_subparser
    parser.set_default_subparser('service')
    return parser.parse_args()

if __name__ == '__main__':
    args = init()
    if args.command == 'runtask':
        run_task = RunTask(args)
        run_task.run()
    else:
        service_manager = ServiceManager(args)
        service_manager.run()
