# =============================================================================
# Workflow Business Parameters — registro backend de parámetros de negocio y
# contratos de salida por tipo de nodo.
#
# El portal deja de ser la fuente de verdad de los formularios: este módulo
# describe cada nodo con BusinessParameterSchema (Simple/Guided/Advanced) y
# NodeOutputContract (Data Picker / Live Preview). Los `config` internos se
# mantienen exactamente igual: el renderer escribe las mismas claves.
#
# No ejecuta nada ni duplica el registry de nodos: lo describe.
# =============================================================================
from __future__ import annotations

from typing import Any

from src.platform.workflows.business_schema import (
    BusinessOutputField,
    BusinessParameterSchema,
    NodeBusinessSchema,
)
from src.platform.workflows.intent import OPERATOR_LABELS

# --- Helpers de construcción ------------------------------------------------

def _p(key: str, label: str, type: str = "text", **kwargs: Any) -> BusinessParameterSchema:
    return BusinessParameterSchema(key=key, label=label, type=type, **kwargs)  # type: ignore[arg-type]


def _out(key: str, label: str, type: str = "text", **kwargs: Any) -> BusinessOutputField:
    return BusinessOutputField(key=key, label=label, type=type, **kwargs)  # type: ignore[arg-type]


_OPERATOR_OPTIONS = [
    {"value": op, "label": label}
    for op, label in (
        ("==", OPERATOR_LABELS["eq"]),
        ("!=", OPERATOR_LABELS["neq"]),
        (">", OPERATOR_LABELS["gt"]),
        (">=", OPERATOR_LABELS["gte"]),
        ("<", OPERATOR_LABELS["lt"]),
        ("<=", OPERATOR_LABELS["lte"]),
        ("contains", OPERATOR_LABELS["contains"]),
    )
]

_IMPORTANCE_OPTIONS = [
    {"value": "INFO", "label": "Informativo"},
    {"value": "WARNING", "label": "Atención"},
    {"value": "CRITICAL", "label": "Crítico"},
]

_SECTION_OPTIONS = [
    {"value": "reports", "label": "Reportes"},
    {"value": "sales", "label": "Ventas"},
    {"value": "finance", "label": "Finanzas"},
    {"value": "operations", "label": "Operaciones"},
    {"value": "alerts", "label": "Alertas"},
]

_TIMEZONES = [
    {"value": "America/Lima", "label": "Lima (GMT-5)"},
    {"value": "America/Bogota", "label": "Bogotá (GMT-5)"},
    {"value": "America/Mexico_City", "label": "Ciudad de México (GMT-6)"},
    {"value": "America/Argentina/Buenos_Aires", "label": "Buenos Aires (GMT-3)"},
    {"value": "America/Santiago", "label": "Santiago (GMT-3/-4)"},
    {"value": "America/Sao_Paulo", "label": "São Paulo (GMT-3)"},
    {"value": "UTC", "label": "UTC"},
]

_NOTIFICATION_CHANNELS = [
    {"value": "in_app", "label": "Zent"},
    {"value": "email", "label": "Correo"},
    {"value": "webhook", "label": "Webhook"},
]


# ---------------------------------------------------------------------------
# Schemas por nodo
# ---------------------------------------------------------------------------
def _notify_schema() -> NodeBusinessSchema:
    return NodeBusinessSchema(
        node_type="notify",
        label="Avisar",
        category="output",
        description="Envía un aviso a personas, equipos o canales.",
        parameters=[
            _p(
                "channel",
                "Enviar por",
                "enum",
                required=True,
                validation={"options": _NOTIFICATION_CHANNELS},
                help="Solo se muestran los canales conectados en Integraciones cuando estén disponibles.",
            ),
            _p("title", "Asunto", "text", placeholder="Stock bajo", examples=["Alerta de stock bajo"]),
            _p(
                "message",
                "Mensaje",
                "textarea",
                placeholder="Producto: {{Producto → Nombre}} · Stock: {{Inventario → Stock}}",
                data_source="any",
                help="Escribe el mensaje y agrega datos con el selector.",
            ),
            _p("data", "Datos adjuntos (JSON)", "json", min_level="advanced"),
        ],
        outputs=[
            _out("sent", "Enviado", "boolean"),
            _out("channel", "Canal", "text"),
            _out("result", "Resultado del canal", "json"),
        ],
    )


def _condition_schema() -> NodeBusinessSchema:
    return NodeBusinessSchema(
        node_type="condition",
        label="Tomar una decisión",
        category="logic",
        description="Continúa por caminos distintos según una regla.",
        parameters=[
            _p(
                "field",
                "Dato a evaluar",
                "data_reference",
                required=True,
                data_source="any",
                placeholder="Stock disponible",
                help="Elige un dato de la lista; no necesitas escribir referencias.",
            ),
            _p(
                "operator",
                "Cumple que",
                "enum",
                required=True,
                validation={"options": _OPERATOR_OPTIONS},
                default=">",
            ),
            _p("value", "Valor", "text", data_source="any", placeholder="10", examples=["10", "20000"]),
        ],
        outputs=[_out("result", "Resultado", "boolean")],
    )


def _ai_decision_schema() -> NodeBusinessSchema:
    return NodeBusinessSchema(
        node_type="ai_decision",
        label="Decisión de IA",
        category="ai",
        description="Elige una ruta con una pregunta de negocio. La confianza baja puede pedir revisión humana.",
        parameters=[
            _p(
                "decision_kind",
                "Tipo",
                "enum",
                required=True,
                default="route",
                validation={
                    "options": [
                        {"value": "route", "label": "Elegir ruta"},
                        {"value": "yes_no", "label": "Sí / No"},
                        {"value": "score", "label": "Evaluar puntuación"},
                    ]
                },
            ),
            _p(
                "question",
                "Pregunta",
                "textarea",
                required=True,
                data_source="any",
                placeholder="Determinar si el cliente requiere revisión manual",
            ),
            _p(
                "options",
                "Opciones (JSON)",
                "json",
                help='[{"id":"approve","label":"Aprobar"},{"id":"reject","label":"Rechazar"}]',
            ),
            _p("confidence_min", "Confianza mínima", "number", min_level="guided", default=0.65),
            _p(
                "on_low_confidence",
                "Si la confianza es baja",
                "enum",
                min_level="guided",
                default="fallback",
                validation={
                    "options": [
                        {"value": "fallback", "label": "Usar respaldo"},
                        {"value": "human_review", "label": "Revisión humana"},
                        {"value": "stop", "label": "Detener"},
                        {"value": "llm", "label": "Preguntar a un agente"},
                    ]
                },
            ),
            _p("score_threshold", "Umbral de puntuación", "number", min_level="advanced", default=0.5),
        ],
        outputs=[
            _out("result", "Resultado", "boolean"),
            _out("choice", "Opción", "text"),
            _out("route", "Ruta", "text"),
            _out("confidence", "Confianza", "number"),
            _out("low_confidence", "Confianza baja", "boolean"),
        ],
    )


def _llm_schema() -> NodeBusinessSchema:
    return NodeBusinessSchema(
        node_type="llm",
        label="Preguntar a un agente",
        category="ai",
        description="Analiza con un agente de Zent y devuelve una conclusión estructurada si la pides.",
        parameters=[
            _p(
                "agent_id",
                "¿Quién debe analizar esto?",
                "agent",
                required=True,
                dynamic_options="agents",
                placeholder="Agente de inventario",
            ),
            _p(
                "prompt",
                "¿Qué quieres que haga?",
                "textarea",
                data_source="any",
                placeholder="Recomienda qué hacer con este stock bajo",
                examples=["Analiza la venta y recomienda próximos pasos"],
            ),
            _p(
                "context_mode",
                "Contexto",
                "enum",
                min_level="guided",
                default="auto",
                validation={
                    "options": [
                        {"value": "auto", "label": "Automático (solo lo disponible)"},
                        {"value": "manual", "label": "Elegir secciones"},
                        {"value": "none", "label": "Sin contexto"},
                    ]
                },
                help="Automático incluye solo secciones con contenido (datos, conocimiento, evidencia).",
            ),
            _p(
                "context_selectors",
                "Usar como contexto",
                "json",
                min_level="guided",
                help='Lista: ["trigger","knowledge","evidence","claims","data:<nodo>","knowledge:<nodo>"].',
            ),
            _p(
                "output_type",
                "Resultado esperado",
                "enum",
                min_level="guided",
                default="text",
                validation={
                    "options": [
                        {"value": "text", "label": "Texto libre"},
                        {"value": "decision", "label": "Decisión"},
                        {"value": "classification", "label": "Clasificación"},
                        {"value": "business_assessment", "label": "Evaluación de negocio"},
                        {"value": "json_schema", "label": "JSON personalizado"},
                    ]
                },
                help="Decisión/Evaluación validan el JSON y exponen campos como «Riesgo» o «Decisión».",
            ),
            _p(
                "output_schema",
                "JSON personalizado (schema)",
                "json",
                min_level="advanced",
            ),
            _p("model", "Modelo (solo sin agente)", "text", min_level="advanced", default="gpt-4o-mini"),
        ],
        outputs=[
            _out("text", "Respuesta del agente", "text"),
            _out("agent_id", "Agente", "text"),
            _out("model", "Modelo", "text"),
            _out("cost", "Costo", "money"),
            _out("status", "Estado", "text"),
            _out("decision", "Decisión", "json"),
            _out("confidence", "Confianza", "number"),
            _out("context_summary", "Contexto incluido", "json"),
            _out("reason_codes", "Motivos", "json"),
        ],
    )


def _query_business_data_schema() -> NodeBusinessSchema:
    return NodeBusinessSchema(
        node_type="query_business_data",
        label="Consultar datos de negocio",
        category="data",
        description="Pregunta en lenguaje natural sobre tus datos conectados.",
        parameters=[
            _p(
                "ask",
                "¿Qué dato necesitas?",
                "textarea",
                required=True,
                placeholder="Stock disponible por producto en el almacén de Lima",
                data_source="any",
            ),
        ],
        outputs=[
            _out("rows", "Resultados", "record_list"),
            _out("columns", "Columnas", "json"),
            _out("answer", "Respuesta", "text"),
            _out("evidence", "Evidencia", "evidence"),
            _out("evidence_ids", "Evidencias", "json"),
            _out("row_count", "Filas", "number"),
            _out("query_id", "Consulta", "text"),
        ],
    )


def _kb_query_schema() -> NodeBusinessSchema:
    return NodeBusinessSchema(
        node_type="kb_query",
        label="Consultar knowledge base",
        category="data",
        description="Busca, responde o investiga en el conocimiento de Zent.",
        parameters=[
            _p(
                "operation",
                "¿Qué necesitas hacer?",
                "enum",
                default="search",
                validation={
                    "options": [
                        {"value": "search", "label": "Buscar información"},
                        {"value": "answer", "label": "Responder una pregunta"},
                        {"value": "find_evidence", "label": "Encontrar evidencia"},
                        {"value": "extract_facts", "label": "Extraer hechos"},
                        {"value": "compare", "label": "Comparar documentos"},
                        {"value": "check_conflicts", "label": "Detectar contradicciones"},
                        {"value": "investigate", "label": "Investigar con Zent"},
                    ]
                },
                help="Los modos avanzados usan Knowledge V2 y pueden requerir permisos.",
            ),
            _p(
                "knowledge_base_id",
                "Base de conocimiento",
                "database",
                required=True,
                dynamic_options="knowledge_bases",
                placeholder="Políticas internas",
            ),
            _p(
                "query",
                "¿Sobre qué?",
                "text",
                required=True,
                data_source="any",
                placeholder="política de reposición de stock",
            ),
            _p(
                "subject",
                "Tema a verificar (contradicciones)",
                "text",
                min_level="guided",
                data_source="any",
                placeholder="descuento máximo",
                help="Solo para Detectar contradicciones: el tema normalizado en el ledger de claims.",
            ),
            _p(
                "budget",
                "Presupuesto de investigación (JSON)",
                "json",
                min_level="advanced",
                help='Solo para Investigar: {"max_llm_calls": 8, "max_cost_usd": 0.5, "max_seconds": 60}.',
            ),
            _p(
                "compare_left",
                "Comparar: lado A",
                "text",
                min_level="guided",
                data_source="any",
                placeholder="política antigua",
            ),
            _p(
                "compare_right",
                "Comparar: lado B",
                "text",
                min_level="guided",
                data_source="any",
                placeholder="política nueva",
            ),
            _p("limit", "Máximo de resultados", "number", min_level="guided", default=5),
        ],
        outputs=[
            _out("status", "Estado", "text"),
            _out("answer", "Respuesta", "text"),
            _out("documents", "Documentos", "record_list"),
            _out("chunks", "Fragmentos", "record_list"),
            _out("count", "Encontrados", "number"),
            _out("citations", "Citas", "json"),
            _out("claims", "Afirmaciones", "json"),
            _out("facts", "Hechos", "json"),
            _out("entities", "Entidades", "json"),
            _out("findings", "Hallazgos", "json"),
            _out("differences", "Diferencias", "json"),
            _out("conflicts", "Contradicciones", "json"),
            _out("has_conflicts", "Hay contradicciones", "boolean"),
            _out("coverage", "Cobertura", "json"),
            _out("temporal_context", "Vigencia", "json"),
            _out("cognitive_run_id", "Investigación", "text"),
            _out("metrics", "Métricas", "json"),
            _out("evidence_ids", "Evidencias", "json"),
            _out("reason_codes", "Motivos", "json"),
        ],
    )


def _api_call_schema() -> NodeBusinessSchema:
    return NodeBusinessSchema(
        node_type="api_call",
        label="Consultar servicio",
        category="integration",
        description="Consulta un servicio externo (modo técnico).",
        risk_level="elevated",
        parameters=[
            _p("url", "Dirección", "text", required=True, placeholder="https://…", data_source="any"),
            _p(
                "method",
                "Método",
                "enum",
                min_level="advanced",
                default="GET",
                validation={"options": [{"value": "GET", "label": "GET"}, {"value": "POST", "label": "POST"}]},
            ),
            _p("json_body", "Cuerpo (JSON)", "json", min_level="advanced", data_source="any"),
            _p("json_path", "Campo de salida", "text", min_level="advanced", placeholder="quantity"),
        ],
        outputs=[
            _out("extracted", "Campo extraído", "json"),
            _out("json", "Respuesta JSON", "json"),
            _out("status_code", "Código HTTP", "number"),
            _out("body", "Cuerpo", "text"),
            _out("ok", "Correcto", "boolean"),
        ],
    )


def _marketplace_action_schema() -> NodeBusinessSchema:
    return NodeBusinessSchema(
        node_type="marketplace_action",
        label="Acción de integración",
        category="integration",
        description="Ejecuta una capacidad instalada (formulario según su schema).",
        parameters=[
            _p(
                "install_id",
                "Integración",
                "integration",
                required=True,
                dynamic_options="installed_integrations",
            ),
            _p("action_id", "Acción", "action", required=True, dynamic_options="actions"),
            _p("purpose", "Propósito de uso", "text", min_level="advanced"),
        ],
        outputs=[
            _out("evidence_id", "Evidencia", "text"),
            _out("cached", "Desde caché", "boolean"),
            _out("cost", "Costo", "money"),
            _out("latency_ms", "Latencia (ms)", "number"),
        ],
    )


def _business_node_schema() -> NodeBusinessSchema:
    return NodeBusinessSchema(
        node_type="business_node",
        label="Operación de negocio",
        category="business",
        description="Operación compuesta de un Business Pack (varias capacidades).",
        parameters=[
            _p("title", "Título del resultado", "text", placeholder="Verificación de cliente"),
            _p("actions", "Acciones internas (JSON)", "json", min_level="advanced"),
            _p("business_result", "Resultado de negocio (JSON)", "json", min_level="advanced"),
        ],
        outputs=[
            _out("result_id", "Resultado", "text"),
            _out("evidence_ids", "Evidencias", "json"),
            _out("total_cost", "Costo total", "money"),
        ],
    )


def _business_result_schema() -> NodeBusinessSchema:
    return NodeBusinessSchema(
        node_type="business_result",
        label="Resultado de negocio",
        category="output",
        description="Publica un resultado en el inbox de Zent.",
        parameters=[
            _p("title", "Título", "text", required=True, placeholder="Resumen diario de ventas"),
            _p(
                "section",
                "Sección",
                "enum",
                validation={"options": _SECTION_OPTIONS},
                default="reports",
            ),
            _p(
                "importance",
                "Importancia",
                "enum",
                validation={"options": _IMPORTANCE_OPTIONS},
                default="INFO",
            ),
            _p("summary", "Resumen", "textarea", data_source="any"),
            _p("metrics", "Métricas (JSON)", "json", min_level="advanced"),
            _p("insights", "Hallazgos (JSON)", "json", min_level="advanced"),
            _p("entities", "Entidades (JSON)", "json", min_level="advanced"),
        ],
        outputs=[
            _out("result_id", "Resultado", "text"),
            _out("importance", "Importancia", "text"),
        ],
    )


def _logic_schema(node_type: str, label: str, description: str, parameters: list, outputs: list) -> NodeBusinessSchema:
    return NodeBusinessSchema(
        node_type=node_type,
        label=label,
        category="logic",
        description=description,
        parameters=parameters,
        outputs=outputs,
    )


def _control_schema(
    node_type: str,
    label: str,
    description: str,
    parameters: list,
    outputs: list,
    **kw: Any,
) -> NodeBusinessSchema:
    return NodeBusinessSchema(
        node_type=node_type,
        label=label,
        category="control",
        description=description,
        parameters=parameters,
        outputs=outputs,
        **kw,
    )


def _trigger_schedule_schema() -> NodeBusinessSchema:
    return NodeBusinessSchema(
        node_type="trigger_schedule",
        label="Programar",
        category="trigger",
        description="Ejecuta la automatización según una programación.",
        parameters=[
            _p("daily", "Todos los días (hh:mm)", "text", placeholder="08:00"),
            _p("weekly", "Días de la semana (0-6, hh:mm)", "text", min_level="advanced"),
            _p("every_minutes", "Cada N minutos", "number", min_level="advanced"),
            _p(
                "timezone",
                "Zona horaria",
                "timezone",
                min_level="guided",
                default="UTC",
                validation={"options": _TIMEZONES},
            ),
        ],
        outputs=[],
    )


def _trigger_event_schema() -> NodeBusinessSchema:
    return NodeBusinessSchema(
        node_type="trigger_event",
        label="Cuando ocurra algo",
        category="trigger",
        description="Reacciona a un evento del negocio.",
        parameters=[
            _p(
                "event_type",
                "Evento",
                "enum",
                required=True,
                dynamic_options="event_types",
                default="source.synced",
            ),
            _p("filters", "Filtros (JSON)", "json", min_level="advanced"),
        ],
        outputs=[],
    )


def _trigger_webhook_schema() -> NodeBusinessSchema:
    return NodeBusinessSchema(
        node_type="trigger_webhook",
        label="Webhook",
        category="trigger",
        description="Entrada HTTP para sistemas externos.",
        parameters=[
            _p("note", "URL pública", "text", min_level="advanced", placeholder="se genera al guardar"),
        ],
        outputs=[],
    )


def _register(registry: dict[str, NodeBusinessSchema]) -> None:
    schemas = [
        _notify_schema(),
        _condition_schema(),
        _llm_schema(),
        _ai_decision_schema(),
        _query_business_data_schema(),
        _kb_query_schema(),
        _api_call_schema(),
        _marketplace_action_schema(),
        _business_node_schema(),
        _business_result_schema(),
        _logic_schema(
            "for_each",
            "Hacer esto por cada...",
            "Repite una parte del flujo por cada elemento de una lista.",
            [
                _p("collection", "Lista", "data_reference", required=True, data_source="record_list"),
                _p("max_iterations", "Máximo de iteraciones", "number", min_level="guided", default=100),
                _p(
                    "expected_items",
                    "Ítems esperados (para costo)",
                    "number",
                    min_level="guided",
                    help="Estimación para el presupuesto; la rama se avisa si usa agentes o conocimiento.",
                ),
                _p("concurrency", "Concurrencia", "number", min_level="advanced", default=1),
                _p(
                    "fail_policy",
                    "Si falla",
                    "enum",
                    min_level="guided",
                    default="fail",
                    validation={
                        "options": [
                            {"value": "fail", "label": "Detener el flujo"},
                            {"value": "continue", "label": "Continuar"},
                        ]
                    },
                ),
            ],
            [
                _out("items_processed", "Procesados", "number"),
                _out("results", "Resultados", "json"),
                _out("warnings", "Advertencias", "json"),
            ],
        ),
        _logic_schema(
            "filter",
            "Quedarme solo con...",
            "Filtra una lista con una o varias condiciones.",
            [
                _p("items", "Lista", "data_reference", required=True, data_source="record_list"),
                _p(
                    "conditions",
                    "Condiciones (JSON)",
                    "json",
                    min_level="guided",
                    help='Lista: [{"field":"estado","operator":"==","value":"activo"}].',
                ),
                _p("field", "Campo (condición simple)", "text", data_source="any"),
                _p("operator", "Cumple que", "enum", validation={"options": _OPERATOR_OPTIONS}, default="=="),
                _p("value", "Valor", "text", data_source="any"),
                _p(
                    "op",
                    "Combinar con",
                    "enum",
                    min_level="guided",
                    default="and",
                    validation={
                        "options": [
                            {"value": "and", "label": "Todas"},
                            {"value": "or", "label": "Alguna"},
                        ]
                    },
                ),
            ],
            [
                _out("filtered", "Resultados", "record_list"),
                _out("count", "Cantidad", "number"),
                _out("total", "Total", "number"),
            ],
        ),
        _logic_schema(
            "set_variable",
            "Guardar un dato",
            "Guarda un dato para pasos posteriores.",
            [
                _p("name", "Nombre", "text", required=True),
                _p("value", "Valor", "text", data_source="any"),
            ],
            [_out("variable", "Variable", "text"), _out("value", "Valor", "json")],
        ),
        _logic_schema(
            "join",
            "Esperar todos los resultados",
            "Espera a todos los pasos anteriores y conserva ramas con nombre.",
            [
                _p(
                    "branch_labels",
                    "Nombres de rama (JSON)",
                    "json",
                    min_level="advanced",
                    help='Opcional: {"<node_id>": "Ventas"} para renombrar ramas.',
                ),
            ],
            [_out("branches", "Ramas", "json"), _out("values", "Resultados", "json")],
        ),
        _logic_schema(
            "merge",
            "Usar el primer resultado disponible",
            "Elige un resultado según la estrategia (primer disponible, primer éxito, preferido o respaldo).",
            [
                _p(
                    "strategy",
                    "Estrategia",
                    "enum",
                    min_level="guided",
                    default="first_available",
                    validation={
                        "options": [
                            {"value": "first_available", "label": "Primero que responda"},
                            {"value": "first_success", "label": "Primero exitoso"},
                            {"value": "prefer_source", "label": "Preferir una rama"},
                            {"value": "fallback", "label": "Respaldo ordenado"},
                        ]
                    },
                ),
                _p("source_node_id", "Rama preferida (node_id)", "text", min_level="advanced", data_source="any"),
                _p("sources", "Respaldo (node_ids JSON)", "json", min_level="advanced"),
            ],
            [
                _out("first", "Primer resultado", "json"),
                _out("values", "Resultados", "json"),
                _out("strategy", "Estrategia", "text"),
                _out("selected_from", "Origen", "text"),
            ],
        ),
        _control_schema(
            "human_approval",
            "Esperar aprobación",
            "Pausa hasta que una persona apruebe; el revisor ve la decisión, evidencia y citas del run.",
            [
                _p("action", "Acción a aprobar", "text", required=True, placeholder="Aprobar pago"),
                _p("summary", "Resumen", "textarea", data_source="any"),
                _p("expires_minutes", "Expira (minutos)", "number", min_level="advanced", default=1440),
            ],
            [
                _out("approval_id", "Aprobación", "text"),
                _out("status", "Estado", "text"),
                _out("context", "Contexto mostrado", "json"),
            ],
            risk_level="critical",
        ),
        _control_schema(
            "stop",
            "Terminar el flujo",
            "Termina el flujo.",
            [
                _p(
                    "status",
                    "Al detener",
                    "enum",
                    default="success",
                    validation={
                        "options": [
                            {"value": "success", "label": "Éxito"},
                            {"value": "fail", "label": "Fallo"},
                        ]
                    },
                ),
                _p("message", "Mensaje", "text", data_source="any"),
            ],
            [],
        ),
        _trigger_schedule_schema(),
        _trigger_event_schema(),
        _trigger_webhook_schema(),
    ]
    for schema in schemas:
        registry[schema.node_type] = schema


NODE_BUSINESS_SCHEMAS: dict[str, NodeBusinessSchema] = {}
_register(NODE_BUSINESS_SCHEMAS)


# ---------------------------------------------------------------------------
# API del registro
# ---------------------------------------------------------------------------
def node_business_schema(node_type: str) -> NodeBusinessSchema | None:
    return NODE_BUSINESS_SCHEMAS.get(str(node_type))


def business_parameters_for(
    node_type: str,
    level: str = "simple",
    *,
    include_secret: bool = False,
) -> list[BusinessParameterSchema]:
    schema = node_business_schema(node_type)
    if schema is None:
        return []
    return schema.parameters_for(level, include_secret=include_secret)


def business_outputs_for(node_type: str) -> list[BusinessOutputField]:
    schema = node_business_schema(node_type)
    return list(schema.outputs) if schema else []


def all_node_schemas() -> list[NodeBusinessSchema]:
    return sorted(NODE_BUSINESS_SCHEMAS.values(), key=lambda s: (s.category, s.label))


def output_contracts() -> dict[str, dict[str, Any]]:
    """Contratos de salida por node_type para el Data Picker."""
    return {
        node_type: {
            "node_type": node_type,
            "outputs": [field.model_dump(mode="json") for field in schema.outputs],
            "sample": {},
            "source": "contract",
        }
        for node_type, schema in NODE_BUSINESS_SCHEMAS.items()
        if schema.outputs
    }


# ---------------------------------------------------------------------------
# JSON Schema (marketplace/capabilities) → BusinessParameterSchema
# ---------------------------------------------------------------------------
_TYPE_MAP: dict[str, str] = {
    "string": "text",
    "number": "number",
    "integer": "integer",
    "boolean": "boolean",
    "array": "json",
    "object": "json",
}


def _json_schema_to_type(raw: dict[str, Any]) -> str:
    declared = str(raw.get("x-business-type") or "")
    if declared:
        return declared
    if raw.get("enum"):
        return "enum"
    fmt = str(raw.get("format") or "")
    if fmt == "email":
        return "email"
    if fmt == "date":
        return "date"
    if fmt == "date-time":
        return "datetime"
    if fmt == "time":
        return "time"
    schema_type = str(raw.get("type") or "string")
    if schema_type == "string" and raw.get("widget") == "textarea":
        return "textarea"
    return _TYPE_MAP.get(schema_type, "text")


def parameters_from_json_schema(
    schema: dict[str, Any] | None,
    *,
    prefix: str = "",
    min_level: str = "simple",
) -> list[BusinessParameterSchema]:
    """Convierte un JSON Schema de capability (marketplace) a parámetros de UI.

    Soporta extensiones `x-business-*` para label, unidad, grupo, nivel,
    secreto, helper y placeholder. Sin extensiones usa name/description/title.
    """
    data = schema if isinstance(schema, dict) else {}
    properties = data.get("properties")
    if not isinstance(properties, dict):
        return []
    required = {str(k) for k in (data.get("required") or [])}
    parameters: list[BusinessParameterSchema] = []
    for key, raw in properties.items():
        prop = raw if isinstance(raw, dict) else {}
        param_type = _json_schema_to_type(prop)
        declared_level = str(prop.get("x-business-level") or "")
        level = declared_level if declared_level in ("simple", "guided", "advanced") else min_level
        validation: dict[str, Any] = {}
        if prop.get("enum"):
            options = prop.get("enum") or []
            labels = prop.get("x-business-enum-labels") or []
            validation["options"] = [
                {
                    "value": option,
                    "label": labels[idx] if idx < len(labels) else str(option),
                }
                for idx, option in enumerate(options)
            ]
        for rule in ("minimum", "maximum", "minLength", "maxLength", "pattern", "format"):
            if prop.get(rule) is not None:
                validation[rule] = prop[rule]
        parameters.append(
            BusinessParameterSchema(
                key=f"{prefix}{key}",
                label=str(prop.get("x-business-label") or prop.get("title") or key.replace("_", " ").capitalize()),
                description=prop.get("description") or prop.get("x-business-help"),
                type=param_type,  # type: ignore[arg-type]
                required=str(key) in required,
                default=prop.get("default"),
                placeholder=prop.get("x-business-placeholder") or prop.get("examples", [None])[0],
                examples=list(prop.get("examples") or [])[:10],
                min_level=level,  # type: ignore[arg-type]
                secret=bool(prop.get("x-business-secret", False)),
                dynamic_options=prop.get("x-business-options"),
                data_source=prop.get("x-business-data-source"),
                unit=prop.get("x-business-unit"),
                validation=validation,
                help=prop.get("x-business-help"),
                business_group=prop.get("x-business-group"),
            )
        )
    return parameters


__all__ = [
    "NODE_BUSINESS_SCHEMAS",
    "all_node_schemas",
    "business_outputs_for",
    "business_parameters_for",
    "node_business_schema",
    "output_contracts",
    "parameters_from_json_schema",
]
