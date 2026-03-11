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

    findings: List[Dict[str, Any]] = []
    build_success = False
    build_output = ""
    workspace_root = os.getenv("WORKSPACE_ROOT", "/workspace")
    pr_dir = os.path.join(workspace_root, f"pr-{pr_number}")
    os.makedirs(pr_dir, exist_ok=True)

    try:
        # Clone the repository into the PR workspace
        gitea_url = os.getenv("GITEA_URL", "http://tuskersquad-gitea:3000").rstrip("/")
        repo_url = f"{gitea_url}/{repository}.git"
        # Use HEAD SHA for checkout if available
        provider = None
        try:
            from services.langgraph_api.core.git_provider import get_provider
            provider = get_provider(None)
        except Exception:
            pass

        pr_info = None
        if provider:
            try:
                pr_info = provider.get_pr_info(repository, pr_number)
            except Exception:
                pr_info = None

        clone_cmd = ["git", "clone", "--depth", "1", repo_url, pr_dir]
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
            # attempt to checkout the PR commit if known
            if pr_info and pr_info.head_sha:
                try:
                    subprocess.run(
                        ["git", "fetch", "origin", pr_info.head_sha],
                        cwd=pr_dir,
                        capture_output=True,
                        text=True,
                        timeout=120,
                    )
                    subprocess.run(
                        ["git", "checkout", pr_info.head_sha],
                        cwd=pr_dir,
                        capture_output=True,
                        text=True,
                        timeout=120,
                    )
                except Exception:
                    pass

            # Check for build files and attempt build
            build_files: List[str] = []
            if os.path.exists(os.path.join(pr_dir, "Dockerfile")):
                build_files.append("Dockerfile")
            if os.path.exists(os.path.join(pr_dir, "package.json")):
                build_files.append("package.json")
            if os.path.exists(os.path.join(pr_dir, "requirements.txt")):
                build_files.append("requirements.txt")
            if os.path.exists(os.path.join(pr_dir, "Makefile")):
                build_files.append("Makefile")
            # language-specific build detection
            if os.path.exists(os.path.join(pr_dir, "pom.xml")) or os.path.exists(os.path.join(pr_dir, "build.gradle")):
                build_files.append("java_build")

            if not build_files:
                findings.append({
                    "id": fid,
                    "agent": "builder",
                    "severity": "MEDIUM",
                    "title": "No build configuration found",
                    "description": "Repository lacks standard build files (Dockerfile, package.json, requirements.txt, Makefile, java build file)",
                    "test_name": "build_config_check",
                })
                fid += 1
            else:
                # Docker build
                if "Dockerfile" in build_files:
                    docker_args = ["docker"]
                    # respect custom docker host
                    dh = os.getenv("DEPLOY_HOST", "localhost")
                    if dh and dh != "localhost":
                        user = os.getenv("DEPLOY_SSH_USER", "")
                        host_ref = f"ssh://{user}@{dh}" if user else f"ssh://{dh}"
                        docker_args += ["-H", host_ref]
                    build_cmd = docker_args + ["build", "-t", f"pr-{pr_number}-build", pr_dir]
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
                            "description": f"Docker image built successfully from {repo_url}",
                            "test_name": "docker_build",
                        })
                    else:
                        findings.append({
                            "id": fid,
                            "agent": "builder",
                            "severity": "HIGH",
                            "title": "Docker build failed",
                            "description": f"Docker build failed with exit code {build_result.returncode}.",
                            "test_name": "docker_build",
                        })
                    fid += 1
                # Node.js build
                if "package.json" in build_files and not build_success:
                    try:
                        npm_cmd = ["npm", "install"]
                        result = subprocess.run(npm_cmd, cwd=pr_dir, capture_output=True, text=True, timeout=300)
                        if result.returncode == 0:
                            build_success = True
                            findings.append({
                                "id": fid,
                                "agent": "builder",
                                "severity": "LOW",
                                "title": "npm install succeeded",
                                "description": "Dependencies installed successfully",
                                "test_name": "node_build",
                            })
                        else:
                            findings.append({
                                "id": fid,
                                "agent": "builder",
                                "severity": "HIGH",
                                "title": "npm install failed",
                                "description": result.stderr,
                                "test_name": "node_build",
                            })
                    except Exception as e:
                        findings.append({
                            "id": fid,
                            "agent": "builder",
                            "severity": "HIGH",
                            "title": "npm build error",
                            "description": str(e),
                            "test_name": "node_build",
                        })
                    fid += 1
                # Python build
                if "requirements.txt" in build_files and not build_success:
                    try:
                        pip_cmd = ["pip", "install", "--break-system-packages", "-r", "requirements.txt"]
                        result = subprocess.run(pip_cmd, cwd=pr_dir, capture_output=True, text=True, timeout=300)
                        if result.returncode == 0:
                            build_success = True
                            findings.append({
                                "id": fid,
                                "agent": "builder",
                                "severity": "LOW",
                                "title": "pip install succeeded",
                                "description": "Requirements installed successfully",
                                "test_name": "python_build",
                            })
                        else:
                            findings.append({
                                "id": fid,
                                "agent": "builder",
                                "severity": "HIGH",
                                "title": "pip install failed",
                                "description": result.stderr,
                                "test_name": "python_build",
                            })
                    except Exception as e:
                        findings.append({
                            "id": fid,
                            "agent": "builder",
                            "severity": "HIGH",
                            "title": "python build error",
                            "description": str(e),
                            "test_name": "python_build",
                        })
                    fid += 1
                # Java build
                if "java_build" in build_files and not build_success:
                    try:
                        if os.path.exists(os.path.join(pr_dir, "pom.xml")):
                            mvn_cmd = ["mvn", "package", "-DskipTests"]
                        else:
                            mvn_cmd = ["./gradlew", "build", "-x", "test"]
                        result = subprocess.run(mvn_cmd, cwd=pr_dir, capture_output=True, text=True, timeout=900)
                        if result.returncode == 0:
                            build_success = True
                            findings.append({
                                "id": fid,
                                "agent": "builder",
                                "severity": "LOW",
                                "title": "Java build succeeded",
                                "description": "Project compiled successfully",
                                "test_name": "java_build",
                            })
                        else:
                            findings.append({
                                "id": fid,
                                "agent": "builder",
                                "severity": "HIGH",
                                "title": "Java build failed",
                                "description": result.stderr,
                                "test_name": "java_build",
                            })
                    except Exception as e:
                        findings.append({
                            "id": fid,
                            "agent": "builder",
                            "severity": "HIGH",
                            "title": "java build error",
                            "description": str(e),
                            "test_name": "java_build",
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
        "workspace_dir": pr_dir,
    }