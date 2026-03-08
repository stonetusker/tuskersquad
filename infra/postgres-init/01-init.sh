#!/bin/bash
# Runs on first start of the postgres container.
# Creates the tuskersquad database and tusker user if they don't exist.
set -e

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "postgres" << EOSQL
-- Create the application database if it doesn't exist
SELECT 'CREATE DATABASE tuskersquad'
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'tuskersquad')\gexec

-- Ensure the tusker user exists with full privileges
DO \$\$
BEGIN
  IF NOT EXISTS (SELECT FROM pg_catalog.pg_roles WHERE rolname = 'tusker') THEN
    CREATE USER tusker WITH PASSWORD 'tusker';
  END IF;
END
\$\$;

GRANT ALL PRIVILEGES ON DATABASE tuskersquad TO tusker;
EOSQL

echo "PostgreSQL init complete: tuskersquad database ready"
