#!/usr/bin/env python
# This script is designed to run on python 2.7 or 3.x, in order to avoid
# making users think about it.
# Similarly, it can only depend on the standard library.
from __future__ import division
from __future__ import print_function
from __future__ import unicode_literals
from __future__ import absolute_import

import errno
import json
import os
import subprocess
import sys
import tempfile
import time

class ToolError(Exception):
    pass


def is_mac():
    return sys.platform == 'darwin'

def sanity_check():
    # Check for kind
    try:
        version = subprocess.check_output(["kind", "version"])
    except OSError as e:
        if e.errno == errno.EACCES: # permission denied
            raise ToolError("You seem to have a `kind` in your path, but it isn't executable.")
        if e.errno == errno.ENOENT:
            message = "You need to install kind.\n"
            if is_mac():
                message += "Try running `brew install kind`.\n"
            message += "Check https://kind.sigs.k8s.io/docs/user/quick-start for details."
            raise ToolError(message)
    except subprocess.CalledProcessError:
        raise ToolError("The `kind` you have installed does not behave as we expect.")

    # Check for kubectl
    try:
        version = subprocess.check_output(["kubectl", "version", "-o", "json", "--client", "true"])
    except OSError as e:
        if e.errno == errno.EACCES:
            raise ToolError("You seem to have a `kubectl` in your path, but it isn't executable")
        if e.errno == errno.ENOENT:
            message = "You need to install kubectl.\n"
            try:
                subprocess.check_output("gcloud", "version")
            except (OSError, subprocess.CalledProcessError):
                if is_mac():
                    message += "Try running `brew install kubectl`.\n"
            else:
                message += "Try running `gcloud components install kubectl`.\n"
            message += "Check https://kubernetes.io/docs/tasks/tools/install-kubectl/ for details."
        raise ToolError(message)
    except subprocess.CalledProcessError:
        raise ToolError("The `kubectl` you have installed does not behave as we expect.")

def kubectl(*args, **argv):
    return subprocess.check_call(("kubectl", "--context=kind-rebble") + args, **argv)

def prepare_cluster():
    root_dir = os.path.dirname(__file__) + '/..'
    print("Creating kind cluster 'rebble'...")
    try:
        subprocess.check_call(["kind", "create", "cluster", "--config=%s/kind.yaml" % root_dir, "--name=rebble"])
    except subprocess.CalledProcessError:
        raise ToolError("Couldn't create cluster.")

    print("Applying dev configuration to cluster...")
    try:
        kubectl("apply", "-k", "%s/overlays/dev" % root_dir)
    except subprocess.CalledProcessError:
        raise ToolError("Couldn't apply cluster config")

def create_databases():
    print("Creating required databases...")
    try:
        for db in ('auth', 'appstore', 'timeline'):
            kubectl(
                "exec", "postgres-0", "--",
                "psql", "-U", "postgres",
                "-c", "CREATE DATABASE %s;" % db,
                "-c", "CREATE USER %(db)s WITH ENCRYPTED PASSWORD '%(db)s'; GRANT ALL PRIVILEGES ON DATABASE %(db)s TO %(db)s;" % {'db': db}
            )
    except subprocess.CalledProcessError:
        raise ToolError("Creating users and databases failed.")

def wait_for_pod_state(pod, states, timeout=None):
    start = time.time()
    spinner = '|/-\\'
    spinner_index = 0
    while True:
        try:
            pod_status = subprocess.check_output(
                ["kubectl", "--context=kind-rebble", "get", "pod", pod, "-o=jsonpath={.status.phase}"], stderr=subprocess.STDOUT).decode('utf-8')
        except subprocess.CalledProcessError as e:
            if e.returncode == 1 and b'NotFound' in e.output:
                pod_status = "NotFound"
            else:
                raise
        print("\r[%s] %s status: %s" % (spinner[spinner_index], pod, pod_status.ljust(10)), end='')
        if pod_status in states:
            print()
            return
        if timeout is not None and time.time() - start > timeout:
            print()
            raise ToolError("Timed out waiting for %s to be %s" % (pod, states))
        spinner_index = (spinner_index + 1) % len(spinner)
        time.sleep(1)

def wait_for_db():
    print("Waiting for postgres to be available...")
    print("Depending on your internet connection, this may take some time.")
    wait_for_pod_state('postgres-0', ['Running'], timeout=900)
    time.sleep(5)
    print("Ready.")


def tmpfile():
    if sys.version_info[0] == 2:
        return tempfile.NamedTemporaryFile('w+')
    return tempfile.NamedTemporaryFile('w+', encoding='utf-8')


def prepare_db(app, deployment_name):
    print("Preparing %s db..." % deployment_name)
    print("Creating migration pod...")
    try:
        deployment = subprocess.check_output(["kubectl", "--context=kind-rebble", "get", "deployment", deployment_name, "-o", "json"])
    except subprocess.CalledProcessError:
        raise ToolError("Couldn't get %s deployment" % deployment_name)
    deployment = json.loads(deployment)
    pod = deployment['spec']['template']
    pod.update({'kind': 'Pod', 'apiVersion': 'v1'})
    pod['metadata']['name'] = "create-%s-db" % deployment_name
    del pod['spec']['containers'][0]['readinessProbe']
    del pod['spec']['containers'][0]['livenessProbe']
    pod['spec']['containers'][0]['args'] = ['flask', 'db', 'upgrade']
    pod['spec']['containers'][0]['env'].append({'name': 'FLASK_APP', 'value': app})
    pod['spec']['restartPolicy'] = 'Never'

    with tmpfile() as f:
        json.dump(pod, f)
        f.flush()
        try:
            kubectl("apply", "-f", f.name)
        except subprocess.CalledProcessError:
            raise ToolError("Couldn't apply pod.")
    print("Waiting for pod to complete...")
    wait_for_pod_state(pod['metadata']['name'], ['Succeeded'], timeout=60)
    kubectl("logs", pod['metadata']['name'])
    print("Cleaning up...")
    kubectl("delete", "pod", pod['metadata']['name'])
    print("Pod complete.")


def prepare_dbs():
    prepare_db("auth", "auth")
    prepare_db("appstore", "appstore-api")
    prepare_db("timeline_sync", "timeline-sync")


def prepare_oauth_token():
    print("Creating Rebble oauth app...")
    try:
        kubectl(
            "exec", "postgres-0", "--",
            "psql", "-U", "postgres", "-d", "auth", "-c",
            "INSERT INTO oauth_clients (name, client_id, client_secret, redirect_uris, is_confidential, default_scopes, is_rws) VALUES ('rebble', 'rebble-id', 'rebble-secret', '{http://localhost:8080/boot/auth/complete}', FALSE, '{pebble_token,pebble,profile}', TRUE);"
        )
    except subprocess.CalledProcessError:
        raise ToolError("Creating oauth app failed.")


def main():
    try:
        sanity_check()
        prepare_cluster()
        wait_for_db()
        create_databases()
        prepare_dbs()
        prepare_oauth_token()
        print("Done.")
    except ToolError as e:
        print(e.message)
        sys.exit(1)

if __name__ == "__main__":
    main()
