# coding: utf-8
import logging
import yaml
import render

logger = logging.getLogger(__name__)


def h1(x): print("\033[1m\033[4m\033[94m{x}\033[0m\n".format(x=x))


def h2(x): print("\033[1m\033[4m{x}\033[0m\n".format(x=x))


def success(x): print("\033[92m* {x}\033[0m\n".format(x=x))


def error(x): print("\033[91mx {x}\033[0m\n".format(x=x))


def info(x): print("  {x}\n".format(x=x))


def is_same_container_definition(a: dict, b: dict) -> bool:
    if not len(a) == len(b):
        return False
    for i in range(len(a)):
        if not compare_container_definitions(a[i], b[i]):
            return False
    return True


def adjust_container_definition(definition: dict):
    for d in definition:
        remove_keys = []
        for k, v in d.items():
            if isinstance(v, list):
                if len(v) == 0:
                    remove_keys.append(k)
                if k == 'environment':
                    d[k] = sorted(v, key=lambda x: x['name'])

        for k in remove_keys:
            d.pop(k)
    return definition


def compare_container_definitions(a: dict, b: dict) -> bool:
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


def get_variables(deploy_name: str, name: str, base_service_config: dict, environment_config: dict, is_task_definition_config_env: bool):
    variables = {"item": name}
    service_config = {}
    # ベースの値を取得
    variables.update(base_service_config)
    service_config.update(base_service_config)
    # ベースのvars
    base_vars = base_service_config.get("vars")
    if base_vars:
        variables.update(base_vars)
    # 各環境の設定値を取得
    variables.update(environment_config)
    # 各環境の設定を取得
    environment_config_services = environment_config.get(deploy_name)
    if environment_config_services:
        environment_service = environment_config_services.get(name)
        if environment_service:
            variables.update(environment_service)
            service_config.update(environment_service)
            environment_vars = environment_service.get("vars")
            if environment_vars:
                variables.update(environment_vars)
    # varsをrenderする
    vars_renderd = render.render_template(yaml.dump(variables), variables, is_task_definition_config_env)
    variables.update(yaml.load(vars_renderd))
    return service_config, variables

    