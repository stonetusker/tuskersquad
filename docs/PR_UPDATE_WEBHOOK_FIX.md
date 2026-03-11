# PR Update Webhook Issue: Synchronize Event Not Triggering

## Problem
When a PR is updated with new commits, the TuskerSquad workflow is not being triggered again. Only the initial PR creation triggers a workflow; subsequent pushes to the PR branch do not.

## Root Cause

The webhook registration in `gitea_setup.sh` was incomplete:

```bash
# BEFORE (incomplete):
"events": ["pull_request"],
"active": true
```

This configuration tells Gitea to listen for `pull_request` events, but **doesn't explicitly enable all pull_request actions** that Gitea can send (like `synchronize` when commits are pushed). 

In Gitea's webhook API, you need to explicitly set:
- `"push_events": true` — Enable push event notifications
- `"pull_request_events": true` — Enable FULL pull_request lifecycle events (opened, synchronize, closed, etc.)

Without these flags, Gitea may only send webhooks for **some** pull_request actions (like `opened`), not all.

## Fix Applied

Updated [scripts/gitea_setup.sh](../scripts/gitea_setup.sh) to register webhooks with complete configuration:

```bash
# AFTER (complete):
{
    "type": "gitea",
    "config": {
        "url": "...",
        "content_type": "json",
        "secret": "..."
    },
    "events": ["pull_request"],
    "active": true,
    "push_events": true,                  # ✅ NEW
    "pull_request_events": true,          # ✅ NEW
    "issue_events": false,                # ✅ NEW (explicitly disabled for perf)
    "issues_only": false                  # ✅ NEW
}
```

## What This Enables

| Event | Before | After | Result |
|-------|--------|-------|--------|
| PR created (action: `opened`) | ✅ Works | ✅ Works | Initial workflow triggered |
| Commits pushed to PR (action: `synchronize`) | ❌ NOT delivered | ✅ NOW works | Update workflow triggered |
| PR reopened (action: `reopened`) | ⚠️ Maybe | ✅ NOW works | Re-review triggered |
| Branch updated (action: `synchronize`) | ❌ NOT delivered | ✅ NOW works | Latest code reviewed |

## Steps to Apply the Fix

### Option A: Fresh Start (Recommended)
```bash
# Stop and remove containers
make down

# Update images and restart
make up --build

# The new webhook will be auto-registered with correct configuration
```

The webhook is registered automatically by `gitea-setup` container on startup.

### Option B: Manual Webhook Update (If Containers Are Running)

If you want to update the webhook without restarting:

```bash
# Delete existing webhook
curl -X DELETE \
  -H "Authorization: token ${GITEA_TOKEN}" \
  http://localhost:3000/api/v1/repos/tusker/shopflow/hooks/<hook_id>

# Get the hook ID from:
curl -H "Authorization: token ${GITEA_TOKEN}" \
  http://localhost:3000/api/v1/repos/tusker/shopflow/hooks
# Look for the URL matching http://tuskersquad-integration:8001/gitea/webhook
```

Then re-register by running the setup container manually or restarting:
```bash
docker restart tuskersquad-gitea-setup
```

### Option C: Verify Webhook in Gitea UI

After the fix is applied:

1. Open http://localhost:3000 and login
2. Navigate to repository (tusker/shopflow)
3. Click **Settings** → **Webhooks**
4. Click the TuskerSquad webhook entry
5. Verify the webhook includes:
   - ✅ `Events`: "pull_request"
   - ✅ `Push Events`: enabled (checkbox checked)
   - ✅ `Pull Request Events`: enabled (checkbox checked)

## Testing the Fix

```bash
# 1. Create or edit a PR
git checkout -b test-feature
echo "test" >> README.md
git add -A
git commit -m "Test commit"
git push origin test-feature

# 2. Open PR in Gitea (http://localhost:3000)
# 3. Push another commit to the same branch
echo "test2" >> README.md
git add -A
git commit -m "Updated commit"
git push origin test-feature

# 4. Check that TuskerSquad Review Started comment appears
# 5. Check logs for workflow creation:
docker logs -f tuskersquad-integration | grep -E "(webhook_parsed|workflow_started)"
# Should see TWO workflow_started events (one for opened, one for synchronize)
```

## Verification Checklist

After applying the fix:

- [ ] Webhook shows "Push Events: enabled" in Gitea UI
- [ ] Webhook shows "Pull Request Events: enabled" in Gitea UI
- [ ] Create a new PR → Workflow is triggered ✅
- [ ] Push a new commit to PR → Workflow is triggered again ✅
- [ ] Integration service logs show: `webhook_parsed ... action='synchronize'` for each push
- [ ] Docker logs show multiple `workflow_started` entries for the same PR (one per push)
- [ ] Dashboard shows multiple workflows for the same PR

## Log Patterns to Expect

**When PR is created**:
```
gitea_webhook_received event='pull_request'
webhook_parsed provider=gitea action='opened' repo='tusker/shopflow' pr=5
workflow_started provider=gitea repo='tusker/shopflow' pr=5 wf=<uuid>
```

**When commits are pushed to PR**:
```
gitea_webhook_received event='pull_request'
webhook_parsed provider=gitea action='synchronize' repo='tusker/shopflow' pr=5
workflow_started provider=gitea repo='tusker/shopflow' pr=5 wf=<uuid-2>
```

## Additional Improvements

### Better Error Logging
[services/integration_service/main.py](../services/integration_service/main.py#L227) now logs a warning if a webhook is received without an `action` field:
```python
if not action and pr_num and repo:
    logger.warning("gitea_webhook_missing_action repo='%s' pr=%s", repo, pr_num)
```

This helps identify webhook payload issues early.

## Related Documentation

- [Gitea Webhook Behavior](GITEA_WEBHOOK_BEHAVIOR.md) — Comprehensive webhook documentation
- [Troubleshooting Git Provider](TROUBLESHOOTING_GIT_PROVIDER.md) — Environment variable setup
- [Build & Deploy Test Guide](BUILD_DEPLOY_TEST.md) — Testing end-to-end workflows

## References

- [Gitea Webhook API Documentation](https://docs.gitea.io/en-us/webhooks/)
- [GitHub Webhook Comparison](https://docs.github.com/en/developers/webhooks-and-events/webhooks/creating-webhooks)
