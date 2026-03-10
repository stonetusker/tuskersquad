#!/bin/sh
# gitea_setup.sh
#
# Runs once in the gitea-setup container after Gitea is healthy.
# Creates the shopflow repo and registers the TuskerSquad webhook.
# Safe to run multiple times - checks before creating anything.
#
# Auth: uses GITEA_TOKEN if set, otherwise basic auth with admin credentials.
# The admin user is created by gitea_init.sh inside the Gitea container.

set -e

GITEA_URL="${GITEA_URL:-http://tuskersquad-gitea:3000}"
ADMIN_USER="${GITEA_ADMIN_USER:-tusker}"
ADMIN_PASS="${GITEA_ADMIN_PASS:-tusker1234}"
REPO_NAME="${REPO_NAME:-shopflow}"
INTEGRATION_URL="${INTEGRATION_URL:-http://tuskersquad-integration:8001}"
WEBHOOK_SECRET="${GITEA_WEBHOOK_SECRET:-}"
API="${GITEA_URL}/api/v1"
WEBHOOK_URL="${INTEGRATION_URL}/gitea/webhook"

echo "[gitea-setup] Gitea:   ${GITEA_URL}"
echo "[gitea-setup] Repo:    ${ADMIN_USER}/${REPO_NAME}"
echo "[gitea-setup] Webhook: ${WEBHOOK_URL}"

# Pick auth method
if [ -n "${GITEA_TOKEN}" ]; then
    AUTH_HEADER="Authorization: token ${GITEA_TOKEN}"
    echo "[gitea-setup] Auth: token"
else
    ENCODED=$(printf '%s:%s' "${ADMIN_USER}" "${ADMIN_PASS}" | base64 | tr -d '\n')
    AUTH_HEADER="Authorization: Basic ${ENCODED}"
    echo "[gitea-setup] Auth: basic (${ADMIN_USER})"
fi

# Wait for Gitea root to return 200
echo "[gitea-setup] Waiting for Gitea to be ready..."
MAX=30
i=0
CODE="000"
while [ $i -lt $MAX ]; do
    CODE=$(curl -s -o /dev/null -w "%{http_code}" "${GITEA_URL}/" 2>/dev/null || echo "000")
    if [ "$CODE" = "200" ]; then
        echo "[gitea-setup] Gitea ready (HTTP 200)"
        break
    fi
    i=$((i + 1))
    echo "[gitea-setup] Attempt $i/$MAX HTTP $CODE - waiting 3s..."
    sleep 3
done
if [ "$CODE" != "200" ]; then
    echo "[gitea-setup] ERROR: Gitea not ready after ${MAX} attempts"
    exit 1
fi

# Extra wait for gitea_init.sh to finish creating the admin user
sleep 3

# Verify auth
echo "[gitea-setup] Checking credentials..."
AUTH_CHECK=$(curl -s -o /dev/null -w "%{http_code}" \
    -H "${AUTH_HEADER}" "${API}/user" 2>/dev/null || echo "000")
if [ "$AUTH_CHECK" != "200" ]; then
    echo "[gitea-setup] Auth returned HTTP ${AUTH_CHECK} - waiting 5s for admin creation..."
    sleep 5
    AUTH_CHECK=$(curl -s -o /dev/null -w "%{http_code}" \
        -H "${AUTH_HEADER}" "${API}/user" 2>/dev/null || echo "000")
fi
if [ "$AUTH_CHECK" != "200" ]; then
    echo "[gitea-setup] Auth failed (HTTP ${AUTH_CHECK}). Check credentials. Skipping setup."
    exit 0
fi
echo "[gitea-setup] Auth OK"

# Create repo if missing
echo "[gitea-setup] Checking repo ${ADMIN_USER}/${REPO_NAME}..."
REPO_CODE=$(curl -s -o /dev/null -w "%{http_code}" \
    -H "${AUTH_HEADER}" "${API}/repos/${ADMIN_USER}/${REPO_NAME}" 2>/dev/null || echo "000")

if [ "$REPO_CODE" = "200" ]; then
    echo "[gitea-setup] Repo exists, skipping"
else
    CREATE_CODE=$(curl -s -o /dev/null -w "%{http_code}" \
        -X POST \
        -H "${AUTH_HEADER}" \
        -H "Content-Type: application/json" \
        -d "{\"name\":\"${REPO_NAME}\",\"description\":\"ShopFlow demo app\",\"private\":false,\"auto_init\":true,\"default_branch\":\"main\"}" \
        "${API}/user/repos" 2>/dev/null || echo "000")
    echo "[gitea-setup] Repo create HTTP ${CREATE_CODE}"
fi

# Register webhook if missing
echo "[gitea-setup] Checking webhooks..."
HOOKS=$(curl -s -H "${AUTH_HEADER}" \
    "${API}/repos/${ADMIN_USER}/${REPO_NAME}/hooks" 2>/dev/null || echo "[]")

if echo "$HOOKS" | grep -q "${WEBHOOK_URL}"; then
    echo "[gitea-setup] Webhook already registered"
else
    HOOK_CODE=$(curl -s -o /dev/null -w "%{http_code}" \
        -X POST \
        -H "${AUTH_HEADER}" \
        -H "Content-Type: application/json" \
        -d "{\"type\":\"gitea\",\"config\":{\"url\":\"${WEBHOOK_URL}\",\"content_type\":\"json\",\"secret\":\"${WEBHOOK_SECRET}\"},\"events\":[\"pull_request\"],\"active\":true}" \
        "${API}/repos/${ADMIN_USER}/${REPO_NAME}/hooks" 2>/dev/null || echo "000")
    echo "[gitea-setup] Webhook register HTTP ${HOOK_CODE}"
fi

echo "[gitea-setup] Setup complete"
echo "[gitea-setup]   Gitea UI: ${GITEA_URL}"
echo "[gitea-setup]   Repo:     ${GITEA_URL}/${ADMIN_USER}/${REPO_NAME}"
echo "[gitea-setup]   Webhook:  ${WEBHOOK_URL}"
echo ""
echo "[gitea-setup] To post PR comments, generate a token:"
echo "[gitea-setup]   1. Open ${GITEA_URL}/user/settings/applications"
echo "[gitea-setup]   2. Create token (scopes: repository + issue read/write)"
echo "[gitea-setup]   3. Set GITEA_TOKEN=<token> in infra/.env"
echo "[gitea-setup]   4. Run: docker compose -f infra/docker-compose.yml restart"
