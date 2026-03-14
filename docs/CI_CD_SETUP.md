# CI/CD Setup (GitHub Actions)

This repository now includes split CI/CD workflows:

- `.github/workflows/ci.yml`
- `.github/workflows/cd.yml`

Execution flow:

1. `CI` runs quality gates (lint, typecheck, security, tests, frontend build, docker build)
2. `CD` runs only after successful `CI` on `main`/`master`, or by manual dispatch
3. `CD` publishes container image to GHCR (`ghcr.io/<owner>/aethelgard:<sha>`)
4. `CD` deploys to staging Kubernetes
5. `CD` smoke tests staging health endpoint
6. `CD` deploys to production Kubernetes
7. `CD` performs production health check + automatic rollback on failure

## 1) Configure GitHub Environments

Create two environments in GitHub repository settings:

- `staging`
- `production`

Recommended protection rules:

- `production`: required reviewers (manual approval gate)
- optional wait timer and branch restrictions

## 2) Required Repository Secrets

Set these repository secrets:

- `KUBE_CONFIG_STAGING_B64` — base64-encoded kubeconfig for staging cluster
- `KUBE_CONFIG_PRODUCTION_B64` — base64-encoded kubeconfig for production cluster

How to encode kubeconfig:

```bash
base64 -w 0 ~/.kube/config
```

## 3) Required Repository Variables

Set these repository variables:

- `STAGING_HEALTHCHECK_URL` (example: `https://staging.example.com/health`)
- `PRODUCTION_HEALTHCHECK_URL` (example: `https://api.example.com/health`)

Optional namespace overrides:

- `K8S_NAMESPACE_STAGING` (default: `aethelgard`)
- `K8S_NAMESPACE_PRODUCTION` (default: `aethelgard`)

## 4) Cluster Secret Contract

The Kubernetes deployment expects this secret in each target namespace:

- Secret name: `aethelgard-secrets`
- Required keys:
  - `aethelgard-api-key`
  - `openai-api-key`

Example:

```bash
kubectl -n aethelgard create secret generic aethelgard-secrets \
  --from-literal=aethelgard-api-key='<your-api-key>' \
  --from-literal=openai-api-key='<your-openai-key>'
```

## 5) Trigger Model

- On push to `main`/`master`: `CI` runs first; `CD` runs only if `CI` succeeds.
- On PR: only `CI` runs.
- Manual deployment is available from the `CD` workflow via `workflow_dispatch`.
- Manual deploy accepts an optional `git_ref` input.

## 6) Rollback Behavior

If production rollout or health check fails, the pipeline runs:

```bash
kubectl rollout undo deployment/aethelgard-api
```

and waits for rollback status.