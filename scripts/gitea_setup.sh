#!/bin/sh
# gitea_setup.sh
#
# Runs once after Gitea is healthy. Creates the shopflow repo and registers
# the TuskerSquad webhook so PRs trigger reviews automatically.
#
# Safe to run multiple times - checks before creating anything.
# Runs as a one-shot container in docker-compose (restart: "no").
#
# Required env vars:
#   GITEA_URL           - e.g. http://tuskersquad-gitea:3000
#   GITEA_ADMIN_USER    - admin username (default: tusker)
#   GITEA_ADMIN_PASS    - admin password (default: tusker1234)
#   INTEGRATION_URL     - e.g. http://tuskersquad-integration:8001
#   REPO_NAME           - repo to create (default: shopflow)
#   GITEA_TOKEN         - if set, used as the API token instead of basic auth
#   GITEA_WEBHOOK_SECRET - optional shared secret for HMAC validation

set -e

GITEA_URL="${GITEA_URL:-http://tuskersquad-gitea:3000}"
ADMIN_USER="${GITEA_ADMIN_USER:-tusker}"
ADMIN_PASS="${GITEA_ADMIN_PASS:-tusker1234}"
REPO_NAME="${REPO_NAME:-shopflow}"
INTEGRATION_URL="${INTEGRATION_URL:-http://tuskersquad-integration:8001}"
WEBHOOK_SECRET="${GITEA_WEBHOOK_SECRET:-}"

API="${GITEA_URL}/api/v1"
WEBHOOK_URL="${INTEGRATION_URL}/gitea/webhook"

echo "[gitea-setup] Starting setup for repo: ${REPO_NAME}"
echo "[gitea-setup] Gitea URL: ${GITEA_URL}"
echo "[gitea-setup] Webhook target: ${WEBHOOK_URL}"

# Build auth header. Prefer token if provided, fall back to basic auth.
if [ -n "${GITEA_TOKEN}" ]; then
    AUTH_HEADER="Authorization: token ${GITEA_TOKEN}"
    echo "[gitea-setup] Using token auth"
else
    # Base64-encode user:pass for basic auth
    ENCODED=$(printf "%s:%s" "${ADMIN_USER}" "${ADMIN_PASS}" | base64)
    AUTH_HEADER="Authorization: Basic ${ENCODED}"
    echo "[gitea-setup] Using basic auth (token not set)"
fi

# Wait until Gitea API responds. The healthcheck should guarantee this
# but we add a small extra wait just in case.
echo "[gitea-setup] Waiting for Gitea API..."
MAX_TRIES=20
i=0
while [ $i -lt $MAX_TRIES ]; do
    STATUS=$(curl -s -o /dev/null -w "%{http_code}" "${API}/settings/api" 2>/dev/null || echo "000")
    if [ "$STATUS" = "200" ]; then
        echo "[gitea-setup] Gitea API is ready"
        break
    fi
    i=$((i + 1))
    echo "[gitea-setup] Waiting... attempt $i/$MAX_TRIES (status=$STATUS)"
    sleep 3
done

if [ "$STATUS" != "200" ]; then
    echo "[gitea-setup] ERROR: Gitea API did not become ready. Exiting."
    exit 1
fi

# Create the repo if it does not exist
echo "[gitea-setup] Checking if repo '${ADMIN_USER}/${REPO_NAME}' exists..."
REPO_STATUS=$(curl -s -o /dev/null -w "%{http_code}" \
    -H "${AUTH_HEADER}" \
    "${API}/repos/${ADMIN_USER}/${REPO_NAME}" 2>/dev/null || echo "000")

if [ "$REPO_STATUS" = "200" ]; then
    echo "[gitea-setup] Repo already exists, skipping creation"
else
    echo "[gitea-setup] Creating repo '${REPO_NAME}'..."
    CREATE_RESULT=$(curl -s -w "\n%{http_code}" \
        -X POST \
        -H "${AUTH_HEADER}" \
        -H "Content-Type: application/json" \
        -d "{
            \"name\": \"${REPO_NAME}\",
            \"description\": \"ShopFlow demo app for TuskerSquad reviews\",
            \"private\": false,
            \"auto_init\": true,
            \"default_branch\": \"main\"
        }" \
        "${API}/user/repos" 2>/dev/null)
    
    HTTP_CODE=$(echo "$CREATE_RESULT" | tail -1)
    if [ "$HTTP_CODE" = "201" ]; then
        echo "[gitea-setup] Repo created successfully"
    else
        echo "[gitea-setup] Repo creation returned HTTP $HTTP_CODE (may already exist)"
    fi
fi

# Register the webhook if not already there
echo "[gitea-setup] Checking existing webhooks on '${ADMIN_USER}/${REPO_NAME}'..."
EXISTING_HOOKS=$(curl -s \
    -H "${AUTH_HEADER}" \
    "${API}/repos/${ADMIN_USER}/${REPO_NAME}/hooks" 2>/dev/null || echo "[]")

# Check if our webhook URL is already registered
if echo "$EXISTING_HOOKS" | grep -q "${WEBHOOK_URL}"; then
    echo "[gitea-setup] Webhook already registered, skipping"
else
    echo "[gitea-setup] Registering webhook -> ${WEBHOOK_URL}"

    # Build the secret field. If no secret set, use empty string.
    SECRET_JSON="\"secret\": \"${WEBHOOK_SECRET}\""

    HOOK_RESULT=$(curl -s -w "\n%{http_code}" \
        -X POST \
        -H "${AUTH_HEADER}" \
        -H "Content-Type: application/json" \
        -d "{
            \"type\": \"gitea\",
            \"config\": {
                \"url\": \"${WEBHOOK_URL}\",
                \"content_type\": \"json\",
                ${SECRET_JSON}
            },
            \"events\": [\"pull_request\"],
            \"active\": true
        }" \
        "${API}/repos/${ADMIN_USER}/${REPO_NAME}/hooks" 2>/dev/null)

    HTTP_CODE=$(echo "$HOOK_RESULT" | tail -1)
    if [ "$HTTP_CODE" = "201" ]; then
        echo "[gitea-setup] Webhook registered successfully"
    else
        echo "[gitea-setup] Webhook registration returned HTTP $HTTP_CODE"
        echo "$HOOK_RESULT" | head -1
    fi
fi

echo "[gitea-setup] Setup complete"
echo "[gitea-setup] Gitea UI: ${GITEA_URL}"
echo "[gitea-setup] Webhook:  ${WEBHOOK_URL}"
echo "[gitea-setup] Repo:     ${GITEA_URL}/${ADMIN_USER}/${REPO_NAME}"
