-- Google Drive (gdrive) es un tipo de kb_sources registrado por plugin.
-- No hay CHECK de type (mismo patrón que 008_connector_types).
ALTER TABLE kb_sources DROP CONSTRAINT IF EXISTS kb_sources_type_check;
ALTER TABLE kb_sources ALTER COLUMN type TYPE VARCHAR(40);
