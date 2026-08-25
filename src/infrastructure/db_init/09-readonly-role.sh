#!/bin/bash
# =============================================================================
# Read-only Role — SQL Expert (Text-to-SQL Engine)
# =============================================================================
# Rol PostgreSQL dedicado para ejecutar consultas generadas por el motor
# Text-to-SQL. SOLO SELECT sobre el esquema público; sin DDL/DML.
# La contraseña viene de POSTGRES_READONLY_PASSWORD (docker-compose env).
# =============================================================================
set -e

READONLY_PASSWORD="${POSTGRES_READONLY_PASSWORD:-readonly_change_me}"

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<-EOSQL
    DO \$\$
    DECLARE
        t text;
    BEGIN
        IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'rag_reader') THEN
            EXECUTE format('CREATE ROLE rag_reader LOGIN PASSWORD %L NOSUPERUSER NOCREATEDB NOCREATEROLE', '$READONLY_PASSWORD');
        ELSE
            EXECUTE format('ALTER ROLE rag_reader WITH LOGIN PASSWORD %L NOSUPERUSER NOCREATEDB NOCREATEROLE', '$READONLY_PASSWORD');
        END IF;

        EXECUTE 'GRANT USAGE ON SCHEMA public TO rag_reader';
        EXECUTE 'GRANT SELECT ON ALL TABLES IN SCHEMA public TO rag_reader';
        EXECUTE 'GRANT SELECT ON ALL SEQUENCES IN SCHEMA public TO rag_reader';
        EXECUTE 'ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON TABLES TO rag_reader';
        EXECUTE 'ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON SEQUENCES TO rag_reader';

        IF EXISTS (SELECT 1 FROM information_schema.schemata WHERE schema_name = 'farmacia') THEN
            EXECUTE 'GRANT USAGE ON SCHEMA farmacia TO rag_reader';
            EXECUTE 'GRANT SELECT ON ALL TABLES IN SCHEMA farmacia TO rag_reader';
            EXECUTE 'GRANT SELECT ON ALL SEQUENCES IN SCHEMA farmacia TO rag_reader';
            EXECUTE 'ALTER DEFAULT PRIVILEGES IN SCHEMA farmacia GRANT SELECT ON TABLES TO rag_reader';
            EXECUTE 'ALTER DEFAULT PRIVILEGES IN SCHEMA farmacia GRANT SELECT ON SEQUENCES TO rag_reader';
        END IF;

        FOREACH t IN ARRAY ARRAY[
            'organizations','users','memberships','roles','permissions',
            'role_permissions','api_keys','subscriptions','plans','invoices',
            'usage_events','usage_logs','audit_logs','portal_sessions'
        ]
        LOOP
            IF EXISTS (
                SELECT 1 FROM information_schema.tables
                WHERE table_schema = 'public' AND table_name = t
            ) THEN
                EXECUTE format('REVOKE SELECT ON TABLE public.%I FROM rag_reader', t);
            END IF;
        END LOOP;

        REVOKE ALL ON SCHEMA pg_catalog FROM rag_reader;
        REVOKE ALL ON SCHEMA information_schema FROM rag_reader;
    END \$\$;
EOSQL

echo "Read-only role rag_reader provisioned."
