# =============================================================================
# Node Catalog — metadata semántica de negocio por tipo de nodo
# (Workflow Semantic Core, Fase 3; API/endpoint en Fase 4).
#
# Fuente backend: describe QUÉ es cada nodo, CUÁNDO usarlo y qué secciones del
# WorkflowContext lee/escribe. El portal y el planner IA lo consumen en fases
# posteriores; el registry sigue siendo la verdad de ejecución.
# =============================================================================
from __future__ import annotations

from typing import Any

# Tokens de dependencia que el catálogo puede verificar contra el tenant.
REQUIREMENT_TOKENS: frozenset[str] = frozenset(
    {
        "agents",
        "knowledge_bases",
        "installed_integrations",
        "managed_db",
    }
)

# Categorías visibles (orden de paleta en el portal).
CATEGORIES: tuple[dict[str, Any], ...] = (
    {"id": "trigger", "label": "Disparadores", "order": 0},
    {"id": "data", "label": "Datos", "order": 1},
    {"id": "ai", "label": "Inteligencia", "order": 2},
    {"id": "integration", "label": "Integraciones", "order": 3},
    {"id": "logic", "label": "Lógica", "order": 4},
    {"id": "business", "label": "Negocio", "order": 5},
    {"id": "control", "label": "Control", "order": 6},
    {"id": "output", "label": "Salidas", "order": 7},
)


def _meta(
    business_name: str,
    short_description: str,
    *,
    long_description: str = "",
    subcategory: str | None = None,
    when_to_use: tuple[str, ...] = (),
    when_not_to_use: tuple[str, ...] = (),
    examples: tuple[dict[str, Any], ...] = (),
    context_reads: tuple[str, ...] = (),
    context_writes: tuple[str, ...] = (),
    requires: tuple[str, ...] = (),
    optional_dependencies: tuple[str, ...] = (),
    supports_simulation: bool | None = None,
    supports_agent: bool = False,
    supports_knowledge: bool = False,
) -> dict[str, Any]:
    return {
        "business_name": business_name,
        "short_description": short_description,
        "long_description": long_description or short_description,
        "subcategory": subcategory,
        "when_to_use": tuple(when_to_use),
        "when_not_to_use": tuple(when_not_to_use),
        "examples": tuple(examples),
        "context_reads": tuple(context_reads),
        "context_writes": tuple(context_writes),
        "requires": tuple(requires),
        "optional_dependencies": tuple(optional_dependencies),
        "supports_simulation": supports_simulation,
        "supports_agent": supports_agent,
        "supports_knowledge": supports_knowledge,
    }


# Metadata semántica por node_type. Debe cubrir todo el registry (test).
NODE_METADATA: dict[str, dict[str, Any]] = {
    # ------------------------------------------------------------------
    # Triggers
    # ------------------------------------------------------------------
    "trigger_schedule": _meta(
        "Programar",
        "Ejecuta la automatización según una programación.",
        long_description=(
            "Dispara el flujo por calendario (diario, semanal o cada N minutos) "
            "en la zona horaria elegida."
        ),
        when_to_use=(
            "el flujo debe correr por calendario",
            "necesitas un resumen periódico",
        ),
        when_not_to_use=(
            "los datos cambian y quieres reaccionar al cambio; usa un evento o watcher",
        ),
        examples=(
            {"title": "Resumen diario 18:00", "config": {"daily": "18:00", "timezone": "America/Lima"}},
        ),
        supports_simulation=False,
    ),
    "trigger_webhook": _meta(
        "Webhook",
        "Recibe una llamada HTTP de un sistema externo.",
        long_description=(
            "Expone una URL pública protegida por secreto para que otro sistema "
            "inicie el flujo con su payload."
        ),
        when_to_use=("un sistema externo puede llamar a Zent",),
        when_not_to_use=(
            "el sistema no puede enviar peticiones o no hay secreto compartido; usa Programar",
        ),
        examples=(
            {"title": "POST del POS", "config": {"note": "se genera al guardar"}},
        ),
        supports_simulation=False,
    ),
    "trigger_event": _meta(
        "Cuando ocurra algo",
        "Reacciona a un evento del negocio (venta, factura, stock).",
        long_description=(
            "Se suscribe a eventos internos (sales.closed, invoice.overdue, ...) "
            "con filtros por campo."
        ),
        when_to_use=("existe un evento estándar como sales.closed o invoice.overdue",),
        when_not_to_use=(
            "necesitas detectar cambios por sondeo de tabla; usa un watcher",
        ),
        examples=(
            {"title": "Venta cerrada", "config": {"event_type": "sales.closed", "filters": {}}},
        ),
        supports_simulation=False,
    ),
    # ------------------------------------------------------------------
    # Datos / integraciones
    # ------------------------------------------------------------------
    "api_call": _meta(
        "Consultar servicio",
        "Consulta un servicio externo (modo técnico).",
        long_description=(
            "Llama un endpoint HTTP permitido en la allowlist del tenant, con "
            "SSRF check y extracción opcional de un campo."
        ),
        when_to_use=("la API ya está permitida en la allowlist del tenant",),
        when_not_to_use=(
            "existe una acción de integración instalada; usa Acción de integración",
        ),
        examples=(
            {
                "title": "Consultar stock",
                "config": {
                    "url": "https://api.example.com/stock",
                    "method": "GET",
                    "json_path": "available",
                },
            },
        ),
        context_reads=("trigger", "variables"),
        context_writes=("data",),
        optional_dependencies=("api_allowlist",),
        supports_simulation=True,
    ),
    "kb_query": _meta(
        "Consultar knowledge base",
        "Busca en una base de conocimiento de Zent.",
        long_description=(
            "Recupera fragmentos de documentos/políticas; en Fase 7 adjunta "
            "citations y referencias de evidencia al contexto."
        ),
        when_to_use=("la respuesta está en documentos, políticas o procedimientos",),
        when_not_to_use=(
            "necesitas totales o filas de una base de datos; usa Consultar datos de negocio",
        ),
        examples=(
            {
                "title": "Política de reposición",
                "config": {
                    "knowledge_base_id": "…",
                    "query": "política de reposición de stock",
                    "limit": 5,
                },
            },
        ),
        context_reads=("trigger", "variables"),
        context_writes=("knowledge", "evidence", "claims"),
        requires=("knowledge_bases",),
        supports_knowledge=True,
    ),
    "query_business_data": _meta(
        "Consultar datos de negocio",
        "Pregunta en lenguaje natural sobre tus datos conectados.",
        long_description=(
            "Pasa por el pipeline semántico completo (text-to-SQL, answerability, "
            "evidencia) y devuelve respuesta, filas y columnas cuando aplica."
        ),
        when_to_use=("necesitas métricas, totales o filas de datos",),
        when_not_to_use=(
            "la respuesta es un documento o política; usa Consultar knowledge base",
        ),
        examples=(
            {"title": "Stock por producto", "config": {"ask": "stock disponible por producto en Lima"}},
        ),
        context_reads=("trigger", "variables"),
        context_writes=("data", "evidence"),
        requires=("managed_db",),
        optional_dependencies=("knowledge_bases",),
        supports_knowledge=True,
    ),
    "marketplace_action": _meta(
        "Acción de integración",
        "Ejecuta una capacidad instalada (formulario según su schema).",
        long_description=(
            "Corre una acción del marketplace con el runtime gobernado: costos, "
            "caché, evidencia externa y purpose de uso."
        ),
        when_to_use=("hay una integración instalada que resuelve la operación",),
        when_not_to_use=("la integración no está instalada o falta permiso",),
        examples=(
            {
                "title": "Consultar RUC",
                "config": {
                    "install_id": "…",
                    "action_id": "peru.taxpayer.lookup",
                    "inputs": {"ruc": "{{trigger.ruc}}"},
                },
            },
        ),
        context_reads=("trigger", "variables"),
        context_writes=("data", "evidence"),
        requires=("installed_integrations",),
        supports_simulation=True,
    ),
    # ------------------------------------------------------------------
    # IA
    # ------------------------------------------------------------------
    "llm": _meta(
        "Preguntar a un agente",
        "Pide a un agente de Zent que analice o recomiende.",
        long_description=(
            "Ejecuta el AgentRuntime con el prompt y el contexto declarado en "
            "config.context_reads; si declaras output_schema, la decisión "
            "estructurada queda disponible para los pasos siguientes."
        ),
        when_to_use=(
            "necesitas interpretación, priorización o recomendación",
            "el resultado debe ser JSON estructurado (output_schema)",
        ),
        when_not_to_use=("basta una regla determinística; usa Si / si no",),
        examples=(
            {
                "title": "Riesgo de venta",
                "config": {
                    "agent_id": "…",
                    "prompt": "Analiza la venta {{trigger.sale_id}} y devuelve risk, reason y recommendation",
                    "context_reads": ["data", "knowledge", "evidence"],
                },
            },
        ),
        context_reads=(
            "trigger",
            "data",
            "knowledge",
            "evidence_refs",
            "claim_refs",
            "entity_refs",
            "findings",
            "decisions",
            "artifacts",
        ),
        context_writes=("findings", "decisions", "artifacts"),
        requires=("agents",),
        supports_agent=True,
    ),
    # ------------------------------------------------------------------
    # Lógica
    # ------------------------------------------------------------------
    "condition": _meta(
        "Si / si no",
        "Divide el flujo según una regla de negocio.",
        long_description=(
            "Evalúa una referencia del trigger, variables o la salida de otro nodo "
            "y elige la rama then/else."
        ),
        when_to_use=("hay que elegir una rama por un valor",),
        when_not_to_use=("necesitas muchas reglas anidadas; divide el flujo",),
        examples=(
            {
                "title": "Stock crítico",
                "config": {
                    "field": "{{nodes.stock.output.available}}",
                    "operator": "<",
                    "value": "10",
                },
            },
        ),
        context_reads=("trigger", "variables"),
        supports_simulation=False,
    ),
    "for_each": _meta(
        "Para cada",
        "Repite una parte del flujo por cada elemento de una lista.",
        long_description=(
            "Ejecuta el subgrafo declarado para cada ítem con concurrencia y "
            "máximo de iteraciones acotados."
        ),
        when_to_use=("debes procesar listas de ítems, facturas o resultados",),
        when_not_to_use=("solo hay un elemento; no agregues el nodo",),
        examples=(
            {
                "title": "Notificar por ítem",
                "config": {
                    "collection": "{{nodes.query.output.rows}}",
                    "max_iterations": 50,
                    "concurrency": 2,
                },
            },
        ),
        context_reads=("trigger", "variables", "data"),
        supports_simulation=False,
    ),
    "join": _meta(
        "Unir resultados",
        "Espera a todos los pasos anteriores.",
        long_description="Converge varias ramas del grafo antes de continuar.",
        when_to_use=("varias ramas deben converger antes del siguiente paso",),
        when_not_to_use=("solo hay una rama; el edge directo basta",),
        supports_simulation=False,
    ),
    "merge": _meta(
        "Primer resultado",
        "Continúa con el primer paso que termine.",
        long_description="Toma el primer predecesor resuelto y sigue el flujo.",
        when_to_use=("cualquiera de varias fuentes sirve para continuar",),
        when_not_to_use=("necesitas todos los resultados; usa Unir resultados",),
        supports_simulation=False,
    ),
    "filter": _meta(
        "Filtrar",
        "Filtra una lista por una condición.",
        long_description="Reduce una lista antes de iterar, analizar o avisar.",
        when_to_use=("quieres reducir filas antes de un agente o un aviso",),
        when_not_to_use=("puedes filtrar directamente en la consulta de datos",),
        examples=(
            {
                "title": "Solo stock bajo",
                "config": {
                    "items": "{{nodes.query.output.rows}}",
                    "field": "stock",
                    "operator": "<",
                    "value": "10",
                },
            },
        ),
        context_reads=("trigger", "variables", "data"),
        supports_simulation=False,
    ),
    "set_variable": _meta(
        "Guardar variable",
        "Guarda un dato para pasos posteriores.",
        long_description="Escribe una variable del run reutilizable por referencias.",
        when_to_use=("quieres reutilizar un valor calculado en varios pasos",),
        when_not_to_use=("el valor se usa una sola vez; referencia el nodo directo",),
        examples=({"title": "Umbral", "config": {"name": "umbral", "value": "10"}},),
        context_reads=("trigger", "variables", "data", "knowledge"),
        context_writes=("variables",),
        supports_simulation=False,
    ),
    # ------------------------------------------------------------------
    # Control
    # ------------------------------------------------------------------
    "human_approval": _meta(
        "Esperar aprobación",
        "Pausa hasta que una persona apruebe.",
        long_description=(
            "Crea una aprobación con expiración; el run queda pending_approval y "
            "se reanuda con la decisión humana."
        ),
        when_to_use=("la acción es sensible (pago, envío, borrado)",),
        when_not_to_use=("la acción es reversible y de bajo costo",),
        examples=(
            {
                "title": "Aprobar pago",
                "config": {
                    "action": "Aprobar pago al proveedor",
                    "summary": "{{nodes.llm.output.recommendation}}",
                    "expires_minutes": 1440,
                },
            },
        ),
        context_reads=("trigger", "variables", "decisions", "findings"),
        supports_simulation=True,
    ),
    "stop": _meta(
        "Detener",
        "Termina el flujo.",
        long_description="Corta el flujo con estado de éxito o fallo.",
        when_to_use=("una condición de negocio indica no continuar",),
        when_not_to_use=("solo quieres una rama vacía; deja el flujo sin ese paso",),
        examples=({"title": "No continuar", "config": {"status": "success", "message": "Sin acciones"}},),
        supports_simulation=False,
    ),
    # ------------------------------------------------------------------
    # Salidas
    # ------------------------------------------------------------------
    "notify": _meta(
        "Avisar",
        "Envía un aviso a personas, equipos o canales.",
        long_description=(
            "Envía in-app, correo o webhook; los canales no conectados se "
            "rechazan con un mensaje de negocio."
        ),
        when_to_use=("informar a una persona o canal externo",),
        when_not_to_use=(
            "el resultado debe quedar en el inbox de Zent con métricas; usa Resultado de negocio",
        ),
        examples=(
            {
                "title": "Alerta de stock",
                "config": {
                    "channel": "in_app",
                    "title": "Stock bajo",
                    "message": "Producto {{nodes.stock.output.name}} con {{nodes.stock.output.available}} unidades",
                },
            },
        ),
        context_reads=("trigger", "variables", "data", "knowledge", "decisions"),
        optional_dependencies=("notification_channels",),
        supports_simulation=True,
    ),
    "business_result": _meta(
        "Resultado de negocio",
        "Publica un resultado en el inbox de Zent.",
        long_description=(
            "Persiste un BusinessResult (métricas, hallazgos, entidades) visible en "
            "el dashboard/inbox; contribuye el artefacto al contexto."
        ),
        when_to_use=("quieres dejar métricas o hallazgos en el inbox",),
        when_not_to_use=("solo quieres avisar; usa Avisar",),
        examples=(
            {
                "title": "Resumen diario",
                "config": {
                    "title": "Resumen diario de ventas",
                    "section": "reports",
                    "summary": "{{nodes.llm.output.recommendation}}",
                },
            },
        ),
        context_reads=("trigger", "variables", "data", "knowledge", "findings", "decisions"),
        context_writes=("artifacts",),
        supports_simulation=True,
    ),
    # ------------------------------------------------------------------
    # Negocio
    # ------------------------------------------------------------------
    "business_node": _meta(
        "Operación de negocio",
        "Operación compuesta de un Business Pack (varias capacidades).",
        long_description=(
            "Ejecuta varias acciones de integración, normaliza el resultado y "
            "publica un BusinessResult; oculta el detalle del pack."
        ),
        when_to_use=("existe un pack instalado que resuelve la operación completa",),
        when_not_to_use=("necesitas control fino de cada paso; usa nodos simples",),
        examples=(
            {
                "title": "Verificación de cliente",
                "config": {
                    "title": "Verificación de cliente",
                    "actions": [
                        {"action_id": "peru.taxpayer.lookup", "inputs": {"ruc": "{{trigger.ruc}}"}}
                    ],
                },
            },
        ),
        context_reads=("trigger", "variables", "data"),
        context_writes=("data", "evidence"),
        requires=("installed_integrations",),
        supports_simulation=True,
    ),
    # ------------------------------------------------------------------
    # Cierre
    # ------------------------------------------------------------------
    "end": _meta(
        "Fin",
        "Cierra el flujo.",
        long_description="Nodo terminal explícito; no ejecuta efectos.",
        when_to_use=("quieres marcar el final explícito de una rama",),
        when_not_to_use=("el grafo ya termina en un nodo real; es opcional",),
        supports_simulation=False,
    ),
}


def metadata_for(node_type: str) -> dict[str, Any]:
    """Copia de la metadata semántica de un node_type (para el catálogo)."""
    return dict(NODE_METADATA.get(str(node_type), {}))


def semantic_metadata(node_type: str) -> dict[str, Any]:
    """Kwargs para `registry.register(...)`/`NodeTypeDef`."""
    return metadata_for(node_type)


__all__ = [
    "CATEGORIES",
    "NODE_METADATA",
    "REQUIREMENT_TOKENS",
    "metadata_for",
    "semantic_metadata",
]
