"""
Correlator Agent
================
This agent is the "root cause analyst" — it reads the CorrelationBus
(shared observations posted by all agents) and performs cross-layer analysis.

Real-world analogy:
  - Frontend tester says: "checkout button returns wrong total"
  - Log inspector says:   "order-service logged price_inflated_by_bug"
  - Log inspector says:   "catalog-service logged price_rule_applied_incorrectly"
  - Correlator joins all three → root cause: price bug in catalog cascades through order

The Correlator does NOT run tests itself. It synthesises:
  1. Client-side observations   (from backend/frontend/security/sre agents)
  2. Server-side observations   (from log_inspector agent via bus)
  3. Cross-service correlations (identified by log_inspector)

Output:
  - root_cause_chains: list of causal chains with evidence
  - enhanced findings: original findings annotated with root cause context
  - developer_brief:   a concise briefing for the human reviewer

This is what gets handed to the Judge and ultimately to the human approver.
"""

import logging
import os
import asyncio
from datetime import datetime
from typing import Any, Dict, List, Optional

logger = logging.getLogger("agents.correlator")


# ── Correlation rules ─────────────────────────────────────────────────────────
# Maps a (client-side symptom) → (server-side log event) → root cause description

_CORRELATION_RULES = [
    {
        "id":              "price_bug",
        "symptom_keywords": ["price", "total", "checkout", "cost", "amount"],
        "server_events":    ["price_inflated_by_bug", "price_rule_applied_incorrectly"],
        "root_cause":       "Price calculation bug: order-service applies a 35% inflation multiplier (BUG_PRICE). "
                            "Catalog-service may also apply an incorrect VAT rule (BUG_PRICE_RULE). "
                            "These can compound: a $79.99 item becomes $145.78 (1.35 × 1.35). "
                            "Root cause: BUG_PRICE flag active in order-service checkout handler.",
        "affected_services": ["order-service", "catalog-service"],
        "severity":          "HIGH",
        "fix_hint":          "Remove the `if BUG_PRICE: total = total * 1.35` block in order_service/main.py "
                             "and verify catalog price_rule logic. Add checkout total assertion in integration tests.",
    },
    {
        "id":               "inventory_oversell",
        "symptom_keywords": ["stock", "inventory", "out of stock", "available", "quantity", "reserve"],
        "server_events":    ["inventory_count_inflated", "reservation_bypassed_stock_check",
                             "order_created_with_failed_reservations"],
        "root_cause":       "Inventory oversell bug: BUG_INVENTORY causes catalog-service to report "
                            "inflated stock counts (+999). BUG_NO_ROLLBACK causes order-service to "
                            "create orders even when stock reservation fails. "
                            "Combined effect: users can order products that are out of stock.",
        "affected_services": ["catalog-service", "order-service"],
        "severity":          "HIGH",
        "fix_hint":          "Fix stock check in catalog_service/main.py reserve_stock(). "
                             "Add rollback in order_service/main.py when reservation fails. "
                             "Add constraint test: POST /checkout with stock=0 must return 409.",
    },
    {
        "id":               "auth_jwt",
        "symptom_keywords": ["auth", "token", "jwt", "login", "unauthorised", "session", "bearer"],
        "server_events":    ["jwt_issued_without_expiry", "token_validation_failed",
                             "sql_injection_probe_detected"],
        "root_cause":       "Authentication vulnerability: BUG_JWT_NO_EXPIRY causes user-service to "
                            "issue JWTs with no expiry claim. Stolen tokens are valid indefinitely. "
                            "Additionally, login endpoint does not sanitise email inputs — "
                            "SQL injection probe patterns were detected in server logs.",
        "affected_services": ["user-service", "order-service"],
        "severity":          "HIGH",
        "fix_hint":          "Add exp claim to JWT payload in user_service/main.py _issue_jwt(). "
                             "Add input validation for email field. "
                             "Validate token expiry in /auth/validate endpoint.",
    },
    {
        "id":               "latency",
        "symptom_keywords": ["latency", "slow", "timeout", "p95", "response time", "performance"],
        "server_events":    ["checkout_slow_path_active"],
        "root_cause":       "Performance regression: BUG_SLOW flag causes order-service checkout "
                            "to sleep 3 seconds before processing. This inflates all checkout "
                            "P95 latency measurements and will cause SLA breaches under load.",
        "affected_services": ["order-service"],
        "severity":          "MEDIUM",
        "fix_hint":          "Remove `if BUG_SLOW: time.sleep(3)` from order_service/main.py. "
                             "Verify checkout P95 < 500ms in load tests.",
    },
    {
        "id":               "cross_service_failure",
        "symptom_keywords": ["cascade", "downstream", "dependency", "unreachable", "failed"],
        "server_events":    ["catalog_service_unreachable", "user_service_unreachable",
                             "catalog_lookup_failed", "user_auth_failed"],
        "root_cause":       "Service dependency failure: order-service makes synchronous calls "
                            "to catalog-service and user-service during checkout. "
                            "If either is unavailable, checkout fails entirely with no fallback. "
                            "No circuit-breaker or retry logic is present.",
        "affected_services": ["order-service", "catalog-service", "user-service"],
        "severity":          "MEDIUM",
        "fix_hint":          "Add retry with backoff and circuit-breaker pattern to order-service "
                             "outbound HTTP calls. Consider async stock reservation for resilience.",
    },
]


def _keywords_match(text: str, keywords: List[str]) -> bool:
    text_lower = text.lower()
    return any(k.lower() in text_lower for k in keywords)


def _build_rca_chain(
    rule: Dict,
    client_findings: List[Dict],
    server_observations: List[Dict],
) -> Optional[Dict]:
    """
    Try to build a causal chain for a rule by matching:
      - at least one client-side finding whose title/description matches symptom_keywords
      - OR at least one server-side observation matching server_events

    Returns a chain dict or None if no evidence.
    """
    matched_client = []
    for f in client_findings:
        text = f"{f.get('title','')} {f.get('description','')}"
        if _keywords_match(text, rule["symptom_keywords"]):
            matched_client.append(f)

    matched_server = []
    for obs in server_observations:
        event = obs.get("event", "")
        if event in rule["server_events"]:
            matched_server.append(obs)

    if not matched_client and not matched_server:
        return None

    evidence_lines = []
    for f in matched_client[:3]:
        evidence_lines.append(
            f"  [CLIENT/{f.get('agent','?').upper()}] {f.get('title','')} ({f.get('severity','')})"
        )
    for obs in matched_server[:3]:
        evidence_lines.append(
            f"  [SERVER/{obs.get('service','?').upper()}] {obs.get('event','')} — {obs.get('detail','')[:120]}"
        )

    return {
        "rule_id":           rule["id"],
        "root_cause":        rule["root_cause"],
        "affected_services": rule["affected_services"],
        "severity":          rule["severity"],
        "fix_hint":          rule["fix_hint"],
        "evidence":          evidence_lines,
        "client_finding_count": len(matched_client),
        "server_event_count":   len(matched_server),
    }


def _build_developer_brief(chains: List[Dict], cross_service: List[Dict]) -> str:
    """
    Produce a concise, developer-readable brief for the human reviewer.
    This is shown in the PR comment and the TuskerSquad dashboard.
    """
    lines = [
        "## Root Cause Analysis — Full-Stack Review",
        "",
        f"TuskerSquad performed cross-layer analysis correlating "
        f"{sum(c['client_finding_count'] for c in chains)} client-side observations "
        f"with {sum(c['server_event_count'] for c in chains)} server-side log events "
        f"across {len(set(s for c in chains for s in c['affected_services']))} microservices.",
        "",
    ]

    if chains:
        lines.append("### Confirmed Root Causes")
        lines.append("")
        for i, chain in enumerate(chains, 1):
            lines.append(f"**{i}. [{chain['severity']}] {chain['rule_id'].replace('_', ' ').title()}**")
            lines.append("")
            lines.append(f"Root cause: {chain['root_cause']}")
            lines.append("")
            lines.append("Evidence:")
            lines.extend(chain["evidence"])
            lines.append("")
            lines.append(f"Fix: {chain['fix_hint']}")
            lines.append("")

    if cross_service:
        lines.append("### Cross-Service Failure Chains")
        lines.append("")
        for cs in cross_service[:3]:
            services = " → ".join(cs.get("services_involved", []))
            lines.append(f"- **{services}**: correlated via `{cs.get('correlation_id','?')[:8]}...`")
            chain_str = " → ".join(
                f"[{e['service']}] {e['event']}"
                for e in cs.get("event_chain", [])[:4]
            )
            lines.append(f"  Chain: {chain_str}")
            lines.append("")

    if not chains and not cross_service:
        lines.append("No cross-layer root causes identified. All agent findings appear to be isolated.")

    lines.append("---")
    lines.append("*Generated by TuskerSquad Correlator — cross-layer full-stack analysis*")

    return "\n".join(lines)


def _llm_rca(chains: List[Dict], all_findings: List[Dict], bus: List[Dict],
             workflow_id: str) -> Optional[str]:
    """
    Optional LLM-enhanced RCA narrative. Only called when Ollama is available.
    The rule-based chains are always produced regardless.
    """
    if not os.getenv("OLLAMA_URL"):
        return None
    try:
        import asyncio
        from core.llm_client import get_llm_client

        def _run_async(coro):
            try:
                loop = asyncio.get_event_loop()
                if loop.is_closed():
                    return asyncio.run(coro)
                if loop.is_running():
                    import concurrent.futures
                    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                        return pool.submit(asyncio.run, coro).result(timeout=30)
                return loop.run_until_complete(coro)
            except RuntimeError:
                return asyncio.run(coro)

        llm = get_llm_client()
        findings_text = "\n".join(
            f"- [{f.get('severity')}] {f.get('agent')}: {f.get('title')}"
            for f in all_findings[:15]
        )
        bus_text = "\n".join(
            f"- [{obs.get('from_agent')}] {obs.get('observation_type')}: "
            f"{obs.get('service','')} {obs.get('event','')}"
            for obs in bus[:10]
        )
        chains_text = "\n".join(
            f"- {c['rule_id']}: {c['root_cause'][:200]}"
            for c in chains
        )
        prompt = (
            "You are a senior QA architect performing root cause analysis on a microservices PR.\n\n"
            f"Client-side findings:\n{findings_text}\n\n"
            f"Server-side log observations:\n{bus_text}\n\n"
            f"Identified root cause chains:\n{chains_text}\n\n"
            "Write a 3-sentence developer briefing that:\n"
            "1. States what the user-visible symptom is\n"
            "2. Names the exact service and code location that is the root cause\n"
            "3. Gives the highest-priority fix\n\n"
            "Briefing:"
        )

        resp = _run_async(
            asyncio.wait_for(
                llm.generate("correlator", prompt, workflow_id=workflow_id),
                timeout=90
            )
        )
        return resp
    except Exception as exc:
        logger.debug("correlator_llm_failed: %s", exc)
        return None


def run_correlator_agent(
    workflow_id: str,
    repository: str,
    pr_number: int,
    findings: List[Dict],           # all findings from previous agents
    bus_observations: List[Dict],   # observations posted to CorrelationBus
    fid: int = 1,
) -> Dict[str, Any]:
    """
    Main entry point.

    Returns:
      findings:         new annotated findings (root cause chains as findings)
      fid:              updated finding ID counter
      agent_log:        standard log dict
      root_cause_chains: structured list for state and dashboard display
      developer_brief:  human-readable markdown for PR comment
    """
    start = datetime.utcnow()
    new_findings: List[Dict[str, Any]] = []
    now = datetime.utcnow().isoformat()

    logger.info("correlator_started workflow=%s findings_in=%d bus_obs=%d",
                workflow_id, len(findings), len(bus_observations))

    # Separate client-side and server-side observations
    client_findings   = [f for f in findings if f.get("agent") != "log_inspector"]
    server_obs        = [o for o in bus_observations if o.get("from_agent") == "log_inspector"]
    cross_service_obs = [o for o in server_obs if o.get("observation_type") == "cross_service_correlation"]

    # ── Apply correlation rules ────────────────────────────────────────────────
    root_cause_chains = []
    for rule in _CORRELATION_RULES:
        chain = _build_rca_chain(rule, client_findings, server_obs)
        if chain:
            root_cause_chains.append(chain)

    # ── Convert chains → findings ──────────────────────────────────────────────
    for chain in root_cause_chains:
        evidence_str = "\n".join(chain["evidence"])
        new_findings.append({
            "id":          fid,
            "workflow_id": workflow_id,
            "agent":       "correlator",
            "severity":    chain["severity"],
            "title":       f"correlator - root cause: {chain['rule_id'].replace('_', ' ')}",
            "description": (
                f"Root cause identified across {', '.join(chain['affected_services'])}.\n"
                f"{chain['root_cause']}\n\n"
                f"Evidence ({chain['client_finding_count']} client + {chain['server_event_count']} server):\n"
                f"{evidence_str}\n\n"
                f"Fix: {chain['fix_hint']}"
            ),
            "test_name":             "root_cause_analysis",
            "created_at":            now,
            "root_cause_chain":      chain,
            "affected_services":     chain["affected_services"],
        })
        fid += 1

    # ── Build developer brief ──────────────────────────────────────────────────
    developer_brief = _build_developer_brief(root_cause_chains, cross_service_obs)

    # ── Optional LLM enhancement ───────────────────────────────────────────────
    llm_narrative = _llm_rca(root_cause_chains, findings, bus_observations, workflow_id)
    if llm_narrative:
        new_findings.append({
            "id":          fid,
            "workflow_id": workflow_id,
            "agent":       "correlator",
            "severity":    "LOW",
            "title":       "correlator - LLM-enhanced root cause narrative",
            "description": llm_narrative,
            "test_name":   "llm_rca",
            "created_at":  now,
        })
        fid += 1

    # ── No correlations found ──────────────────────────────────────────────────
    if not new_findings:
        new_findings.append({
            "id":          fid,
            "workflow_id": workflow_id,
            "agent":       "correlator",
            "severity":    "LOW",
            "title":       "correlator - no cross-layer correlations found",
            "description": (
                "Cross-layer analysis found no causal links between client-side findings "
                "and server-side log events. Each finding appears to be isolated."
            ),
            "test_name":   "correlation_analysis",
            "created_at":  now,
        })
        fid += 1

    logger.info(
        "correlator_complete workflow=%s chains=%d new_findings=%d",
        workflow_id, len(root_cause_chains), len(new_findings),
    )

    return {
        "findings":          new_findings,
        "fid":               fid,
        "agent_log": {
            "agent":         "correlator",
            "status":        "COMPLETED",
            "started_at":    start.isoformat(),
            "completed_at":  datetime.utcnow().isoformat(),
        },
        "root_cause_chains": root_cause_chains,
        "developer_brief":   developer_brief,
    }
