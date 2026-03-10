"""
Tester Agent
============
Executes automated tests against deployed ephemeral environment.
"""

import logging
import os
import subprocess
import json
from datetime import datetime
from typing import Any, Dict, List

logger = logging.getLogger("agents.tester")


def run_tester_agent(
    workflow_id: Any,
    repository: str,
    pr_number: int,
    deploy_url: str = "",
    fid: int = 1,
) -> Dict[str, Any]:
    """
    Tester agent — runs automated tests against deployed application.
    """
    start = datetime.utcnow()

    findings = []
    test_results = {}
    test_success = False

    try:
        if not deploy_url:
            findings.append({
                "id": fid,
                "agent": "tester",
                "severity": "HIGH",
                "title": "No deployment URL available",
                "description": "Cannot run tests - no deployed application URL from deployer agent",
                "test_name": "url_check",
            })
            return {
                "findings": findings,
                "agent_log": {
                    "agent": "tester",
                    "status": "COMPLETED",
                    "started_at": start.isoformat(),
                    "completed_at": datetime.utcnow().isoformat(),
                    "test_success": False,
                },
                "fid": fid,
                "test_success": False,
                "test_results": test_results,
            }

        # Basic health check
        health_cmd = ["curl", "-f", "-s", "--max-time", "10", f"{deploy_url}/health"]
        health_result = subprocess.run(health_cmd, capture_output=True, text=True, timeout=15)

        if health_result.returncode != 0:
            findings.append({
                "id": fid,
                "agent": "tester",
                "severity": "HIGH",
                "title": "Application health check failed",
                "description": f"Health endpoint not responding at {deploy_url}/health",
                "test_name": "health_check",
            })
            fid += 1
        else:
            findings.append({
                "id": fid,
                "agent": "tester",
                "severity": "LOW",
                "title": "Application health check passed",
                "description": f"Health endpoint responding correctly at {deploy_url}",
                "test_name": "health_check",
            })
            fid += 1

            # API endpoint tests
            api_tests = [
                {"endpoint": "/products", "method": "GET", "expected_status": 200},
                {"endpoint": "/auth/login", "method": "POST", "expected_status": 422},  # Validation error expected
                {"endpoint": "/checkout", "method": "POST", "expected_status": 401},  # Auth required
            ]

            api_passed = 0
            api_total = len(api_tests)

            for test in api_tests:
                try:
                    cmd = ["curl", "-s", "-o", "/dev/null", "-w", "%{http_code}", "--max-time", "10",
                           "-X", test["method"], f"{deploy_url}{test['endpoint']}"]
                    result = subprocess.run(cmd, capture_output=True, text=True, timeout=15)

                    if result.returncode == 0:
                        status_code = int(result.stdout.strip())
                        if status_code == test["expected_status"]:
                            api_passed += 1
                        else:
                            findings.append({
                                "id": fid,
                                "agent": "tester",
                                "severity": "MEDIUM",
                                "title": f"API test failed: {test['endpoint']}",
                                "description": f"Expected status {test['expected_status']}, got {status_code}",
                                "test_name": "api_test",
                            })
                            fid += 1
                    else:
                        findings.append({
                            "id": fid,
                            "agent": "tester",
                            "severity": "MEDIUM",
                            "title": f"API test error: {test['endpoint']}",
                            "description": f"Request failed: {result.stderr}",
                            "test_name": "api_test",
                        })
                        fid += 1
                except Exception as e:
                    findings.append({
                        "id": fid,
                        "agent": "tester",
                        "severity": "MEDIUM",
                        "title": f"API test exception: {test['endpoint']}",
                        "description": f"Test failed with exception: {str(e)}",
                        "test_name": "api_test",
                    })
                    fid += 1

            test_results["api_tests"] = {"passed": api_passed, "total": api_total}

            # Performance test - basic load test
            perf_cmd = ["curl", "-s", "--max-time", "30", f"{deploy_url}/products"]
            perf_times = []

            for i in range(5):
                start_time = datetime.utcnow()
                result = subprocess.run(perf_cmd, capture_output=True, text=True, timeout=10)
                end_time = datetime.utcnow()

                if result.returncode == 0:
                    response_time = (end_time - start_time).total_seconds() * 1000  # ms
                    perf_times.append(response_time)

            if perf_times:
                avg_response_time = sum(perf_times) / len(perf_times)
                max_response_time = max(perf_times)

                test_results["performance"] = {
                    "avg_response_time_ms": avg_response_time,
                    "max_response_time_ms": max_response_time,
                    "samples": len(perf_times)
                }

                if avg_response_time > 1000:  # 1 second threshold
                    findings.append({
                        "id": fid,
                        "agent": "tester",
                        "severity": "MEDIUM",
                        "title": "Slow API response time",
                        "description": f"Average response time {avg_response_time:.1f}ms exceeds 1000ms threshold",
                        "test_name": "performance_test",
                    })
                    fid += 1
                else:
                    findings.append({
                        "id": fid,
                        "agent": "tester",
                        "severity": "LOW",
                        "title": "Performance test passed",
                        "description": f"Average response time {avg_response_time:.1f}ms within acceptable range",
                        "test_name": "performance_test",
                    })
                    fid += 1

            # Overall test success criteria
            test_success = api_passed >= api_total * 0.8  # 80% API tests pass

    except subprocess.TimeoutExpired:
        findings.append({
            "id": fid,
            "agent": "tester",
            "severity": "HIGH",
            "title": "Test execution timeout",
            "description": "Automated testing exceeded timeout limit",
            "test_name": "test_timeout",
        })
    except Exception as e:
        findings.append({
            "id": fid,
            "agent": "tester",
            "severity": "HIGH",
            "title": "Test system error",
            "description": f"Unexpected error during testing: {str(e)}",
            "test_name": "test_error",
        })

    log = {
        "agent": "tester",
        "status": "COMPLETED",
        "started_at": start.isoformat(),
        "completed_at": datetime.utcnow().isoformat(),
        "test_success": test_success,
        "test_results": test_results,
    }
    logger.info("tester_complete workflow=%s repo=%s pr=%d success=%s results=%s",
                workflow_id, repository, pr_number, test_success, test_results)

    return {
        "findings": findings,
        "agent_log": log,
        "fid": fid,
        "test_success": test_success,
        "test_results": test_results,
    }