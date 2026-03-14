#!/bin/sh
# gitea_setup.sh
#
# One-shot initialisation for the tuskersquad-gitea-setup container.
# Triggered by: make up (first time) or make setup (manual re-run).
# NOT triggered by: make restart (which only bounces application services).
#
# Fully idempotent — safe to run multiple times. Each step checks current
# state before acting:
#   1. Wait for Gitea API
#   2. Authenticate with basic auth (always; token in .env is never used here)
#   3. Check / create shopflow repository
#   4. Create API token for services (ONLY on first-time run; skipped if repo exists)
#   5. Register webhook
#   6. Upload ShopFlow source via Gitea Contents API

# No set -e — each step has explicit error handling.

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

SRC="/shopflow-src"   # source baked into image by Dockerfile.gitea-setup

########################################
# Helpers
########################################

log()  { echo "[gitea-setup] $*"; }
warn() { echo "[gitea-setup] WARNING: $*"; }
die()  { echo "[gitea-setup] FATAL: $*"; exit 1; }

upload_file() {
    RPATH="$1"
    LPATH="$2"
    MSG="$3"

    B64=$(python3 -c "import base64,sys; sys.stdout.write(base64.b64encode(open('${LPATH}','rb').read()).decode())")

    EXISTING=$(curl -s -o /dev/null -w "%{http_code}" \
        -H "${AUTH_HEADER}" \
        "${API}/repos/${ADMIN_USER}/${REPO_NAME}/contents/${RPATH}" 2>/dev/null || echo "000")

    if [ "${EXISTING}" = "200" ]; then
        log "  skip (exists): ${RPATH}"
        return 0
    fi

    HTTP=$(curl -s -o /dev/null -w "%{http_code}" \
        -X POST \
        -H "${AUTH_HEADER}" \
        -H "Content-Type: application/json" \
        -d "{\"message\":\"${MSG}\",\"content\":\"${B64}\",\"new_branch\":\"main\"}" \
        "${API}/repos/${ADMIN_USER}/${REPO_NAME}/contents/${RPATH}" 2>/dev/null || echo "000")

    if [ "${HTTP}" = "201" ]; then
        log "  uploaded: ${RPATH}"
    else
        warn "upload failed for ${RPATH} (HTTP ${HTTP})"
    fi
}

########################################
# Step 1 — Wait for Gitea API
########################################

log "Step 1: Waiting for Gitea API ..."
i=0; CODE="000"
while [ "$i" -lt "$MAX_RETRIES" ]; do
    CODE=$(curl -s -o /dev/null -w "%{http_code}" "${API}/version" 2>/dev/null || echo "000")
    [ "$CODE" = "200" ] && { log "  Gitea API ready"; break; }
    log "  attempt $((i+1))/${MAX_RETRIES} — HTTP ${CODE}"
    sleep "$SLEEP_TIME"
    i=$((i+1))
done
[ "$CODE" = "200" ] || die "Gitea API not ready after $((MAX_RETRIES * SLEEP_TIME))s"

########################################
# Step 2 — Basic auth (always; never uses GITEA_TOKEN)
#
# Basic auth with ADMIN_USER/ADMIN_PASS is always correct for THIS Gitea
# instance — the credentials are set in docker-compose.yml and recreated
# by gitea_init.sh on every fresh volume. The GITEA_TOKEN in infra/.env is
# for the running application services to post PR comments; this script
# never touches it and never uses it for any operation.
########################################

log "Step 2: Authenticating as ${ADMIN_USER} ..."
ENCODED=$(printf '%s:%s' "${ADMIN_USER}" "${ADMIN_PASS}" | base64 | tr -d '\n')
AUTH_HEADER="Authorization: Basic ${ENCODED}"

i=0; AUTH_CODE="000"
while [ "$i" -lt "$MAX_RETRIES" ]; do
    AUTH_CODE=$(curl -s -o /dev/null -w "%{http_code}" \
        -H "${AUTH_HEADER}" "${API}/user" 2>/dev/null || echo "000")
    [ "$AUTH_CODE" = "200" ] && { log "  basic auth OK"; break; }
    log "  auth attempt $((i+1))/${MAX_RETRIES} — HTTP ${AUTH_CODE}"
    sleep "$SLEEP_TIME"
    i=$((i+1))
done
[ "$AUTH_CODE" = "200" ] || die "Admin auth failed (HTTP ${AUTH_CODE}) — check GITEA_ADMIN_USER/PASS in docker-compose.yml"

########################################
# Step 3 — Check / create repository
########################################

log "Step 3: Checking repository ${ADMIN_USER}/${REPO_NAME} ..."
REPO_CODE=$(curl -s -o /dev/null -w "%{http_code}" \
    -H "${AUTH_HEADER}" \
    "${API}/repos/${ADMIN_USER}/${REPO_NAME}" 2>/dev/null || echo "000")

if [ "$REPO_CODE" = "200" ]; then
    log "  repository already exists"
    FIRST_RUN=0
else
    FIRST_RUN=1
    log "  creating repository '${REPO_NAME}' ..."
    CREATE_CODE=$(curl -s -o /dev/null -w "%{http_code}" \
        -X POST \
        -H "${AUTH_HEADER}" \
        -H "Content-Type: application/json" \
        -d "{\"name\":\"${REPO_NAME}\",\"description\":\"ShopFlow demo e-commerce app\",\"private\":false,\"auto_init\":false,\"default_branch\":\"main\"}" \
        "${API}/user/repos" 2>/dev/null || echo "000")
    [ "$CREATE_CODE" = "201" ] || die "Repository creation failed (HTTP ${CREATE_CODE})"
    log "  repository created (HTTP 201)"
fi

########################################
# Step 4 — Create API token (first run only)
#
# A token is only created when the repo didn't exist (first-time setup).
# On subsequent runs (make setup re-run, or gitea-setup container restarted
# accidentally), the repo already exists so we skip this entirely — the token
# already in infra/.env is still valid and the services depend on it.
#
# Rotating the token on every run would silently break langgraph and
# integration-service until the operator notices, updates .env, and restarts.
########################################

log "Step 4: API token ..."
if [ "$FIRST_RUN" = "0" ]; then
    log "  Gitea already initialised — skipping token creation"
    log "  (GITEA_TOKEN in infra/.env is still valid)"
else
    log "  first-time setup — creating service token ..."
    curl -s -o /dev/null -X DELETE \
        -H "${AUTH_HEADER}" \
        "${API}/users/${ADMIN_USER}/tokens/tuskersquad-auto" 2>/dev/null || true

    TOKEN_RESP=$(curl -s -X POST \
        -H "${AUTH_HEADER}" \
        -H "Content-Type: application/json" \
        -d '{"name":"tuskersquad-auto"}' \
        "${API}/users/${ADMIN_USER}/tokens" 2>/dev/null || echo "{}")

    AUTO_TOKEN=$(printf '%s' "${TOKEN_RESP}" | grep -o '"sha1":"[^"]*"' | sed 's/"sha1":"//;s/"//')

    if [ -n "${AUTO_TOKEN}" ]; then
        log "  ============================================================"
        log "  token created — copy to infra/.env then run: make restart"
        log "  GITEA_TOKEN=${AUTO_TOKEN}"
        log "  ============================================================"
    else
        warn "token creation failed — PR comments will not work"
        warn "Create manually: Gitea UI > ${ADMIN_USER} > Settings > Applications"
    fi
fi

########################################
# Step 5 — Register webhook
########################################

log "Step 5: Checking webhook ..."
HOOKS=$(curl -s \
    -H "${AUTH_HEADER}" \
    "${API}/repos/${ADMIN_USER}/${REPO_NAME}/hooks" 2>/dev/null || echo "[]")

if printf '%s' "${HOOKS}" | grep -q "${WEBHOOK_URL}"; then
    log "  webhook already registered"
else
    log "  registering webhook -> ${WEBHOOK_URL}"
    HOOK_CODE=$(curl -s -o /dev/null -w "%{http_code}" \
        -X POST \
        -H "${AUTH_HEADER}" \
        -H "Content-Type: application/json" \
        -d "{\"type\":\"gitea\",\"config\":{\"url\":\"${WEBHOOK_URL}\",\"content_type\":\"json\",\"secret\":\"${WEBHOOK_SECRET}\"},\"events\":[\"pull_request\"],\"active\":true,\"push_events\":true,\"pull_request_events\":true,\"issue_events\":false}" \
        "${API}/repos/${ADMIN_USER}/${REPO_NAME}/hooks" 2>/dev/null || echo "000")
    [ "$HOOK_CODE" = "201" ] && log "  webhook registered" || warn "webhook HTTP ${HOOK_CODE}"
fi

########################################
# Step 6 — Upload ShopFlow source
########################################

log "Step 6: Checking ShopFlow source ..."
FILE_COUNT=$(curl -s \
    -H "${AUTH_HEADER}" \
    "${API}/repos/${ADMIN_USER}/${REPO_NAME}/contents/" 2>/dev/null \
    | grep -o '"type"' | wc -l | tr -d ' ')

if [ "${FILE_COUNT}" -gt "2" ]; then
    log "  repo already has ${FILE_COUNT} files — skipping upload"
elif [ ! -f "${SRC}/apps/backend/main.py" ]; then
    warn "Source not found at ${SRC} — image may not have been rebuilt"
    warn "Run: docker compose build gitea-setup && make setup"
else
    log "  uploading ShopFlow source via Gitea Contents API ..."
    COMMIT_MSG="feat: initial ShopFlow demo application"

    # Dockerfile (generated — not from SRC)
    DF_B64=$(python3 -c "
import base64
content = b'''# ShopFlow demo backend
FROM python:3.11-slim
RUN apt-get update && apt-get install -y --no-install-recommends gcc libffi-dev && rm -rf /var/lib/apt/lists/*
WORKDIR /app
RUN pip install --no-cache-dir --upgrade pip==24.3.1
COPY requirements.txt /tmp/demo-requirements.txt
RUN pip install --no-cache-dir -r /tmp/demo-requirements.txt
COPY apps/ /app/apps/
ENV PYTHONPATH=/app
HEALTHCHECK --interval=10s --timeout=5s --start-period=30s --retries=6 CMD python3 -c \"import urllib.request; urllib.request.urlopen(\'http://localhost:8080/health\', timeout=4)\"
CMD [\"uvicorn\", \"apps.backend.main:app\", \"--host\", \"0.0.0.0\", \"--port\", \"8080\"]
'''
print(base64.b64encode(content).decode(), end='')
")
    HTTP=$(curl -s -o /dev/null -w "%{http_code}" -X POST \
        -H "${AUTH_HEADER}" -H "Content-Type: application/json" \
        -d "{\"message\":\"${COMMIT_MSG}\",\"content\":\"${DF_B64}\",\"new_branch\":\"main\"}" \
        "${API}/repos/${ADMIN_USER}/${REPO_NAME}/contents/Dockerfile" 2>/dev/null || echo "000")
    [ "$HTTP" = "201" ] && log "  uploaded: Dockerfile" || warn "Dockerfile HTTP ${HTTP}"

    upload_file "requirements.txt"                    "${SRC}/apps/backend/requirements.txt"   "${COMMIT_MSG}"

    GI_B64=$(python3 -c "import base64; print(base64.b64encode(b'__pycache__/\n*.pyc\n*.pyo\n.env\n*.db\n').decode(), end='')")
    HTTP=$(curl -s -o /dev/null -w "%{http_code}" -X POST \
        -H "${AUTH_HEADER}" -H "Content-Type: application/json" \
        -d "{\"message\":\"${COMMIT_MSG}\",\"content\":\"${GI_B64}\",\"new_branch\":\"main\"}" \
        "${API}/repos/${ADMIN_USER}/${REPO_NAME}/contents/.gitignore" 2>/dev/null || echo "000")
    [ "$HTTP" = "201" ] && log "  uploaded: .gitignore" || warn ".gitignore HTTP ${HTTP}"

    upload_file "apps/__init__.py"                    "${SRC}/apps/__init__.py"                 "${COMMIT_MSG}"
    upload_file "apps/backend/__init__.py"            "${SRC}/apps/backend/__init__.py"         "${COMMIT_MSG}"
    upload_file "apps/backend/routes/__init__.py"     "${SRC}/apps/backend/routes/__init__.py"  "${COMMIT_MSG}"
    upload_file "apps/backend/auth.py"                "${SRC}/apps/backend/auth.py"             "${COMMIT_MSG}"
    upload_file "apps/backend/bug_flags.py"           "${SRC}/apps/backend/bug_flags.py"        "${COMMIT_MSG}"
    upload_file "apps/backend/database.py"            "${SRC}/apps/backend/database.py"         "${COMMIT_MSG}"
    upload_file "apps/backend/dependencies.py"        "${SRC}/apps/backend/dependencies.py"     "${COMMIT_MSG}"
    upload_file "apps/backend/main.py"                "${SRC}/apps/backend/main.py"             "${COMMIT_MSG}"
    upload_file "apps/backend/models.py"              "${SRC}/apps/backend/models.py"           "${COMMIT_MSG}"
    upload_file "apps/backend/schemas.py"             "${SRC}/apps/backend/schemas.py"          "${COMMIT_MSG}"
    upload_file "apps/backend/seed_data.py"           "${SRC}/apps/backend/seed_data.py"        "${COMMIT_MSG}"
    upload_file "apps/backend/routes/auth.py"         "${SRC}/apps/backend/routes/auth.py"      "${COMMIT_MSG}"
    upload_file "apps/backend/routes/checkout.py"     "${SRC}/apps/backend/routes/checkout.py"  "${COMMIT_MSG}"
    upload_file "apps/backend/routes/orders.py"       "${SRC}/apps/backend/routes/orders.py"    "${COMMIT_MSG}"
    upload_file "apps/backend/routes/products.py"     "${SRC}/apps/backend/routes/products.py"  "${COMMIT_MSG}"
    upload_file "apps/backend/routes/user.py"         "${SRC}/apps/backend/routes/user.py"      "${COMMIT_MSG}"
    upload_file "apps/backend/static/index.html"      "${SRC}/apps/backend/static/index.html"   "${COMMIT_MSG}"

    log "  source upload complete"
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
