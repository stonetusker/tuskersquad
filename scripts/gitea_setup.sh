#!/bin/sh
# gitea_setup.sh
#
# One-shot initialisation for the tuskersquad-gitea-setup container.
# Safe to run multiple times — every step is idempotent.
#
# Steps:
#   1. Wait for Gitea API
#   2. Authenticate as admin
#   3. Auto-create API token (if GITEA_TOKEN not set)
#   4. Create shopflow repository
#   5. Register TuskerSquad webhook
#   6. Upload ShopFlow demo source via Gitea Contents API
#      (curl + base64, no git required)
#
# Source files are baked into the image at /shopflow-src/
# (see infra/Dockerfile.gitea-setup COPY directives).

# Intentionally no `set -e` — each step has explicit error handling
# so one failure doesn't silently abort all remaining steps.

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

# Source files live here (baked into the Docker image)
SRC="/shopflow-src"

########################################
# Helpers
########################################

log()  { echo "[gitea-setup] $*"; }
warn() { echo "[gitea-setup] WARNING: $*"; }
die()  { echo "[gitea-setup] FATAL: $*"; exit 1; }

# Upload one file to Gitea via the Contents API.
# Usage: upload_file <repo_path> <local_path> <commit_message>
upload_file() {
    RPATH="$1"   # e.g. apps/backend/main.py
    LPATH="$2"   # e.g. /shopflow-src/apps/backend/main.py
    MSG="$3"

    # base64-encode the file (python3 in image; avoids busybox base64 line-wrap issues)
    B64=$(python3 -c "import base64,sys; sys.stdout.write(base64.b64encode(open('${LPATH}','rb').read()).decode())")

    # Check if file already exists (idempotent)
    EXISTING=$(curl -s -o /dev/null -w "%{http_code}" \
        -H "${AUTH_HEADER}" \
        "${API}/repos/${ADMIN_USER}/${REPO_NAME}/contents/${RPATH}" 2>/dev/null || echo "000")

    if [ "${EXISTING}" = "200" ]; then
        log "  skip (exists): ${RPATH}"
        return 0
    fi

    # "new_branch":"main" ensures Gitea targets the main branch even on an empty repo
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

log "Step 1: Waiting for Gitea API at ${API}/version ..."
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
# Step 2 — Admin authentication
#
# Always use basic auth (ADMIN_USER + ADMIN_PASS) for ALL setup operations.
# These credentials are set in docker-compose.yml and are always correct for
# this Gitea instance — they never go stale.
#
# GITEA_TOKEN in .env is for the running services (langgraph, integration) to
# post PR comments. It is NOT used here — a scopeless or stale token would
# cause 401/403 on repo/webhook/content operations.
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
[ "$AUTH_CODE" = "200" ] || die "Admin authentication failed (HTTP ${AUTH_CODE}) — check GITEA_ADMIN_USER / GITEA_ADMIN_PASS"

########################################
# Step 3 — Auto-create API token for services
#
# The token is NOT used by this setup script for any operations.
# All setup (repo create, webhook, file upload) uses basic auth throughout —
# basic auth has full admin access and never goes stale.
#
# The token is created here purely so the langgraph and integration services
# can post PR comments to Gitea. It is printed to logs for the operator to
# copy into infra/.env.
########################################

log "Step 3: Creating service API token ..."

# Always delete the old auto-token and issue a fresh one so the operator
# gets a valid token regardless of previous state.
curl -s -o /dev/null -X DELETE \
    -H "${AUTH_HEADER}" \
    "${API}/users/${ADMIN_USER}/tokens/tuskersquad-auto" 2>/dev/null || true

TOKEN_RESP=$(curl -s \
    -X POST \
    -H "${AUTH_HEADER}" \
    -H "Content-Type: application/json" \
    -d '{"name":"tuskersquad-auto"}' \
    "${API}/users/${ADMIN_USER}/tokens" 2>/dev/null || echo "{}")

AUTO_TOKEN=$(printf '%s' "${TOKEN_RESP}" | grep -o '"sha1":"[^"]*"' | sed 's/"sha1":"//;s/"//')

if [ -n "${AUTO_TOKEN}" ]; then
    log "  token created"
    log "  >>> COPY TO infra/.env:  GITEA_TOKEN=${AUTO_TOKEN}"
    log "  >>> Then run: make restart"
else
    warn "Could not create service token — PR comment posting will not work"
    warn "Create manually: Gitea UI > ${ADMIN_USER} > Settings > Applications"
fi
# AUTH_HEADER remains BASIC_HEADER for all subsequent setup steps

########################################
# Step 4 — Create repository
########################################

log "Step 4: Checking repository ${ADMIN_USER}/${REPO_NAME} ..."
REPO_CODE=$(curl -s -o /dev/null -w "%{http_code}" \
    -H "${AUTH_HEADER}" \
    "${API}/repos/${ADMIN_USER}/${REPO_NAME}" 2>/dev/null || echo "000")

if [ "$REPO_CODE" = "200" ]; then
    log "  repository already exists — skipping creation"
else
    log "  creating repository '${REPO_NAME}' ..."
    CREATE_CODE=$(curl -s -o /dev/null -w "%{http_code}" \
        -X POST \
        -H "${AUTH_HEADER}" \
        -H "Content-Type: application/json" \
        -d "{\"name\":\"${REPO_NAME}\",\"description\":\"ShopFlow demo e-commerce app\",\"private\":false,\"auto_init\":false,\"default_branch\":\"main\"}" \
        "${API}/user/repos" 2>/dev/null || echo "000")

    if [ "$CREATE_CODE" = "201" ]; then
        log "  repository created (HTTP 201)"
    else
        die "Repository creation failed (HTTP ${CREATE_CODE})"
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

    if [ "$HOOK_CODE" = "201" ]; then
        log "  webhook registered (HTTP 201)"
    else
        warn "webhook registration returned HTTP ${HOOK_CODE}"
    fi
fi

########################################
# Step 6 — Upload ShopFlow demo source
########################################

log "Step 6: Checking ShopFlow source in repository ..."

# Count files already in repo root
FILE_COUNT=$(curl -s \
    -H "${AUTH_HEADER}" \
    "${API}/repos/${ADMIN_USER}/${REPO_NAME}/contents/" 2>/dev/null \
    | grep -o '"type"' | wc -l | tr -d ' ')

if [ "${FILE_COUNT}" -gt "2" ]; then
    log "  repo already has ${FILE_COUNT} items — skipping source upload"
else
    # Verify baked-in source is present
    if [ ! -f "${SRC}/apps/backend/main.py" ]; then
        warn "Source not found at ${SRC} — was the image rebuilt after adding Dockerfile.gitea-setup?"
        warn "Run: docker compose build gitea-setup && docker compose up gitea-setup"
    else
        log "  uploading ShopFlow demo source via Gitea Contents API ..."
        log "  (source baked into image at ${SRC})"

        COMMIT_MSG="feat: initial ShopFlow demo application"

        # ── Dockerfile at repo root (builder_agent looks here) ──────────
        # Write the Dockerfile content directly (not from SRC — it's generated)
        log "  generating Dockerfile ..."
        DF_B64=$(python3 -c "
import base64
content = '''# ShopFlow demo backend — auto-generated by TuskerSquad gitea-setup
FROM python:3.11-slim

RUN apt-get update \\\\
 && apt-get install -y --no-install-recommends gcc libffi-dev \\\\
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app

RUN pip install --no-cache-dir --upgrade pip==24.3.1

COPY requirements.txt /tmp/demo-requirements.txt
RUN pip install --no-cache-dir -r /tmp/demo-requirements.txt

COPY apps/ /app/apps/

ENV PYTHONPATH=/app

HEALTHCHECK --interval=10s --timeout=5s --start-period=30s --retries=6 \\\\
  CMD python3 -c \"import urllib.request; urllib.request.urlopen(\\x27http://localhost:8080/health\\x27, timeout=4)\"

CMD [\"uvicorn\", \"apps.backend.main:app\", \"--host\", \"0.0.0.0\", \"--port\", \"8080\"]
'''
print(base64.b64encode(content.encode()).decode(), end='')
")
        HTTP=$(curl -s -o /dev/null -w "%{http_code}" \
            -X POST \
            -H "${AUTH_HEADER}" \
            -H "Content-Type: application/json" \
            -d "{\"message\":\"${COMMIT_MSG}\",\"content\":\"${DF_B64}\",\"new_branch\":\"main\"}" \
            "${API}/repos/${ADMIN_USER}/${REPO_NAME}/contents/Dockerfile" 2>/dev/null || echo "000")
        [ "$HTTP" = "201" ] && log "  uploaded: Dockerfile" || warn "Dockerfile upload HTTP ${HTTP}"

        # ── requirements.txt at repo root ───────────────────────────────
        upload_file "requirements.txt"          "${SRC}/apps/backend/requirements.txt" "${COMMIT_MSG}"

        # ── .gitignore ──────────────────────────────────────────────────
        GI_B64=$(python3 -c "import base64; print(base64.b64encode(b'__pycache__/\n*.pyc\n*.pyo\n.env\n*.db\n').decode(), end='')")
        HTTP=$(curl -s -o /dev/null -w "%{http_code}" \
            -X POST \
            -H "${AUTH_HEADER}" \
            -H "Content-Type: application/json" \
            -d "{\"message\":\"${COMMIT_MSG}\",\"content\":\"${GI_B64}\",\"new_branch\":\"main\"}" \
            "${API}/repos/${ADMIN_USER}/${REPO_NAME}/contents/.gitignore" 2>/dev/null || echo "000")
        [ "$HTTP" = "201" ] && log "  uploaded: .gitignore" || warn ".gitignore upload HTTP ${HTTP}"

        # ── Python package __init__ files ────────────────────────────────
        upload_file "apps/__init__.py"                    "${SRC}/apps/__init__.py"                    "${COMMIT_MSG}"
        upload_file "apps/backend/__init__.py"            "${SRC}/apps/backend/__init__.py"            "${COMMIT_MSG}"
        upload_file "apps/backend/routes/__init__.py"     "${SRC}/apps/backend/routes/__init__.py"     "${COMMIT_MSG}"

        # ── Backend source ───────────────────────────────────────────────
        upload_file "apps/backend/auth.py"                "${SRC}/apps/backend/auth.py"                "${COMMIT_MSG}"
        upload_file "apps/backend/bug_flags.py"           "${SRC}/apps/backend/bug_flags.py"           "${COMMIT_MSG}"
        upload_file "apps/backend/database.py"            "${SRC}/apps/backend/database.py"            "${COMMIT_MSG}"
        upload_file "apps/backend/dependencies.py"        "${SRC}/apps/backend/dependencies.py"        "${COMMIT_MSG}"
        upload_file "apps/backend/main.py"                "${SRC}/apps/backend/main.py"                "${COMMIT_MSG}"
        upload_file "apps/backend/models.py"              "${SRC}/apps/backend/models.py"              "${COMMIT_MSG}"
        upload_file "apps/backend/schemas.py"             "${SRC}/apps/backend/schemas.py"             "${COMMIT_MSG}"
        upload_file "apps/backend/seed_data.py"           "${SRC}/apps/backend/seed_data.py"           "${COMMIT_MSG}"

        # ── Routes ───────────────────────────────────────────────────────
        upload_file "apps/backend/routes/auth.py"         "${SRC}/apps/backend/routes/auth.py"         "${COMMIT_MSG}"
        upload_file "apps/backend/routes/checkout.py"     "${SRC}/apps/backend/routes/checkout.py"     "${COMMIT_MSG}"
        upload_file "apps/backend/routes/orders.py"       "${SRC}/apps/backend/routes/orders.py"       "${COMMIT_MSG}"
        upload_file "apps/backend/routes/products.py"     "${SRC}/apps/backend/routes/products.py"     "${COMMIT_MSG}"
        upload_file "apps/backend/routes/user.py"         "${SRC}/apps/backend/routes/user.py"         "${COMMIT_MSG}"

        # ── Static UI ────────────────────────────────────────────────────
        upload_file "apps/backend/static/index.html"      "${SRC}/apps/backend/static/index.html"      "${COMMIT_MSG}"

        log "  source upload complete"
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
log "  1. Add GITEA_TOKEN to infra/.env (auto-token printed above)"
log "     OR create manually: Gitea > ${ADMIN_USER} > Settings > Applications"
log "     Required scopes: repository + issue (read/write)"
log "  2. run: make restart"
