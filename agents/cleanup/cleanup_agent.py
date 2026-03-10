"""
Cleanup Agent
=============
Stops and removes containers created for a PR and deletes workspace.
"""

import logging
import os
import shutil
import subprocess
import time
from datetime import datetime
from typing import Any, Dict, List

logger = logging.getLogger("agents.cleanup")


def run_cleanup_agent(
    workflow_id: Any,
    repository: str,
    pr_number: int,
    container_name: str = "",
    workspace_dir: str = "",
    fid: int = 1,
) -> Dict[str, Any]:
    start = datetime.utcnow()
    findings: List[Dict[str, Any]] = []

    # Stop and remove container with retries and force options
    if container_name:
        try:
            # First try graceful stop
            stop_result = subprocess.run(
                ["docker", "stop", container_name],
                capture_output=True, text=True, timeout=30
            )

            # Always try to remove, even if stop failed
            rm_result = subprocess.run(
                ["docker", "rm", "-f", container_name],
                capture_output=True, text=True, timeout=30
            )

            if rm_result.returncode != 0:
                findings.append({
                    "id": fid,
                    "agent": "cleanup",
                    "severity": "MEDIUM",
                    "title": "Container cleanup failed",
                    "description": f"Failed to remove container {container_name}: {rm_result.stderr}",
                    "test_name": "container_cleanup",
                })
                fid += 1
            else:
                logger.info("Container %s cleaned up successfully", container_name)

        except subprocess.TimeoutExpired:
            findings.append({
                "id": fid,
                "agent": "cleanup",
                "severity": "HIGH",
                "title": "Container cleanup timeout",
                "description": f"Timeout while cleaning up container {container_name}",
                "test_name": "container_cleanup_timeout",
            })
            fid += 1
        except Exception as e:
            findings.append({
                "id": fid,
                "agent": "cleanup",
                "severity": "HIGH",
                "title": "Container cleanup error",
                "description": f"Unexpected error cleaning up container {container_name}: {str(e)}",
                "test_name": "container_cleanup_error",
            })
            fid += 1

    # Remove workspace directory with retries
    if workspace_dir and os.path.exists(workspace_dir):
        try:
            # Try multiple times in case of temporary locks
            for attempt in range(3):
                try:
                    shutil.rmtree(workspace_dir)
                    logger.info("Workspace %s cleaned up successfully", workspace_dir)
                    break
                except OSError as e:
                    if attempt == 2:  # Last attempt
                        raise e
                    time.sleep(1)  # Wait before retry

        except Exception as e:
            findings.append({
                "id": fid,
                "agent": "cleanup",
                "severity": "MEDIUM",
                "title": "Workspace cleanup error",
                "description": f"Failed to remove workspace directory {workspace_dir}: {str(e)}",
                "test_name": "workspace_cleanup",
            })
            fid += 1

    # Additional cleanup: check for orphaned containers with similar names
    try:
        # Look for containers that might be related to this workflow
        ps_result = subprocess.run(
            ["docker", "ps", "-a", "--filter", f"name={workflow_id}", "--format", "{{.Names}}"],
            capture_output=True, text=True, timeout=10
        )

        if ps_result.returncode == 0:
            orphaned_containers = [line.strip() for line in ps_result.stdout.split('\n') if line.strip() and line.strip() != container_name]
            for orphan in orphaned_containers:
                try:
                    subprocess.run(["docker", "rm", "-f", orphan], capture_output=True, timeout=10)
                    logger.info("Cleaned up orphaned container: %s", orphan)
                except Exception:
                    pass  # Don't fail if we can't clean up orphans

    except Exception:
        pass  # Orphan cleanup is best-effort

    log = {
        "agent": "cleanup",
        "status": "COMPLETED",
        "started_at": start.isoformat(),
        "completed_at": datetime.utcnow().isoformat(),
    }
    return {"findings": findings, "agent_log": log, "fid": fid}