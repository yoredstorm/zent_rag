# =============================================================================
# Document Understanding — versiones cacheables por etapa
# =============================================================================
# RAW (archivo original) no se toca. PARSED lo produce el parser. CANONICAL
# es este esquema. RETRIEVAL / EMBEDDED quedan fuera: si solo cambia el modelo
# de embeddings no hay que repetir OCR ni este pase.
# =============================================================================

SCHEMA_VERSION = "2"
PARSER_VERSION = "document-understanding-1.0.0"
CHUNKING_VERSION = "structure-first-1"
PIPELINE = "document_understanding"

# Namespace estable para ids derivados (procedimientos, relaciones). No es ATPCO.
DERIVED_NS = "6f1c2a44-9b0e-4d7a-8c31-0a6e5d4b7f18"
