#!/bin/bash
# =============================================================================
# Dev-only seed: API token with admin:* scope for local testing.
# Runs ONLY when RAG_SEED_DEMO_DATA=true (docker-compose dev / CI).
# Never executes in production databases.
# =============================================================================
set -euo pipefail

if [ "${RAG_SEED_DEMO_DATA:-false}" != "true" ]; then
    echo "RAG_SEED_DEMO_DATA != true — skipping dev seed (admin token)."
    exit 0
fi

echo "Seeding dev API key (RAG_SEED_DEMO_DATA=true)..."

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<'SQL'
INSERT INTO api_keys (id, organization_id, key_hash, key_prefix, name, scopes)
SELECT
    '30000000-0000-0000-0000-000000000001',
    '00000000-0000-0000-0000-000000000001',
    encode(sha256('rag_test_dev_token_for_local_testing_123'::bytea), 'hex'),
    'rag_test_',
    'Dev Token',
    '["rag:query", "rag:ingest", "admin:*"]'::jsonb
WHERE EXISTS (SELECT 1 FROM organizations WHERE id = '00000000-0000-0000-0000-000000000001')
AND NOT EXISTS (SELECT 1 FROM api_keys WHERE organization_id = '00000000-0000-0000-0000-000000000001');
SQL

echo "Dev seed complete."
