import enum


class ProcessMode(enum.Enum):
    deployService = 0
    checkDeployService = 1
    runTask = 6
    waitForStable = 7
    checkServiceAndTask = 8


class ProcessStatus(enum.Enum):
    normal = 0
    error = 1


class DeployTargetType(enum.Enum):
    service = 0
    service_describe = 1
    task = 2


class Deploy(object):
    def __init__(self, name, target_type):
        self.name = name
        self.status = ProcessStatus.normal
        self.target_type = target_type


class ParameterNotFoundException(Exception):
    pass


class ParameterInvalidException(Exception):
    pass


class VariableNotFoundException(Exception):
    pass


class EnvironmentValueNotFoundException(Exception):
    pass
