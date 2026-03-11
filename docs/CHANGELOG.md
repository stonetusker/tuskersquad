# TuskerSquad Changelog

## v9 — Validation Abort + False-Positive Fix

### Critical Bugs Fixed

#### 1. Workflow did not stop when repository was inaccessible
**Symptom:** `Repository tusker/shopflow not found or not accessible` appeared in logs,
but the pipeline continued running all 18 agents anyway.

**Root cause:** The LangGraph graph correctly routed to END on `validator_failed=True`,
but `execute_workflow()` in `pr_review_workflow.py` read `result.get("decision", "REVIEW_REQUIRED")`
after `graph.invoke()` returned. Since `decision` was never set (the judge node never ran),
the workflow was silently treated as "waiting for human approval" instead of rejected.
Additionally, `SimpleGraph` (the LangGraph fallback) completely skipped `repo_validator_node`.

**Fix:**
- `pr_review_workflow.execute_workflow()` now checks `result.get("validator_failed")` immediately
  after `graph.invoke()` returns, before any other processing.
- On `validator_failed=True`: marks workflow as `FAILED`, writes a `REJECT` governance decision,
  and posts a clear ❌ PR comment via `_post_validation_failure_comment()` explaining exactly
  what failed and what to fix.
- `SimpleGraph.invoke()` now runs `repo_validator_node` first and returns immediately
  (aborting all subsequent nodes) when `validator_failed=True`.

#### 2. Agents reported PASS/no-issues even when no source code was available
**Symptom:** After a validation failure (or builder/deployer failure), agents like Frontend
Engineer posted `[PASS] Risk: NONE — Tested UI flows, form validation, accessibility, cart
behaviour - All checks passed.`

**Root cause:** All analysis agents (`backend`, `frontend`, `security`, `sre`) tested
`DEMO_APP_URL` — the permanently-running demo-backend — regardless of whether the PR code
was available. Since the demo-backend is always healthy, they always reported green results.
This created a misleading picture: agents appeared to validate the PR when they had no access
to it.

**Fix:**
- All four agents now accept `deploy_url` and `build_success` parameters.
- When `deploy_url` is set (ephemeral PR deployment), agents probe that URL instead.
- When `deploy_url` is empty, agents emit a **MEDIUM** finding titled
  `"[agent] - tested against permanent demo app, not PR code"` explaining exactly what happened.
- `_run_eng_agent()` in `graph_builder.py` passes `deploy_url` and `build_success` from state
  to agents automatically via `inspect.signature()` (no change to calling code needed).
- `_derive_agent_decision_summary()` now detects `pr_coverage_warning` findings and returns
  `decision=FLAG` instead of `decision=PASS` with "All checks passed."

#### 3. repo_validator: vague error messages
**Symptom:** Errors like "Repository inaccessible" or "Cannot checkout PR branch" gave no
actionable detail — no actual git error, no hint about token scopes.

**Fix:** Complete rewrite of `repo_validator_agent.py` error handling:
- Git provider initialisation failure → specific message about `GIT_PROVIDER`/`GITEA_TOKEN` env vars.
- Clone failure → includes the actual `git clone` stderr output.
- Checkout failure → includes `git fetch` and `git checkout` stderr.
- PR not found → distinguishes "PR doesn't exist" from "repo doesn't exist".
- `validator_failed` is now derived from `any HIGH finding` rather than the `repo_ok and pr_ok` booleans.

#### 4. SimpleGraph missing new pipeline agents
**Symptom:** When running without LangGraph installed, the `builder`, `deployer`, `tester`,
`api_validator`, `security_runtime`, `runtime_analyzer`, and `cleanup` nodes were never called.

**Fix:** `SimpleGraph.invoke()` now runs the complete 5-phase pipeline:
1. `repo_validator` (aborts if failed)
2. Static analysis: `planner`, `backend`, `frontend`, `security`, `sre`
3. Build/deploy/test: `builder`, `deployer`, `tester`, `api_validator`, `security_runtime`, `runtime_analyzer`
4. Analysis/governance: `log_inspector`, `correlator`, `challenger`, `qa_lead`, `judge`
5. Cleanup: `cleanup`

---

## v8 — Full Build/Deploy/Test Pipeline

See [BUILD_DEPLOY_TEST.md](BUILD_DEPLOY_TEST.md) for details on the new pipeline agents.

### New agents (Sprint 4)
- `builder` — clones PR branch, builds Docker image
- `deployer` — runs ephemeral container on port 19000+
- `tester` — runs API tests against ephemeral deployment
- `api_validator` — validates public endpoints return expected status codes
- `security_runtime` — Trivy image scan (if available)
- `runtime_analyzer` — reads container stats and logs
- `repo_validator` — validates repository and PR accessibility
- `cleanup` — stops and removes ephemeral containers and workspaces

### Bugs fixed in v8
See v8 release notes (19 bugs — schema columns, docker socket mount, env vars,
port collision, network name, pip flag, Gitea URL, API prefix, cleanup, BOM chars,
workflow_state TypedDict, gitea_setup.sh token auto-creation).

---

## v7 — Ephemeral Environment (Sprint 3)

- Ephemeral environment agent spins up per-PR containers
- Runtime validator checks health and logs of running container
- Enhanced demo with additional bug flags

## v6 — Immediate Per-Agent Comments + Webhook Auto-Trigger

- Each agent posts to the PR immediately on completion (no waiting for full pipeline)
- `gitea_setup.sh` automatically registers webhook on first boot
- Code style agent added
- Infrastructure guide published

## v5 — Initial Release (Sprint 1)

- GitHub / GitLab / Gitea connectors
- Diff-aware analysis (planner reads the PR diff)
- Multi-provider support via `GIT_PROVIDER` env var
