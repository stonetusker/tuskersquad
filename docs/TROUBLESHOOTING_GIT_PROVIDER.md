# Troubleshooting: Git Provider Not Configured

## Symptom
```
Finding: repo_validator 
  Title: "Git provider not configured"
  Description: "Could not initialise a Git provider client. Check GIT_PROVIDER, GITEA_URL, and GITEA_TOKEN environment variables..."
```

The PR workflow starts but immediately fails at the `repo_validator` step.

---

## Root Causes

### **Primary Cause: Missing GITEA_TOKEN**
The LangGraph service doesn't have a valid Gitea personal access token.

**Why**: The `.env` file has `GITEA_TOKEN=` (empty) by default. Without this token, the `GiteaProvider` cannot authenticate to Gitea's REST API, so all calls fail.

### **Secondary Cause: GITEA_URL Not Accessible**
The LangGraph service cannot reach the Gitea instance at the configured URL.

**Why**: 
- If running in Docker, `GITEA_URL=http://tuskersquad-gitea:3000` must be correct
- If running locally, `GITEA_URL=http://localhost:3000` instead
- If using an external Gitea instance, the URL must be publicly reachable from the LangGraph service

---

## Solution

### **1. Generate GITEA_TOKEN (One-time setup)**

```bash
# 1. Open http://localhost:3000 in your browser
# 2. Log in with admin credentials (default: tusker / tusker1234)
# 3. Click your avatar (top-right) → Settings
# 4. Left menu → Applications
# 5. Click "Generate Token" button
# 6. Fill in:
#    Name: "TuskerSquad"  (or any name)
#    Scopes: Check BOTH:
#      ☑ repository (read and write)
#      ☑ issues (read and write)
# 7. Click Generate → Copy the token (starts with prefix, long alphanumeric string)
```

### **2. Update infra/.env**

```bash
cd infra
# If .env doesn't exist, create it:
cp .env.example .env

# Edit .env with your text editor:
GITEA_TOKEN=<paste_your_token_here>

# Also verify these are set correctly:
GITEA_URL=http://tuskersquad-gitea:3000
GITEA_ADMIN_USER=tusker
GITEA_ADMIN_PASS=tusker1234
```

### **3. Restart Services**

```bash
make down
make up --build
```

Wait for all services to be healthy:
```bash
docker compose -f infra/docker-compose.yml ps
```

All services should show **Status: healthy** or **State: exited (successfully)**.

### **4. Verify Token Works**

```bash
# Test the token manually:
curl -H "Authorization: token YOUR_GITEA_TOKEN" \
  http://localhost:3000/api/v1/user

# Should return your user info (not 401 Unauthorized)
```

---

## Verification Steps

1. **Check Docker container environment**:
```bash
docker exec tuskersquad-langgraph env | grep GITEA
# Should show:
# GITEA_URL=http://tuskersquad-gitea:3000
# GITEA_TOKEN=<your_token>
```

2. **Test Gitea connectivity from inside langgraph container**:
```bash
docker exec tuskersquad-langgraph \
  curl -H "Authorization: token YOUR_TOKEN" \
  http://tuskersquad-gitea:3000/api/v1/user
# Should NOT get 401 or empty response
```

3. **Check integration service logs**:
```bash
docker logs tuskersquad-integration | head -50
# Look for success logs, not "webhook_received" without subsequent processing
```

4. **Check langgraph logs for repo_validator**:
```bash
docker logs tuskersquad-langgraph | grep -A5 "repo_validator"
# Should see detailed error message if token is missing
```

---

## Advanced Debugging

### **If Token is Set But Still Fails**

Check if the token has the correct scopes:
```bash
curl -H "Authorization: token YOUR_TOKEN" \
  http://localhost:3000/api/v1/user/tokens

# Output should show the token with scopes: ["repo", "user", "write:issue_label", ...]
```

### **If Gitea URL is Wrong**

```bash
# Check what the langgraph service thinks the URL is:
docker exec tuskersquad-langgraph python3 -c \
  "import os; print('GITEA_URL:', os.getenv('GITEA_URL'))"

# Should output: GITEA_URL: http://tuskersquad-gitea:3000
# NOT: GITEA_URL: (empty)
```

### **Network Issues**

If services are running but can't reach Gitea:
```bash
# Check if containers are on the same Docker network:
docker network inspect tuskersquad-net

# Should list both langgraph-api and gitea containers
```

---

## Common Mistakes

| Mistake | Why It Fails | Fix |
|---------|-------------|-----|
| Token is empty in `.env` | `GiteaProvider._token()` returns `""`, auth fails | Paste token after `GITEA_TOKEN=` |
| Token has wrong scopes | Can't read PR info or write comments | Regenerate with `repo` + `issues` scopes |
| GITEA_URL is wrong | Network request fails before token is even checked | Verify it's `http://tuskersquad-gitea:3000` in Docker |
| Token not reloaded after restart | Container still has old (empty) value | Run `make down && make up` |
| `.env` file not in `infra/` directory | Docker compose can't find it | Put it at `infra/.env`, run `make up` from repo root |

---

## Code Changes (Sprint Fix)

The `repo_validator_agent.py` was improved to:
1. **Check if provider object exists** (was checking a falsy instance)
2. **Validate provider.\_url()** explicitly (not just provider truthiness)
3. **Validate provider.\_token()** explicitly (not just provider truthiness)
4. **Provide clearer error messages** with specific missing variable names

This gives users actionable errors like:
> "Git provider 'gitea' is missing required environment variables: GITEA_TOKEN. For Gitea: GITEA_URL should be 'http://tuskersquad-gitea:3000' and GITEA_TOKEN must be a personal access token..."

Instead of the vague:
> "Git provider not configured"

---

## References

- [Gitea OAuth2 Applications](https://docs.gitea.io/en-us/oauth2-provider/)
- [Docker Compose Networking](https://docs.docker.com/compose/networking/)
- [TuskerSquad Setup Guide](https://github.com/example/tuskersquad/blob/main/docs/BUILD_DEPLOY_TEST.md)
