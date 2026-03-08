#!/bin/bash
# ─────────────────────────────────────────────────────────────────────────────
# TuskerSquad — Stonetusker Systems
# Postgres init: runs on first container start only.
# Creates DB and user idempotently, then applies schema.
# ─────────────────────────────────────────────────────────────────────────────
set -e

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<-SQL
    -- Ensure tuskersquad DB exists
    SELECT 'CREATE DATABASE tuskersquad'
    WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'tuskersquad')
    \gexec

    -- Ensure tusker user exists
    DO \$\$
    BEGIN
        IF NOT EXISTS (SELECT FROM pg_catalog.pg_roles WHERE rolname = 'tusker') THEN
            CREATE ROLE tusker LOGIN PASSWORD 'tusker';
        END IF;
    END
    \$\$;

    GRANT ALL PRIVILEGES ON DATABASE tuskersquad TO tusker;
SQL

echo "TuskerSquad: postgres init complete"
