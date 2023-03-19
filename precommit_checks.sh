#!/bin/bash -e

# pip3 install kubernetes-typed[client] types-requests types-Flask

set -x

black */*.py

mypy --strict frontend/*.py
mypy --strict backend/*.py
mypy --strict toolbox/*.py

echo "All good :-)"

#EOF