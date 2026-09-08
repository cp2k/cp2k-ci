#!/bin/bash -e

kubectl logs -l "app.kubernetes.io/name=cp2kci-kube-runner-app" --all-containers --prefix --tail=1000 -f

#EOF
