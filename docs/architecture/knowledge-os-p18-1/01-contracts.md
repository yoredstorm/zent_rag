# P18.1-09 — Contrato `knowledge_explorer_insight/v1`

Read model regenerable. No crea objetos canónicos ni es autoridad.

```json
{
  "contract": "knowledge_explorer_insight/v1",
  "model_version": "deterministic-explorer-1",
  "generated_at": "ISO-8601",
  "source": {
    "source_id": "uuid",
    "document_id": "uuid|null",
    "name": "string",
    "source_type": "file|csv|...",
    "status": "indexed|...",
    "genre": "narrative|technical|policy|legal|tabular|mixed|educational|unknown",
    "genre_confidence": 0.0,
    "genre_evidence": [],
    "document_type": "string|null",
    "pages": 0,
    "sections": 0,
    "tables": 0
  },
  "summary": "string",
  "topics": [
    {
      "id": "string",
      "label": "string",
      "summary": "string",
      "scope": "documento",
      "source_locator": {"page": 0, "section_path": []},
      "verification_state": "mixed",
      "count": 0,
      "insights": [
        {
          "kind": "concept|business_rule|field|...",
          "object_id": "uuid|null",
          "name": "string",
          "claim_text": "string",
          "grounded_excerpt": "string|null",
          "evidence_ids": ["uuid"],
          "source_locator": {"page": 0, "section_path": [], "locator": "string"},
          "verification_state": "discovered|inferred|verified|...",
          "uncertainty": "alta|media|baja",
          "confidence": 0.0,
          "why_related": "string"
        }
      ]
    }
  ],
  "warnings": [{"code": "string", "message": "string", "severity": "info|warning"}],
  "provenance": {
    "source_fingerprint": "sha256|null",
    "source_profile_version": "string|null",
    "contract": "knowledge_explorer_insight/v1",
    "method": "deterministic",
    "authority": "read_model"
  },
  "counts": {
    "objects_total": 0,
    "objects_visible": 0,
    "objects_hidden": 0,
    "insights": 0,
    "topics": 0
  }
}
```

## Reglas

- Cada `insight` con `grounded_excerpt` debe tener `evidence_ids` y
  `source_locator`. Sin excerpt, `uncertainty=alta`.
- `confidence` es la confianza calculada del objeto, no comprensión del
  documento.
- `explorer_visibility=hidden` y `needs_review` viven en metadata versionada;
  no borran ni cambian ids.
- El endpoint es determinista. Un LLM de resumen queda apagado por defecto y,
  si se habilita, no puede escribir conocimiento canónico.
