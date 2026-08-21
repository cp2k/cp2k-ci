#!/bin/bash -e

kubectl logs -l "app.kubernetes.io/name=cp2kci-backend-app" --all-containers --prefix --tail=1000 -f

#EOF
