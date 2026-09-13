# =============================================================================
# Business Parameter Schema — capa de abstracción entre NodeMeta/FieldDef y la
# experiencia empresarial (Simple / Guided / Advanced).
#
# El backend es la fuente de verdad de los parámetros de un nodo o de una
# acción de integración; el portal solo los renderiza. `config` interno del
# nodo no cambia: el schema describe cómo editarlo en lenguaje de negocio.
#
# No crea motores ni nodos: es modelo de datos + validación.
# =============================================================================
from __future__ import annotations

from typing import Any, Literal, get_args

from pydantic import BaseModel, ConfigDict, Field, model_validator

# Tipos de parámetro visibles para negocio (misión §7). Los tipos "data-bound"
# (database, table, column, field, entity, agent, integration, action...) se
# resuelven con opciones dinámicas provistas por el backend.
ParameterType = Literal[
    "text",
    "textarea",
    "number",
    "integer",
    "money",
    "percentage",
    "email",
    "person",
    "team",
    "date",
    "datetime",
    "time",
    "duration",
    "timezone",
    "boolean",
    "enum",
    "database",
    "table",
    "column",
    "field",
    "entity",
    "agent",
    "integration",
    "action",
    "template",
    "condition",
    "secret",
    "data_reference",
    "json",
]

PARAMETER_TYPES: tuple[ParameterType, ...] = get_args(ParameterType)

# Tipos de salida IR que no son parámetros editables (contratos de salida).
OUTPUT_ONLY_TYPES = ("record", "record_list", "document", "evidence", "binary")

OutputFieldType = ParameterType | Literal["record", "record_list", "document", "evidence", "binary"]

# Etiquetas de respaldo para la UI (la UI puede sobreescribirlas por i18n).
PARAMETER_TYPE_LABELS: dict[str, str] = {
    "text": "Texto",
    "textarea": "Texto largo",
    "number": "Número",
    "integer": "Número entero",
    "money": "Monto",
    "percentage": "Porcentaje",
    "email": "Correo",
    "person": "Persona",
    "team": "Equipo",
    "date": "Fecha",
    "datetime": "Fecha y hora",
    "time": "Hora",
    "duration": "Duración",
    "timezone": "Zona horaria",
    "boolean": "Sí / No",
    "enum": "Opción",
    "database": "Base de datos",
    "table": "Tabla",
    "column": "Columna",
    "field": "Campo",
    "entity": "Entidad",
    "agent": "Agente",
    "integration": "Integración",
    "action": "Acción",
    "template": "Plantilla",
    "condition": "Condición",
    "secret": "Secreto",
    "data_reference": "Dato de otro paso",
    "json": "Datos (JSON)",
    "record": "Registro",
    "record_list": "Lista de registros",
    "document": "Documento",
    "evidence": "Evidencia",
    "binary": "Archivo",
}

# Tipos cuyas opciones vienen del backend (agents, kbs, instalaciones...).
DYNAMIC_OPTION_TYPES: frozenset[str] = frozenset(
    {
        "person",
        "team",
        "database",
        "table",
        "column",
        "field",
        "entity",
        "agent",
        "integration",
        "action",
        "template",
        "data_reference",
    }
)

# Tipos que nunca deben viajar en claro al browser ni al graph.
SECRET_TYPES: frozenset[str] = frozenset({"secret"})

LEVELS = ("simple", "guided", "advanced")
LEVEL_RANK: dict[str, int] = {"simple": 0, "guided": 1, "advanced": 2}

MODEL_CONFIG = ConfigDict(extra="forbid")


class BusinessParameterSchema(BaseModel):
    """Descripción de un campo editable en modo Simple/Guided/Advanced.

    - `min_level` → primer nivel donde el campo es visible. `advanced=True` es
      azúcar equivalente a `min_level="advanced"` (compatibilidad de lectura).
    - `secret=True` → el valor real vive en SecretStore; el graph guarda una ref.
    - `dynamic_options` → clave de proveedor de opciones que el backend resuelve
      (p. ej. `agents`, `knowledge_bases`, `installed_integrations`).
    - `data_source` → tipo de dato esperado por el Data Picker cuando el valor es
      una referencia a la salida de otro paso.
    """

    model_config = MODEL_CONFIG

    key: str = Field(min_length=1, max_length=80)
    label: str = Field(min_length=1, max_length=160)
    description: str | None = Field(default=None, max_length=600)
    type: ParameterType = "text"
    required: bool = False
    default: Any = None
    placeholder: str | None = Field(default=None, max_length=200)
    examples: list[Any] = Field(default_factory=list, max_length=10)
    advanced: bool = False
    min_level: Literal["simple", "guided", "advanced"] = "simple"
    secret: bool = False
    dynamic_options: str | None = Field(default=None, max_length=80)
    data_source: str | None = Field(default=None, max_length=80)
    unit: str | None = Field(default=None, max_length=40)
    validation: dict[str, Any] = Field(default_factory=dict)
    help: str | None = Field(default=None, max_length=600)
    business_group: str | None = Field(default=None, max_length=80)

    @model_validator(mode="after")
    def _coerce_consistency(self) -> "BusinessParameterSchema":
        # Un secreto declarado por tipo nunca puede quedar como no-secreto.
        if self.type in SECRET_TYPES and not self.secret:
            self.secret = True
        # `advanced=True` mantiene compatibilidad con FieldDef: implica nivel advanced.
        if self.advanced and self.min_level != "advanced":
            self.min_level = "advanced"
        if self.min_level == "advanced":
            self.advanced = True
        # Los tipos de opciones dinámicas requieren proveedor; si no viene, se
        # infiere del tipo para que la UI no quede sin opciones.
        if self.type in DYNAMIC_OPTION_TYPES and not self.dynamic_options:
            self.dynamic_options = self.type
        return self

    @property
    def static_options(self) -> list[dict[str, Any]]:
        """Opciones fijas opcionales declaradas en `validation.options`."""
        options = self.validation.get("options")
        return list(options) if isinstance(options, list) else []

    @property
    def is_data_bound(self) -> bool:
        return self.type in DYNAMIC_OPTION_TYPES or self.data_source is not None

    def visible_at(self, level: str) -> bool:
        """Simple/Guided ocultan lo avanzado; Advanced muestra todo.

        Los campos `secret` se filtran aparte (política de cada superficie):
        el nivel describe complejidad, no sensibilidad.
        """
        current = LEVEL_RANK.get(str(level), 0)
        return LEVEL_RANK.get(self.min_level, 0) <= current


class BusinessOutputField(BaseModel):
    """Campo de salida tipado de un nodo/capacidad (contrato de salida)."""

    model_config = MODEL_CONFIG

    key: str = Field(min_length=1, max_length=80)
    label: str = Field(min_length=1, max_length=160)
    type: OutputFieldType = "text"
    description: str | None = Field(default=None, max_length=600)
    example: Any = None
    sample: Any = None
    unit: str | None = Field(default=None, max_length=40)
    business_group: str | None = Field(default=None, max_length=80)


class NodeOutputContract(BaseModel):
    """Salidas de un nodo para el Data Picker y el Live Preview.

    `source` documenta de dónde salió el contrato: declarado (`contract`),
    derivado de un sample (`sample`) o del último run (`runtime`). Los outputs
    reales de un run siempre tienen prioridad sobre lo declarado.
    """

    model_config = MODEL_CONFIG

    node_type: str = Field(min_length=1, max_length=80)
    outputs: list[BusinessOutputField] = Field(default_factory=list)
    sample: dict[str, Any] = Field(default_factory=dict)
    source: Literal["contract", "sample", "runtime"] = "contract"


class NodeBusinessSchema(BaseModel):
    """Schema completo de un nodo para la UI: parámetros + salidas."""

    model_config = MODEL_CONFIG

    node_type: str = Field(min_length=1, max_length=80)
    label: str = Field(min_length=1, max_length=160)
    category: str = Field(default="data", max_length=40)
    description: str | None = Field(default=None, max_length=600)
    risk_level: Literal["info", "normal", "elevated", "critical"] = "normal"
    parameters: list[BusinessParameterSchema] = Field(default_factory=list)
    outputs: list[BusinessOutputField] = Field(default_factory=list)

    def parameters_for(self, level: str = "simple", *, include_secret: bool = False) -> list[BusinessParameterSchema]:
        """Parámetros visibles para un nivel de configuración."""
        result = [p for p in self.parameters if p.visible_at(level)]
        if not include_secret:
            result = [p for p in result if not p.secret]
        return result


__all__ = [
    "BusinessOutputField",
    "BusinessParameterSchema",
    "DYNAMIC_OPTION_TYPES",
    "LEVELS",
    "LEVEL_RANK",
    "NodeBusinessSchema",
    "NodeOutputContract",
    "OUTPUT_ONLY_TYPES",
    "OutputFieldType",
    "PARAMETER_TYPE_LABELS",
    "PARAMETER_TYPES",
    "ParameterType",
    "SECRET_TYPES",
]
