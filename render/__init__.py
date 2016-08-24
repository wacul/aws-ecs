# coding: utf-8
import json
import os
import jinja2
import jinja2.loaders


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
        .render(context)


class FilePathLoader(jinja2.BaseLoader):
    """ Custom Jinja2 template loader which just loads a single template file """

    def __init__(self, cwd):
        self.cwd = cwd

    def get_source(self, environment, template):
        # Path
        filename = os.path.join(self.cwd, template)

        # Read
        try:
            with open(template, 'r') as f:
                contents = f.read()
        except IOError:
            raise jinja2.TemplateNotFound(template)

        # Finish
        uptodate = lambda: False
        return contents, filename, uptodate

def parse_env(data_string):
    # Parse
    if isinstance(data_string, str):
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


def load_json(config_json_file):
    if os.path.isfile(config_json_file):
        with open(config_json_file, 'r') as config_json_data:
            return json.load(config_json_data)

def render_definition(template_dir, template_file, config_json, is_env):
    context = {}
    context.update(config_json)
    if is_env:
        context.update(parse_env(os.environ))

    # Render
    render_definition = render_template(os.getcwd(), os.path.join(template_dir, template_file), context)
    return json.loads(render_definition)
