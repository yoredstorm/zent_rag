# =============================================================================
# Long-Context Engine — evidencia completa, no top-k.
# =============================================================================
# Paquete aditivo: representaciones de la consulta, pata exacta (must_keep),
# presupuesto adaptativo por modelo, requirements, information gain, empaquetado
# y expansión progresiva. No reemplaza al motor híbrido ni al adaptativo: los
# evoluciona. Todo detrás de settings; nada de negocio vertical.
# =============================================================================
from __future__ import annotations

__all__ = [
    "exact_search",
    "exact_tokens",
    "must_keep",
    "normalize",
]
