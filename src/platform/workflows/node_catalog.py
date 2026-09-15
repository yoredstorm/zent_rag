# =============================================================================
# Node Catalog — metadata semántica de negocio por tipo de nodo
# (Workflow Semantic Core, Fase 3; API/endpoint en Fase 4).
#
# Fuente backend: describe QUÉ es cada nodo, CUÁNDO usarlo y qué secciones del
# WorkflowContext lee/escribe. El portal y el planner IA lo consumen en fases
# posteriores; el registry sigue siendo la verdad de ejecución.
# =============================================================================
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from src.platform.workflows.values import jsonable

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
        "Busca, responde o investiga en el conocimiento de Zent.",
        long_description=(
            "Operaciones: buscar información, responder una pregunta grounded, "
            "encontrar evidencia, extraer hechos, comparar documentos, detectar "
            "contradicciones o investigar con el Cognitive OS. El resultado "
            "incluye `status` tipado para ramificar."
        ),
        when_to_use=(
            "la respuesta está en documentos, políticas o procedimientos",
            "necesitas evidencia localizable (citas, página, documento)",
        ),
        when_not_to_use=(
            "necesitas totales o filas de una base de datos; usa Consultar datos de negocio",
        ),
        examples=(
            {
                "title": "Responder con política",
                "config": {
                    "operation": "answer",
                    "knowledge_base_id": "…",
                    "query": "política de reposición de stock",
                    "limit": 5,
                },
            },
            {
                "title": "Buscar información",
                "config": {
                    "operation": "search",
                    "knowledge_base_id": "…",
                    "query": "descuentos comerciales",
                },
            },
        ),
        context_reads=("trigger", "variables"),
        context_writes=("knowledge", "evidence", "claims", "entities"),
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
        "Analiza con un agente de Zent y devuelve una conclusión estructurada.",
        long_description=(
            "Ejecuta el AgentRuntime con contexto seleccionable (automático por "
            "defecto: solo secciones con contenido) y resultado esperado "
            "(texto, decisión, clasificación, evaluación de negocio o JSON "
            "personalizado). La decisión viaja tipada (DecisionResult) y los "
            "campos validados quedan referenciables."
        ),
        when_to_use=(
            "necesitas interpretación, priorización o recomendación",
            "el resultado debe ser JSON estructurado (decisión/evaluación)",
        ),
        when_not_to_use=("basta una regla determinística; usa Si / si no",),
        examples=(
            {
                "title": "Riesgo de venta",
                "config": {
                    "agent_id": "…",
                    "prompt": "Analiza la venta {{trigger.sale_id}} y recomienda próximos pasos",
                    "context_mode": "auto",
                    "output_type": "business_assessment",
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
        context_writes=("artifacts", "entities"),
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
        context_writes=("data", "evidence", "entities"),
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


def planner_hints(capabilities: dict[str, Any] | None = None) -> str:
    """Bloque compacto del catálogo backend para el planner IA.

    Incluye qué nodo usar, cuándo, y (si hay capabilities) qué nodos no están
    disponibles ahora para el tenant.
    """
    unavailable: list[str] = []
    unavailable_types: set[str] = set()
    if capabilities is not None:
        try:
            from src.platform.workflows.nodes import registry

            for node_def in registry.all():
                available, reason = catalog_availability(node_def, capabilities)
                if not available and reason:
                    unavailable.append(f"{node_def.node_type}: {reason}")
                    unavailable_types.add(node_def.node_type)
        except Exception:  # noqa: BLE001 — hints nunca rompen el copilot
            unavailable = []
            unavailable_types = set()

    lines: list[str] = []
    for node_type, meta in NODE_METADATA.items():
        if node_type in unavailable_types:
            continue
        name = str(meta.get("business_name") or node_type)
        when = meta.get("when_to_use") or ()
        hint = str(when[0]) if when else str(meta.get("short_description") or "")
        lines.append(f"- {node_type}: {name}. {hint}".strip())

    parts: list[str] = []
    if lines:
        parts.append("Nodos disponibles (catálogo backend):\n" + "\n".join(lines))
    if unavailable:
        parts.append("No disponibles ahora en este tenant: " + "; ".join(unavailable[:10]))
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Catálogo autorizado/disponible por tenant (Fase 4)
# ---------------------------------------------------------------------------
CATALOG_VERSION = 1

_REQUIREMENT_REASONS: dict[str, str] = {
    "agents": "No hay agentes disponibles en este espacio.",
    "knowledge_bases": "No hay bases de conocimiento disponibles.",
    "installed_integrations": "No hay integraciones instaladas.",
    "managed_db": "No hay una base de datos de negocio conectada.",
}


def _requirement_status(
    requirement: str, capabilities: dict[str, Any]
) -> tuple[bool, str | None]:
    if requirement == "agents":
        return bool(capabilities.get("agents")), _REQUIREMENT_REASONS["agents"]
    if requirement == "knowledge_bases":
        return bool(capabilities.get("knowledge_bases")), _REQUIREMENT_REASONS["knowledge_bases"]
    if requirement == "installed_integrations":
        return bool(capabilities.get("actions")), _REQUIREMENT_REASONS["installed_integrations"]
    if requirement == "managed_db":
        return bool(capabilities.get("managed_db")), _REQUIREMENT_REASONS["managed_db"]
    return True, None


def catalog_availability(
    node_def: Any,
    capabilities: dict[str, Any] | None,
    *,
    permissions: frozenset[str] | None = None,
) -> tuple[bool, str | None]:
    """¿Puede usarse este nodo en el tenant/espacio y con estos permisos?

    Devuelve `(available, unavailable_reason)`. `permissions=None` omite el
    filtro RBAC (caller con `admin:*`).
    """
    caps = capabilities or {}
    for requirement in getattr(node_def, "requires", ()) or ():
        ok, reason = _requirement_status(str(requirement), caps)
        if not ok:
            return False, reason
    if permissions is not None:
        from src.platform.workflows.nodes import capability_permission

        for capability in sorted(getattr(node_def, "capabilities", frozenset()) or frozenset()):
            permission = capability_permission(capability)
            if permission and permission not in permissions:
                return False, f"Permiso insuficiente: {permission}"
    return True, None


async def build_node_catalog(
    organization_id: UUID,
    *,
    workspace_id: UUID | None = None,
    permissions: frozenset[str] | None = None,
) -> dict[str, Any]:
    """Catálogo semántico backend: definiciones autorizadas y disponibles.

    Combina el registry (ejecución), `NODE_METADATA` (negocio), las Business
    Schemas (formularios) y las capacidades reales del tenant.
    """
    from src.platform.workflows.nodes import registry
    from src.platform.workflows.parameters import node_business_schema
    from src.platform.workflows.plan_compiler import load_capabilities

    capabilities = await load_capabilities(organization_id, workspace_id)
    nodes: list[dict[str, Any]] = []
    for node_def in registry.all():
        schema = node_business_schema(node_def.node_type)
        available, reason = catalog_availability(node_def, capabilities, permissions=permissions)
        nodes.append(
            {
                "node_type": node_def.node_type,
                "version": node_def.version,
                "label": node_def.label,
                "business_name": node_def.business_name or node_def.label,
                "short_description": node_def.short_description,
                "long_description": node_def.long_description,
                "category": node_def.category,
                "subcategory": node_def.subcategory,
                "risk_level": node_def.risk_level,
                "capabilities": sorted(node_def.capabilities),
                "inputs": jsonable(node_def.inputs),
                "outputs": jsonable(node_def.outputs),
                "context_reads": list(node_def.context_reads),
                "context_writes": list(node_def.context_writes),
                "requires": list(node_def.requires),
                "optional_dependencies": list(node_def.optional_dependencies),
                "supports_simulation": node_def.simulation_supported,
                "supports_agent": node_def.supports_agent,
                "supports_knowledge": node_def.supports_knowledge,
                "when_to_use": list(node_def.when_to_use),
                "when_not_to_use": list(node_def.when_not_to_use),
                "examples": jsonable(list(node_def.examples)),
                "parameters": [
                    parameter.model_dump(mode="json")
                    for parameter in (schema.parameters if schema else [])
                ],
                "output_fields": [
                    field.model_dump(mode="json") for field in (schema.outputs if schema else [])
                ],
                "available": available,
                "unavailable_reason": reason,
            }
        )
    return {
        "catalog_version": CATALOG_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "categories": [dict(category) for category in CATEGORIES],
        "nodes": nodes,
    }


__all__ = [
    "CATALOG_VERSION",
    "CATEGORIES",
    "NODE_METADATA",
    "REQUIREMENT_TOKENS",
    "build_node_catalog",
    "catalog_availability",
    "metadata_for",
    "planner_hints",
    "semantic_metadata",
]
