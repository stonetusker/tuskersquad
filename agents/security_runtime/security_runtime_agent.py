"""
Security Runtime Agent
======================
Scans the container image for vulnerabilities or leaked secrets using external tools.
"""

import logging
import subprocess
from datetime import datetime
from typing import Any, Dict, List

logger = logging.getLogger("agents.security_runtime")


def run_security_runtime_agent(
    workflow_id: Any,
    repository: str,
    pr_number: int,
    build_artifacts: Dict[str, Any] = None,
    fid: int = 1,
) -> Dict[str, Any]:
    start = datetime.utcnow()
    findings: List[Dict[str, Any]] = []

    image = None
    if build_artifacts:
        image = build_artifacts.get("docker_image")

    if not image:
        findings.append({
            "id": fid,
            "agent": "security_runtime",
            "severity": "MEDIUM",
            "title": "No image to scan",
            "description": "Build did not produce a Docker image",
            "test_name": "image_check",
        })
        fid += 1
    else:
        # scan with trivy if available
        try:
            scan_cmd = ["trivy", "image", "--quiet", "--no-progress", image]
            result = subprocess.run(scan_cmd, capture_output=True, text=True, timeout=600)
            output = result.stdout + result.stderr
            if result.returncode != 0:
                findings.append({
                    "id": fid,
                    "agent": "security_runtime",
                    "severity": "HIGH",
                    "title": "Trivy scan failure",
                    "description": output[:500],
                    "test_name": "trivy_scan",
                })
            else:
                # parse vulnerabilities summary lines
                if "CRITICAL" in output or "HIGH" in output:
                    findings.append({
                        "id": fid,
                        "agent": "security_runtime",
                        "severity": "MEDIUM",
                        "title": "Vulnerabilities detected",
                        "description": "Image scan reports high/critical vulnerabilities",
                        "test_name": "trivy_vulns",
                    })
            fid += 1
        except FileNotFoundError:
            # tool not present; just log
            logger.info("trivy not installed, skipping security scan")
        except Exception as e:
            findings.append({
                "id": fid,
                "agent": "security_runtime",
                "severity": "LOW",
                "title": "Security scan error",
                "description": str(e),
                "test_name": "trivy_error",
            })
            fid += 1

    log = {
        "agent": "security_runtime",
        "status": "COMPLETED",
        "started_at": start.isoformat(),
        "completed_at": datetime.utcnow().isoformat(),
    }
    return {"findings": findings, "agent_log": log, "fid": fid}