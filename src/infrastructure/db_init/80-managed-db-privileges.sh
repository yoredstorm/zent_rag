#!/bin/bash
# =============================================================================
# Managed DB privileges — LocalPostgresProvider (Phase 31C)
# =============================================================================
# CREATE DATABASE zent_cust_* and LOGIN roles zent_schema_admin_* /
# zent_query_reader_* need CREATEDB + CREATEROLE. Official Postgres image
# already makes POSTGRES_USER a superuser; this is explicit and re-runnable
# on existing volumes:
#   docker exec rag-postgres bash /docker-entrypoint-initdb.d/80-managed-db-privileges.sh
# =============================================================================
set -e

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<-EOSQL
    DO \$\$
    BEGIN
        EXECUTE format(
            'ALTER ROLE %I WITH CREATEDB CREATEROLE',
            current_user
        );
    END
    \$\$;
EOSQL

echo "Managed DB privileges: CREATEDB CREATEROLE granted to current_user"
