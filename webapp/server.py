#!/usr/bin/env python3

import os
import yaml
import subprocess
from flask import Flask, request, jsonify, render_template

app = Flask(__name__)

# Paths
my_dir_path = os.path.dirname(os.path.realpath(__file__))
VALUES_YML_PATH = os.path.join(my_dir_path, "values.yaml")
UPDATED_YML_PATH = os.path.join(my_dir_path, "updated_values.yaml")


# Function to infer correct default values for all types
def infer_default_value(value):
    """Infer the correct default value based on type."""
    if isinstance(value, str):
        return ""  # Empty string
    elif isinstance(value, int):
        return 0  # Default 0 for integers
    elif isinstance(value, float):
        return 0.0  # Default 0.0 for floats
    elif isinstance(value, bool):
        return False  # Default False for booleans
    elif isinstance(value, list):
        return []  # Empty list
    elif isinstance(value, dict):
        return {
            k: infer_default_value(v)
            for k, v in value.items()
        }  # Recursive
    else:
        return None  # Default None for unknown types


# Generate templates dynamically for arrays
def generate_templates(data):
    templates = {}

    def recursive_template(obj, key_path=""):
        if isinstance(obj, list) and len(obj) > 0 and isinstance(obj[0], dict):
            templates[key_path] = {
                k: infer_default_value(v)
                for k, v in obj[0].items()
            }
        elif isinstance(obj, dict):
            for key, value in obj.items():
                recursive_template(value,
                                   f"{key_path}.{key}" if key_path else key)

    recursive_template(data)
    return templates


def namespace_exists(namespace, kubectl_config):
    """Check if a Kubernetes namespace exists."""
    command = f"kubectl --kubeconfig={kubectl_config} get namespace {namespace} --no-headers"
    result = subprocess.run(command,
                            shell=True,
                            capture_output=True,
                            text=True)
    return result.returncode == 0


def create_namespace(namespace, kubectl_config):
    """Create a Kubernetes namespace if it doesn't exist."""
    command = f"kubectl --kubeconfig={kubectl_config} create namespace {namespace}"
    subprocess.run(command, shell=True)


def helm_release_exists(namespace, release_name):
    """Check if a Helm release exists in the specified namespace."""
    try:
        command = f"helm -n {namespace} ls --filter {release_name} --output json"
        result = subprocess.run(command,
                                shell=True,
                                capture_output=True,
                                text=True)
        return len(result.stdout.strip()
                   ) > 0  # Helm returns non-empty output if the release exists
    except Exception as e:
        print(f"Error checking Helm release: {e}")
        return False


@app.route("/")
def index():
    # Load YAML values
    with open(VALUES_YML_PATH, "r") as file:
        values = yaml.safe_load(file)

    # Generate templates for arrays
    templates = generate_templates(values)

    return render_template("index.html", values=values, templates=templates)


@app.route("/update", methods=["POST"])
def update_values():
    data = request.json

    # Extract Helm-specific inputs
    namespace = data.pop("helmNamespace", "default")
    release_name = data.pop("helmReleaseName", "5gcore")
    helm_chart_path = data.pop("helmChartPath",
                               "/opt/opensource-5g-core/helm-chart")
    kubectl_config = data.pop("kubectlConfigPath",
                              "/etc/kubernetes/admin.conf")

    # Check if namespace exists, and create it if necessary
    if not namespace_exists(namespace, kubectl_config):
        create_namespace(namespace, kubectl_config)

    # Check if the Helm release already exists
    release_exists = helm_release_exists(namespace, release_name)

    # Save updated YAML values
    with open(UPDATED_YML_PATH, "w") as file:
        yaml.safe_dump(data, file)

    # Determine whether to install or upgrade
    if release_exists:
        # Prompt user for upgrade or abort
        return jsonify({
            "status":
            "exists",
            "message":
            f"The Helm release '{release_name}' already exists in namespace '{namespace}'. Do you want to upgrade?",
        })

    # Helm install
    command = (
        f"helm -n {namespace} install {release_name} -f {UPDATED_YML_PATH} {helm_chart_path}"
    )
    process = subprocess.run(command,
                             shell=True,
                             capture_output=True,
                             text=True)

    if process.returncode != 0:
        return jsonify({"status": "error", "output": process.stderr})

    return jsonify({"status": "success", "output": process.stdout})


@app.route("/upgrade", methods=["POST"])
def upgrade_release():
    data = request.json

    # Extract Helm-specific inputs
    namespace = data.pop("helmNamespace", "default")
    release_name = data.pop("helmReleaseName", "5gcore")
    helm_chart_path = data.pop("helmChartPath",
                               "/opt/opensource-5g-core/helm-chart")

    # Helm upgrade
    command = (
        f"helm -n {namespace} upgrade {release_name} -f {UPDATED_YML_PATH} {helm_chart_path}"
    )
    process = subprocess.run(command,
                             shell=True,
                             capture_output=True,
                             text=True)

    if process.returncode != 0:
        return jsonify({"status": "error", "output": process.stderr})

    return jsonify({"status": "success", "output": process.stdout})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5001)
