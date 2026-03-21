# TuskerSquad E2E Workflow Testing Guide

## Overview
This document provides step-by-step test scenarios for the complete PR governance workflow from Gitea webhook to final decision.

## Architecture Flow
```
Gitea PR Event
    ↓
Integration Service (Receives Webhook)
    ↓
LangGraph API (Creates workflow)
    ↓
LangGraph Workflow Execution (Background thread)
    ├─ Repo Validator (Early gate)
    ├─ Planner (Diff analysis)
    ├─ Engineering Agents (Backend/Frontend/Security/SRE)
    ├─ Builder → Deployer → Tester
    ├─ Runtime Analyzer
    ├─ Log Inspector → Correlator
    ├─ Challenger → QA Lead
    ├─ Judge (Decision)
    └─ Cleanup
    ↓
Final Decision (APPROVE/REJECT/REVIEW_REQUIRED)
    ↓
Possible Merge & Deploy (on APPROVE)
    ↓
Workflow Completion
```

## Test Case 1: Early Validation Failure (Repo Not Found)

### Setup
- Create a PR in a non-existent repository e.g., `nonexistent/repo`
- Ensure GITEA_URL, GITEA_TOKEN are set correctly

### Expected Flow
1. Webhook received: event='pull_request', action='opened'
2. Integration service calls POST `/api/workflow/start`
3. Workflow created with status='RUNNING'
4. Background thread executes workflow
5. repo_validator node runs immediately
6. Checks if repo exists and is accessible
7. Git provider returns error (repo not found)
8. Creates HIGH severity finding: "Git provider not configured" or "Repository clone failed"
9. Sets validator_failed=True
10. Graph routes to END (all other nodes skipped)
11. execute_workflow() detects validator_failed
12. Updates DB status to "FAILED"
13. Updates registry status to "FAILED"
14. Posts rejection comment on PR
15. API endpoint returns status='FAILED'

### Verification Checklist
```
☐ Webhook received by integration service
☐ Info log: "webhook_parsed provider=gitea action='opened' repo='nonexistent/repo' pr=X"
☐ Workflow created in DB with status='RUNNING'
☐ Info log: "execute_workflow_started workflow=UUID"
☐ Error log: "repo_validator_failed workflow=UUID"
☐ Error log: "workflow_aborted_validator_failed workflow=UUID reason='...' status=FAILED (DB+Registry updated)"
☐ Rejection comment posted on PR
☐ GET /api/workflow/{id} returns "status": "FAILED"
☐ Governance decision in DB shows decision='REJECT'
☐ Duration: ~1-2 seconds (quick early exit)
```

### Logs to Check
```bash
# Integration service
2026-03-11 06:58:13,913 INFO gitea_webhook_received event='pull_request'
2026-03-11 06:58:13,913 INFO webhook_parsed provider=gitea action='opened'
2026-03-11 06:58:13,923 INFO execute_workflow_started workflow=8cb5464e...

# LangGraph API
2026-03-11 06:58:13,927 ERROR repo_validator_failed workflow=8cb5464e repo=... pr=2 findings=1
2026-03-11 06:58:13,943 INFO workflow_aborted_validator_failed workflow=8cb5464e reason='...' status=FAILED

# API responses
GET /api/workflow/8cb5464e-969c...
→ status: "FAILED"
```

---

## Test Case 2: Successful Build & Deploy

### Setup
- Create a PR with valid code changes
- Ensure repository is cloned, built successfully
- Configure AUTO_MERGE_ON_APPROVE=true, DEPLOY_ON_MERGE=true

### Expected Flow
1. All validation passes
2. All agents run and post comments
3. Judge makes APPROVE decision
4. Status updated to 'COMPLETED'
5. Merge & deploy background thread starts
6. PR merged into target branch
7. Deploy pipeline triggered
8. Status fields updated: merge_status='success', deploy_status='triggered'
9. Final governance comment posted
10. Workflow stays in state for audit

### Verification Checklist
```
☐ All agent comments posted on PR (planner, backend, frontend, security, sre, etc.)
☐ Judge decision: "[APPROVED]"
☐ Final summary comment posted
☐ Merge comment posted showing merge_status='success'
☐ Deploy comment posted showing deploy_status='triggered'
☐ GET /api/workflow/{id} returns:
  - status: 'COMPLETED'
  - decision: 'APPROVE'
  - merge_status: 'success'
  - deploy_status: 'triggered'
☐ PR labels updated: tuskersquad:approved, tuskersquad:deployed
☐ DB governance_actions shows decision='APPROVE', approved=true
☐ Duration: 5-10 seconds (full pipeline)
```

### Logs to Check
```bash
2026-03-11 06:58:13,923 INFO execute_workflow_started workflow=UUID
2026-03-11 06:58:13,943 INFO node_completed node=repo_validator
2026-03-11 06:58:13,950 INFO node_completed node=planner
...
2026-03-11 06:58:14,020 INFO node_completed node=judge workflow=UUID decision=APPROVE
2026-03-11 06:58:14,022 INFO workflow_completed workflow=UUID decision=APPROVE status=COMPLETED (DB+Registry updated)
2026-03-11 06:58:14,045 INFO merge_deploy_thread_started
2026-03-11 06:58:14,150 INFO merge_pr_sync repo=tusker/shopflow pr=2 merged=true
2026-03-11 06:58:14,170 INFO deploy_triggered repo=tusker/shopflow pr=2 pipeline_url=...
```

---

## Test Case 3: Judge Decision = REVIEW_REQUIRED

### Setup
- Modify one agent to return HIGH severity findings
- Ensure judge makes REVIEW_REQUIRED decision

### Expected Flow
1. All agents run
2. One or more agents report HIGH severity findings
3. Judge uses findings to decide: REVIEW_REQUIRED
4. Status updated to 'WAITING_HUMAN_APPROVAL'
5. LangGraph interrupt() called
6. Execution paused (hangs in human_approval_node)
7. Registry shows "status": "WAITING_HUMAN_APPROVAL"
8. Human reviews via UI and clicks APPROVE/REJECT
9. API POST /workflow/{id}/release-override called
10. Background thread wakes up with decision
11. Execution resumes, status updated to 'COMPLETED'

### Verification Checklist
```
☐ Findings with severity='HIGH' appear in comments
☐ Judge decision: "[REVIEW REQUIRED]"
☐ GET /api/workflow/{id} returns status: 'WAITING_HUMAN_APPROVAL'
☐ Dashboard UI shows interrupt payload with findings
☐ Manual approval via POST /api/workflow/{id}/release-override
☐ Status transitions to 'COMPLETED' after approval
☐ Merge & deploy triggered (if AUTO_MERGE_ON_APPROVE)
☐ Duration: 10+ seconds (includes wait for human)
```

### Logs to Check
```bash
2026-03-11 06:58:14,020 INFO judge_decision workflow=UUID decision=REVIEW_REQUIRED
2026-03-11 06:58:14,021 INFO human_approval_needed workflow=UUID (paused)
...
(Human action)
...
2026-03-11 06:59:30,100 INFO human_approval_received workflow=UUID decision=APPROVE
2026-03-11 06:59:30,110 INFO workflow_completed workflow=UUID decision=APPROVE status=COMPLETED
```

---

## Test Case 4: Test Failure in Tester Agent

### Setup
- Deployed app has failing endpoint
- Tester tries to hit /health endpoint
- curl command fails with non-200 status

### Expected Flow
1. Builder completes successfully
2. Deployer deploys container
3. Tester starts, health check fails
4. Creates HIGH severity finding: "Application health check failed"
5. Stops testing (early exit)
6. Runtime analyzer picks up no test_results
7. Judge sees HIGH findings
8. Decision: REVIEW_REQUIRED

### Verification Checklist
```
☐ Tester comment shows "[HIGH] Application health check failed"
☐ Tester finding: test_name='health_check', severity='HIGH'
☐ Runtime analyzer comment shows runtime health status
☐ Judge includes runtime health in decision reasoning
☐ Final decision: REVIEW_REQUIRED (due to HIGH findings)
```

---

## Test Case 5: Cleanup Always Runs (Even on Failure)

### Setup
- Create any PR that will execute the workflow
- Even if builder fails, cleanup should run

### Expected Flow
1. Graph completes (success or failure)
2. Last node before END is cleanup_node
3. Cleanup removes:
   - Docker container (docker stop, docker rm)
   - Workspace directory (rm -rf)
   - Orphaned containers
4. Posts cleanup comment
5. Returns cleanup findings

### Verification Checklist
```
☐ Cleanup node always executes (check logs)
☐ Container stop/rm commands logged
☐ Workspace cleanup logged  
☐ No orphaned containers left behind on host
☐ Cleanup comment posted on PR
☐ Status transitions properly after cleanup
☐ Test with success AND failure scenarios
```

---

## Test Case 6: Database Status Consistency

### Setup
- Any workflow execution
- Monitor both DB and API responses in parallel

### Expected Flow
1. Workflow starts, both DB and registry: status='RUNNING'
2. Workflow completes, both DB and registry: status='COMPLETED'
3. API always returns status from DB (cached with registry overlay)
4. Get /workflow/{id}/merge-status includes status field

### Verification Checklist
```
☐ DB query: SELECT status FROM workflow_runs WHERE id='UUID'
  → Should match GET /api/workflow/{id} status field
☐ Check at each transition:
  - Initial: status='RUNNING'
  - After completion: status='COMPLETED' or 'FAILED' or 'WAITING_HUMAN_APPROVAL'
☐ Registry may lag behind DB but API always reads from DB
☐ /api/workflow/{id}/merge-status includes "status" field
☐ No stale status values returned to client
```

---

## Test Case 7: Negative - Missing Git Provider Config

### Setup
- Unset GITEA_URL, GITEA_TOKEN environment variables
- Try to run a workflow

### Expected Flow
1. Webhook received
2. Workflow created
3. repo_validator tries to get provider
4. get_provider() returns GiteaProvider (default)
5. GiteaProvider._url() returns empty (GITEA_URL not set)
6. PRInfo lookup fails
7. HIGH severity finding: "Git provider not configured"
8. validator_failed=True
9. Workflow aborted early

### Verification Checklist
```
☐ Error log: "Git provider not configured"
☐ Finding description mentions GITEA_URL, GITEA_TOKEN
☐ Status: FAILED
☐ Rejection comment posted
☐ No further agents execute
```

---

## Test Case 8: Database Persistence Across Restarts

### Setup
- Start workflow execution
- Let it get to WAITING_HUMAN_APPROVAL
- Restart langgraph service
- Resume with human decision

### Expected Flow
1. Workflow in WAITING_HUMAN_APPROVAL saved to DB
2. Service restart: DB still contains workflow state
3. GET /api/workflow/{id} queries DB
4. POST /workflow/{id}/release-override calls resume
5. Graph resumes from checkpoint (LangGraph MemorySaver)
6. Final decision applied
7. Status transitions to COMPLETED

### Verification Checklist
```
☐ Workflow data persisted before service restart
☐ After restart, data still readable from DB
☐ GET /api/workflow/{id} shows correct state
☐ Resume operation finds workflow in DB
☐ Graph resumes (not restarted)
☐ Final completion succeeds
```

---

## Manual Test Commands

### Start a Workflow
```bash
curl -X POST http://localhost:8000/api/workflow/start \
  -H "Content-Type: application/json" \
  -d '{
    "repo": "tusker/shopflow",
    "pr_number": 2,
    "provider": "gitea"
  }'

# Response:
# {
#   "workflow_id": "8cb5464e-969c-4e4d-9dbd-56a46c8f494f",
#   "status": "RUNNING",
#   "provider": "gitea"
# }
```

### Check Workflow Status
```bash
curl http://localhost:8000/api/workflow/8cb5464e-969c-4e4d-9dbd-56a46c8f494f

# Response should show:
# {
#   "workflow_id": "8cb5464e-969c-4e4d-9dbd-56a46c8f494f",
#   "status": "COMPLETED" or "FAILED" or "WAITING_HUMAN_APPROVAL",
#   "decision": "APPROVE" or "REJECT" or "REVIEW_REQUIRED",
#   ...
# }
```

### Check Merge Status
```bash
curl http://localhost:8000/api/workflow/8cb5464e-969c-4e4d-9dbd-56a46c8f494f/merge-status

# Response:
# {
#   "workflow_id": "8cb5464e-969c-4e4d-9dbd-56a46c8f494f",
#   "status": "COMPLETED",
#   "merge_status": "success" or "pending" or "failed" or "skipped",
#   "deploy_status": "triggered" or "pending" or "failed" or "skipped",
#   "deploy_url": "http://..."
# }
```

### Resume Approval
```bash
curl -X POST http://localhost:8000/api/workflow/8cb5464e-969c-4e4d-9dbd-56a46c8f494f/release-override \
  -H "Content-Type: application/json" \
  -d '{
    "reason": "Approved after manual review",
    "decision": "APPROVE"
  }'

# Workflow resumes and continues to merge/deploy
```

### View Findings
```bash
curl http://localhost:8000/api/workflows/8cb5464e-969c-4e4d-9dbd-56a46c8f494f/findings

# Response: array of findings with agent, severity, title, description
```

---

## Troubleshooting

### Workflow Stuck in RUNNING
**Before Fix**: API returned status='RUNNING' from registry even though DB showed 'FAILED'
**After Fix**: API always reads status from DB

**Check**:
```sql
SELECT status, merge_status, deploy_status FROM workflow_runs WHERE id='UUID';
```
Should show actual status, not RUNNING.

### Status Not Updating
**Check logs** for:
```
workflow_completed workflow=UUID decision=APPROVE status=COMPLETED (DB+Registry updated)
workflow_aborted_validator_failed workflow=UUID reason=... status=FAILED (DB+Registry updated)
```

If these messages don't appear, workflow execution may have crashed.

### No Comments Posted
Check:
1. Gitea comment endpoint returns non-200 status
2. GITEA_TOKEN has correct permissions
3. PR still exists in Gitea

### Merge Failed
Check:
1. AUTO_MERGE_ON_APPROVE is true
2. MERGE_STYLE is valid (merge, rebase, squash)
3. No conflicts in PR
4. User token has merge permission

---

## Success Criteria

✅ **Test passes** if:
- Workflow completes within expected time
- Status correctly reflects actual state (DB + API)
- Comments posted correctly  
- Decisions are correct based on findings
- Merge/deploy logic works as configured
- Cleanup always executes
- Database remains consistent with API responses
- No stale status values returned

❌ **Test fails** if:
- API returns wrong status
- Status doesn't transition properly
- Comments missing or empty
- Workflow hangs indefinitely
- Database state inconsistent with API
- Cleanup doesn't execute
- Merge/deploy skipped when should proceed
