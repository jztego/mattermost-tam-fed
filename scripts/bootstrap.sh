#!/usr/bin/env bash
# Bring the lab cluster up. Assumes Colima k3s is already running and
# kubectl/helm point at it. See README.md for the one-time cluster start.
set -euo pipefail
cd "$(dirname "$0")/.."

if ! kubectl get nodes >/dev/null 2>&1; then
  echo "kubectl cannot reach a cluster. Start Colima first:"
  echo "  colima start --kubernetes --cpu 6 --memory 12 --disk 40 --vz-rosetta"
  exit 1
fi

helm repo add ingress-nginx https://kubernetes.github.io/ingress-nginx >/dev/null
helm repo add mattermost https://helm.mattermost.com >/dev/null
helm repo update
helm upgrade --install ingress-nginx ingress-nginx/ingress-nginx \
  --namespace ingress-nginx --create-namespace \
  --set controller.ingressClassResource.name=nginx \
  --set controller.ingressClassResource.default=true \
  --set controller.watchIngressWithoutClass=true \
  --set controller.service.type=ClusterIP \
  --set controller.admissionWebhooks.enabled=false
helm upgrade --install mattermost-operator mattermost/mattermost-operator \
  --namespace mattermost-operator --create-namespace
kubectl -n mattermost-operator rollout status deploy/mattermost-operator --timeout=180s

# The Enterprise server image and the interview OpenLDAP image publish
# linux/amd64 only. This node is arm64. Pull them explicitly, then the
# manifests use imagePullPolicy IfNotPresent so kube reuses the local image.
docker pull --platform linux/amd64 mattermost/mattermost-enterprise-edition:11.7.15
docker pull --platform linux/amd64 ghcr.io/rroemhild/docker-test-openldap:master
docker pull bitnamilegacy/minio:latest
docker pull postgres:16-alpine

kubectl apply -f deploy/data-plane.yaml
kubectl apply -f deploy/mattermost.yaml
kubectl -n mattermost rollout status statefulset/postgres --timeout=180s
kubectl -n mattermost rollout status deploy/minio --timeout=180s
kubectl -n mattermost rollout status deploy/openldap --timeout=180s
for _ in $(seq 1 60); do
  if kubectl -n mattermost get deploy/mm >/dev/null 2>&1; then
    break
  fi
  sleep 5
done
kubectl -n mattermost rollout status deploy/mm --timeout=300s

echo
echo "Server is up inside the cluster. From the Mac:"
echo "  kubectl -n mattermost port-forward svc/mm 8065:8065"
echo "  python3 scripts/workspace.py"
