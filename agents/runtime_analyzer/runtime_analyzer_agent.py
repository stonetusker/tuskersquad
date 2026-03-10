"""
Runtime Analyzer Agent
======================
Analyzes runtime behavior and test results from deployed application.
"""

import logging
import os
import subprocess
import json
from datetime import datetime
from typing import Any, Dict, List

logger = logging.getLogger("agents.runtime_analyzer")


def run_runtime_analyzer_agent(
    workflow_id: Any,
    repository: str,
    pr_number: int,
    deploy_url: str = "",
    test_results: Dict[str, Any] = None,
    container_name: str = "",
    fid: int = 1,
) -> Dict[str, Any]:
    """
    Runtime analyzer agent — analyzes application runtime behavior and correlates with test results.
    """
    start = datetime.utcnow()

    findings = []
    analysis_results = {}

    try:
        if not deploy_url:
            findings.append({
                "id": fid,
                "agent": "runtime_analyzer",
                "severity": "HIGH",
                "title": "No deployment for analysis",
                "description": "Cannot analyze runtime - no deployed application URL available",
                "test_name": "deployment_check",
            })
            return {
                "findings": findings,
                "agent_log": {
                    "agent": "runtime_analyzer",
                    "status": "COMPLETED",
                    "started_at": start.isoformat(),
                    "completed_at": datetime.utcnow().isoformat(),
                },
                "fid": fid,
                "analysis_results": analysis_results,
            }

        # Analyze container logs if container name available
        if container_name:
            try:
                logs_cmd = ["docker", "logs", "--tail", "100", container_name]
                logs_result = subprocess.run(logs_cmd, capture_output=True, text=True, timeout=30)

                if logs_result.returncode == 0:
                    logs = logs_result.stdout + logs_result.stderr

                    # Analyze logs for common issues
                    error_patterns = [
                        ("ERROR", "HIGH", "Error messages in logs"),
                        ("Exception", "HIGH", "Exceptions in logs"),
                        ("WARN", "MEDIUM", "Warning messages in logs"),
                        ("timeout", "MEDIUM", "Timeout issues detected"),
                        ("connection refused", "MEDIUM", "Connection issues detected"),
                    ]

                    log_findings = []
                    for pattern, severity, description in error_patterns:
                        if pattern.lower() in logs.lower():
                            count = logs.lower().count(pattern.lower())
                            log_findings.append({
                                "pattern": pattern,
                                "severity": severity,
                                "description": f"{description} ({count} occurrences)",
                                "count": count
                            })

                    analysis_results["log_analysis"] = {
                        "total_lines": len(logs.split('\n')),
                        "findings": log_findings
                    }

                    # Add findings for critical issues
                    for finding in log_findings:
                        if finding["severity"] == "HIGH":
                            findings.append({
                                "id": fid,
                                "agent": "runtime_analyzer",
                                "severity": finding["severity"],
                                "title": f"Runtime log issue: {finding['pattern']}",
                                "description": finding["description"],
                                "test_name": "log_analysis",
                            })
                            fid += 1

                else:
                    findings.append({
                        "id": fid,
                        "agent": "runtime_analyzer",
                        "severity": "MEDIUM",
                        "title": "Could not retrieve container logs",
                        "description": f"Failed to get logs from container {container_name}",
                        "test_name": "log_retrieval",
                    })
                    fid += 1

            except subprocess.TimeoutExpired:
                findings.append({
                    "id": fid,
                    "agent": "runtime_analyzer",
                    "severity": "LOW",
                    "title": "Log analysis timeout",
                    "description": "Log retrieval timed out",
                    "test_name": "log_timeout",
                })
                fid += 1

        # Analyze test results correlation
        if test_results:
            analysis_results["test_correlation"] = test_results

            # API test analysis
            api_results = test_results.get("api_tests", {})
            if api_results:
                api_pass_rate = api_results.get("passed", 0) / api_results.get("total", 1)
                if api_pass_rate < 0.8:
                    findings.append({
                        "id": fid,
                        "agent": "runtime_analyzer",
                        "severity": "HIGH",
                        "title": "Low API test pass rate",
                        "description": f"Only {api_pass_rate:.1%} of API tests passed ({api_results.get('passed', 0)}/{api_results.get('total', 0)})",
                        "test_name": "api_test_analysis",
                    })
                    fid += 1

            # Performance analysis
            perf_results = test_results.get("performance", {})
            if perf_results:
                avg_time = perf_results.get("avg_response_time_ms", 0)
                if avg_time > 2000:  # 2 second threshold for runtime analysis
                    findings.append({
                        "id": fid,
                        "agent": "runtime_analyzer",
                        "severity": "MEDIUM",
                        "title": "Runtime performance degradation",
                        "description": f"Average response time {avg_time:.1f}ms indicates potential performance issues",
                        "test_name": "performance_analysis",
                    })
                    fid += 1

        # Runtime behavior analysis - check for memory leaks, etc.
        try:
            # Get container stats
            if container_name:
                stats_cmd = ["docker", "stats", "--no-stream", "--format", "json", container_name]
                stats_result = subprocess.run(stats_cmd, capture_output=True, text=True, timeout=10)

                if stats_result.returncode == 0:
                    try:
                        stats = json.loads(stats_result.stdout)
                        analysis_results["container_stats"] = {
                            "cpu_percent": stats.get("CPUPerc", "0%"),
                            "memory_usage": stats.get("MemUsage", "unknown"),
                            "memory_percent": stats.get("MemPerc", "0%"),
                        }
                    except json.JSONDecodeError:
                        pass
        except Exception:
            pass  # Non-critical if stats collection fails

        # Overall runtime health assessment
        runtime_healthy = True
        high_severity_findings = [f for f in findings if f.get("severity") == "HIGH"]
        if high_severity_findings:
            runtime_healthy = False

        analysis_results["runtime_health"] = {
            "healthy": runtime_healthy,
            "high_priority_issues": len(high_severity_findings),
            "total_findings": len(findings)
        }

        if runtime_healthy:
            findings.append({
                "id": fid,
                "agent": "runtime_analyzer",
                "severity": "LOW",
                "title": "Runtime analysis completed",
                "description": "Application runtime behavior appears healthy with no critical issues detected",
                "test_name": "runtime_health_check",
            })
            fid += 1

    except Exception as e:
        findings.append({
            "id": fid,
            "agent": "runtime_analyzer",
            "severity": "HIGH",
            "title": "Runtime analysis error",
            "description": f"Unexpected error during runtime analysis: {str(e)}",
            "test_name": "analysis_error",
        })

    log = {
        "agent": "runtime_analyzer",
        "status": "COMPLETED",
        "started_at": start.isoformat(),
        "completed_at": datetime.utcnow().isoformat(),
        "analysis_results": analysis_results,
    }
    logger.info("runtime_analyzer_complete workflow=%s repo=%s pr=%d findings=%d",
                workflow_id, repository, pr_number, len(findings))

    return {
        "findings": findings,
        "agent_log": log,
        "fid": fid,
        "analysis_results": analysis_results,
    }