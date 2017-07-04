# coding: utf-8
import os

import jinja2
import jinja2.loaders


def parse_env(data_string):
    # Parse
    if isinstance(data_string, str):
        data = filter(
            lambda l: len(l) == 2,
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


def render_template(template, config, is_env):
    context = {}
    context.update(config)
    if is_env:
        context.update(parse_env(os.environ))

    # raises errors for undefined variables
    env = jinja2.Environment(undefined=jinja2.StrictUndefined)
    rendered = env.from_string(template).render(context)
    return rendered
