#!/bin/sh
# gitea_setup.sh
#
# One-shot initialisation run by the tuskersquad-gitea-setup container.
#
# What this script does (all steps are idempotent):
#   1. Wait for the Gitea API to become available
#   2. Verify admin credentials
#   3. Auto-create a GITEA_TOKEN if one is not provided in the environment
#   4. Create the shopflow repository (with auto_init=true for an initial commit)
#   5. Register the TuskerSquad webhook on the repo
#   6. Push the ShopFlow demo app source code into the repo so the builder
#      agent has real code to clone, build, and test
#
# Prerequisites (provided by infra/Dockerfile.gitea-setup):
#   - curl  (all Gitea REST API calls)
#   - git   (pushing demo app source)
#
# NOTE: set -e is intentionally NOT used. Individual failures are handled
# with explicit checks so one optional step cannot abort later required steps.

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

MAX_RETRIES=50
SLEEP_TIME=3

########################################
# Helpers
########################################

log() { echo "[gitea-setup] $1"; }

die() {
    log "FATAL: $1"
    exit 1
}

# api_get_code <path> — returns HTTP status code only
api_get_code() {
    curl -s -o /dev/null -w "%{http_code}" \
        -H "${AUTH_HEADER}" \
        "${API}${1}" 2>/dev/null || echo "000"
}

# api_post_code <path> <json_body> — returns HTTP status code only
api_post_code() {
    curl -s -o /dev/null -w "%{http_code}" \
        -X POST \
        -H "${AUTH_HEADER}" \
        -H "Content-Type: application/json" \
        -d "$2" \
        "${API}${1}" 2>/dev/null || echo "000"
}

# api_post_body <path> <json_body> — returns HTTP response body
api_post_body() {
    curl -s \
        -X POST \
        -H "${AUTH_HEADER}" \
        -H "Content-Type: application/json" \
        -d "$2" \
        "${API}${1}" 2>/dev/null || echo "{}"
}

# api_get_body <path> — returns HTTP response body
api_get_body() {
    curl -s \
        -H "${AUTH_HEADER}" \
        -H "Content-Type: application/json" \
        "${API}${1}" 2>/dev/null || echo "[]"
}

# api_delete <path>
api_delete() {
    curl -s -o /dev/null -X DELETE \
        -H "${AUTH_HEADER}" \
        "${API}${1}" 2>/dev/null || true
}

########################################
# Step 1 — Wait for Gitea API
########################################

log "Waiting for Gitea API at ${API}/version ..."

i=0
CODE="000"
while [ "$i" -lt "$MAX_RETRIES" ]; do
    CODE=$(curl -s -o /dev/null -w "%{http_code}" "${API}/version" 2>/dev/null || echo "000")
    if [ "$CODE" = "200" ]; then
        log "Gitea API ready (HTTP 200)"
        break
    fi
    log "  attempt $((i+1))/${MAX_RETRIES} — HTTP ${CODE}"
    sleep "$SLEEP_TIME"
    i=$((i+1))
done

[ "$CODE" = "200" ] || die "Gitea API did not become ready after $((MAX_RETRIES * SLEEP_TIME))s"

########################################
# Step 2 — Build auth header and verify
########################################

if [ -n "${GITEA_TOKEN}" ]; then
    AUTH_HEADER="Authorization: token ${GITEA_TOKEN}"
    log "Auth: using supplied GITEA_TOKEN"
else
    ENCODED=$(printf '%s:%s' "${ADMIN_USER}" "${ADMIN_PASS}" | base64 | tr -d '\n')
    AUTH_HEADER="Authorization: Basic ${ENCODED}"
    log "Auth: basic auth as ${ADMIN_USER}"
fi

log "Waiting for admin authentication..."
i=0
AUTH_CODE="000"
while [ "$i" -lt "$MAX_RETRIES" ]; do
    AUTH_CODE=$(api_get_code "/user")
    if [ "$AUTH_CODE" = "200" ]; then
        log "Admin auth OK"
        break
    fi
    log "  auth attempt $((i+1))/${MAX_RETRIES} — HTTP ${AUTH_CODE}"
    sleep "$SLEEP_TIME"
    i=$((i+1))
done

[ "$AUTH_CODE" = "200" ] || die "Admin authentication failed (HTTP ${AUTH_CODE})"

########################################
# Step 3 — Auto-create API token if needed
########################################

if [ -z "${GITEA_TOKEN}" ]; then
    log "GITEA_TOKEN not set — creating 'tuskersquad-auto' token..."

    # Delete any leftover token from a previous run (idempotent)
    api_delete "/users/${ADMIN_USER}/tokens/tuskersquad-auto"

    TOKEN_BODY=$(api_post_body "/users/${ADMIN_USER}/tokens" \
        '{"name":"tuskersquad-auto","scopes":["write:repository","write:issue","read:user"]}')

    AUTO_TOKEN=$(printf '%s' "${TOKEN_BODY}" | grep -o '"sha1":"[^"]*"' | sed 's/"sha1":"//;s/"//')

    if [ -n "${AUTO_TOKEN}" ]; then
        log "  token created: ${AUTO_TOKEN%"${AUTO_TOKEN#????????}"}..."
        log "  >>> COPY TO infra/.env: GITEA_TOKEN=${AUTO_TOKEN}"
        GITEA_TOKEN="${AUTO_TOKEN}"
        AUTH_HEADER="Authorization: token ${GITEA_TOKEN}"
    else
        log "  WARNING: could not auto-create token — PR comments will not work"
        log "  Manual: Gitea UI > Settings > Applications > Generate Token"
        log "  Required scopes: repository read+write, issue read+write"
        log "  Then: add GITEA_TOKEN=<value> to infra/.env and run: make restart"
    fi
fi

########################################
# Step 4 — Create repository
########################################

log "Checking repository ${ADMIN_USER}/${REPO_NAME} ..."

REPO_CODE=$(api_get_code "/repos/${ADMIN_USER}/${REPO_NAME}")

if [ "$REPO_CODE" = "200" ]; then
    log "Repository already exists — skipping creation"
else
    log "Creating repository '${REPO_NAME}' ..."

    CREATE_CODE=$(api_post_code "/user/repos" \
        "{\"name\":\"${REPO_NAME}\",\"description\":\"ShopFlow demo e-commerce application\",\"private\":false,\"auto_init\":true,\"default_branch\":\"main\"}")

    if [ "$CREATE_CODE" = "201" ]; then
        log "Repository created (HTTP 201)"
    else
        die "Repository creation failed (HTTP ${CREATE_CODE})"
    fi
fi

########################################
# Step 5 — Register webhook
########################################

log "Checking webhook registration ..."

HOOKS=$(api_get_body "/repos/${ADMIN_USER}/${REPO_NAME}/hooks")

if printf '%s' "${HOOKS}" | grep -q "${WEBHOOK_URL}"; then
    log "Webhook already registered"
else
    log "Registering webhook -> ${WEBHOOK_URL}"

    HOOK_CODE=$(api_post_code "/repos/${ADMIN_USER}/${REPO_NAME}/hooks" \
        "{\"type\":\"gitea\",\"config\":{\"url\":\"${WEBHOOK_URL}\",\"content_type\":\"json\",\"secret\":\"${WEBHOOK_SECRET}\"},\"events\":[\"pull_request\"],\"active\":true,\"push_events\":true,\"pull_request_events\":true,\"issue_events\":false}")

    if [ "$HOOK_CODE" = "201" ]; then
        log "Webhook registered (HTTP 201)"
    else
        log "WARNING: webhook registration returned HTTP ${HOOK_CODE}"
    fi
fi

########################################
# Step 6 — Push ShopFlow demo source
########################################

log "Checking if demo app source needs to be pushed ..."

CONTENTS=$(api_get_body "/repos/${ADMIN_USER}/${REPO_NAME}/contents/")
FILE_COUNT=$(printf '%s' "${CONTENTS}" | grep -o '"type"' | wc -l | tr -d ' ')

if [ "${FILE_COUNT}" -gt "1" ]; then
    log "Repo already has ${FILE_COUNT} item(s) — skipping source push"
elif [ ! -d "/app/apps/backend" ]; then
    log "WARNING: /app/apps/backend not mounted — skipping source push"
    log "         Verify volumes in docker-compose.yml gitea-setup section"
else
    log "Pushing ShopFlow demo app source into ${REPO_NAME} ..."

    WORK_DIR=$(mktemp -d)
    log "  workdir: ${WORK_DIR}"

    git config --global user.email "setup@tuskersquad.local"
    git config --global user.name  "TuskerSquad Setup"
    git config --global http.sslVerify "false"
    git config --global init.defaultBranch "main"

    CLONE_URL="http://${ADMIN_USER}:${ADMIN_PASS}@tuskersquad-gitea:3000/${ADMIN_USER}/${REPO_NAME}.git"
    log "  cloning ${GITEA_URL}/${ADMIN_USER}/${REPO_NAME}.git ..."

    if git clone "${CLONE_URL}" "${WORK_DIR}/repo" 2>&1; then
        cd "${WORK_DIR}/repo"

        # ── Build repo layout ─────────────────────────────────────────────
        # Resulting tree:
        #
        #   Dockerfile            <- repo root (builder_agent looks here)
        #   requirements.txt      <- repo root (Dockerfile COPYs from here)
        #   .gitignore
        #   apps/__init__.py      <- required for apps.backend.* Python imports
        #   apps/backend/         <- complete ShopFlow backend package

        mkdir -p apps/backend
        cp -r /app/apps/backend/. apps/backend/

        # apps/__init__.py
        touch apps/__init__.py
        if [ -f "/app/apps/__init__.py" ]; then
            cp /app/apps/__init__.py apps/__init__.py
        fi

        # requirements.txt at repo root so Dockerfile can COPY it simply
        cp /app/apps/backend/requirements.txt requirements.txt

        # Self-contained Dockerfile at repo root
        cat > Dockerfile << 'DOCKERFILE_EOF'
# ShopFlow — TuskerSquad demo e-commerce backend
# Auto-generated by gitea-setup on first boot.
FROM python:3.11-slim

RUN apt-get update \
 && apt-get install -y --no-install-recommends gcc libffi-dev \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app

RUN pip install --no-cache-dir --upgrade pip==24.3.1

COPY requirements.txt /tmp/demo-requirements.txt
RUN pip install --no-cache-dir -r /tmp/demo-requirements.txt

COPY apps/ /app/apps/

ENV PYTHONPATH=/app

HEALTHCHECK --interval=10s --timeout=5s --start-period=30s --retries=6 \
  CMD python3 -c "import urllib.request; urllib.request.urlopen('http://localhost:8080/health', timeout=4)"

CMD ["uvicorn", "apps.backend.main:app", "--host", "0.0.0.0", "--port", "8080"]
DOCKERFILE_EOF

        cat > .gitignore << 'GITIGNORE_EOF'
__pycache__/
*.pyc
*.pyo
.env
*.db
GITIGNORE_EOF

        git add .
        git commit -m "feat: initial ShopFlow demo application

Auto-seeded by TuskerSquad gitea-setup on first boot.
ShopFlow is the e-commerce test target for the TuskerSquad
AI PR governance pipeline. It includes intentional bug flags
(BUG_PRICE, BUG_SECURITY, BUG_SLOW) for agent detection demos."

        if git push origin main 2>&1; then
            log "Demo app pushed successfully to ${ADMIN_USER}/${REPO_NAME}"
        else
            log "WARNING: git push failed — builder will clone an empty repo on first run"
        fi

        cd /
        rm -rf "${WORK_DIR}"
    else
        log "WARNING: git clone failed — skipping source push"
        rm -rf "${WORK_DIR}"
    fi
fi

########################################
# Done
########################################

log ""
log "=========================================="
log "  TuskerSquad Gitea setup complete!"
log "=========================================="
log "  UI         : ${GITEA_URL}"
log "  Repository : ${GITEA_URL}/${ADMIN_USER}/${REPO_NAME}"
log "  Webhook    : ${WEBHOOK_URL}"
log ""
log "To enable PR comment posting:"
log "  1. Copy the GITEA_TOKEN printed above to infra/.env"
log "     OR: Gitea UI > ${ADMIN_USER} > Settings > Applications"
log "         Generate token with: repo read+write, issue read+write"
log "  2. run: make restart"
