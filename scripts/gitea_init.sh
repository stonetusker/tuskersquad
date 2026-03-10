#!/bin/sh
# gitea_init.sh
#
# Entrypoint wrapper for the Gitea container.
#
# Responsibilities:
#  - Start Gitea server
#  - Wait for API readiness
#  - Ensure admin user exists
#  - Reset admin password from environment variables
#
# Safe to run multiple times.

set -e

########################################
# Environment
########################################

ADMIN_USER="${GITEA_ADMIN_USER:-tusker}"
ADMIN_PASS="${GITEA_ADMIN_PASS:-tusker1234}"
ADMIN_EMAIL="${GITEA_ADMIN_EMAIL:-admin@tuskersquad.local}"

GITEA_API="http://localhost:3000/api/v1/version"

MAX_RETRIES=40
SLEEP_TIME=2

log() {
    echo "[gitea-init] $1"
}

########################################
# Start Gitea
########################################

log "Starting Gitea..."

/usr/bin/entrypoint &

GITEA_PID=$!

########################################
# Wait for API readiness
########################################

log "Waiting for Gitea API..."

i=0
HTTP_CODE="000"

while [ $i -lt $MAX_RETRIES ]; do

    HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" "${GITEA_API}" || echo "000")

    if [ "$HTTP_CODE" = "200" ]; then
        log "Gitea API ready"
        break
    fi

    log "Attempt $((i+1))/${MAX_RETRIES} - HTTP ${HTTP_CODE}"
    sleep "${SLEEP_TIME}"
    i=$((i+1))

done

if [ "$HTTP_CODE" != "200" ]; then
    log "WARNING: API not ready after timeout, continuing anyway"
fi

########################################
# Ensure admin user exists
########################################

log "Checking admin user '${ADMIN_USER}'..."

USER_EXISTS=$(su git -c "/usr/local/bin/gitea admin user list" | grep -c "^.*${ADMIN_USER}.*" || true)

if [ "$USER_EXISTS" = "0" ]; then

    log "Creating admin user '${ADMIN_USER}'"

    su git -c "/usr/local/bin/gitea admin user create \
        --admin \
        --username '${ADMIN_USER}' \
        --password '${ADMIN_PASS}' \
        --email '${ADMIN_EMAIL}' \
        --must-change-password=false"

else

    log "Admin user exists — resetting password"

    su git -c "/usr/local/bin/gitea admin user change-password \
        --username '${ADMIN_USER}' \
        --password '${ADMIN_PASS}'"

fi

########################################
# Confirmation
########################################

log "Admin user ready"
log "Username: ${ADMIN_USER}"
log "Password: ${ADMIN_PASS}"

########################################
# Wait for gitea process
########################################

wait ${GITEA_PID}