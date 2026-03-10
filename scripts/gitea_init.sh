#!/bin/sh
# gitea_init.sh
#
# Entrypoint wrapper for the Gitea container.
# Starts Gitea in the background, waits for it to be ready,
# creates the admin user if it does not already exist, then
# keeps Gitea running in the foreground.
#
# Mounted as /gitea_init.sh inside the container.
# Used via: command: ["/bin/sh", "/gitea_init.sh"]

ADMIN_USER="${GITEA_ADMIN_USER:-tusker}"
ADMIN_PASS="${GITEA_ADMIN_PASS:-tusker1234}"
ADMIN_EMAIL="${GITEA_ADMIN_EMAIL:-admin@tuskersquad.local}"

echo "[gitea-init] Starting Gitea..."
/usr/bin/entrypoint &
GITEA_PID=$!

echo "[gitea-init] Waiting for Gitea HTTP to be ready..."
MAX=40
i=0
while [ $i -lt $MAX ]; do
    if wget -qO- http://localhost:3000/ > /dev/null 2>&1; then
        echo "[gitea-init] Gitea is up"
        break
    fi
    i=$((i + 1))
    sleep 2
done

if [ $i -eq $MAX ]; then
    echo "[gitea-init] Gitea did not start in time - continuing anyway"
fi

# Create the admin user. Gitea returns an error if the user already exists,
# so we suppress that and check the exit code separately.
echo "[gitea-init] Creating admin user '${ADMIN_USER}' (skipped if already exists)..."
/usr/local/bin/gitea admin user create \
    --admin \
    --username "${ADMIN_USER}" \
    --password "${ADMIN_PASS}" \
    --email "${ADMIN_EMAIL}" \
    --must-change-password=false \
    2>&1 | grep -v "user already exists" || true

echo "[gitea-init] Admin user setup done"

# Keep the process alive - wait for gitea to exit
wait $GITEA_PID
