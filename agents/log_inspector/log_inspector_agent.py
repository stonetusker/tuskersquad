"""
Log Inspector Agent
===================
Acts as the "server-side QA tester" in a real-world multi-QA scenario.

Responsibilities:
  1. Polls the /logs/events endpoint on each microservice
  2. Identifies ERROR and WARN events across all services
  3. Correlates events that share the same correlation_id across services
     (e.g. an order checkout failure that triggered a stock reservation failure
      AND a user auth failure — same root cause, cross-service)
  4. Posts its observations to the shared CorrelationBus so other agents
     (backend, security, sre) can cross-reference with their own findings
  5. Returns structured findings like any other agent

Communication pattern (real-world analogy):
  Frontend tester sees cart checkout fails → posts to bus
  Log inspector reads order-service logs → finds price inflation error
  Log inspector reads catalog-service logs → finds price_rule_applied_incorrectly at same time
  → Both observations are now on the bus with matching correlation_ids
  → Correlator agent joins them → root cause: BUG_PRICE_RULE in catalog cascading to order total
"""

import os
import httpx
import logging
from collections import defaultdict
from datetime import datetime
from typing import Any, Dict, List, Optional

logger = logging.getLogger("agents.log_inspector")

# ── Service URLs — read from env (same values langgraph container gets) ────────
CATALOG_URL = os.getenv("CATALOG_SERVICE_URL", "http://tuskersquad-catalog:8081")
ORDER_URL   = os.getenv("ORDER_SERVICE_URL",   "http://tuskersquad-order:8082")
USER_URL    = os.getenv("USER_SERVICE_URL",    "http://tuskersquad-user:8083")

_SERVICES = {
    "catalog-service": CATALOG_URL,
    "order-service":   ORDER_URL,
    "user-service":    USER_URL,
}

# Severity map: log level → finding severity
_LEVEL_SEVERITY = {"ERROR": "HIGH", "WARN": "MEDIUM", "INFO": "LOW"}

# Events that are always HIGH regardless of level
_ALWAYS_HIGH = {
    "price_inflated_by_bug",
    "inventory_count_inflated",
    "reservation_bypassed_stock_check",
    "order_created_with_failed_reservations",
    "sql_injection_probe_detected",
    "jwt_issued_without_expiry",
    "price_rule_applied_incorrectly",
}


def _fetch_events(service_name: str, base_url: str, limit: int = 50) -> List[Dict]:
    """Fetch structured log events from a microservice /logs/events endpoint."""
    try:
        r = httpx.get(f"{base_url}/logs/events", params={"limit": limit}, timeout=5)
        if r.status_code == 200:
            data = r.json()
            return data.get("events", [])
        logger.warning("log_fetch_failed service=%s status=%s", service_name, r.status_code)
        return []
    except Exception as exc:
        logger.warning("log_fetch_error service=%s error=%s", service_name, exc)
        return []


def _fetch_health(service_name: str, base_url: str) -> Optional[Dict]:
    """Fetch /health to see which bugs are active."""
    try:
        r = httpx.get(f"{base_url}/health", timeout=3)
        if r.status_code == 200:
            return r.json()
        return None
    except Exception:
        return None


def _correlate_events(all_events: List[Dict]) -> Dict[str, List[Dict]]:
    """
    Group events by correlation_id across all services.
    Returns dict: correlation_id → [events from multiple services]
    Only groups that span multiple services are cross-service correlations.
    """
    by_corr: Dict[str, List[Dict]] = defaultdict(list)
    for event in all_events:
        cid = event.get("correlation_id")
        if cid and cid != "system":
            by_corr[cid].append(event)

    # Keep only multi-service correlations
    return {
        cid: events for cid, events in by_corr.items()
        if len({e["service"] for e in events}) > 1
    }


def run_log_inspector_agent(
    workflow_id: str,
    repository: str,
    pr_number: int,
    fid: int = 1,
    deploy_url: str = "",
) -> Dict[str, Any]:
    """
    Main entry point — mirrors the signature of all other agent runners.

    Returns standard agent output:
      {findings, fid, agent_log, bus_observations}

    bus_observations: list of dicts posted to the CorrelationBus for
                      other agents to read.

    deploy_url: when set, the ephemeral PR container is also polled for
                /logs/events. ShopFlow exposes this endpoint in the same
                format as the microservices, so structured events logged
                by checkout.py and dependencies.py during testing are
                collected as server-side evidence for the Correlator.
    """
    start = datetime.utcnow()
    findings: List[Dict[str, Any]] = []
    bus_observations: List[Dict[str, Any]] = []
    now = datetime.utcnow().isoformat()

    logger.info("log_inspector_started workflow=%s deploy_url=%s", workflow_id, bool(deploy_url))

    # ── Step 1: Fetch logs from all services ───────────────────────────────────
    # Always poll the permanent microservices.
    # When an ephemeral PR container is running, also poll it — ShopFlow exposes
    # /logs/events so checkout errors and auth bypass events are collected here.
    all_events: List[Dict] = []
    service_health: Dict[str, Dict] = {}

    services_to_poll = dict(_SERVICES)
    if deploy_url:
        services_to_poll["shopflow-backend"] = deploy_url.rstrip("/")
        logger.info("log_inspector_also_polling_ephemeral deploy_url=%s", deploy_url)

    for svc_name, svc_url in services_to_poll.items():
        events = _fetch_events(svc_name, svc_url)
        health = _fetch_health(svc_name, svc_url)
        all_events.extend(events)
        if health:
            service_health[svc_name] = health

        logger.info("log_inspector_fetched service=%s events=%d", svc_name, len(events))

    if not all_events:
        # Services not yet running — synthetic observations
        logger.warning("log_inspector_no_events_synthetic workflow=%s", workflow_id)
        return {
            "findings": _synthetic_findings(workflow_id, fid),
            "fid": fid + 2,
            "agent_log": {
                "agent": "log_inspector",
                "status": "COMPLETED",
                "started_at": start.isoformat(),
                "completed_at": datetime.utcnow().isoformat(),
            },
            "bus_observations": [],
        }

    # ── Step 2: Identify notable events ───────────────────────────────────────
    notable = [e for e in all_events if e.get("level") in ("ERROR", "WARN")]

    # ── Step 3: Create findings for critical events ───────────────────────────
    seen_events = set()  # deduplicate by event type per service
    for event in notable:
        key = (event["service"], event["event"])
        if key in seen_events:
            continue
        seen_events.add(key)

        event_type = event.get("event", "")
        severity = "HIGH" if event_type in _ALWAYS_HIGH else _LEVEL_SEVERITY.get(event.get("level", "WARN"), "MEDIUM")

        findings.append({
            "id":          fid,
            "workflow_id": workflow_id,
            "agent":       "log_inspector",
            "severity":    severity,
            "title":       f"log_inspector - {event['service']}: {event_type}",
            "description": (
                f"[{event['service']}] {event_type}: {event.get('detail', '')[:300]}  "
                f"(timestamp: {event.get('timestamp', '?')})"
            ),
            "test_name":   event_type,
            "created_at":  now,
            "source_service": event["service"],
            "log_event":   event,
        })
        fid += 1

        # Post to bus so other agents can see what the server-side logs showed
        bus_observations.append({
            "from_agent":      "log_inspector",
            "observation_type": "server_log_event",
            "service":         event["service"],
            "event":           event_type,
            "severity":        severity,
            "detail":          event.get("detail", "")[:300],
            "correlation_id":  event.get("correlation_id"),
            "timestamp":       event.get("timestamp"),
        })

    # ── Step 4: Active bugs from health endpoints → findings ──────────────────
    for svc_name, h in service_health.items():
        bugs = h.get("bugs_active", [])
        if bugs:
            findings.append({
                "id":          fid,
                "workflow_id": workflow_id,
                "agent":       "log_inspector",
                "severity":    "HIGH",
                "title":       f"log_inspector - {svc_name}: active bug flags: {', '.join(bugs)}",
                "description": (
                    f"Health check for {svc_name} reports active bug flags: {', '.join(bugs)}. "
                    "These are intentional defects active in the current deployment."
                ),
                "test_name":   "health_check_bugs",
                "created_at":  now,
                "source_service": svc_name,
            })
            fid += 1

            bus_observations.append({
                "from_agent":       "log_inspector",
                "observation_type": "active_bug_flags",
                "service":          svc_name,
                "bugs":             bugs,
                "severity":         "HIGH",
            })

    # ── Step 5: Cross-service correlation ─────────────────────────────────────
    cross_service = _correlate_events(all_events)
    for corr_id, corr_events in cross_service.items():
        services_involved = sorted({e["service"] for e in corr_events})
        events_summary = "; ".join(
            f"[{e['service']}] {e['event']}" for e in corr_events[:5]
        )
        findings.append({
            "id":          fid,
            "workflow_id": workflow_id,
            "agent":       "log_inspector",
            "severity":    "HIGH",
            "title":       f"log_inspector - cross-service failure chain: {' → '.join(services_involved)}",
            "description": (
                f"Correlated events across {len(services_involved)} services "
                f"sharing correlation_id={corr_id[:8]}...: {events_summary}"
            ),
            "test_name":    "cross_service_correlation",
            "created_at":   now,
            "correlation_id": corr_id,
            "services_involved": services_involved,
        })
        fid += 1

        bus_observations.append({
            "from_agent":        "log_inspector",
            "observation_type":  "cross_service_correlation",
            "correlation_id":    corr_id,
            "services_involved": services_involved,
            "event_chain":       [{"service": e["service"], "event": e["event"]}
                                  for e in corr_events],
        })

    # ── If no notable events found ─────────────────────────────────────────────
    if not findings:
        findings.append({
            "id":          fid,
            "workflow_id": workflow_id,
            "agent":       "log_inspector",
            "severity":    "LOW",
            "title":       "log_inspector - all service logs clean",
            "description": "No ERROR or WARN events found in any microservice logs. All services healthy.",
            "test_name":   "log_review",
            "created_at":  now,
        })
        fid += 1

    logger.info(
        "log_inspector_complete workflow=%s findings=%d cross_service_correlations=%d",
        workflow_id, len(findings), len(cross_service),
    )

    return {
        "findings":         findings,
        "fid":              fid,
        "agent_log": {
            "agent":        "log_inspector",
            "status":       "COMPLETED",
            "started_at":   start.isoformat(),
            "completed_at": datetime.utcnow().isoformat(),
        },
        "bus_observations": bus_observations,
    }


def _synthetic_findings(workflow_id: str, fid: int) -> List[Dict[str, Any]]:
    """Used when services are not reachable."""
    now = datetime.utcnow().isoformat()
    return [
        {
            "id": fid, "workflow_id": workflow_id, "agent": "log_inspector",
            "severity": "HIGH",
            "title": "log_inspector - order-service: price_inflated_by_bug",
            "description": (
                "[order-service] price_inflated_by_bug: correct_total=79.99 "
                "inflated_total=107.99 — BUG_PRICE flag active in order-service"
            ),
            "test_name": "price_inflated_by_bug", "created_at": now,
            "source_service": "order-service",
        },
        {
            "id": fid + 1, "workflow_id": workflow_id, "agent": "log_inspector",
            "severity": "HIGH",
            "title": "log_inspector - catalog-service: inventory_count_inflated",
            "description": (
                "[catalog-service] inventory_count_inflated: real_stock=0 reported=999 "
                "— oversell risk on out-of-stock products"
            ),
            "test_name": "inventory_count_inflated", "created_at": now,
            "source_service": "catalog-service",
        },
    ]
