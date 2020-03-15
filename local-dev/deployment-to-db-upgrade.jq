# Pull out the pod template
.spec.template
# Mark this as a pod
| .kind = "Pod"
| .apiVersion = "v1"
# Give it a name
| .metadata.name = "create-" + $deployment + "-db"
# Remove the readiness probes - we aren't starting a server
| .spec.containers[0].readinessProbe = null
| .spec.containers[0].livenessProbe = null
# Override the command
| .spec.containers[0].args = ["flask", "db", "upgrade"]
# We need to specify the FLASK_APP environment variable
| .spec.containers[0].env += [{"name": "FLASK_APP", "value": $app}]
# We only want to run once
| .spec.restartPolicy = "Never"
