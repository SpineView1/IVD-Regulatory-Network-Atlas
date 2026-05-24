#!/usr/bin/env bash
set -euo pipefail

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<-EOSQL
    CREATE ROLE pgbackrest LOGIN REPLICATION;
    GRANT pg_read_all_data TO pgbackrest;
EOSQL
