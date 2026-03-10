"""
Deployer Agent
==============
Deploys built application to ephemeral environment for testing.
"""

import logging
import os
import subprocess
import time
from datetime import datetime
from typing import Any, Dict, List

logger = logging.getLogger("agents.deployer")


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

        # Check if image exists
        check_cmd = ["docker", "image", "inspect", docker_image]
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
            # Run ephemeral container
            run_cmd = [
                "docker", "run", "-d",
                "--name", container_name,
                "--network", "tuskersquad-net",
                "-p", f"808{pr_number % 10}:8080",  # Dynamic port assignment
                docker_image
            ]

            run_result = subprocess.run(run_cmd, capture_output=True, text=True, timeout=60)

            if run_result.returncode == 0:
                container_id = run_result.stdout.strip()
                deploy_url = f"http://localhost:808{pr_number % 10}"

                # Wait for container to be healthy
                max_attempts = 30
                for attempt in range(max_attempts):
                    health_cmd = ["docker", "inspect", "--format", "{{.State.Health.Status}}", container_id]
                    health_result = subprocess.run(health_cmd, capture_output=True, text=True)

                    if health_result.returncode == 0 and "healthy" in health_result.stdout.lower():
                        deploy_success = True
                        findings.append({
                            "id": fid,
                            "agent": "deployer",
                            "severity": "LOW",
                            "title": "Ephemeral deployment successful",
                            "description": f"Application deployed to {deploy_url}, container healthy after {attempt * 2}s",
                            "test_name": "ephemeral_deploy",
                        })
                        break
                    elif attempt == max_attempts - 1:
                        findings.append({
                            "id": fid,
                            "agent": "deployer",
                            "severity": "HIGH",
                            "title": "Deployment health check failed",
                            "description": f"Container started but failed health check after {max_attempts * 2}s",
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

    return {
        "findings": findings,
        "agent_log": log,
        "fid": fid,
        "deploy_success": deploy_success,
        "deploy_url": deploy_url,
        "container_name": container_name,
    }