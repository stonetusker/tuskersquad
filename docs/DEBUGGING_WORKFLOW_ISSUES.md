# Debugging TuskerSquad Workflow Issues

## Quick Diagnosis: Stuck in RUNNING Status

### 1. Check Database Status (Source of Truth)
```sql
psql -h localhost -U postgres -d tuskersquad_db
SELECT id, repository, pr_number, status, current_agent, 
       merge_status, deploy_status, deploy_url, created_at, updated_at
FROM workflow_runs 
WHERE id = '8cb5464e-969c-4e4d-9dbd-56a46c8f494f'::uuid;
```

**Expected**: status should be one of: RUNNING, COMPLETED, FAILED, WAITING_HUMAN_APPROVAL

### 2. Check API Response
```bash
curl -s http://localhost:8000/api/workflow/8cb5464e-969c-4e4d-9dbd-56a46c8f494f | jq .
```

**Expected**: 
```json
{
  "workflow_id": "8cb5464e-969c-4e4d-9dbd-56a46c8f494f",
  "status": "...",  // Should match DB!
  "decision": "...",
  "rationale": "...",
  ...
}
```

### 3. If API Status ≠ DB Status
This indicates the API fix wasn't applied. The API should **always** read status from DB first.

**Check**: Does `/api/workflow/{id}` endpoint do this?
```python
# CORRECT (After Fix):
row = _get_wf_row(db, workflow_id)  # Read from DB
result = _wf_to_dict(row)  # Gets status from DB
# ... then overlay registry ...
return result

# INCORRECT (Before Fix):
reg = await workflow_registry.get_workflow(workflow_id)
if reg:
    return reg  # Returns "RUNNING" from registry!
```

---

## Issue 1: Validator Fails but Status Doesn't Update

### Symptoms
- Validator finds error (repo not found)
- Comments posted (I see rejection comment)
- But `curl /api/workflow/{id}` still shows status=RUNNING

### Root Cause
API reads status from registry cache instead of DB. Timing issue between DB update (immediate) and registry update (via _update_registry).

### Diagnosis

**1. Check logs for key messages**:
```bash
docker logs tuskersquad-langgraph 2>&1 | grep -E "(validator_failed|aborted_validator|status=FAILED)"
```

**Expected to see**:
```
ERROR agents.repo_validator repo_validator_failed workflow=...
ERROR langgraph.workflows.pr_review workflow_aborted_validator_failed workflow=... status=FAILED (DB+Registry updated)
```

**2. Query database directly**:
```sql
SELECT status FROM workflow_runs WHERE id='UUID'::uuid;
```

**Expected**: `FAILED` (not RUNNING)

**3. Check registry state** (harder to access, but can monitor):
Add logging before returning in get_workflow:
```python
logger.info("api_workflow_response workflow=%s db_status=%s registry_status=%s",
            workflow_id, result["status"], reg.get("status") if reg else "N/A")
```

### Fix Verification
After applying the fix, the API endpoint should:
1. Always read `status` from DB (not registry)
2. Use registry for other fields like `decision`, `rationale`, etc.
3. Log what it's returning for debugging

---

## Issue 2: Graph Completes But Returns Empty Decision

### Symptoms
- Graph runs (duration=0.02s logged)
- But decision field is empty/missing
- No final comment posted

### Root Cause
Validator failed AND returned early, so decision/rationale never set by remaining agents.

### Diagnosis

**1. Check if validator_failed in result**:
```bash
docker logs tuskersquad-langgraph 2>&1 | grep "validator_failed"
```

**2. Check findings for validator error**:
```bash
curl -s http://localhost:8000/api/workflows/UUID/findings | jq '.[] | select(.agent=="repo_validator")'
```

**Expected**: Should show HIGH finding with clear error message

**3. Verify comment was posted**:
- Go to Gitea PR page
- Should see rejection comment from TuskerSquad
- Comment should explain why workflow aborted

### Fix Verification
After completing workflow, check:
```sql
SELECT f.agent, f.severity, f.title, f.description 
FROM engineering_findings f 
WHERE f.workflow_id = 'UUID'::uuid
ORDER BY f.agent;
```

All agents are filtered by validator check or post their findings.

---

## Issue 3: Workflow Status Never Transitions to COMPLETED

### Symptoms
- Workflow runs all agents
- Judge makes decision
- But status stays RUNNING
- Comments posted by agents but no final summary

### Root Cause
DB and registry update didn't both succeed, OR API is still reading from stale registry.

### Diagnosis

**1. Check judge decision in logs**:
```bash
docker logs tuskersquad-langgraph 2>&1 | grep "judge_decision"
```

**Expected**: 
```
INFO langgraph.graph_builder node_completed node=judge workflow=...
INFO langgraph.workflows.pr_review judge_decision workflow=... decision=APPROVE
INFO langgraph.workflows.pr_review workflow_completed workflow=... decision=APPROVE status=COMPLETED (DB+Registry updated)
```

**2. If judge_decision appears but not workflow_completed**:
Workflow is crashing in the transition logic. Check for exceptions:
```bash
docker logs tuskersquad-langgraph 2>&1 | grep -A5 "execute_workflow_failed"
```

**3. Check if final summary was posted**:
Look at PR comments - should see final consolidated summary comment after all agent comments.

If NO final summary: workflow didn't reach the completion block.

### Fix Verification

```sql
-- Check governance decision was recorded
SELECT workflow_id, decision, approved, created_at 
FROM governance_actions 
WHERE workflow_id = 'UUID'::uuid;
```

Should show either APPROVE, REJECT, or REVIEW_REQUIRED.

---

## Issue 4: Merge/Deploy Never Triggers After APPROVE

### Symptoms
- Judge decision = APPROVE
- Status = COMPLETED
- But merge doesn't happen
- merge_status stays NULL

### Root Cause
AUTO_MERGE_ON_APPROVE not true OR background thread crashed OR merge API failed.

### Diagnosis

**1. Check merge config**:
```bash
docker exec tuskersquad-langgraph env | grep -E "AUTO_MERGE|MERGE_STYLE"
```

**Expected**: `AUTO_MERGE_ON_APPROVE=true` or `true` string

**2. Check if merge thread started**:
```bash
docker logs tuskersquad-langgraph 2>&1 | grep -E "(merge_deploy_thread|merge_pr_sync)"
```

**Expected**:
```
INFO api.workflow_routes merge_deploy_thread_started workflow=...
INFO langgraph.gitea merge_pr_sync repo=... pr=... merged=true
```

**3. If merge thread crashed, check error**:
```bash
docker logs tuskersquad-langgraph 2>&1 | grep -B2 "merge_deploy_thread_failed"
```

Likely causes:
- Gitea API error (token invalid, PR doesn't exist)
- Merge conflicts
- Permissions issue

**4. Verify DB didn't update merge_status**:
```sql
SELECT merge_status, deploy_status FROM workflow_runs WHERE id='UUID'::uuid;
```

If both NULL: merge thread never ran.

### Fix Verification

```sql
SELECT merge_status, deploy_status, deploy_url FROM workflow_runs WHERE id='UUID'::uuid;
```

Should show:
- merge_status: 'success' OR 'failed' OR 'skipped'
- deploy_status: 'triggered' OR 'failed' OR 'skipped'
- deploy_url: pipeline URL or empty

---

## Issue 5: Workflow Hangs in WAITING_HUMAN_APPROVAL

### Symptoms
- judge_decision = REVIEW_REQUIRED
- Status = WAITING_HUMAN_APPROVAL
- BUT cannot approve/reject via API
- Resume endpoint returns error

### Root Cause
Graph checkpoint not persisted OR interrupt payload malformed OR resume command format wrong.

### Diagnosis

**1. Verify workflow created AND paused**:
```bash
curl -s http://localhost/api/workflow/UUID | jq '.status'
```

**Expected**: `"WAITING_HUMAN_APPROVAL"`

**2. Check if interrupt payload is valid**:
```bash
curl -s http://localhost:8000/api/workflows/UUID/reasoning | jq .
```

Should show human_approval_node info.

**3. Try resume with correct format**:
```bash
curl -X POST http://localhost:8000/api/workflow/UUID/release-override \
  -H "Content-Type: application/json" \
  -d '{
    "reason": "Approved manually",
    "decision": "APPROVE"
  }'
```

Check response for errors.

**4. If resume fails**, check logs:
```bash
docker logs tuskersquad-langgraph 2>&1 | grep -E "(resume_workflow|human_approval_received|human_approval_failed)"
```

### Fix Verification

After resume, status should transition:
```sql
SELECT status FROM workflow_runs WHERE id='UUID'::uuid;
```

Should be COMPLETED (not hanging).

---

## Deep Dive: Log Analysis

### Complete Workflow Execution Log Pattern

**Successful execution should show**:
```
[T0] INFO execute_workflow_started workflow=UUID
[T0+1ms] INFO node_completed node=repo_validator
[T0+10ms] INFO node_completed node=planner
[T0+50ms] INFO node_completed node=backend
[T0+100ms] INFO node_completed node=frontend
[T0+150ms] INFO node_completed node=security
[T0+200ms] INFO node_completed node=sre
[T0+250ms] INFO node_completed node=builder
[T0+300ms] INFO node_completed node=deployer
[T0+350ms] INFO node_completed node=tester
[T0+400ms] INFO node_completed node=runtime_analyzer
[T0+450ms] INFO node_completed node=log_inspector
[T0+500ms] INFO node_completed node=correlator
[T0+550ms] INFO node_completed node=challenger
[T0+600ms] INFO node_completed node=qa_lead
[T0+650ms] INFO node_completed node=judge workflow=UUID decision=APPROVE
[T0+700ms] INFO workflow_completed workflow=UUID decision=APPROVE status=COMPLETED (DB+Registry updated)
[T0+750ms] INFO final_summary_posted workflow=UUID
[T0+800ms] INFO merge_deploy_thread_started
[T0+900ms] INFO merge_pr_sync merged=true
[T0+1000ms] INFO deploy_triggered deploy_url=...
```

### Failure Pattern: Early Exit (Validator Fails)
```
[T0] INFO execute_workflow_started workflow=UUID
[T0+1ms] INFO node_completed node=repo_validator
[T0+10ms] ERROR repo_validator_failed workflow=UUID findings=1
[T0+15ms] ERROR workflow_aborted_validator_failed workflow=UUID status=FAILED (DB+Registry updated)
[T0+20ms] INFO validation_failure_comment_posted workflow=UUID
```

Duration: ~20ms instead of 1s+

---

## Real-Time Status Monitoring

### Watch workflow progress
```bash
watch -n 1 'curl -s http://localhost:8000/api/workflow/UUID | jq "{status, current_agent, decision}"'
```

### Monitor database updates
```bash
watch -n 1 'psql -h localhost -U postgres -d tuskersquad_db -c "SELECT status, current_agent, merge_status FROM workflow_runs WHERE id='\''UUID'\''::uuid;"'
```

### Check Gitea PR in real-time
```bash
watch -n 5 'curl -s "http://localhost:3000/api/v1/repos/{owner}/{repo}/issues/{pr}/comments?token={token}" | jq "length"'
```

(Shows number of comments growing as agents complete)

---

## Common Issues & Quick Fixes

| Issue | Check | Fix |
|-------|-------|-----|
| Status always RUNNING | DB vs API | Apply get_workflow() fix |
| No validator error | Gitea config | Check GITEA_URL, GITEA_TOKEN env |
| Validator passes but should fail | Git clone cmd | Check SSH key/credentials |
| Agents don't post comments | Post function | Check Gitea token permissions |
| Graph doesn't complete | LangGraph logs | Check recursion_limit, graph structure |
| Merge fails | Gitea API | Check AUTO_MERGE_ON_APPROVE, token |
| Deploy fails | Pipeline | Check DEPLOY_ON_MERGE, pipeline exists |
| Cleanup doesn't run | cleanup_node | Verify in graph edges, not END |

---

## Enabling Debug Logging

### Increase log level
```bash
export LOG_LEVEL=DEBUG
```

### Or per-module
```python
logging.getLogger("langgraph.workflows").setLevel(logging.DEBUG)
logging.getLogger("langgraph.graph_builder").setLevel(logging.DEBUG)
```

### Check Docker logs with follow
```bash
docker logs -f --tail=100 tuskersquad-langgraph 2>&1 | grep -E "(workflow|status|decision)"
```

### Search logs for specific workflow
```bash
docker logs tuskersquad-langgraph 2>&1 | grep "8cb5464e-969c-4e4d-9dbd-56a46c8f494f"
```
