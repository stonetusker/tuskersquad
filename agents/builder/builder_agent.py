"""
Builder Agent
=============
Builds the application from PR source code in an isolated environment.
"""

import logging
import os
import tempfile
import subprocess
from datetime import datetime
from typing import Any, Dict, List

logger = logging.getLogger("agents.builder")


def run_builder_agent(
    workflow_id: Any,
    repository: str,
    pr_number: int,
    fid: int = 1,
) -> Dict[str, Any]:
    """
    Builder agent — clones PR branch, builds application, validates build artifacts.
    """
    start = datetime.utcnow()

    findings = []
    build_success = False
    build_output = ""

    try:
        # Clone the repository to a temporary directory
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_url = f"http://tuskersquad-gitea:3000/{repository}.git"
            clone_cmd = ["git", "clone", "--depth", "1", repo_url, temp_dir]

            # For PR builds, we'd need to fetch the PR branch
            # For now, we'll build from main branch as demo
            result = subprocess.run(
                clone_cmd,
                capture_output=True,
                text=True,
                timeout=300
            )

            if result.returncode != 0:
                findings.append({
                    "id": fid,
                    "agent": "builder",
                    "severity": "HIGH",
                    "title": "Repository clone failed",
                    "description": f"Failed to clone repository: {result.stderr}",
                    "test_name": "repo_clone",
                })
                fid += 1
            else:
                # Check for build files and attempt build
                build_files = []
                if os.path.exists(os.path.join(temp_dir, "Dockerfile")):
                    build_files.append("Dockerfile")
                if os.path.exists(os.path.join(temp_dir, "package.json")):
                    build_files.append("package.json")
                if os.path.exists(os.path.join(temp_dir, "requirements.txt")):
                    build_files.append("requirements.txt")
                if os.path.exists(os.path.join(temp_dir, "Makefile")):
                    build_files.append("Makefile")

                if not build_files:
                    findings.append({
                        "id": fid,
                        "agent": "builder",
                        "severity": "MEDIUM",
                        "title": "No build configuration found",
                        "description": "Repository lacks standard build files (Dockerfile, package.json, requirements.txt, Makefile)",
                        "test_name": "build_config_check",
                    })
                    fid += 1
                else:
                    # Attempt Docker build if Dockerfile exists
                    if "Dockerfile" in build_files:
                        build_cmd = ["docker", "build", "-t", f"pr-{pr_number}-build", temp_dir]
                        build_result = subprocess.run(
                            build_cmd,
                            capture_output=True,
                            text=True,
                            timeout=600
                        )
                        build_output = build_result.stdout + "\n" + build_result.stderr

                        if build_result.returncode == 0:
                            build_success = True
                            findings.append({
                                "id": fid,
                                "agent": "builder",
                                "severity": "LOW",
                                "title": "Docker build successful",
                                "description": f"Application built successfully. Build files found: {', '.join(build_files)}",
                                "test_name": "docker_build",
                            })
                        else:
                            findings.append({
                                "id": fid,
                                "agent": "builder",
                                "severity": "HIGH",
                                "title": "Docker build failed",
                                "description": f"Build failed with exit code {build_result.returncode}. Check build logs.",
                                "test_name": "docker_build",
                            })
                        fid += 1

    except subprocess.TimeoutExpired:
        findings.append({
            "id": fid,
            "agent": "builder",
            "severity": "HIGH",
            "title": "Build timeout",
            "description": "Build process exceeded timeout limit (10 minutes)",
            "test_name": "build_timeout",
        })
    except Exception as e:
        findings.append({
            "id": fid,
            "agent": "builder",
            "severity": "HIGH",
            "title": "Build system error",
            "description": f"Unexpected error during build: {str(e)}",
            "test_name": "build_error",
        })

    log = {
        "agent": "builder",
        "status": "COMPLETED",
        "started_at": start.isoformat(),
        "completed_at": datetime.utcnow().isoformat(),
        "build_success": build_success,
        "build_output": build_output[:1000],  # Truncate for storage
    }
    logger.info("builder_complete workflow=%s repo=%s pr=%d success=%s", workflow_id, repository, pr_number, build_success)

    return {
        "findings": findings,
        "agent_log": log,
        "fid": fid,
        "build_success": build_success,
        "build_artifacts": {"docker_image": f"pr-{pr_number}-build"} if build_success else {},
    }