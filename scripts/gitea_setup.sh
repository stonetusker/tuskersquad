#!/bin/sh
# gitea_setup.sh
#
# Initializes Gitea after it becomes healthy.
# Responsibilities:
#   - Wait for Gitea API readiness
#   - Verify admin authentication
#   - Create repository if missing
#   - Register TuskerSquad webhook
#
# Safe to run multiple times.

set -e

########################################
# Configuration
########################################

GITEA_URL="${GITEA_URL:-http://tuskersquad-gitea:3000}"
API="${GITEA_URL}/api/v1"

ADMIN_USER="${GITEA_ADMIN_USER:-tusker}"
ADMIN_PASS="${GITEA_ADMIN_PASS:-tusker1234}"

REPO_NAME="${REPO_NAME:-shopflow}"

INTEGRATION_URL="${INTEGRATION_URL:-http://tuskersquad-integration:8001}"
WEBHOOK_URL="${INTEGRATION_URL}/gitea/webhook"

WEBHOOK_SECRET="${GITEA_WEBHOOK_SECRET:-}"

MAX_RETRIES=40
SLEEP_TIME=3

########################################
# Logging helper
########################################

log() {
    echo "[gitea-setup] $1"
}

########################################
# Authentication
########################################

if [ -n "${GITEA_TOKEN}" ]; then
    AUTH_HEADER="Authorization: token ${GITEA_TOKEN}"
    log "Auth method: token"
else
    ENCODED=$(printf '%s:%s' "${ADMIN_USER}" "${ADMIN_PASS}" | base64 | tr -d '\n')
    AUTH_HEADER="Authorization: Basic ${ENCODED}"
    log "Auth method: basic (${ADMIN_USER})"
fi

########################################
# Wait for Gitea API
########################################

log "Waiting for Gitea API..."

i=0
CODE="000"

while [ $i -lt $MAX_RETRIES ]; do

    CODE=$(curl -s -o /dev/null -w "%{http_code}" \
        "${API}/version" || echo "000")

    if [ "$CODE" = "200" ]; then
        log "Gitea API ready"
        break
    fi

    log "Attempt $((i+1))/${MAX_RETRIES} HTTP ${CODE}"
    sleep "${SLEEP_TIME}"
    i=$((i+1))

done

if [ "$CODE" != "200" ]; then
    log "ERROR: Gitea API not ready"
    exit 1
fi

########################################
# Wait for admin authentication
########################################

log "Waiting for admin authentication..."

i=0
AUTH_CODE="000"

while [ $i -lt $MAX_RETRIES ]; do

    AUTH_CODE=$(curl -s -o /dev/null -w "%{http_code}" \
        -H "${AUTH_HEADER}" \
        "${API}/user" || echo "000")

    if [ "$AUTH_CODE" = "200" ]; then
        log "Admin authentication OK"
        break
    fi

    log "Admin not ready yet (HTTP ${AUTH_CODE})"
    sleep "${SLEEP_TIME}"
    i=$((i+1))

done

if [ "$AUTH_CODE" != "200" ]; then
    log "ERROR: Admin authentication failed"
    exit 1
fi

########################################
# Repository setup
########################################

log "Checking repository ${ADMIN_USER}/${REPO_NAME}..."

REPO_CODE=$(curl -s -o /dev/null -w "%{http_code}" \
    -H "${AUTH_HEADER}" \
    "${API}/repos/${ADMIN_USER}/${REPO_NAME}" || echo "000")

if [ "$REPO_CODE" = "200" ]; then
    log "Repository already exists"
else

    log "Creating repository ${REPO_NAME}"

    CREATE_CODE=$(curl -s -o /dev/null -w "%{http_code}" \
        -X POST \
        -H "${AUTH_HEADER}" \
        -H "Content-Type: application/json" \
        -d "{
            \"name\": \"${REPO_NAME}\",
            \"description\": \"ShopFlow demo application\",
            \"private\": false,
            \"auto_init\": true,
            \"default_branch\": \"main\"
        }" \
        "${API}/user/repos" || echo "000")

    log "Repository creation HTTP ${CREATE_CODE}"

    if [ "$CREATE_CODE" != "201" ]; then
        log "ERROR: Repository creation failed"
        exit 1
    fi
fi

########################################
# Webhook setup
########################################

log "Checking webhook registration..."

HOOKS=$(curl -s \
    -H "${AUTH_HEADER}" \
    "${API}/repos/${ADMIN_USER}/${REPO_NAME}/hooks" || echo "[]")

if echo "$HOOKS" | grep -q "${WEBHOOK_URL}"; then
    log "Webhook already registered"
else

    log "Registering webhook"

    HOOK_CODE=$(curl -s -o /dev/null -w "%{http_code}" \
        -X POST \
        -H "${AUTH_HEADER}" \
        -H "Content-Type: application/json" \
        -d "{
            \"type\": \"gitea\",
            \"config\": {
                \"url\": \"${WEBHOOK_URL}\",
                \"content_type\": \"json\",
                \"secret\": \"${WEBHOOK_SECRET}\"
            },
            \"events\": [\"pull_request\"],
            \"active\": true
        }" \
        "${API}/repos/${ADMIN_USER}/${REPO_NAME}/hooks" || echo "000")

    log "Webhook register HTTP ${HOOK_CODE}"

    if [ "$HOOK_CODE" != "201" ]; then
        log "ERROR: Webhook registration failed"
        exit 1
    fi
fi

########################################
# Completion
########################################

log "Setup complete"
log "Gitea UI:  ${GITEA_URL}"
log "Repository: ${GITEA_URL}/${ADMIN_USER}/${REPO_NAME}"
log "Webhook:   ${WEBHOOK_URL}"

echo ""
log "To enable PR comment posting:"
log "1. Open ${GITEA_URL}/user/settings/applications"
log "2. Create token (repo + issue permissions)"
log "3. Set GITEA_TOKEN=<token> in infra/.env"
log "4. Restart containers"