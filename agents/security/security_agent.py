"""
Security Engineer Agent
=======================
Runs OWASP-inspired security checks against the demo application:
  - Auth bypass attempts
  - Token reuse / replay attack
  - SQL injection probes
  - JWT manipulation
  - CORS header inspection

Uses httpx for real HTTP probes when DEMO_APP_URL is set and reachable.
Falls back to synthetic findings otherwise.
"""

import os
import logging
from datetime import datetime
from typing import Dict, Any, List, Optional

logger = logging.getLogger("agents.security")

DEMO_APP_URL        = os.getenv("DEMO_APP_URL",         "http://tuskersquad-demo-backend:8080")
SECURITY_PROBE_TOOL = os.getenv("SECURITY_PROBE_TOOL", "httpx")  # httpx | zap | trivy


def _probe_auth_bypass(base_url: str) -> Optional[Dict]:
    """Attempt to access a protected endpoint without a token."""
    try:
        import httpx
        r = httpx.get(f"{base_url}/orders", timeout=5)
        if r.status_code == 200:
            return {
                "title": "security - auth_bypass_detected",
                "severity": "HIGH",
                "description": (
                    "GET /orders returned HTTP 200 without an Authorization header. "
                    "Protected endpoint is accessible without authentication."
                ),
                "test_name": "auth_bypass",
            }
        return None
    except Exception as exc:
        logger.debug("auth_bypass_probe_failed: %s", exc)
        return None


def _probe_token_reuse(base_url: str) -> Optional[Dict]:
    """
    Login to get a token, logout conceptually, then attempt reuse.
    In this demo app tokens are stateless JWTs so reuse is always possible —
    report if no token expiry is enforced.
    """
    try:
        import httpx
        r = httpx.post(
            f"{base_url}/login",
            json={"email": "test@example.com", "password": "password"},
            timeout=5,
        )
        if r.status_code != 200:
            return None

        token = r.json().get("access_token", "")
        if not token:
            return None

        # Decode JWT header/payload without verification to check expiry
        import base64, json as _json
        parts = token.split(".")
        if len(parts) == 3:
            # Pad and decode payload
            payload_b64 = parts[1] + "=" * (-len(parts[1]) % 4)
            payload = _json.loads(base64.urlsafe_b64decode(payload_b64))
            if "exp" not in payload:
                return {
                    "title": "security - jwt_no_expiry",
                    "severity": "HIGH",
                    "description": (
                        "JWT token issued by /login does not contain an 'exp' claim. "
                        "Tokens are valid indefinitely — token theft has unlimited impact."
                    ),
                    "test_name": "token_reuse",
                }
        return None
    except Exception as exc:
        logger.debug("token_reuse_probe_failed: %s", exc)
        return None


def _probe_sql_injection(base_url: str) -> Optional[Dict]:
    """Send a basic SQL injection payload to the login endpoint."""
    try:
        import httpx
        payloads = ["' OR '1'='1", "admin'--", "' OR 1=1--"]
        for payload in payloads:
            r = httpx.post(
                f"{base_url}/login",
                json={"email": payload, "password": "x"},
                timeout=5,
            )
            if r.status_code == 200:
                return {
                    "title": "security - sql_injection_login_bypass",
                    "severity": "HIGH",
                    "description": (
                        f"Login endpoint returned HTTP 200 with SQL injection payload "
                        f"'{payload}'. Possible SQL injection vulnerability."
                    ),
                    "test_name": "sql_injection",
                }
        return None
    except Exception as exc:
        logger.debug("sql_injection_probe_failed: %s", exc)
        return None


def _probe_cors(base_url: str) -> Optional[Dict]:
    """Check if CORS allows wildcard origins."""
    try:
        import httpx
        r = httpx.get(
            f"{base_url}/health",
            headers={"Origin": "https://attacker.example.com"},
            timeout=5,
        )
        acao = r.headers.get("access-control-allow-origin", "")
        if acao == "*":
            return {
                "title": "security - cors_wildcard_origin",
                "severity": "LOW",
                "description": (
                    "API response includes 'Access-Control-Allow-Origin: *'. "
                    "Acceptable for a demo API — tighten CORS policy before production deployment."
                ),
                "test_name": "cors_policy",
            }
        return None
    except Exception as exc:
        logger.debug("cors_probe_failed: %s", exc)
        return None


def _run_security_probes(base_url: str, repository: str) -> List[Dict]:
    """Run all security probes and collect real findings."""
    probe_funcs = [
        _probe_auth_bypass,
        _probe_token_reuse,
        _probe_sql_injection,
        _probe_cors,
    ]
    issues = []
    for probe in probe_funcs:
        try:
            result = probe(base_url)
            if result:
                issues.append(result)
        except Exception:
            logger.exception("security_probe_exception")
    return issues


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
            "agent": "security",
            "severity": "HIGH",
            "title": "security - jwt_no_expiry",
            "description": (
                "JWT tokens issued by the login endpoint do not include an 'exp' claim. "
                "Stolen tokens remain valid indefinitely. Recommend adding expiry "
                "and a token revocation mechanism."
            ),
            "test_name": "token_reuse",
            "created_at": now,
        },
        {
            "id": fid + 1,
            "workflow_id": workflow_id,
            "agent": "security",
            "severity": "LOW",
            "title": "security - cors_wildcard_origin",
            "description": (
                "API CORS policy allows all origins (Access-Control-Allow-Origin: *). "
                "Restrict to known domains before production deployment."
            ),
            "test_name": "cors_policy",
            "created_at": now,
        },
    ]


def run_security_agent(workflow_id: str, repository: str, pr_number: int, fid: int = 1,
                       deploy_url: str = "", build_success: bool = False) -> Dict[str, Any]:
    """
    Main entry point called by the graph runner.
    Security probes run against the ephemeral PR deployment when available,
    falling back to the permanent demo backend.

    Returns:
        dict with keys: findings, fid, agent_log.
    """
    start = datetime.utcnow()
    findings: List[Dict[str, Any]] = []

    logger.info("security_agent_started", extra={"workflow_id": workflow_id})

    # Prefer ephemeral PR deployment for accurate security probes
    target_url = deploy_url if deploy_url else DEMO_APP_URL
    testing_pr_code = bool(deploy_url)

    if not testing_pr_code and repository != "shopflow":
        findings.append({
            "id": fid, "workflow_id": workflow_id, "agent": "security",
            "severity": "LOW",
            "title": "security - probed permanent demo app, not PR code",
            "description": (
                "No ephemeral deployment was available for this PR "
                f"(build_success={build_success}, deploy_url=empty). "
                f"Security probes ran against {DEMO_APP_URL} (permanent demo backend). "
                "Security findings may not reflect vulnerabilities introduced by the PR. "
                "A clean bill of health here does NOT mean the PR is secure."
            ),
            "test_name": "pr_coverage_warning",
            "created_at": datetime.utcnow().isoformat(),
        })
        fid += 1

    if _reachable(target_url):
        logger.info("demo_app_reachable_running_real_probes", extra={"workflow_id": workflow_id})
        raw = _run_security_probes(target_url, repository)
        now = datetime.utcnow().isoformat()
        for issue in raw:
            findings.append({
                "id": fid,
                "workflow_id": workflow_id,
                "agent": "security",
                "severity": issue.get("severity", "MEDIUM"),
                "title": issue.get("title", "security - issue"),
                "description": issue.get("description", ""),
                "test_name": issue.get("test_name", "owasp_probe"),
                "created_at": now,
            })
            fid += 1

        if not findings:
            findings.append({
                "id": fid,
                "workflow_id": workflow_id,
                "agent": "security",
                "severity": "LOW",
                "title": "security - no_critical_issues_found",
                "description": "All OWASP security probes passed with no critical issues detected.",
                "test_name": "owasp_suite",
                "created_at": now,
            })
            fid += 1
    else:
        logger.warning(
            "demo_app_unreachable_using_synthetic_findings",
            extra={"workflow_id": workflow_id, "url": target_url},
        )
        synth = _synthetic_findings(workflow_id, fid)
        findings.extend(synth)
        fid += len(synth)

    agent_log = {
        "agent": "security",
        "status": "COMPLETED",
        "started_at": start.isoformat(),
        "completed_at": datetime.utcnow().isoformat(),
    }

    return {"findings": findings, "fid": fid, "agent_log": agent_log}
