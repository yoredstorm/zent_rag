# Verified Query Repository (Phase 26C/26D)

Organization-validated NL↔SQL knowledge. Statuses:
`DRAFT | IN_REVIEW | VERIFIED | DEPRECATED | INVALID`.

## Search

```text
Question → Semantic AST → Verified Query Search
```

Scores combine text, metrics, segments, entities, time structure, dialect.
**Text similarity alone is never enough.**

## Adaptation

Time-only adaptation returns updated AST + original SQL.
Never unsafe string replacement on arbitrary SQL.

## Learning

Repeated equality filters in successful SQL → `MappingSuggestion` with status
`INFERRED`. Human must `APPROVE` / `REJECT` / `EDIT_AND_APPROVE`.

## SQL Expert (26D)

`PostgresSqlExpert` searches verified queries **before** LLM generation.
Hits still pass `validate_sql` — Verified ≠ unrestricted.

## API

- `GET/POST /api/v1/intelligence/verified-queries`
- `GET /api/v1/intelligence/verified-queries/search?q=`
- `GET /api/v1/intelligence/mapping-suggestions`
- `POST /api/v1/intelligence/mapping-suggestions/{id}/review`

## Modules

- `src/core/domain/verified_query.py`
- `src/intelligence/verified_query_store.py`
- `src/intelligence/verified_queries.py`
- migration `082_verified_queries.py`
