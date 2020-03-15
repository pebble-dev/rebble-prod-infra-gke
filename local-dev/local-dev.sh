#!/usr/bin/env bash

# set -x

ROOT_DIR="$(dirname "${BASH_SOURCE[0]}")/../"
JQ="jq-is-missing"

exists() {
  command -v "$1" > /dev/null 2>&1
}

is-mac() {
  [ "$(uname)" == "Darwin" ]
}

is-linux() {
  [ "$(uname)" == "Linux" ]
}

fail() {
  echo "$@"
  exit 1
}

ensure-jq() {
  if exists jq; then
    JQ="jq"
    return 0
  fi
  if ! exists /tmp/jq; then
    if is-mac; then
      echo "Downloading jq..."
      curl -L -o /tmp/jq https://github.com/stedolan/jq/releases/download/jq-1.6/jq-osx-amd64 || fail "couldn't fetch jq"
      chmod +x /tmp/jq
    elif is-linux; then
      echo "Downloading jq..."
      curl -L -o /tmp/hq https://github.com/stedolan/jq/releases/download/jq-1.6/jq-linux64 || fail "couldn't fetch jq"
      chmod +x /tmp/jq
    else
      echo "You need to install jq."
      echo "Check https://stedolan.github.io/jq/ for details."
      exit 1
    fi
  fi
  JQ="/tmp/jq"
}

sanity-check() {
  # Check that our tools are available
  if ! exists 'kind'; then
    echo "You need to install kind."
    if is-mac && exists 'brew'; then
      echo "Try running brew install kind"
    fi
    echo "Check https://kind.sigs.k8s.io/docs/user/quick-start for details."
    exit 1
  fi

  if ! exists 'kubectl'; then
    echo "You need to install kubectl"
    if exists 'gcloud'; then
      echo "Try running gcloud components install kubectl"
    elif is-mac && exists 'brew'; then
      echo "Try running brew install kubectl"
    fi
    echo "Check https://kubernetes.io/docs/tasks/tools/install-kubectl/ for details."
    exit 1
  fi

  ensure-jq
}

prepare-cluster() {
  echo "Creating kind cluster 'rebble'..."
  result=0
  kind create cluster --config="${ROOT_DIR}/kind.yaml" --name=rebble || fail "Cluster creation failed"
  echo "Applying dev configuration to cluster..."
  kubectl apply --context=kind-rebble -k "${ROOT_DIR}/overlays/dev" || fail "Applying cluster config failed"
}

create-databases() {
  # We need three users: appstore, timeline and auth
  echo "Creating required postgres databases..."
  result=0
  kubectl exec postgres-0 -- psql -U postgres -c "CREATE DATABASE auth;" -c "CREATE USER auth WITH ENCRYPTED PASSWORD 'auth'; GRANT ALL PRIVILEGES ON DATABASE auth TO auth;" || result=$?
  kubectl exec postgres-0 -- psql -U postgres -c "CREATE DATABASE appstore;" -c "CREATE USER appstore WITH ENCRYPTED PASSWORD 'appstore'; GRANT ALL PRIVILEGES ON DATABASE appstore TO appstore;" || result=$?
  kubectl exec postgres-0 -- psql -U postgres -c "CREATE DATABASE timeline;" -c "CREATE USER timeline WITH ENCRYPTED PASSWORD 'timeline'; GRANT ALL PRIVILEGES ON DATABASE timeline TO timeline;" || result=$?
  if (( $result != 0 )); then
    fail "Creating users and databases failed."
  fi
}

wait_for_db() {
  echo "Waiting for postgres to be available..."
  echo "Depending on your internet connection, this may take some time."
  wait_for_pod_state "postgres-0" "Running"
  sleep 5
  echo "Done"
}

wait_for_pod_state() {
  pod="$1"
  state="$2"
  while true
  do
    sleep 2
    pod_status="$(kubectl get pod "$pod" -o=jsonpath='{.status.phase}' 2>/dev/null)"
    echo "Current $pod status: $pod_status"
    if [ "$pod_status" = "$state" ]; then
      break
    fi
  done
}

prepare-db() {
  app="$1"
  deployment="$2"
  echo "Preparing ${deployment} db..."
  # run the migration inside the image
  echo "Creating migration pod..."
  kubectl get deployment "$deployment" -o json | "$JQ" --arg deployment "$deployment" --arg app "$app" -r -f "$ROOT_DIR/local-dev/deployment-to-db-upgrade.jq" | kubectl apply -f -
  echo "Waiting for pod to complete..."
  # TODO: this will wait forever if it doesn't succeed
  wait_for_pod_state "create-${deployment}-db" "Succeeded"
  kubectl logs "create-${deployment}-db"
  echo "Cleaning up..."
  kubectl delete pod "create-${deployment}-db"
  echo "Pod complete"
}

prepare-dbs() {
  prepare-db auth auth
  prepare-db appstore appstore-api
  prepare-db timeline_sync "timeline-sync"
}

sanity-check
prepare-cluster
wait_for_db
create-databases
prepare-dbs

