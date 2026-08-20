#!/bin/bash
# =============================================================================
# Demo vertical seed (farmacia) — SOLO cuando RAG_SEED_DEMO_DATA=true
# =============================================================================
# - Carga el esquema demo farmacia (02-seed-retail.sql) y el seed masivo
#   de rendimiento (05-massive-seed-performance.sql).
# - Aplica los prompts del vertical demo_farmacia al organization demo vía
#   organizations.config_json.
# Nunca se ejecuta en producción (el flag está en false).
# =============================================================================
set -euo pipefail

if [ "${RAG_SEED_DEMO_DATA:-false}" != "true" ]; then
    echo "RAG_SEED_DEMO_DATA != true — skipping demo vertical seed (farmacia)."
    exit 0
fi

echo "Seeding demo vertical (farmacia)..."

SCRIPT_DIR="$(dirname "$0")"

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" \
    -f "$SCRIPT_DIR/seed-demo/farmacia/02-seed-retail.sql"

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" \
    -f "$SCRIPT_DIR/seed-demo/farmacia/05-massive-seed-performance.sql"

echo "Demo vertical seed complete."
