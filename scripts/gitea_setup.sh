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
# Auto-create GITEA_TOKEN if not provided
########################################

if [ -z "${GITEA_TOKEN}" ]; then
    log "GITEA_TOKEN not set - attempting to create API token automatically..."

    # Delete existing tuskersquad-auto token if it exists (idempotent)
    curl -s -o /dev/null -X DELETE         -H "${AUTH_HEADER}"         "${API}/users/${ADMIN_USER}/tokens/tuskersquad-auto" || true

    # Create a new token
    TOKEN_RESPONSE=$(curl -s         -X POST         -H "${AUTH_HEADER}"         -H "Content-Type: application/json"         -d "{\"name\": \"tuskersquad-auto\", \"scopes\": [\"write:repository\", \"write:issue\", \"read:user\"]}"         "${API}/users/${ADMIN_USER}/tokens" || echo "{}")

    AUTO_TOKEN=$(echo "${TOKEN_RESPONSE}" | grep -o '"sha1":"[^"]*"' | sed 's/"sha1":"//;s/"//')

    if [ -n "${AUTO_TOKEN}" ]; then
        log "Auto-token created: ${AUTO_TOKEN:0:8}..."
        log "IMPORTANT: Add this to infra/.env: GITEA_TOKEN=${AUTO_TOKEN}"
        GITEA_TOKEN="${AUTO_TOKEN}"
        AUTH_HEADER="Authorization: token ${GITEA_TOKEN}"
    else
        log "WARNING: Could not auto-create token. Set GITEA_TOKEN manually in infra/.env"
    fi
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
            \"active\": true,
            \"push_events\": true,
            \"pull_request_events\": true,
            \"issue_events\": false,
            \"issues_only\": false
        }" \
        "${API}/repos/${ADMIN_USER}/${REPO_NAME}/hooks" || echo "000")

    log "Webhook register HTTP ${HOOK_CODE}"

    if [ "$HOOK_CODE" != "201" ]; then
        log "ERROR: Webhook registration failed"
        exit 1
    fi
fi

########################################
# Upload demo app source code
# FIX F-1: The shopflow repo was created empty (auto_init only adds a README).
# builder_agent clones this repo and needs a Dockerfile at the root plus the
# ShopFlow backend source.  We push all of that here on first boot.
# Idempotent: skipped if the repo already has more than the initial README.
########################################

log "Checking if demo app source needs to be uploaded..."

# Count files currently in repo (via Gitea API)
CONTENTS=$(wget -qO- \
    --header="${AUTH_HEADER}" \
    "${API}/repos/${ADMIN_USER}/${REPO_NAME}/contents/" 2>/dev/null || echo "[]")

FILE_COUNT=$(echo "$CONTENTS" | grep -o '"type"' | wc -l)

if [ "${FILE_COUNT}" -gt "1" ]; then
    log "Repo already has ${FILE_COUNT} item(s) — skipping demo app upload"
else
    log "Uploading ShopFlow demo app source..."

    # Check required source files are present
    if [ ! -d "/app/apps/backend" ]; then
        log "WARNING: /app/apps/backend not found — skipping demo upload"
        log "Make sure the apps volume is mounted in docker-compose.yml"
    elif [ ! -f "/app/Dockerfile.demo" ]; then
        log "WARNING: /app/Dockerfile.demo not found — skipping demo upload"
    else
        WORK_DIR=$(mktemp -d)

        # Configure git identity (required even for a plain push)
        git config --global user.email "setup@tuskersquad.local"
        git config --global user.name  "TuskerSquad Setup"
        git config --global http.sslVerify "false"

        # Clone using admin credentials embedded in URL
        CLONE_URL="http://${ADMIN_USER}:${ADMIN_PASS}@tuskersquad-gitea:3000/${ADMIN_USER}/${REPO_NAME}.git"
        git clone "${CLONE_URL}" "${WORK_DIR}/repo" 2>&1 | head -5

        cd "${WORK_DIR}/repo"

        # Copy ShopFlow backend source files into repo root
        # The builder agent looks for a Dockerfile at the repo root.
        cp -r /app/apps/backend/. .

        # Create an apps/__init__.py at the correct path so Python imports work
        # (uvicorn runs  apps.backend.main:app  with PYTHONPATH=/app)
        mkdir -p apps/backend
        cp -r /app/apps/backend/. apps/backend/
        touch apps/__init__.py
        if [ -f "/app/apps/__init__.py" ]; then
            cp /app/apps/__init__.py apps/__init__.py
        fi

        # Place Dockerfile at repo root (builder requires it at the top level)
        # Rewrite COPY paths to match the layout we pushed (all files are at root)
        cat > Dockerfile << 'DOCKERFILE_EOF'
# ShopFlow demo application
# Generated by TuskerSquad gitea-setup on first boot.
FROM python:3.11-slim

RUN apt-get update \
 && apt-get install -y --no-install-recommends gcc libffi-dev \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app

RUN pip install --no-cache-dir --upgrade pip==24.3.1

# requirements.txt is at the repo root (copied from apps/backend/requirements.txt)
COPY requirements.txt /tmp/demo-requirements.txt
RUN pip install --no-cache-dir -r /tmp/demo-requirements.txt

# Copy source — apps/ package hierarchy so imports work
COPY apps/ /app/apps/

ENV PYTHONPATH=/app

HEALTHCHECK --interval=10s --timeout=5s --start-period=30s --retries=6 \
  CMD python3 -c "import urllib.request; urllib.request.urlopen('http://localhost:8080/health', timeout=4)"

CMD ["uvicorn", "apps.backend.main:app", "--host", "0.0.0.0", "--port", "8080"]
DOCKERFILE_EOF

        # Add a .gitignore so __pycache__ / .pyc don't get committed
        cat > .gitignore << 'GITIGNORE_EOF'
__pycache__/
*.pyc
*.pyo
.env
*.db
GITIGNORE_EOF

        # Commit and push
        git add .
        git commit -m "feat: initial ShopFlow demo application (auto-uploaded by TuskerSquad)"
        git push origin main

        PUSH_CODE=$?
        if [ "$PUSH_CODE" = "0" ]; then
            log "Demo app uploaded successfully to ${REPO_NAME}"
        else
            log "WARNING: Demo app push failed (exit ${PUSH_CODE}) — check git output above"
        fi

        cd /
        rm -rf "${WORK_DIR}"
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