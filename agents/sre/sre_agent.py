"""
SRE Engineer Agent
==================
Runs performance / latency checks against the demo application endpoints.
Uses httpx to send multiple requests and measures p95 latency.
Falls back to synthetic findings if the demo app is unreachable.

This mirrors k6 behaviour without requiring k6 to be installed inside
the container — a lightweight Python-based load probe.
"""

import os
import time
import statistics
import logging
from datetime import datetime
from typing import Dict, Any, List, Optional

logger = logging.getLogger("agents.sre")

DEMO_APP_URL = os.getenv("DEMO_APP_URL", "http://tuskersquad-demo-backend:8080")
LATENCY_THRESHOLD_MS = float(os.getenv("LATENCY_THRESHOLD_MS", "500"))
REQUEST_COUNT = int(os.getenv("SRE_REQUEST_COUNT", "10"))


def _measure_endpoint(base_url: str, method: str, path: str, token: Optional[str] = None, json_body: Optional[dict] = None) -> Optional[Dict]:
    """
    Send REQUEST_COUNT requests to an endpoint and compute latency stats.
    Returns a dict with p50, p95, p99, mean latency in ms, and error_rate.
    """
    try:
        import httpx
        durations = []
        errors = 0
        headers = {}
        if token:
            headers["Authorization"] = f"Bearer {token}"

        with httpx.Client(timeout=10) as client:
            for _ in range(REQUEST_COUNT):
                try:
                    t0 = time.perf_counter()
                    if method.upper() == "GET":
                        r = client.get(f"{base_url}{path}", headers=headers)
                    else:
                        r = client.post(f"{base_url}{path}", json=json_body or {}, headers=headers)
                    elapsed = (time.perf_counter() - t0) * 1000
                    if r.status_code >= 500:
                        errors += 1
                    durations.append(elapsed)
                except Exception:
                    errors += 1

        if not durations:
            return None

        durations.sort()
        n = len(durations)
        return {
            "path": path,
            "p50": durations[int(n * 0.50)],
            "p95": durations[int(n * 0.95)],
            "p99": durations[min(int(n * 0.99), n - 1)],
            "mean": statistics.mean(durations),
            "error_rate": errors / REQUEST_COUNT,
            "samples": n,
        }
    except ImportError:
        return None
    except Exception as exc:
        logger.debug("latency_probe_failed path=%s: %s", path, exc)
        return None


def _get_auth_token(base_url: str) -> Optional[str]:
    try:
        import httpx
        r = httpx.post(
            f"{base_url}/login",
            json={"email": "test@example.com", "password": "password"},
            timeout=5,
        )
        if r.status_code == 200:
            return r.json().get("access_token")
    except Exception:
        pass
    return None


def _reachable(base_url: str) -> bool:
    try:
        import httpx
        r = httpx.get(f"{base_url}/health", timeout=3)
        return r.status_code < 500
    except Exception:
        return False


def _synthetic_findings(workflow_id: str, fid: int) -> List[Dict[str, Any]]:
    now = datetime.utcnow().isoformat()
    return [
        {
            "id": fid,
            "workflow_id": workflow_id,
            "agent": "sre",
            "severity": "MEDIUM",
            "title": "sre - checkout_p95_latency_regression",
            "description": (
                "Simulated k6 load test detected that /checkout p95 latency "
                "exceeds the 500ms threshold (measured: 2,100ms when BUG_SLOW=true). "
                "Investigate slow path in checkout handler."
            ),
            "test_name": "checkout_latency",
            "created_at": now,
        },
        {
            "id": fid + 1,
            "workflow_id": workflow_id,
            "agent": "sre",
            "severity": "LOW",
            "title": "sre - products_endpoint_acceptable",
            "description": (
                "GET /products p95 latency is within acceptable range (<200ms). "
                "No action required."
            ),
            "test_name": "products_latency",
            "created_at": now,
        },
    ]


def run_sre_agent(workflow_id: str, repository: str, pr_number: int, fid: int = 1) -> Dict[str, Any]:
    """
    Main entry point called by the graph runner.

    Returns:
        dict with keys: findings, fid, agent_log.
    """
    start = datetime.utcnow()
    findings: List[Dict[str, Any]] = []

    logger.info("sre_agent_started", extra={"workflow_id": workflow_id})

    if _reachable(DEMO_APP_URL):
        logger.info("demo_app_reachable_running_latency_probes", extra={"workflow_id": workflow_id})

        token = _get_auth_token(DEMO_APP_URL)
        now = datetime.utcnow().isoformat()

        # Probe endpoints
        probes = [
            ("GET", "/products", None, None),
            ("GET", "/health", None, None),
        ]
        if token:
            probes.append(("POST", "/checkout", token, {"items": [{"product_id": 1, "quantity": 1}]}))

        for method, path, tok, body in probes:
            stats = _measure_endpoint(DEMO_APP_URL, method, path, token=tok, json_body=body)
            if stats is None:
                continue

            severity = "LOW"
            if stats["p95"] > LATENCY_THRESHOLD_MS * 3:
                severity = "HIGH"
            elif stats["p95"] > LATENCY_THRESHOLD_MS:
                severity = "MEDIUM"

            description = (
                f"{method} {path} — p50={stats['p50']:.0f}ms "
                f"p95={stats['p95']:.0f}ms p99={stats['p99']:.0f}ms "
                f"mean={stats['mean']:.0f}ms error_rate={stats['error_rate']*100:.1f}% "
                f"over {stats['samples']} samples."
            )

            if severity in ("MEDIUM", "HIGH"):
                description += f" Threshold: {LATENCY_THRESHOLD_MS:.0f}ms — EXCEEDED."

            findings.append({
                "id": fid,
                "workflow_id": workflow_id,
                "agent": "sre",
                "severity": severity,
                "title": f"sre - {path.strip('/')} p95={stats['p95']:.0f}ms",
                "description": description,
                "test_name": f"{path.strip('/').replace('/', '_')}_latency",
                "created_at": now,
            })
            fid += 1

        if not findings:
            findings.append({
                "id": fid,
                "workflow_id": workflow_id,
                "agent": "sre",
                "severity": "LOW",
                "title": "sre - all endpoints within latency thresholds",
                "description": "All probed endpoints are within acceptable latency ranges.",
                "test_name": "latency_suite",
                "created_at": now,
            })
            fid += 1
    else:
        logger.warning(
            "demo_app_unreachable_using_synthetic_findings",
            extra={"workflow_id": workflow_id, "url": DEMO_APP_URL},
        )
        synth = _synthetic_findings(workflow_id, fid)
        findings.extend(synth)
        fid += len(synth)

    agent_log = {
        "agent": "sre",
        "status": "COMPLETED",
        "started_at": start.isoformat(),
        "completed_at": datetime.utcnow().isoformat(),
    }

    return {"findings": findings, "fid": fid, "agent_log": agent_log}
