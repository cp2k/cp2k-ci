#!/bin/bash -e

kubectl logs -l "app.kubernetes.io/name=cp2kci-kube-worker-app" --all-containers --prefix --tail=1000 -f

#EOF
