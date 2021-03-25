# rebble-prod-infra-gke
GKE infrastructure configuration

## Getting started locally

We assume you have `kubectl` and `kind` available (and, transitively, Docker or similar). If you do not, the tooling will give you installation hints.

Run `local-dev/local_dev.py`. It'll create a new kind cluster called `rebble`, set it as active, and configure the rebble environment running in it for local development. You can access your services at localhost:8080, e.g. http://localhost:8080/auth for auth.

TODO: more detailed instructions.

## Applying to production

```
kustomize build . | kubectl apply --context=rebble -f -
```
