# =============================================================================
# Representation Layer — versiones de representación
# =============================================================================
# Cada versión entra en el representation_fingerprint. Si una cambia, el
# pipeline sabe que el artefacto de retrieval quedó stale sin reprocesar la
# fuente: solo se re-materializa / re-indexa lo necesario.
# =============================================================================
from __future__ import annotations

REPRESENTATION_SCHEMA_VERSION = "1"

# Representación de contenido del chunk hijo (título + sección + contenido).
CONTENT_REPRESENTATION_VERSION = "content-rep-1"

# Representación de retrieval (conceptos + aliases + preguntas sintéticas).
RETRIEVAL_REPRESENTATION_VERSION = "retrieval-rep-1"

# Representación compacta del padre (sección): compuesta, nunca truncada.
PARENT_REPRESENTATION_VERSION = "parent-semantic-1"

# Codificación sparse: md5-32 + TF (ver infrastructure/qdrant/bm25.py).
# v2: el texto sparse es contenido + representación de retrieval (conserva
# recall lexical); v1 indexaba solo la representación derivada.
SPARSE_ENCODING_VERSION = "md5-32-tf-2-content+retrieval"

# Contextualización del chunk (prefijo de sección) aplicada antes de embeber.
CONTEXTUALIZATION_VERSION = "section-prefix-1"

# Forma en que el conocimiento compilado (entidades, reglas, conceptos) entra
# como metadata del índice. Cambia si cambia qué se anota o cómo.
COMPILER_REPRESENTATION_VERSION = "compiler-rep-1"

# Fase 9: enriquecimiento del retrieval unit con el Semantic Fabric
# (node ids por tipo, dependency ids, semantic neighborhood). Cambiar esta
# versión invalida la representación y re-indexa sin reprocesar la fuente.
FABRIC_REPRESENTATION_VERSION = "fabric-units-1"

# Fase 10: qué texto se embebe por retrieval unit (content/semantic/concept/
# question) y su versión. Cambiarla invalida SOLO el embedding (reindex).
EMBEDDING_REPRESENTATION_VERSION = "embedding-rep-1"
