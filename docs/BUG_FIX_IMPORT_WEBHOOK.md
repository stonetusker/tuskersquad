# Critical Bugs Fixed: PR Update Workflow Trigger + Import Path

## Bug 1: Module Import Error - "No module named 'core.git_provider'"

### Problem
```
repo_validator [REJECTED] Could not initialise a Git provider client: 
  No module named 'core.git_provider'
```

### Root Cause
Agents were using incorrect import path:
```python
from core.git_provider import get_provider  # ❌ WRONG
```

The `core` module doesn't exist in the Python path when agents run. Agents are in `/agents/` but git_provider is in `/services/langgraph_api/core/`.

### Solution Applied
Fixed import path to full package path:
```python
from services.langgraph_api.core.git_provider import get_provider  # ✅ CORRECT
```

**Files Fixed**:
- [agents/repo_validator/repo_validator_agent.py](../../agents/repo_validator/repo_validator_agent.py#L33)
- [agents/builder/builder_agent.py](../../agents/builder/builder_agent.py#L42)

---

## Bug 2: Gitea Webhook Action Name Mismatch - "synchronized" vs "synchronize"

### Problem
Looking at the logs:
```
webhook_parsed provider=gitea action='synchronized' repo='tusker/shopflow' pr=3
INFO:     172.20.0.3:59764 - "POST /gitea/webhook HTTP/1.1" 200 OK
```

The webhook is **received** (200 OK) but **NO workflow is started**. Why? The action is being ignored!

### Root Cause
Gitea sends `"synchronized"` (14 characters) but the code checks for `"synchronize"` (13 characters):

```python
_GITEA_TRIGGER  = {"opened", "synchronize", "reopened", "created", "reopen"}
#                           ^^^^^^^^^^^^^^ WRONG - Gitea sends "synchronized"
```

In `_handle_pr_event()`, the action check:
```python
if action and action not in trigger_actions:
    return JSONResponse({"status": "ignored",
                         "reason": f"action '{action}' does not trigger review"})
```

Since `"synchronized"` is NOT in the set (only `"synchronize"` is), the webhook is **rejected as "ignored"** and no workflow starts.

### Solution Applied
Updated the trigger action set:
```python
_GITEA_TRIGGER  = {"opened", "synchronized", "reopened", "created", "reopen"}
#                           ^^^^^^^^^^^^^^^  NOW CORRECT
```

**File Fixed**: [services/integration_service/main.py](../../services/integration_service/main.py#L52)

---

## Impact

### Before Fix
| Scenario | Result |
|----------|--------|
| Create new PR | ✅ Works (action: `opened`) |
| Push commits to PR | ❌ **BROKEN** (action: `synchronized` → ignored) |
| repo_validator runs | ❌ **Crashes** with `No module named 'core.git_provider'` |

### After Fix
| Scenario | Result |
|----------|--------|
| Create new PR | ✅ Works (action: `opened`) |
| Push commits to PR | ✅ **NOW WORKS** (action: `synchronized` → recognized) |
| repo_validator runs | ✅ **NOW WORKS** (git_provider imported correctly) |

---

## Verification Steps

### Test 1: PR Update Trigger
```bash
# 1. Push a new commit to an existing PR
git checkout -b your-feature
echo "update" >> README.md
git add README.md
git commit -m "Update commit"
git push origin your-feature

# 2. Check integration service logs
docker logs -f tuskersquad-integration | grep -E "(webhook_parsed|workflow_started)"

# Should see:
# webhook_parsed provider=gitea action='synchronized' repo='tusker/shopflow' pr=X
# workflow_started provider=gitea repo='tusker/shopflow' pr=X wf=<new-uuid>
```

### Test 2: repo_validator (No import error)
```bash
# Check langgraph logs for successful repo_validator initialization
docker logs -f tuskersquad-langgraph | grep -E "(repo_validator|git_provider)"

# Should NOT see "No module named 'core.git_provider'"
# Should see successful provider initialization
```

---

## Quick Summary

| Bug | Cause | Fix |
|-----|-------|-----|
| **Import Error** | Wrong path `from core.git_provider` | Changed to `from services.langgraph_api.core.git_provider` |
| **PR Update Missing** | Gitea sends `"synchronized"` but code checks for `"synchronize"` | Added `"synchronized"` to `_GITEA_TRIGGER` set |

Both bugs have been fixed and are ready to test.
