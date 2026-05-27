#!/usr/bin/env bash
# Tear down the local Docker Desktop Kubernetes deployment.
set -uo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

kubectl config use-context docker-desktop >/dev/null
echo "▸ Deleting cloudbrain namespace and all its resources..."
kubectl delete namespace cloudbrain --ignore-not-found
echo "✓ Done"
