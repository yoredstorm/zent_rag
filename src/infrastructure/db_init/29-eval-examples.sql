-- =============================================================================
-- Evaluation Engine — eval_examples como entidad de primer nivel
-- Espejo SQL de la migración alembic 026_eval_examples (bases nuevas).
-- =============================================================================

CREATE TABLE IF NOT EXISTS eval_examples (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID NOT NULL,
    dataset_id UUID NOT NULL REFERENCES eval_datasets(id) ON DELETE CASCADE,
    question TEXT NOT NULL,
    expected_answer TEXT,
    expected_behavior VARCHAR(80),
    expected_sources JSONB NOT NULL DEFAULT '[]',
    must_cite BOOLEAN NOT NULL DEFAULT false,
    metadata JSONB NOT NULL DEFAULT '{}',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_eval_examples_dataset ON eval_examples(dataset_id);
CREATE INDEX IF NOT EXISTS idx_eval_examples_org ON eval_examples(organization_id);

INSERT INTO eval_examples (
    id, organization_id, dataset_id, question, expected_answer,
    expected_behavior, expected_sources, must_cite, metadata
)
SELECT gen_random_uuid(), d.organization_id, d.id,
       c.value ->> 'question',
       c.value ->> 'expected_answer',
       c.value ->> 'expected_behavior',
       COALESCE(c.value -> 'expected_sources', '[]'::jsonb),
       COALESCE((c.value ->> 'must_cite')::boolean, false),
       COALESCE(c.value -> 'metadata', '{}'::jsonb)
FROM eval_datasets d
CROSS JOIN LATERAL jsonb_array_elements(d.cases) c(value)
WHERE (c.value ->> 'question') IS NOT NULL;