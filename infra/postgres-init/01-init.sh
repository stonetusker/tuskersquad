#!/bin/bash
# TuskerSquad — Postgres initialisation
# Runs once on first container start (postgres-init is mounted as initdb.d).
# The DB "tuskersquad" and user "tusker" already exist because Docker creates them
# from POSTGRES_USER / POSTGRES_DB env vars — we just ensure privileges are correct.
set -e

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<-SQL
    -- uuid-ossp extension used by SQLAlchemy UUID columns
    CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

    -- Ensure the tusker role has full access (idempotent)
    GRANT ALL PRIVILEGES ON DATABASE tuskersquad TO tusker;
    GRANT ALL ON SCHEMA public TO tusker;
SQL

echo "TuskerSquad: postgres init complete ✓"
