"""
Deployer Agent
==============
Deploys built application to ephemeral Docker environment for testing.

FIX B-1: deploy_url now uses the container name on the Docker network
(e.g. http://pr-2-ephemeral-<uuid>:8080) instead of http://localhost:<port>.

Containers communicate with each other via their names on the shared Docker
network.  Using localhost:<host_port> resolved to the langgraph container
itself, not the ephemeral container, causing every downstream health check
and test to fail with "connection refused".

The -p host_port:8080 mapping is still created so operators can reach the
container from their laptop for manual debugging, but it is never used as
the deploy_url passed to tester/api_validator/runtime_analyzer.
"""

import logging
import os
import subprocess
import time
import socket
from datetime import datetime
from typing import Any, Dict, List

logger = logging.getLogger("agents.deployer")


def _find_free_port(start_port: int = 19000, max_attempts: int = 1000) -> int:
    """
    Find an available port ON THE DOCKER HOST for -p host_port:8080.

    NOTE: socket.bind() inside this container only checks ports free
    inside the langgraph-api container — not on the Docker host.
    Using it led to every workflow picking port 19000 and colliding.

    The correct approach is to pass -p 0:8080 to docker run and let the
    host OS assign a guaranteed-free ephemeral port.  This function is
    kept as a fallback but is no longer the primary port-selection method.
    See run_deployer_agent() which uses -p 0:8080 + docker port readback.
    """
    for port in range(start_port, start_port + max_attempts):
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.bind(("", port))
                return port
        except OSError:
            continue
    return 0


def run_deployer_agent(
    workflow_id: Any,
    repository: str,
    pr_number: int,
    build_artifacts: Dict[str, Any] = None,
    fid: int = 1,
) -> Dict[str, Any]:
    """
    Deployer agent — deploys built application to ephemeral Docker environment.
    """
    start = datetime.utcnow()

    findings = []
    deploy_success = False
    deploy_url = ""
    public_url = ""
    host_port = 0
    container_name = f"pr-{pr_number}-ephemeral-{workflow_id}"

    try:
        if not build_artifacts or not build_artifacts.get("docker_image"):
            findings.append({
                "id": fid,
                "agent": "deployer",
                "severity": "HIGH",
                "title": "No build artifacts available",
                "description": "Cannot deploy - no Docker image found from builder agent",
                "test_name": "artifact_check",
            })
            return {
                "findings": findings,
                "agent_log": {
                    "agent": "deployer",
                    "status": "COMPLETED",
                    "started_at": start.isoformat(),
                    "completed_at": datetime.utcnow().isoformat(),
                    "deploy_success": False,
                },
                "fid": fid,
                "deploy_success": False,
            }

        docker_image = build_artifacts["docker_image"]

        # Setup docker command with optional remote host
        docker_args = ["docker"]
        dh = os.getenv("DEPLOY_HOST", "localhost")
        if dh and dh != "localhost":
            user = os.getenv("DEPLOY_SSH_USER", "")
            host_ref = f"ssh://{user}@{dh}" if user else f"ssh://{dh}"
            docker_args += ["-H", host_ref]

        # Check if image exists
        check_cmd = docker_args + ["image", "inspect", docker_image]
        check_result = subprocess.run(check_cmd, capture_output=True, text=True)

        if check_result.returncode != 0:
            findings.append({
                "id": fid,
                "agent": "deployer",
                "severity": "HIGH",
                "title": "Docker image not found",
                "description": f"Image {docker_image} does not exist - build may have failed",
                "test_name": "image_check",
            })
            fid += 1
        else:
            # Run ephemeral container on the shared Docker network.
            # deploy_url uses the Docker-network container name so agents inside
            # the langgraph container reach the ephemeral container correctly.
            # public_url uses DOCKER_HOST_IP + the host-side port so a human
            # reviewer can open the app in a browser before approving the PR.
            docker_network = os.getenv("DOCKER_NETWORK", "tuskersquad-net")

            # DOCKER_HOST_IP: IP or hostname of the machine running Docker.
            # Defaults to "localhost" for local dev.
            # Set to server LAN/public IP in infra/.env for remote deployments.
            docker_host_ip = os.getenv("DOCKER_HOST_IP", "localhost")

            # Use -p 0:8080 so the host OS picks a guaranteed-free ephemeral
            # port.  socket.bind() inside this container only sees ports free
            # inside the langgraph container itself — not on the Docker host —
            # so it always returned 19000 and caused port collisions when two
            # PR reviews ran concurrently.  With -p 0:8080 Docker/the host OS
            # selects the port, then we read it back with `docker port`.
            run_cmd = docker_args + [
                "run", "-d",
                "--name", container_name,
                "--network", docker_network,
                "-p", "0:8080",
                docker_image
            ]

            run_result = subprocess.run(run_cmd, capture_output=True, text=True, timeout=60)

            if run_result.returncode == 0:
                container_id = run_result.stdout.strip()
                # Internal URL used by agents on the Docker network
                deploy_url = f"http://{container_name}:8080"

                # Read back the actual host port that Docker assigned.
                # `docker port <id> 8080` prints e.g. "0.0.0.0:19342"
                host_port = 0
                try:
                    port_result = subprocess.run(
                        docker_args + ["port", container_id, "8080"],
                        capture_output=True, text=True, timeout=10
                    )
                    # Output: "0.0.0.0:19342" or ":::19342" — take the last token after ":"
                    if port_result.returncode == 0 and port_result.stdout.strip():
                        port_line = port_result.stdout.strip().split("\n")[0]
                        host_port = int(port_line.rsplit(":", 1)[-1])
                except Exception as _pe:
                    logger.warning("deployer_port_readback_failed container=%s err=%s",
                                   container_name, _pe)

                # Public URL for human reviewers to open in a browser
                public_url = f"http://{docker_host_ip}:{host_port}" if host_port else ""

                # Wait for container to be running and health endpoint to respond
                max_attempts = 30
                health_endpoint = os.getenv("HEALTH_ENDPOINT", "/health")
                for attempt in range(max_attempts):
                    # First check if container is running
                    inspect_cmd = docker_args + ["inspect", "--format", "{{.State.Status}}", container_id]
                    inspect_result = subprocess.run(inspect_cmd, capture_output=True, text=True)
                    if inspect_result.returncode != 0 or "running" not in inspect_result.stdout.lower():
                        if attempt == max_attempts - 1:
                            findings.append({
                                "id": fid,
                                "agent": "deployer",
                                "severity": "HIGH",
                                "title": "Container not running",
                                "description": f"Container {container_name} failed to start or exited",
                                "test_name": "container_running",
                            })
                        time.sleep(2)
                        continue

                    # Then check health endpoint
                    health_check_cmd = ["curl", "-f", "-s", "--max-time", "5", f"{deploy_url}{health_endpoint}"]
                    health_result = subprocess.run(health_check_cmd, capture_output=True, text=True)
                    if health_result.returncode == 0:
                        deploy_success = True
                        # Title includes the public URL so it always
                        # appears in the PR comment (description is truncated
                        # to 140 chars in the comment formatter).
                        access_info = (
                            f" — Preview: {public_url}"
                            if public_url else ""
                        )
                        findings.append({
                            "id": fid,
                            "agent": "deployer",
                            "severity": "LOW",
                            "title": f"Ephemeral deployment successful{access_info}",
                            "description": (
                                f"Application deployed and healthy after {attempt * 2}s.\n"
                                f"Container: {container_name}  port: {host_port}\n"
                                f"Internal (agents): {deploy_url}\n"
                                f"Browser access: {public_url if public_url else 'set DOCKER_HOST_IP in infra/.env'}"
                            ),
                            "test_name": "ephemeral_deploy",
                        })
                        break
                    elif attempt == max_attempts - 1:
                        findings.append({
                            "id": fid,
                            "agent": "deployer",
                            "severity": "HIGH",
                            "title": "Deployment health check failed",
                            "description": f"Container running but health endpoint {health_endpoint} not responding after {max_attempts * 2}s",
                            "test_name": "health_check",
                        })
                    time.sleep(2)
                fid += 1
            else:
                findings.append({
                    "id": fid,
                    "agent": "deployer",
                    "severity": "HIGH",
                    "title": "Container start failed",
                    "description": f"Failed to start ephemeral container: {run_result.stderr}",
                    "test_name": "container_start",
                })
                fid += 1

    except subprocess.TimeoutExpired:
        findings.append({
            "id": fid,
            "agent": "deployer",
            "severity": "HIGH",
            "title": "Deployment timeout",
            "description": "Deployment process exceeded timeout limit",
            "test_name": "deploy_timeout",
        })
    except Exception as e:
        findings.append({
            "id": fid,
            "agent": "deployer",
            "severity": "HIGH",
            "title": "Deployment system error",
            "description": f"Unexpected error during deployment: {str(e)}",
            "test_name": "deploy_error",
        })

    log = {
        "agent": "deployer",
        "status": "COMPLETED",
        "started_at": start.isoformat(),
        "completed_at": datetime.utcnow().isoformat(),
        "deploy_success": deploy_success,
        "deploy_url": deploy_url,
        "container_name": container_name,
    }
    logger.info("deployer_complete workflow=%s repo=%s pr=%d success=%s url=%s",
                workflow_id, repository, pr_number, deploy_success, deploy_url)

    # public_url is set only when a host_port was successfully allocated
    # and DOCKER_HOST_IP is configured. It may be empty if _find_free_port
    # returned 0 (no free port in range).
    return {
        "findings": findings,
        "agent_log": log,
        "fid": fid,
        "deploy_success": deploy_success,
        "deploy_url": deploy_url,
        "public_url": public_url if deploy_success else "",
        "host_port": host_port if deploy_success else 0,
        "container_name": container_name,
    }