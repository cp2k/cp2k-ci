# CP2K Continuous Integration

The CP2K-CI system is a custom solution to run our resource intensive integration tests in a swift and affordable manner. It is based on [Kubernetes](https://kubernetes.io/) and currently deployed on the [Google Cloud Platform](https://cloud.google.com) using [preemptible](https://cloud.google.com/compute/docs/instances/preemptible) virtual machines.

## Overview
The typical use case consists of the following steps:

1. User opens a pull request on Github.
2. Github sends webhook [events](https://developer.github.com/v3/activity/events/types/) to frontend.
3. Frontend places message into [Pub/Sub](https://cloud.google.com/pubsub/docs/) queue.
4. Backend receives Pub/Sub message and launches [Kubernetes jobs](https://kubernetes.io/docs/concepts/workloads/controllers/jobs-run-to-completion/).
5. Backend continuously monitors the jobs and updates their [status](https://developer.github.com/v3/checks/) in the Github UI.
6. The jobs upload their reports to [Cloud Storage](https://cloud.google.com/storage/) via [signed urls](https://cloud.google.com/storage/docs/access-control/signed-urls).
7. The user sees job summaries on Github and may download full reports from Cloud Storage.

## Configuration

The CP2K-CI is configured via the [cp2k-ci.conf](./backend/cp2k-ci.conf) file. The file has the format of the python [configparser](https://docs.python.org/3/library/configparser.html). Each section is refereed to as a _target_. Typical sections looks like this:
```
[cp2k-sdbg]
display_name: Regtest sdbg
repository:   cp2k
cpu:          32
nodepools:    pool-highcpu-32-haswell
tags:         required_check_run dashboard
related_path: Makefile|src|tests|exts|tools/(build_utils|regtesting|toolchain|docker)
build_path:   /tools/docker
dockerfile:   /tools/docker/Dockerfile.test_sdbg
```

The fields have the following meaning. All lists are white-space separated.


| Field        | Description                                                                                  |
| ------------ | ---------------------------------------------------------------------------------------------|
| [foo-bar]    | Internal name used e.g. in report url.                                                       |
| display_name | Visible name of check run.                                                                   |
| repository   | Name of repository below https://github.com/cp2k/ .                                          |
| cpu          | Number of CPUs to allocate for building and running.                                         |
| gpu          | Number of GPUs to allocate for building and running.                                         |
| nodepools    | List of eligible nodepools, [see also](setup/create_node_pools.sh).                          |
| tags         | Tags which determine when and how this target is build and run.                              |
| related_path | Regular expression matching relevant files.                                                  |
| build_args   | List of Docker build arguments.                                                              |
| build_path   | Path to build context within given repository.                                               |
| dockerfile   | Path to Dockerfile within given repository.                                                  |
| cache_from   | Optional name of target that should be used as additional cache source during the build.     |

Tags determine when and how a target is build and run.

| Tag                 | Description                                                                                  |
| ------------------- | -------------------------------------------------------------------------------------------- |
| required_check_run  | Automatically run this as check run for every pull request.                                  |
| optional_check_run  | Add this as an optional check run for every pull request.                                    |
| dashboard           | Run this target when the `submit_all_dashboard_tests` RPC is received.                       |


## Communication with Containers
The CP2K-CI communication with its container via a simple protocol. See the [ci_entrypoint.sh](https://github.com/cp2k/cp2k/blob/master/tools/docker/scripts/ci_entrypoint.sh) script for an example implementation.

The CP2K-CI passes as input the following environment variables to its containers:

| Environment Variable   | Description                                                                |
| ---------------------- | -------------------------------------------------------------------------- |
| `GIT_BRANCH`           | Git branch to test, e.g. `master` or `pull/42/merge`.                      |
| `GIT_REF`              | Git ref to test from given branch, typically the SHA of the latest commit. |

The container must output a report using the [dashboard format](https://www.cp2k.org/dev:dashboard).
Additionally, the container can make files available to the user by writting them to `/workspace/artifacts`.


## Implementation

The CP2K-CI system consists of three components. Each resides in its own sub directory and gets automatically deployed as a container by [Cloud Build](https://cloud.google.com/cloud-build/).

### Frontend
- Hosted on [Cloud Run](https://cloud.google.com/run/docs), reachable at https://ci.cp2k.org.
- Runs a simple [Flask](http://flask.pocoo.org/) application for receiving events from Github via [webhooks](https://developer.github.com/webhooks/).
- After validating their [signature](https://developer.github.com/webhooks/securing/) the Github events are placed into a [Pub/Sub](https://cloud.google.com/pubsub/) message queue.

### Backend
- A Python daemon that contains all the logic.
- Runs as a Kubernetes [Deployment](https://kubernetes.io/docs/concepts/workloads/controllers/deployment/) on a preemptible [n1-standard-1](https://cloud.google.com/compute/docs/machine-types#standard_machine_types) instance.
- Receives messages from Pub/Sub.
- Polls Kubernetes job statuses every 5 seconds.
- Polls Github pull requests every 2.5 minutes as safeguard against lost events.
- All state information is stored in the job's [metadata](https://kubernetes.io/docs/concepts/overview/working-with-objects/annotations/) and the check run's [external_id](https://developer.github.com/v3/checks/runs/#parameters).

### Toolbox
- Collection of utility scripts.
- Used for building and running [targets](./toolbox/run_target.sh).
- Used for running [CronJobs](https://kubernetes.io/docs/concepts/workloads/controllers/cron-jobs/), e.g. for the [Dashboard](manifests/dashboard-cronjob.yaml).
- Cron jobs use the [cp2kcictl.py](./toolbox/cp2kcictl.py) command line tool to inject Pub/Sub messages. It doubles as admin tool.

## Installation
The CP2K-CI system is a one-off implementation that is **not** meant to be installed multiple times.
Nevertheless, the following steps are roughly what needs to be done to re-install the CP2K-CI system:
 - Run scripts in `./setup` (finding the right order is left as an exercise ;-)
 - Run `kubectl apply -f manifests/` repeatedly until ''convergence''.
 - Register Cloud Build [triggers](https://cloud.google.com/cloud-build/docs/running-builds/automate-builds) for all `cloudbuild.yaml` files and run them once manually.
 - Request quota for `PREEMPTIBLE_CPUS` and `IN_USE_ADDRESSES`.
