# author: Ole Schuett

from dataclasses import dataclass
from typing import List


# ======================================================================================
@dataclass
class RepositoryConfig:
    name: str
    targets_config: str
    required_checks: List[str]


# ======================================================================================

REPOSITORY_CONFIGS: List[RepositoryConfig] = [
    RepositoryConfig(
        name="cp2k",
        targets_config="/tools/docker/cp2k-ci.conf",
        required_checks=["precommit", "misc", "pdbg"],
    )
]


# ======================================================================================
def get_repository_config_by_name(name: str) -> RepositoryConfig:
    matches = [r for r in REPOSITORY_CONFIGS if r.name == name]
    assert len(matches) == 1
    return matches[0]


# EOF
