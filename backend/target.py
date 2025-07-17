# author: Ole Schuett

from typing import Any, List

import configparser

from repository_config import RepositoryConfig


# ======================================================================================
class TargetName(str):
    pass


# ======================================================================================
class Target:
    def __init__(
        self,
        repo_conf: RepositoryConfig,
        config: configparser.ConfigParser,
        section: str,
    ):
        self.repository = repo_conf.name
        self.name = TargetName(f"{repo_conf.name}-{section}")
        self.is_required_check = section in repo_conf.required_checks

        # mandatory fields
        self.display_name = config.get(section, "display_name")
        self.cpu = config.getfloat(section, "cpu")
        self.nodepools = config.get(section, "nodepools").split()

        # optional fields
        self.trigger_path = config.get(section, "trigger_path", fallback="")
        self.gpu = config.getint(section, "gpu", fallback=0)
        self.dockerfile = config.get(section, "dockerfile", fallback="")
        self.build_path = config.get(section, "build_path", fallback="")
        self.arch = config.get(section, "arch", fallback="x86")
        self.build_args = config.get(section, "build_args", fallback="")
        self.remote_host = config.get(section, "remote_host", fallback="")
        self.remote_cmd = config.get(section, "remote_cmd", fallback="")
        self.cscs_pipeline = config.get(section, "cscs_pipeline", fallback="")
        self.tags = config.get(section, "tags", fallback="").split()

        cache_from_section = config.get(section, "cache_from", fallback="")
        if cache_from_section:
            self.cache_from = TargetName(f"{repo_conf.name}-{cache_from_section}")
        else:
            self.cache_from = TargetName("")

        if config.has_option(section, "remote_host"):
            self.runner = "remote"
        elif config.has_option(section, "cscs_pipeline"):
            self.runner = "cscs"
        else:
            self.runner = "local"


# ======================================================================================
def parse_target_config(
    repo_conf: RepositoryConfig, target_config_content: bytes
) -> List[Target]:
    config = configparser.ConfigParser()
    config.read_string(target_config_content.decode("utf8"))
    targets: List[Target] = []
    for section in config.sections():
        targets.append(Target(repo_conf, config, section))
    return targets


# EOF
