# coding: utf-8
import logging

logger = logging.getLogger(__name__)


def h1(x): print(f"\033[1m\033[4m\033[94m{x}\033[0m\n")


def success(x): print(f"\033[92m* {x}\033[0m\n")


def error(x): print(f"\033[91mx {x}\033[0m\n")


def info(x): print(f"  {x}\n")


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
