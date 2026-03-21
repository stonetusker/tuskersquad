# Gitea Webhook Behavior Documentation

## Overview
This document details how Gitea webhooks are configured, triggered, and handled in TuskerSquad, including event types, trigger conditions, and known issues.

---

## Webhook Configuration

### Setup Location
- **Script**: [scripts/gitea_setup.sh](../scripts/gitea_setup.sh)
- **Configuration File**: Automated during container startup via `gitea_setup.sh`
- **Webhook Endpoint**: `POST /gitea/webhook` at the integration-service

### Registration Details
The webhook is automatically registered with the following configuration:

```bash
# Webhook settings in gitea_setup.sh (lines 208-230):
{
    "type": "gitea",
    "config": {
        "url": "http://tuskersquad-integration:8001/gitea/webhook",
        "content_type": "json",
        "secret": "${GITEA_WEBHOOK_SECRET}"
    },
    "events": ["pull_request"],
    "active": true
}
```

**Key Points**:
- **Webhook Type**: Gitea (native)
- **Events**: Only `pull_request` events trigger the webhook
- **URL**: Must use container name (`tuskersquad-integration:8001`), not `localhost`
- **Content-Type**: JSON application/json
- **Secret**: Optional (GITEA_WEBHOOK_SECRET in .env)

---

## Webhook Trigger Events

### Gitea Trigger Actions
**Source**: [services/integration_service/main.py](../services/integration_service/main.py#L52), line 52

```python
_GITEA_TRIGGER  = {"opened", "synchronize", "reopened", "created", "reopen"}
```

### Event Explanation

| Action | Meaning | Triggers Review? | Description |
|--------|---------|------------------|-------------|
| `opened` | PR created | ✅ YES | Initial PR creation |
| `synchronize` | PR branch updated | ✅ YES | New commits pushed to PR branch (most common during development) |
| `reopened` | PR reopened after close | ✅ YES | PR was closed, then reopened |
| `created` | Generic create action | ✅ YES | Alternative creation event (uncommon in Gitea) |
| `reopen` | Alternative reopen syntax | ✅ YES | Alternative reopening event |
| `closed` | PR closed | ❌ NO | PR was merged or rejected (review not triggered) |
| Other actions | Various | ❌ NO | Filtered out; workflow not started |

### Push Events
**Important**: Standard "push" events to branches **do NOT trigger PR webhooks**.

- **Push to PR branch**: Generates a `synchronize` event (webhook IS received)
- **Direct push to `main`**: Generates a `push` event (webhook is NOT received; PR webhook is pull_request only)
- This is by design — webhooks only respond to PR state changes, not arbitrary pushes

---

## Webhook Payload Processing

### Gitea Payload Structure
**Source**: [services/integration_service/main.py](../services/integration_service/main.py#L227-L235)

```python
def _parse_gitea(payload: dict) -> tuple:
    """Extract repository, PR number, action, and commit SHA from Gitea webhook payload."""
    repo_obj = payload.get("repository") or {}
    repo     = repo_obj.get("full_name") or repo_obj.get("name", "")
    pr_obj   = payload.get("pull_request") or {}
    pr_num   = payload.get("number") or pr_obj.get("number")
    action   = payload.get("action", "")
    sha      = pr_obj.get("head", {}).get("sha", "")
    # ... parse pr_num as int ...
    return repo, pr_num, action, sha
```

### Webhook Header Verification
**Source**: [services/integration_service/main.py](../services/integration_service/main.py#L187-L192)

```python
# Header name: x-gitea-event
event = request.headers.get("x-gitea-event", "")
if event and event != "pull_request":
    return {"status": "ignored", "reason": f"event '{event}' is not pull_request"}
```

**Expected Header**:
- `x-gitea-event: pull_request` — webhook is processed
- Any other value — webhook is silently ignored

### HMAC Signature Verification
**Source**: [services/integration_service/main.py](../services/integration_service/main.py#L194-L199)

```python
def _verify_gitea_sig(raw_body: bytes, headers: dict) -> bool:
    if not GITEA_WEBHOOK_SECRET:
        return True  # Skip verification if secret not configured
    sig = headers.get("x-gitea-signature", "")
    if not sig:
        return False
    expected = hmac.new(GITEA_WEBHOOK_SECRET.encode(), raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, sig.strip().lower())
```

**Signature Handling**:
- **If `GITEA_WEBHOOK_SECRET` is set**: Request signature MUST match HMAC-SHA256 hash
- **If `GITEA_WEBHOOK_SECRET` is empty**: Signature verification is skipped (any request accepted)
- **Header name**: `x-gitea-signature`
- **Hash algorithm**: SHA256
- **Error response**: 401 Unauthorized if signature invalid

---

## Workflow Trigger Flow

### End-to-End PR Event Processing
**Source**: [services/integration_service/main.py](../services/integration_service/main.py#L361-L380)

```
1. Gitea sends webhook (x-gitea-event: pull_request, action: "synchronize" | "opened" | ...)
    ↓
2. Integration Service receives at POST /gitea/webhook
    ↓
3. Verify HMAC signature (if GITEA_WEBHOOK_SECRET configured)
    ↓
4. Parse payload: extracted repo, pr_number, action, sha
    ↓
5. Check x-gitea-event header (must be "pull_request"; others ignored)
    ↓
6. Check action against _GITEA_TRIGGER set
    ├─ If action NOT in trigger set: return 200 with "ignored" status
    └─ If action in trigger set: continue...
    ↓
7. Validate repo name and PR number are present
    ↓
8. POST "Review Started" comment to Gitea PR asynchronously
    ↓
9. Call LangGraph API: POST /api/workflow/start
    ├─ Body: {"repo": "<owner/repo>", "pr_number": <int>, "provider": "gitea"}
    └─ Returns: {"workflow_id": "<uuid>", ...}
    ↓
10. Return 200 OK with workflow_id
```

### Request/Response Example

**Incoming Webhook** (Gitea → TuskerSquad):
```http
POST /gitea/webhook HTTP/1.1
Host: tuskersquad-integration:8001
x-gitea-event: pull_request
x-gitea-signature: <hmac-sha256-hex>
Content-Type: application/json

{
  "action": "synchronize",
  "number": 42,
  "pull_request": {
    "number": 42,
    "head": { "sha": "abc123def456..." }
  },
  "repository": {
    "full_name": "tusker/shopflow",
    "name": "shopflow"
  }
}
```

**Response** (TuskerSquad → Gitea):
```json
{
  "status": "workflow_started",
  "provider": "gitea",
  "workflow_id": "8cb5464e-969c-4e4d-9dbd-56a46c8f494f",
  "repository": "tusker/shopflow",
  "pr_number": 42,
  "action": "synchronize"
}
```

---

## Synchronize Event Details

### What Triggers "synchronize"?

A `synchronize` event is sent when:
1. **New commits are pushed to the PR branch** (most common)
2. Force-push to the PR branch
3. Merge commits applied to the PR branch
4. Branch is rebased with new commits

### Why It Matters

- **Synchronize = PR has new code** → Review pipeline runs again with latest code
- Allows developers to push fixes/improvements and get automatic re-review
- Each push creates a separate workflow run (multiple reviews on same PR)

### Log Example

**Expected log output when synchronize event arrives**:
```
2026-03-11 06:58:13,913 INFO gitea_webhook_received event='pull_request'
2026-03-11 06:58:13,914 INFO webhook_parsed provider=gitea action='synchronize' repo='tusker/shopflow' pr=42
2026-03-11 06:58:13,915 INFO workflow_started provider=gitea repo='tusker/shopflow' pr=42 wf=8cb5464e-969c-4e4d-9dbd-56a46c8f494f
```

---

## Comparing Providers

### Trigger Actions by Provider

| Provider | Trigger Actions | Notes |
|----------|-----------------|-------|
| **Gitea** | `opened`, `synchronize`, `reopened`, `created`, `reopen` | Supports both `reopened` and `reopen` aliases |
| **GitHub** | `opened`, `synchronize`, `reopened`, `ready_for_review` | `ready_for_review` is GitHub-specific (draft → ready) |
| **GitLab** | `open`, `reopen`, `update` | GitLab uses different action names; `update` = `synchronize` |

### Action Normalization

**GitHub actions are normalized** (to handle both old and new action names):
```python
# GitHub normalization
normalised = {
    "opened": "opened", 
    "synchronize": "synchronize",
    "reopened": "reopened", 
    "ready_for_review": "opened",  # Treat as "opened"
}.get(action, action)
```

**GitLab actions are also normalized**:
```python
# GitLab normalization
normalised = {
    "open": "opened",
    "reopen": "reopened", 
    "update": "synchronize",  # Equivalent to GitHub/Gitea
}.get(action, action)
```

**Gitea actions are NOT normalized** — raw action name is used directly.

---

## Known Issues & Limitations

### 1. **Webhook Must Use Container Hostname**
**Issue**: Webhook URL in Gitea configured to `localhost:8001` instead of `tuskersquad-integration:8001`

**Symptom**: Gitea cannot deliver webhook (connection refused)

**Fix**: Use container name when running in Docker
```bash
# CORRECT (Docker):
WEBHOOK_URL=http://tuskersquad-integration:8001/gitea/webhook

# CORRECT (Local dev):
WEBHOOK_URL=http://localhost:8001/gitea/webhook
```

**Related**: [docs/TROUBLESHOOTING_GIT_PROVIDER.md](TROUBLESHOOTING_GIT_PROVIDER.md)

---

### 2. **GITEA_TOKEN Validation Happens at Workflow Start, Not Webhook Time**
**Issue**: Webhook is received and accepted, but workflow fails immediately with "Git provider not configured"

**Symptom**: 
- Integration Service logs show successful webhook receipt
- PR comment "Review Started" appears
- Then immediate "repo_validator" failure with "Git provider not configured" 

**Root Cause**: 
- Webhook processing doesn't validate GITEA_TOKEN (it only validates payload)
- Token validation happens in `repo_validator` agent when it tries to call Gitea API
- Missing/empty GITEA_TOKEN causes immediate rejection

**Fix**: 
- Set `GITEA_TOKEN` in `infra/.env` before starting services
- Generate token in Gitea UI: Avatar → Settings → Applications → Generate Token
- Required scopes: `repository` (read/write) + `issues` (read/write)

**Related**: [docs/TROUBLESHOOTING_GIT_PROVIDER.md](TROUBLESHOOTING_GIT_PROVIDER.md)

---

### 3. **Webhook Secret Validation Failure Returns 401**
**Issue**: If `GITEA_WEBHOOK_SECRET` is configured in Gitea but not (or incorrectly) set in TuskerSquad

**Symptom**: HTTP 401 response from webhook endpoint, webhook shows "failed" in Gitea UI

**Fix**: Ensure both match:
```bash
# 1. Get secret from Gitea UI: Repo → Settings → Webhooks → Edit → Secret field
# 2. Set in infra/.env:
GITEA_WEBHOOK_SECRET=<exact-value-from-gitea>
```

---

### 4. **Push Events to Main Do NOT Trigger PR Review**
**Issue**: Developer pushes to `main` branch; no webhook received

**Reason**: Webhook is configured for `pull_request` events only, not `push` events

**Expected Behavior**: 
- Push to PR branch → `synchronize` event (webhook received) ✅
- Push to `main` → `push` event (webhook NOT received) ❌

**Solution**: Use Pull Requests for all changes; do not allow direct pushes to `main`

---

### 5. **Multiple Synchronize Events Create Multiple Workflows**
**Issue**: Each push to PR creates a new workflow run; if 10 commits are pushed, 10 separate reviews are triggered

**This is Expected Behavior** — allows continuous re-review as code evolves

**Management**:
- View all workflows for a PR: [Dashboard](http://localhost:8000)
- Each workflow has separate ID, comments, and decision
- Judge node recommends latest decision based on most recent workflow

---

### 6. **Webhook Delivery Is Eventually Consistent (No Retries in Gitea)**
**Issue**: If integration-service is down when webhook is sent, Gitea does not retry

**Symptom**: Webhook shows as "failed" in Gitea UI; no workflow was created

**Fix**: 
- Manually trigger webhook: Repo → Settings → Webhooks → Edit → Test Delivery
- Or use [/webhook/simulate endpoint](../services/integration_service/main.py#L513):
  ```bash
  curl -X POST http://localhost:8001/webhook/simulate \
    -H 'Content-Type: application/json' \
    -d '{"repo":"tusker/shopflow","pr_number":42}'
  ```

---

### 7. **Event Header Name: x-gitea-event vs X-Gitea-Event**
**Issue**: HTTP headers are case-insensitive, but code expects lowercase

**Code**:
```python
event = request.headers.get("x-gitea-event", "")  # FastAPI normalizes to lowercase
```

**This Works Correctly** — FastAPI automatically lowercases header names

---

## Configuration Checklist

- [ ] **Webhook Registration**: Script `gitea_setup.sh` runs automatically on startup
  - Verify in Gitea UI: Repo → Settings → Webhooks (should show entry with integration URL)
  
- [ ] **GITEA_TOKEN**: Set in `infra/.env`
  - Generated in Gitea UI: Avatar → Settings → Applications → Generate Token
  - Scopes: `repository` (read/write) + `issues` (read/write)
  - Verify: `curl -H "Authorization: token $GITEA_TOKEN" http://localhost:3000/api/v1/user`

- [ ] **GITEA_WEBHOOK_SECRET**: Optional, but if set in Gitea UI, must match in `infra/.env`
  - Verify in Gitea UI: Repo → Settings → Webhooks → Edit → Secret field
  
- [ ] **Integration Service Running**: Must be accessible at configured URL
  - Verify: `curl http://localhost:8001/`
  - Docker: `docker exec tuskersquad-integration curl http://localhost:8001/`

- [ ] **Webhook Test**: Create a PR or push commits to existing PR
  - Expect log: `gitea_webhook_received event='pull_request'`
  - Expect comment: "TuskerSquad Review Started" on PR
  - Check dashboard: Workflow should appear within seconds

---

## Debugging Webhook Issues

### Check Webhook Delivery in Gitea UI
1. Open repo in Gitea
2. Settings → Webhooks
3. Click the TuskerSquad webhook entry
4. Scroll to "Recent Deliveries"
5. Click a delivery to see request/response:
   - **Status 200** = Successfully processed
   - **Status 401** = Signature verification failed (check GITEA_WEBHOOK_SECRET)
   - **Timeout/Connection Refused** = Integration service not reachable

### Monitor Integration Service Logs
```bash
docker logs -f tuskersquad-integration | grep -E "(webhook|parsed|workflow_started)"
```

**Expected patterns**:
```
gitea_webhook_received event='pull_request'
webhook_parsed provider=gitea action='synchronize' repo='...' pr=...
workflow_started provider=gitea repo='...' pr=... wf=...
```

### Manual Webhook Trigger
```bash
# Simulate webhook without Gitea
curl -X POST http://localhost:8001/webhook/simulate \
  -H 'Content-Type: application/json' \
  -d '{
    "repo":"tusker/shopflow",
    "pr_number":42,
    "provider":"gitea"
  }'

# Response should be:
# {"status": "workflow_started", "workflow_id": "...", ...}
```

### Check Signature Verification
If webhook shows 401 in Gitea UI:

```bash
# 1. Verify GITEA_WEBHOOK_SECRET in infra/.env
grep GITEA_WEBHOOK_SECRET infra/.env

# 2. Verify same value in Gitea UI
# Repo → Settings → Webhooks → Click webhook → Look for "Secret" field

# 3. If empty in one place, clear in the other
# Option A: Set secret in both places
# Option B: Remove secret from both places (skip verification)
```

---

## Related Documentation

- [Integration Service Architecture](https://github.com/TuskerSquad/TuskerSquad/blob/main/docs/architecture.md)
- [E2E Workflow Testing](E2E_WORKFLOW_TEST_GUIDE.md)
- [Troubleshooting Git Provider](TROUBLESHOOTING_GIT_PROVIDER.md)
- [User Manual - Webhook Simulation](USER_MANUAL.md#webhook-simulation)

---

## Summary

| Aspect | Details |
|--------|---------|
| **Webhook Type** | Gitea native (`pull_request` events only) |
| **Trigger Actions** | `opened`, `synchronize`, `reopened`, `created`, `reopen` |
| **Most Common Event** | `synchronize` (new commits pushed to PR branch) |
| **Auto-Setup** | Yes, via `gitea_setup.sh` on first start |
| **Signature Verification** | HMAC-SHA256 (optional via `GITEA_WEBHOOK_SECRET`) |
| **Authentication** | Via `GITEA_TOKEN` (validated at workflow start, not webhook time) |
| **Failure Handling** | Webhooks are fire-and-forget; no retries in Gitea |
| **Push Events** | Push to PR branch = `synchronize` ✅; push to `main` = `push` ❌ (not received) |
